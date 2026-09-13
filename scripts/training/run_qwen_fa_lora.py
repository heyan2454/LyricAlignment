#!/usr/bin/env python3
"""Single resumable entry point for Qwen Forced Aligner LoRA experiments."""

from __future__ import annotations

import argparse, hashlib, json, os, random, shutil, time
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate_tolerant
from lyricalign.training.qwen_fa_model import apply_audio_lora, freeze_all, trainable_parameter_summary, unfreeze_classifier, unfreeze_projector
from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, decoded_character_predictions, move_inputs, read_jsonl


def atomic_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024): h.update(chunk)
    return h.hexdigest()


def sha256_strings(values: list[str]) -> str:
    """Hash an ordered string list without depending on JSON whitespace."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def legacy_execution_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Project schema-v2 execution identity to the historical schema."""
    return {
        "stage": identity["stage"],
        "seed": identity["seed"],
        "configured_max_steps": identity["configured_max_steps"],
        "train_items": identity["requested_train_items"],
        "validation_items": identity["requested_validation_items"],
    }


def init_from_checkpoint(model: Any, path: Path) -> int:
    """Borrow another run's trainable weights, then start a fresh optimiser and step counter.

    Continuation, not resume: resume must keep the identity of the same run, while this deliberately
    changes the data mixture and wants to know the *marginal* effect.  Starting from the official
    base instead would spend ~1000 steps relearning what the previous arm already knows, which is
    what made the first long-context arm uninformative at equal cost.
    """
    import torch

    state_file = path / "trainer_state.pt"
    if not state_file.exists():
        raise SystemExit(f"init_from_checkpoint: no trainer_state.pt under {path}")
    state = torch.load(state_file, map_location="cpu", weights_only=False)
    trainable = state.get("trainable_state") or {}
    if not trainable:
        raise SystemExit(f"init_from_checkpoint: empty trainable_state under {path}")
    current = dict(model.named_parameters())
    unknown = sorted(set(trainable) - set(current))
    if unknown:
        raise SystemExit(f"init_from_checkpoint: {len(unknown)} parameter(s) not in this model, "
                         f"e.g. {unknown[:3]}")
    with torch.no_grad():
        for name, value in trainable.items():
            target = current[name]
            target.data.copy_(value.to(target.device, target.dtype))
    return int(state.get("step", -1))


