#!/usr/bin/env python3
"""Train a compact GPU TCN or Transformer timestamp decoder from cached evidence."""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.gpu_boundary_decoder import (
    BoundaryDecoderConfig,
    FEATURE_SCHEMA,
    SUPPORTED_ARCHITECTURES,
    build_model,
    monotonic_project,
    save_checkpoint,
)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def load_items(cache_root: Path) -> list[dict[str, Any]]:
    import torch

    items: list[dict[str, Any]] = []
    for path in sorted((cache_root / "shards").glob("*.pt")):
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("schema_version") != FEATURE_SCHEMA:
            raise ValueError(f"unexpected cache schema in {path}")
        items.extend(payload["items"])
    if not items:
        raise ValueError(f"no decoder cache shards found under {cache_root}")
    return items



def canonical_split(value: Any) -> str:
    text = str(value).strip().lower()
    if text in {"train", "training"}:
        return "train"
    if text in {"validation", "valid", "val", "dev", "development"}:
        return "validation"
    return text


def derive_song_holdout(
    train_items: list[dict[str, Any]],
    *,
    seed: int,
    percent: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Create a deterministic song-disjoint validation fallback."""
    import hashlib

    song_ids = sorted({str(item.get("song_id")) for item in train_items})
    if len(song_ids) < 2:
        raise ValueError(
            "cannot derive song-level validation: cache contains fewer than two unique train songs"
        )
    ordered = sorted(
        song_ids,
        key=lambda song_id: hashlib.sha256(f"{seed}:{song_id}".encode()).hexdigest(),
    )
    count = max(1, int(round(len(ordered) * percent / 100.0)))
    count = min(count, len(ordered) - 1)
    validation_songs = set(ordered[:count])
    validation = [item for item in train_items if str(item.get("song_id")) in validation_songs]
    train = [item for item in train_items if str(item.get("song_id")) not in validation_songs]
    if not train or not validation:
        raise ValueError("song-level validation fallback produced an empty partition")
    return train, validation, sorted(validation_songs)


def collate(items: list[dict[str, Any]]) -> dict[str, Any]:
    import torch

    max_slots = max(int(item["slot_count"]) for item in items)
    feature_dim = int(items[0]["features"].shape[-1])
    features = torch.zeros((len(items), max_slots, feature_dim), dtype=torch.float32)
    raw = torch.zeros((len(items), max_slots), dtype=torch.float32)
    target = torch.zeros((len(items), max_slots), dtype=torch.float32)
    official = torch.zeros((len(items), max_slots), dtype=torch.float32)
    mask = torch.zeros((len(items), max_slots), dtype=torch.bool)
    num_labels = torch.zeros((len(items),), dtype=torch.int64)
    segment_sec = torch.zeros((len(items),), dtype=torch.float32)
    for index, item in enumerate(items):
        slots = int(item["slot_count"])
        features[index, :slots] = item["features"].float()
        raw[index, :slots] = item["raw_classes"].float()
        target[index, :slots] = item["target_classes"].float()
        official[index, :slots] = item["official_classes"].float()
        mask[index, :slots] = True
        num_labels[index] = int(item["num_timestamp_labels"])
        segment_sec[index] = float(item["timestamp_segment_sec"])
    return {
        "features": features,
        "raw": raw,
        "target": target,
        "official": official,
        "mask": mask,
        "num_labels": num_labels,
        "segment_sec": segment_sec,
        "item_ids": [str(item["item_id"]) for item in items],
    }


def batches(items: list[dict[str, Any]], batch_size: int, seed: int, epoch: int) -> list[list[dict[str, Any]]]:
    ordered = sorted(
        items,
        key=lambda item: (
            int(item["slot_count"]) // 32,
            random.Random(f"{seed}:{epoch}:{item['item_id']}").random(),
        ),
    )
    return [ordered[offset : offset + batch_size] for offset in range(0, len(ordered), batch_size)]


def masked_mean(values: Any, mask: Any) -> Any:
    return (values * mask).sum() / mask.sum().clamp_min(1)


def loss_and_metrics(
    model: Any,
    batch: dict[str, Any],
    *,
    gate_weight: float,
    projected_weight: float,
) -> tuple[Any, dict[str, float]]:
    import torch
    import torch.nn.functional as F

    features = batch["features"]
    raw = batch["raw"]
    target = batch["target"]
    mask = batch["mask"]
    maximum = int(batch["num_labels"].max().item()) - 1
    output = model(features, mask)
    gate = torch.sigmoid(output["gate_logit"])
    corrected = raw + gate * output["residual_classes"]
    projected = monotonic_project(corrected, mask=mask, maximum=maximum)
    residual_loss = masked_mean(F.smooth_l1_loss(corrected, target, reduction="none", beta=1.0), mask)
    projected_loss = masked_mean(F.smooth_l1_loss(projected, target, reduction="none", beta=1.0), mask)
    gate_target = ((target - raw).abs() >= 1.0).float()
    gate_loss = masked_mean(
        F.binary_cross_entropy_with_logits(output["gate_logit"], gate_target, reduction="none"),
        mask,
    )
    loss = residual_loss + projected_weight * projected_loss + gate_weight * gate_loss
    absolute = (projected.round() - target).abs()
    official_absolute = (batch["official"] - target).abs()
    raw_absolute = (raw - target).abs()
    metrics = {
        "loss": float(loss.detach()),
        "residual_loss": float(residual_loss.detach()),
        "projected_loss": float(projected_loss.detach()),
        "gate_loss": float(gate_loss.detach()),
        "decoder_mae_class": float(masked_mean(absolute, mask).detach()),
        "official_mae_class": float(masked_mean(official_absolute, mask).detach()),
        "raw_mae_class": float(masked_mean(raw_absolute, mask).detach()),
        "decoder_within_1_class": float(masked_mean((absolute <= 1).float(), mask).detach()),
    }
    return loss, metrics


def evaluate(model: Any, items: list[dict[str, Any]], *, batch_size: int, device: str) -> dict[str, Any]:
    import torch

    totals: Counter[str] = Counter()
    weight = 0
    model.eval()
    started = time.perf_counter()
    with torch.inference_mode():
        for chunk in batches(items, batch_size, 0, 0):
            batch = collate(chunk)
            batch = {key: value.to(device) if hasattr(value, "to") else value for key, value in batch.items()}
            _, metrics = loss_and_metrics(model, batch, gate_weight=0.2, projected_weight=0.5)
            slots = int(batch["mask"].sum().item())
            for key, value in metrics.items():
                totals[key] += float(value) * slots
            weight += slots
    elapsed = time.perf_counter() - started
    return {
        **{key: totals[key] / max(1, weight) for key in totals},
        "item_count": len(items),
        "slot_count": weight,
        "wall_sec": elapsed,
        "slots_per_sec": weight / max(elapsed, 1e-9),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--architecture", choices=SUPPORTED_ARCHITECTURES, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-steps", type=int, default=2500)
    parser.add_argument("--validation-every", type=int, default=100)
    parser.add_argument("--save-every", type=int, default=100)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-3)
    parser.add_argument("--gate-weight", type=float, default=0.2)
    parser.add_argument("--projected-weight", type=float, default=0.5)
    parser.add_argument("--hidden-dim", type=int, default=192)
    parser.add_argument("--layers", type=int)
    parser.add_argument("--kernel-size", type=int, default=5)
    parser.add_argument("--dropout", type=float, default=0.10)
    parser.add_argument("--max-residual-classes", type=float, default=96.0)
    parser.add_argument("--transformer-heads", type=int, default=6)
    parser.add_argument("--transformer-ffn-dim", type=int, default=768)
    parser.add_argument("--transformer-max-slots", type=int, default=4096)
    parser.add_argument("--resume", type=Path)
    parser.add_argument(
        "--validation-fallback",
        choices=("error", "song_holdout"),
        default="error",
        help="Fallback used only when cached validation items are absent.",
    )
    parser.add_argument("--validation-holdout-percent", type=float, default=10.0)
    args = parser.parse_args()

    import torch

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    if not args.device.startswith("cuda") and not args.allow_cpu:
        raise RuntimeError("production decoder training is GPU-only; --allow-cpu is test-only")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    items = load_items(args.cache_root)
    cached_split_counts = Counter(canonical_split(item.get("split")) for item in items)
    train = [item for item in items if canonical_split(item.get("split")) == "train"]
    validation = [item for item in items if canonical_split(item.get("split")) == "validation"]
    split_fallback = False
    fallback_validation_songs: list[str] = []
    if not train:
        raise ValueError(
            f"decoder training requires train items; cached split counts={dict(cached_split_counts)}"
        )
    if not validation:
        if args.validation_fallback != "song_holdout":
            raise ValueError(
                "decoder training requires validation items; "
                f"cached split counts={dict(cached_split_counts)}. "
                "Rebuild the smoke cache with split-aware sampling or pass "
                "--validation-fallback song_holdout for an explicitly recorded fallback."
            )
        train, validation, fallback_validation_songs = derive_song_holdout(
            train,
            seed=args.seed,
            percent=args.validation_holdout_percent,
        )
        split_fallback = True

    default_layers = 6 if args.architecture == "tcn" else 4
    config = BoundaryDecoderConfig(
        architecture=args.architecture,
        hidden_dim=args.hidden_dim,
        layers=args.layers if args.layers is not None else default_layers,
        kernel_size=args.kernel_size,
        dropout=args.dropout,
        max_residual_classes=args.max_residual_classes,
        transformer_heads=args.transformer_heads,
        transformer_ffn_dim=args.transformer_ffn_dim,
        transformer_max_slots=args.transformer_max_slots,
    )
    config.validate()
    model = build_model(config).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.max_steps))
    scaler = torch.amp.GradScaler("cuda", enabled=args.device.startswith("cuda"))
    step = 0
    epoch = 0
    best = math.inf
    if args.resume:
        payload = torch.load(args.resume, map_location="cpu", weights_only=False)
        resumed_config = BoundaryDecoderConfig.from_dict(payload["model_config"])
        if resumed_config != config:
            raise ValueError(f"resume config mismatch: requested={config} checkpoint={resumed_config}")
        model.load_state_dict(payload["model_state_dict"])
        if payload.get("optimizer_state_dict"):
            optimizer.load_state_dict(payload["optimizer_state_dict"])
        if payload.get("scheduler_state_dict"):
            scheduler.load_state_dict(payload["scheduler_state_dict"])
        if payload.get("scaler_state_dict"):
            scaler.load_state_dict(payload["scaler_state_dict"])
        step = int(payload.get("training_step", 0))
        epoch = int((payload.get("extra") or {}).get("epoch", 0))
        best = float((payload.get("extra") or {}).get("best_validation_mae_class", best))

    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    atomic_json(run_dir / "resolved_data.json", {
        "cache_root": str(args.cache_root.resolve()),
        "architecture": args.architecture,
        "model_config": config.__dict__,
        "parameter_count": parameter_count,
        "item_count": len(items),
        "train_item_count": len(train),
        "validation_item_count": len(validation),
        "cached_split_counts": dict(sorted(cached_split_counts.items())),
        "split_fallback": split_fallback,
        "split_fallback_kind": "song_holdout" if split_fallback else None,
        "fallback_validation_song_ids": fallback_validation_songs,
        "validation_holdout_percent": args.validation_holdout_percent if split_fallback else None,
        "unique_train_song_count": len({str(item["song_id"]) for item in train}),
        "unique_validation_song_count": len({str(item["song_id"]) for item in validation}),
    })
    started = time.perf_counter()
    while step < args.max_steps:
        model.train()
        for chunk in batches(train, args.batch_size, args.seed, epoch):
            if step >= args.max_steps:
                break
            batch = collate(chunk)
            batch = {
                key: value.to(args.device, non_blocking=True) if hasattr(value, "to") else value
                for key, value in batch.items()
            }
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
                loss, metrics = loss_and_metrics(
                    model,
                    batch,
                    gate_weight=args.gate_weight,
                    projected_weight=args.projected_weight,
                )
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            step += 1
            row = {
                "architecture": args.architecture,
                "step": step,
                "epoch": epoch,
                "lr": scheduler.get_last_lr()[0],
                "wall_sec": time.perf_counter() - started,
                **metrics,
            }
            if args.device.startswith("cuda"):
                row["cuda_max_memory_allocated_bytes"] = int(torch.cuda.max_memory_allocated())
            append_jsonl(run_dir / "metrics.jsonl", row)
            if step == 1 or step % 20 == 0:
                print(json.dumps(row, ensure_ascii=False), flush=True)
            if step % args.validation_every == 0 or step == args.max_steps:
                validation_metrics = evaluate(model, validation, batch_size=args.batch_size, device=args.device)
                validation_metrics.update({"step": step, "architecture": args.architecture})
                append_jsonl(run_dir / "validation.jsonl", validation_metrics)
                if float(validation_metrics["decoder_mae_class"]) < best:
                    best = float(validation_metrics["decoder_mae_class"])
                    save_checkpoint(
                        run_dir / "best.pt",
                        model=model,
                        config=config,
                        training_step=step,
                        optimizer_state_dict=optimizer.state_dict(),
                        scheduler_state_dict=scheduler.state_dict(),
                        scaler_state_dict=scaler.state_dict(),
                        extra={"epoch": epoch, "best_validation_mae_class": best, "validation": validation_metrics},
                    )
            if step % args.save_every == 0 or step == args.max_steps:
                save_checkpoint(
                    run_dir / "last.pt",
                    model=model,
                    config=config,
                    training_step=step,
                    optimizer_state_dict=optimizer.state_dict(),
                    scheduler_state_dict=scheduler.state_dict(),
                    scaler_state_dict=scaler.state_dict(),
                    extra={"epoch": epoch, "best_validation_mae_class": best},
                )
        epoch += 1

    final_validation = evaluate(model, validation, batch_size=args.batch_size, device=args.device)
    summary = {
        "status": "complete",
        "architecture": args.architecture,
        "model_config": config.__dict__,
        "parameter_count": parameter_count,
        "training_step": step,
        "epoch": epoch,
        "best_validation_mae_class": best,
        "final_validation": final_validation,
        "train_item_count": len(train),
        "validation_item_count": len(validation),
        "device": args.device,
        "gpu_first_contract": args.device.startswith("cuda"),
        "wall_sec": time.perf_counter() - started,
    }
    atomic_json(run_dir / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