def apply_duration_oversample(rows: list[dict], *, long_sec: float, factor: int,
                              step_sec_default: float = 0.08) -> tuple[list[dict], dict[str, Any]]:
    """Replicate items that contain at least one labelled character of `long_sec` or more.

    Motivation is measured, not assumed: characters ≥1.0 s are 6.0% of the M4Singer training signal
    but 47% of the >0.2 s misses, and there are only 1,498 characters ≥2.0 s in the whole corpus.
    More optimisation steps cannot fix that (they re-see the same 1,498 examples), but re-weighting
    the sampling can, and it needs no model-code change and no new data.

    Returns the augmented list plus a record for the run's audit trail.
    """
    factor = int(factor)
    if factor <= 1:
        return list(rows), {"enabled": False, "factor": factor, "long_sec": long_sec,
                            "items": len(rows), "items_with_long": 0, "extra_slots": 0}
    def has_long(row: dict) -> bool:
        ids = row.get("timestamp_class_ids") or []
        step = float(row.get("timestamp_segment_sec", step_sec_default))
        return any((ids[2 * index + 1] - ids[2 * index]) * step >= long_sec
                   for index in range(len(ids) // 2))
    out: list[dict] = []
    with_long = 0
    for row in rows:
        out.append(row)
        if has_long(row):
            with_long += 1
            out.extend([row] * (factor - 1))
    return out, {"enabled": True, "long_sec": long_sec, "factor": factor,
                 "items": len(rows), "items_with_long": with_long,
                 "extra_slots": len(out) - len(rows), "total_slots": len(out)}


def song_sample(rows: list[dict], count: int, seed: int) -> list[dict]:
    if not count or count >= len(rows): return rows
    songs: dict[str, list[dict]] = {}
    for row in rows: songs.setdefault(str(row["song_id"]), []).append(row)
    selected: list[dict] = []
    for song in sorted(songs, key=lambda x: hashlib.sha256(f"{seed}:{x}".encode()).hexdigest()):
        selected.extend(songs[song])
        if len(selected) >= count: break
    return sorted(selected, key=lambda row: row["item_id"])


def item_sample(rows: list[dict], count: int, seed: int) -> list[dict]:
    """Fixed overfit smoke set: item-level only, selected across songs/singers."""
    return sorted(rows, key=lambda row: hashlib.sha256(f"{seed}:{row['item_id']}".encode()).hexdigest())[:count]


def run_identity(cfg: dict) -> dict[str, Any]:
    """The immutable inputs that make a resumed run comparable."""
    labels = Path(cfg["data"]["labels"])
    split = Path(cfg["data"]["split_manifest"])
    return {
        "config": yaml.safe_dump(cfg, allow_unicode=True, sort_keys=True),
        "labels": str(labels),
        "labels_sha256": sha256(labels),
        "split_manifest": str(split),
        "split_manifest_sha256": sha256(split),
    }


def verify_resume_identity(run_dir: Path, cfg: dict, execution_identity: dict[str, Any] | None = None) -> None:
    """Reject a resume when its frozen configuration, data, or run arguments changed."""
    execution_identity = execution_identity or {}
    expected = run_identity(cfg)
    config_path = run_dir / "config.yaml"
    source_path = run_dir / "source_manifest_identity.json"
    split_path = run_dir / "split_manifest_identity.json"
    execution_path = run_dir / "execution_identity.json"
    if not all(path.exists() for path in (config_path, source_path, split_path, execution_path)):
        raise RuntimeError(f"cannot resume without complete run identity: {run_dir}")
    observed_config = yaml.safe_dump(yaml.safe_load(config_path.read_text(encoding="utf-8")), allow_unicode=True, sort_keys=True)
    observed_source = json.loads(source_path.read_text(encoding="utf-8"))
    observed_split = json.loads(split_path.read_text(encoding="utf-8"))
    observed_execution = json.loads(execution_path.read_text(encoding="utf-8"))
    if observed_config != expected["config"]:
        raise RuntimeError("resume configuration differs from frozen run configuration")
    if observed_source != {"labels": expected["labels"], "labels_sha256": expected["labels_sha256"]}:
        raise RuntimeError("resume labels identity differs from frozen run identity")
    if observed_split != {"split_manifest": expected["split_manifest"], "split_manifest_sha256": expected["split_manifest_sha256"]}:
        raise RuntimeError("resume split identity differs from frozen run identity")
    compatible_execution = observed_execution == execution_identity
    if execution_identity.get("schema_version") == 2:
        compatible_execution = compatible_execution or observed_execution == legacy_execution_identity(execution_identity)
    if not compatible_execution:
        raise RuntimeError("resume execution identity differs from frozen run identity")


def write_run_identity(run_dir: Path, cfg: dict, args: Any, execution_identity: dict[str, Any] | None = None) -> None:
    execution_identity = execution_identity or {}
    run_dir.mkdir(parents=True, exist_ok=True)
    identity = run_identity(cfg)
    if not (run_dir / "config.yaml").exists():
        (run_dir / "config.yaml").write_text(identity["config"], encoding="utf-8")
        atomic_json(run_dir / "source_manifest_identity.json", {"labels": identity["labels"], "labels_sha256": identity["labels_sha256"]})
        atomic_json(run_dir / "split_manifest_identity.json", {"split_manifest": identity["split_manifest"], "split_manifest_sha256": identity["split_manifest_sha256"]})
        atomic_json(run_dir / "execution_identity.json", execution_identity)
    command = " ".join(sys.argv) + "\n"
    with (run_dir / "commands.log").open("a", encoding="utf-8") as handle:
        handle.write(command)
    if not (run_dir / "command.sh").exists():
        (run_dir / "command.sh").write_text(command, encoding="utf-8")


def checkpoint(run_dir: Path, model: Any, optimizer: Any, scheduler: Any, step: int, epoch: int, next_offset: int,
               *, save_optimizer_state: bool = True) -> Path:
    import torch
    path = run_dir / "checkpoints" / f"step-{step:06d}"
    path.mkdir(parents=True, exist_ok=True)
    trainable = {name: value.detach().cpu() for name, value in model.named_parameters() if value.requires_grad}
    payload = {"trainable_state": trainable, "step": step, "epoch": epoch, "next_offset": next_offset,
               "torch_rng": torch.get_rng_state(),
               "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
               "optimizer_state_saved": bool(save_optimizer_state)}
    if save_optimizer_state:
        payload["optimizer"] = optimizer.state_dict()
        payload["scheduler"] = scheduler.state_dict()
    torch.save(payload, path / "trainer_state.pt")
    projector = {name: value.detach().cpu() for name, value in model.named_parameters() if "multi_modal_projector" in name}
    if projector: torch.save(projector, path / "projector.pt")
    if hasattr(model, "peft_config"): model.save_pretrained(path / "adapter")
    atomic_json(path / "checkpoint_identity.json", {"step": step, "epoch": epoch, "next_offset": next_offset,
        "format": "trainable_parameters_plus_projector_and_optional_peft_adapter", "base_model_saved": False})
    return path


def restore(path: Path, model: Any, optimizer: Any, scheduler: Any) -> tuple[int, int, int]:
    import torch
    state = torch.load(path / "trainer_state.pt", map_location="cpu", weights_only=False)
    current = dict(model.named_parameters())
    missing = set(state["trainable_state"]) - set(current)
    if missing: raise RuntimeError(f"checkpoint parameters unavailable: {sorted(missing)[:3]}")
    for name, value in state["trainable_state"].items(): current[name].data.copy_(value.to(current[name].device, current[name].dtype))
    if "optimizer" in state and "scheduler" in state:
        optimizer.load_state_dict(state["optimizer"]); scheduler.load_state_dict(state["scheduler"])
    else:
        raise RuntimeError(
            "checkpoint has no optimizer state (written in weights-only mode): resume from a "
            "full-state checkpoint, or start a fresh run rather than silently restarting Adam"
        )
    torch.set_rng_state(state["torch_rng"])
    if state["cuda_rng"] is not None and torch.cuda.is_available(): torch.cuda.set_rng_state_all(state["cuda_rng"])
    return int(state["step"]), int(state["epoch"]), int(state.get("next_offset", 0))


def evaluate(model: Any, processor: Any, collator: Any, records: list[dict], references: dict[str, list[dict]], *, device: str, dtype: Any, batch_size: int) -> dict:
    import torch
    model.eval(); predicted: list[dict] = []; loss_sum = 0.0; batches = 0
    with torch.no_grad():
        for offset in range(0, len(records), batch_size):
            chunk = records[offset:offset + batch_size]; inputs, words = collator(chunk); batch = move_inputs(inputs, device, dtype)
            output = model(**batch); loss_sum += float(output.loss); batches += 1
            predicted.extend(decoded_character_predictions(processor, output.logits, batch["input_ids"], words, model.config.timestamp_token_id, chunk))
            if (offset // batch_size + 1) % 100 == 0:
                print(json.dumps({"evaluation_batches_completed": offset // batch_size + 1, "evaluation_batches_total": (len(records) + batch_size - 1) // batch_size}), flush=True)
    reference = [row for record in records for row in references[record["item_id"]]]
    return {"loss": loss_sum / max(1, batches), "metric": evaluate_tolerant(reference, predicted), "prediction_count": len(predicted)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True); parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=["overfit", "r0", "r1", "r2", "r3"], required=True)
    parser.add_argument("--resume", type=Path); parser.add_argument("--overwrite", action="store_true"); parser.add_argument("--max-steps", type=int); parser.add_argument("--device", default="cuda"); parser.add_argument("--seed", type=int)
    parser.add_argument("--train-items", type=int); parser.add_argument("--validation-items", type=int)
    parser.add_argument("--stop-after-step", type=int, help="Planned resumability smoke stop; scheduler still uses configured max steps.")
    parser.add_argument("--cache-dir", type=Path); parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args(); cfg = yaml.safe_load(args.config.read_text(encoding="utf-8")); run_dir = args.run_dir
    stage_cfg = cfg["stages"][args.stage]
    seed = args.seed if args.seed is not None else int(cfg["training"]["seed"])
    configured_max_steps = 0 if args.stage == "r0" else int(args.max_steps or stage_cfg["max_steps"])
    train_limit = int(args.train_items if args.train_items is not None else stage_cfg.get("train_items", 0))
    validation_limit = int(args.validation_items if args.validation_items is not None else stage_cfg.get("validation_items", 0))
    execution_identity = {
        "schema_version": 2,
        "stage": args.stage,
        "seed": seed,
        "configured_max_steps": configured_max_steps,
        "requested_train_items": train_limit,
        "requested_validation_items": validation_limit,
        "zero_limit_semantics": "0 means use the complete frozen split, not zero selected items",
    }
    if run_dir.exists() and any(run_dir.iterdir()) and not args.resume and not args.overwrite: raise SystemExit(f"run exists; use --resume or --overwrite: {run_dir}")
    if args.overwrite and run_dir.exists(): shutil.rmtree(run_dir)
    if args.resume:
        if args.resume.parent.parent != run_dir:
            raise RuntimeError("resume checkpoint must belong to --run-dir")
        verify_resume_identity(run_dir, cfg, execution_identity)
    write_run_identity(run_dir, cfg, args, execution_identity)
    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor, get_cosine_schedule_with_warmup
    random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16")); model_cfg = cfg["model"]
    cache_dir = args.cache_dir or (Path(os.environ["HF_HUB_CACHE"]) if os.environ.get("HF_HUB_CACHE") else None)
    local_files_only = args.local_files_only or os.environ.get("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes", "on"}
    load_kwargs = {"revision": model_cfg["revision"], "local_files_only": local_files_only}
    if cache_dir is not None: load_kwargs["cache_dir"] = str(cache_dir)
    processor = AutoProcessor.from_pretrained(model_cfg["id"], **load_kwargs)
    model = AutoModelForTokenClassification.from_pretrained(model_cfg["id"], dtype=cfg["training"].get("dtype", "bfloat16"), **load_kwargs).to(args.device)
    freeze_all(model)
    if args.stage == "overfit": unfreeze_projector(model); unfreeze_classifier(model)
    elif args.stage in {"r1", "r2", "r3"}: unfreeze_projector(model)
    targets: list[str] = []
    if args.stage in {"r2", "r3"}:
        model, targets = apply_audio_lora(model, scope="top_half" if args.stage == "r2" else "all")
        # PEFT freezes non-adapter parameters during wrapping; the experiment
        # explicitly keeps the projector fully trainable.
        for name, parameter in model.named_parameters():
            if "multi_modal_projector" in name: parameter.requires_grad = True
    atomic_json(run_dir / "lora_target_modules.json", {"stage": args.stage, "targets": targets})
    atomic_json(run_dir / "trainable_parameter_summary.json", trainable_parameter_summary(model))
    init_path = cfg["training"].get("init_from_checkpoint")
    if init_path:
        loaded_from = init_from_checkpoint(model, Path(str(init_path)))
        atomic_json(run_dir / "init_from_checkpoint.json",
                    {"path": str(init_path), "loaded_step": loaded_from,
                     "semantics": "weights borrowed; optimiser state and step counter start fresh"})
        print(json.dumps({"init_from_checkpoint": {"path": str(init_path), "step": loaded_from}}), flush=True)
    atomic_json(run_dir / "model_identity.json", {"model_id": model_cfg["id"], "model_revision": model_cfg["revision"], "timestamp_token_id": model.config.timestamp_token_id, "num_labels": model.config.num_labels})
    labels = read_jsonl(Path(cfg["data"]["labels"])); chars = read_jsonl(Path(cfg["data"]["characters"])); references: dict[str, list[dict]] = {}
    for row in chars: references.setdefault(row["item_id"], []).append(row)
    available_train = [row for row in labels if row["split"] == "train"]
    available_valid = [row for row in labels if row["split"] == "validation"]
    train = song_sample(available_train, train_limit, seed)
    concat_cfg = dict(cfg["training"].get("concat_samples") or {})
    oversample_cfg = dict(cfg["training"].get("duration_oversample") or {})
    train, augmentation = apply_duration_oversample(
        train, long_sec=float(oversample_cfg.get("long_sec", 1.0)),
        factor=int(oversample_cfg.get("factor", 1)))
    atomic_json(run_dir / "training_augmentation.json", augmentation)
    if concat_cfg.get("enabled"):
        if oversample_cfg.get("factor", 1) > 1:
            raise SystemExit("concat_samples and duration_oversample are mutually exclusive: "
                             "picking one variable per experiment keeps the arms comparable")
        from lyricalign.training.qwen_fa_concat import group_concat_records
        train, concat_stats = group_concat_records(
            train, target_sec=float(concat_cfg.get("target_sec", 20.0)),
            max_sec=float(concat_cfg.get("max_sec", 28.0)), gap_sec=float(concat_cfg.get("gap_sec", 0.4)))
        atomic_json(run_dir / "concat_train_view.json", concat_stats)
        print(json.dumps({"concat_view": concat_stats}), flush=True)
    valid = available_valid
    if args.stage == "overfit":
        train = item_sample(available_train, train_limit, seed)
    if validation_limit:
        valid = item_sample(valid, validation_limit, seed)
    atomic_json(run_dir / "resolved_dataset_identity.json", {
        "schema_version": 1,
        "available_train_items": len(available_train),
        "available_validation_items": len(available_valid),
        "selected_train_items": len(train),
        "selected_validation_items": len(valid),
        "selected_train_item_ids_sha256": sha256_strings([str(row["item_id"]) for row in train]),
        "selected_validation_item_ids_sha256": sha256_strings([str(row["item_id"]) for row in valid]),
        "requested_train_items": train_limit,
        "requested_validation_items": validation_limit,
        "seed": seed,
        "stage": args.stage,
    })
    loss_weighting = dict(cfg["training"].get("loss_weighting") or {})
    if loss_weighting.get("enabled"):
        from lyricalign.training.timestamp_loss import weighted_timestamp_loss  # noqa: F401
        loss_weighting = {"long_sec": float(loss_weighting.get("long_sec", 1.0)),
                          "weight": float(loss_weighting.get("weight", 1.0)),
                          "step_sec": float(cfg["training"].get("timestamp_segment_sec", 0.08))}
        atomic_json(run_dir / "loss_weighting.json", {**loss_weighting,
                    "semantics": "per-character slot weights on the training CE only; validation loss stays unweighted so arms remain comparable"})
        print(json.dumps({"loss_weighting": loss_weighting}), flush=True)
    else:
        loss_weighting = None
    collator_cls = QwenFABatchCollator
    if concat_cfg.get("enabled"):
        from lyricalign.training.qwen_fa_concat import QwenFAConcatCollator
        collator_cls = QwenFAConcatCollator
    collator = collator_cls(processor, audio_root=Path(cfg["data"]["audio_root"]),
                            language=cfg["data"]["language"], timestamp_token_id=model.config.timestamp_token_id,
                            **({"gap_sec": float(concat_cfg.get("gap_sec", 0.4))} if concat_cfg.get("enabled") else {}))
    evaluation_batch = int(cfg["training"].get("evaluation_micro_batch_size", cfg["training"]["micro_batch_size"]))
    if args.stage == "r0":
        result = evaluate(model, processor, collator, valid, references, device=args.device, dtype=dtype, batch_size=evaluation_batch)
        atomic_json(run_dir / "evaluation.json", result); print(json.dumps(result, ensure_ascii=False)); return
    trainable = [p for p in model.parameters() if p.requires_grad]
    if args.stage in {"r2", "r3"}:
        projector = [p for name, p in model.named_parameters() if p.requires_grad and "multi_modal_projector" in name]
        adapters = [p for name, p in model.named_parameters() if p.requires_grad and "lora_" in name]
        if not projector or not adapters: raise RuntimeError("R2/R3 must have both trainable projector and LoRA parameters")
        optimizer = torch.optim.AdamW([
            {"params": projector, "lr": float(cfg["training"]["projector_lr"])},
            {"params": adapters, "lr": float(cfg["training"]["lora_lr"])},
        ], weight_decay=float(cfg["training"]["weight_decay"]))
    else:
        optimizer = torch.optim.AdamW(trainable, lr=float(cfg["training"]["projector_lr"]), weight_decay=float(cfg["training"]["weight_decay"]))
    max_steps = configured_max_steps
    run_until_step = min(max_steps, int(args.stop_after_step)) if args.stop_after_step is not None else max_steps
    if run_until_step < 1: raise ValueError("run target must be positive")
    lr_cfg = dict((cfg.get("training") or {}).get("lr_schedule") or {})
    if str(lr_cfg.get("type", "cosine")) == "cyclic_cosine":
        from lyricalign.training.eval_funnel_loop import CyclicCosineScheduler
        scheduler = CyclicCosineScheduler(
            optimizer, cycle_len=int(lr_cfg.get("cycle_len", 2000)),
            warmup_ratio=float(cfg["training"]["warmup_ratio"]),
            cycle_peak_decay=float(lr_cfg.get("cycle_peak_decay", 1.0)))
    else:
        scheduler = get_cosine_schedule_with_warmup(optimizer, int(max_steps * float(cfg["training"]["warmup_ratio"])), max_steps)
    # funnelled validation: cheap screen for many candidates, full set for few, each level once
    funnel_cfg = dict((cfg.get("training") or {}).get("eval_funnel") or {})
    funnel_enabled = bool(funnel_cfg.get("enabled"))
    planner = subsets = funnel_selection = None
    l3_rounds: list[dict[str, Any]] = []

    def _log_funnel(record: dict[str, Any]) -> None:
        with (run_dir / "funnel_evals.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    if funnel_enabled:
        from lyricalign.training.eval_funnel_loop import build_funnel, early_stop_decision, run_pending_evals
        planner, subsets, funnel_meta = build_funnel(cfg, valid, run_dir)
        funnel_selection = funnel_meta["selection"]
        atomic_json(run_dir / "FUNNEL_CONFIG.json", funnel_meta)
    step, epoch, resume_offset = (0, 0, 0) if not args.resume else restore(args.resume, model, optimizer, scheduler)
    micro = int(cfg["training"]["micro_batch_size"]); accum = int(cfg["training"]["gradient_accumulation"]); metrics_path = run_dir / "metrics.jsonl"; started = time.time(); model.train()
    best_path = run_dir / "best_checkpoint.json"
    best_metric = json.loads(best_path.read_text(encoding="utf-8"))["song_macro_boundary_mae_sec"] if best_path.exists() else float("inf")
    last_validation = None
    last_validation_step: int | None = None
    while step < run_until_step:
        accumulated_loss = 0.0
        ordered = sorted(train, key=lambda row: hashlib.sha256(f"{seed}:{epoch}:{row['item_id']}".encode()).hexdigest())
        for offset in range(resume_offset, len(ordered), micro):
            chunk = ordered[offset:offset + micro]; inputs, _ = collator(chunk); moved = move_inputs(inputs, args.device, dtype); output = model(**moved)
            # weighted path is opt-in via training.loss_weighting; with weight=1 it provably
            # reproduces the plain mean cross-entropy (tests/training/test_timestamp_loss.py)
            loss = weighted_timestamp_loss(output.logits, moved["labels"], **loss_weighting) if loss_weighting else output.loss
            (loss / accum).backward(); accumulated_loss += float(loss.detach())
            if ((offset // micro) + 1) % accum: continue
            torch.nn.utils.clip_grad_norm_(trainable, float(cfg["training"]["max_grad_norm"])); optimizer.step(); scheduler.step(); optimizer.zero_grad(set_to_none=True); step += 1
            line = {"step": step, "epoch": epoch, "training_loss": accumulated_loss / accum, "lr": scheduler.get_last_lr()[0], "wall_sec": time.time() - started}
            with metrics_path.open("a", encoding="utf-8") as f: f.write(json.dumps(line) + "\n")
            accumulated_loss = 0.0
            next_offset = offset + micro
            if step % int(cfg["training"]["save_steps"]) == 0 or step == max_steps or step == run_until_step:
                free_gb = shutil.disk_usage(run_dir).free / 1e9
                keep_full = bool(cfg["training"].get("save_full_state", True)) and free_gb >= float(
                    cfg["training"].get("disk_floor_gb", 20.0))
                checkpoint(run_dir, model, optimizer, scheduler, step, epoch, next_offset,
                           save_optimizer_state=keep_full)
                if funnel_enabled and planner.register(step):
                    run_pending_evals(
                        planner, step=step, model=model, processor=processor, collator=collator,
                        subsets=subsets, references=references, device=args.device, dtype=dtype,
                        batch_size=evaluation_batch,
                        segment_sec=float(cfg["training"].get("timestamp_segment_sec", 0.08)),
                        selection=funnel_selection, run_dir=run_dir, log=_log_funnel)
                    # Round bookkeeping runs on every `l3_every` boundary, not only when a *new*
                    # full-set evaluation happened: otherwise a saturated funnel never produces
                    # another L3 job and the early-stop rule can never fire (that is exactly what
                    # happened in the first from-official run).
                    if step % int(planner.l3_every) == 0:
                        top = planner.best("l3") or planner.best("l2") or planner.best("l1")
                        if top is not None:
                            l3_rounds.append({"step": step, "best": top[1], "best_se": top[2]})
                            decision = early_stop_decision(
                                l3_rounds, patience_cycles=int(funnel_cfg.get("patience_cycles", 2)),
                                min_gain_se=float(funnel_cfg.get("min_gain_se", 1.0)))
                            atomic_json(run_dir / "EARLY_STOP.json",
                                        {"history": l3_rounds, "decision": decision})
                            if decision["stop"]:
                                run_until_step = step
            if step % int(cfg["training"]["eval_steps"]) == 0:
                validation = evaluate(model, processor, collator, valid, references, device=args.device, dtype=dtype, batch_size=evaluation_batch)
                validation["evaluation_step"] = step
                validation["evaluation_trigger"] = "periodic"
                last_validation = validation
                last_validation_step = step
                atomic_json(run_dir / f"validation_step_{step:06d}.json", validation)
                candidate = validation["metric"]["song_macro_boundary_mae_sec"]
                with metrics_path.open("a", encoding="utf-8") as f: f.write(json.dumps({"step": step, "validation": validation}) + "\n")
                if candidate < best_metric:
                    best_metric = candidate
                    atomic_json(best_path, {"step": step, "checkpoint": str(run_dir / "checkpoints" / f"step-{step:06d}"), "song_macro_boundary_mae_sec": candidate})
                model.train()
            if step >= run_until_step: break
        epoch += 1
        resume_offset = 0
    terminal_validation_path = run_dir / f"validation_step_{step:06d}.json"
    if last_validation is None and terminal_validation_path.exists():
        last_validation = json.loads(terminal_validation_path.read_text(encoding="utf-8"))
        last_validation_step = int(last_validation.get("evaluation_step", step))
    if last_validation_step != step:
        # A terminal step that is not divisible by eval_steps must still enter
        # validation-only checkpoint selection. This prevents a completed run
        # from reporting a stale periodic evaluation.
        terminal_validation = evaluate(
            model, processor, collator, valid, references,
            device=args.device, dtype=dtype, batch_size=evaluation_batch,
        )
        terminal_validation["evaluation_step"] = step
        terminal_validation["evaluation_trigger"] = "terminal"
        atomic_json(terminal_validation_path, terminal_validation)
        with metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"step": step, "validation": terminal_validation, "trigger": "terminal"}) + "\n")
        candidate = terminal_validation["metric"]["song_macro_boundary_mae_sec"]
        if candidate < best_metric:
            best_metric = candidate
            atomic_json(best_path, {
                "step": step,
                "checkpoint": str(run_dir / "checkpoints" / f"step-{step:06d}"),
                "song_macro_boundary_mae_sec": candidate,
                "selection_split": "validation",
                "evaluation_trigger": "terminal",
            })
        last_validation = terminal_validation
        last_validation_step = step
    result = last_validation
    if result is None:
        raise RuntimeError("validation result was not produced")
    atomic_json(run_dir / "evaluation.json", result)
    if args.stage == "overfit":
        atomic_json(run_dir / "training_evaluation.json", evaluate(model, processor, collator, train, references, device=args.device, dtype=dtype, batch_size=evaluation_batch))
    atomic_json(run_dir / "runtime_summary.json", {"stage": args.stage, "steps": step, "configured_max_steps": max_steps, "completed": step >= max_steps, "planned_stop": args.stop_after_step, "epochs": epoch, "wall_sec": time.time() - started, "train_items": len(train), "validation_items": len(valid), "seed": seed})
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__": main()
