#!/usr/bin/env python3
"""Single resumable entry point for Qwen Forced Aligner LoRA experiments."""

from __future__ import annotations

import argparse, hashlib, json, random, shutil, time
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


def verify_resume_identity(run_dir: Path, cfg: dict) -> None:
    """Reject a resume when its frozen configuration or data changed."""
    expected = run_identity(cfg)
    config_path = run_dir / "config.yaml"
    source_path = run_dir / "source_manifest_identity.json"
    split_path = run_dir / "split_manifest_identity.json"
    if not all(path.exists() for path in (config_path, source_path, split_path)):
        raise RuntimeError(f"cannot resume without complete run identity: {run_dir}")
    observed_config = yaml.safe_dump(yaml.safe_load(config_path.read_text(encoding="utf-8")), allow_unicode=True, sort_keys=True)
    observed_source = json.loads(source_path.read_text(encoding="utf-8"))
    observed_split = json.loads(split_path.read_text(encoding="utf-8"))
    if observed_config != expected["config"]:
        raise RuntimeError("resume configuration differs from frozen run configuration")
    if observed_source != {"labels": expected["labels"], "labels_sha256": expected["labels_sha256"]}:
        raise RuntimeError("resume labels identity differs from frozen run identity")
    if observed_split != {"split_manifest": expected["split_manifest"], "split_manifest_sha256": expected["split_manifest_sha256"]}:
        raise RuntimeError("resume split identity differs from frozen run identity")


def write_run_identity(run_dir: Path, cfg: dict, args: Any) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    identity = run_identity(cfg)
    if not (run_dir / "config.yaml").exists():
        (run_dir / "config.yaml").write_text(identity["config"], encoding="utf-8")
        atomic_json(run_dir / "source_manifest_identity.json", {"labels": identity["labels"], "labels_sha256": identity["labels_sha256"]})
        atomic_json(run_dir / "split_manifest_identity.json", {"split_manifest": identity["split_manifest"], "split_manifest_sha256": identity["split_manifest_sha256"]})
    command = " ".join(sys.argv) + "\n"
    with (run_dir / "commands.log").open("a", encoding="utf-8") as handle:
        handle.write(command)
    if not (run_dir / "command.sh").exists():
        (run_dir / "command.sh").write_text(command, encoding="utf-8")


def checkpoint(run_dir: Path, model: Any, optimizer: Any, scheduler: Any, step: int, epoch: int, next_offset: int) -> Path:
    import torch
    path = run_dir / "checkpoints" / f"step-{step:06d}"
    path.mkdir(parents=True, exist_ok=True)
    trainable = {name: value.detach().cpu() for name, value in model.named_parameters() if value.requires_grad}
    torch.save({"trainable_state": trainable, "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                "step": step, "epoch": epoch, "next_offset": next_offset,
                "torch_rng": torch.get_rng_state(), "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}, path / "trainer_state.pt")
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
    optimizer.load_state_dict(state["optimizer"]); scheduler.load_state_dict(state["scheduler"])
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
    args = parser.parse_args(); cfg = yaml.safe_load(args.config.read_text(encoding="utf-8")); run_dir = args.run_dir
    if run_dir.exists() and any(run_dir.iterdir()) and not args.resume and not args.overwrite: raise SystemExit(f"run exists; use --resume or --overwrite: {run_dir}")
    if args.overwrite and run_dir.exists(): shutil.rmtree(run_dir)
    if args.resume:
        if args.resume.parent.parent != run_dir:
            raise RuntimeError("resume checkpoint must belong to --run-dir")
        verify_resume_identity(run_dir, cfg)
    write_run_identity(run_dir, cfg, args)
    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor, get_cosine_schedule_with_warmup
    seed = args.seed if args.seed is not None else int(cfg["training"]["seed"]); random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16")); model_cfg = cfg["model"]
    processor = AutoProcessor.from_pretrained(model_cfg["id"], revision=model_cfg["revision"])
    model = AutoModelForTokenClassification.from_pretrained(model_cfg["id"], revision=model_cfg["revision"], dtype=cfg["training"].get("dtype", "bfloat16")).to(args.device)
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
    atomic_json(run_dir / "model_identity.json", {"model_id": model_cfg["id"], "model_revision": model_cfg["revision"], "timestamp_token_id": model.config.timestamp_token_id, "num_labels": model.config.num_labels})
    labels = read_jsonl(Path(cfg["data"]["labels"])); chars = read_jsonl(Path(cfg["data"]["characters"])); references: dict[str, list[dict]] = {}
    for row in chars: references.setdefault(row["item_id"], []).append(row)
    train = [row for row in labels if row["split"] == "train"]; valid = [row for row in labels if row["split"] == "validation"]
    limit = int(cfg["stages"][args.stage].get("train_items", 0)); train = song_sample(train, limit, seed)
    if args.stage == "overfit":
        train = item_sample([row for row in labels if row["split"] == "train"], limit, seed)
        valid = item_sample(valid, int(cfg["stages"][args.stage]["validation_items"]), seed)
    collator = QwenFABatchCollator(processor, audio_root=Path(cfg["data"]["audio_root"]), language=cfg["data"]["language"], timestamp_token_id=model.config.timestamp_token_id)
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
    max_steps = args.max_steps or int(cfg["stages"][args.stage]["max_steps"]); scheduler = get_cosine_schedule_with_warmup(optimizer, int(max_steps * float(cfg["training"]["warmup_ratio"])), max_steps)
    step, epoch, resume_offset = (0, 0, 0) if not args.resume else restore(args.resume, model, optimizer, scheduler)
    micro = int(cfg["training"]["micro_batch_size"]); accum = int(cfg["training"]["gradient_accumulation"]); metrics_path = run_dir / "metrics.jsonl"; started = time.time(); model.train()
    best_path = run_dir / "best_checkpoint.json"
    best_metric = json.loads(best_path.read_text(encoding="utf-8"))["song_macro_boundary_mae_sec"] if best_path.exists() else float("inf")
    while step < max_steps:
        accumulated_loss = 0.0
        ordered = sorted(train, key=lambda row: hashlib.sha256(f"{seed}:{epoch}:{row['item_id']}".encode()).hexdigest())
        for offset in range(resume_offset, len(ordered), micro):
            chunk = ordered[offset:offset + micro]; inputs, _ = collator(chunk); output = model(**move_inputs(inputs, args.device, dtype)); (output.loss / accum).backward(); accumulated_loss += float(output.loss.detach())
            if ((offset // micro) + 1) % accum: continue
            torch.nn.utils.clip_grad_norm_(trainable, float(cfg["training"]["max_grad_norm"])); optimizer.step(); scheduler.step(); optimizer.zero_grad(set_to_none=True); step += 1
            line = {"step": step, "epoch": epoch, "training_loss": accumulated_loss / accum, "lr": scheduler.get_last_lr()[0], "wall_sec": time.time() - started}
            with metrics_path.open("a", encoding="utf-8") as f: f.write(json.dumps(line) + "\n")
            accumulated_loss = 0.0
            next_offset = offset + micro
            if step % int(cfg["training"]["save_steps"]) == 0 or step == max_steps:
                checkpoint(run_dir, model, optimizer, scheduler, step, epoch, next_offset)
            if step % int(cfg["training"]["eval_steps"]) == 0:
                validation = evaluate(model, processor, collator, valid, references, device=args.device, dtype=dtype, batch_size=evaluation_batch)
                atomic_json(run_dir / f"validation_step_{step:06d}.json", validation)
                candidate = validation["metric"]["song_macro_boundary_mae_sec"]
                with metrics_path.open("a", encoding="utf-8") as f: f.write(json.dumps({"step": step, "validation": validation}) + "\n")
                if candidate < best_metric:
                    best_metric = candidate
                    atomic_json(best_path, {"step": step, "checkpoint": str(run_dir / "checkpoints" / f"step-{step:06d}"), "song_macro_boundary_mae_sec": candidate})
                model.train()
            if step >= max_steps: break
        epoch += 1
        resume_offset = 0
    result = evaluate(model, processor, collator, valid, references, device=args.device, dtype=dtype, batch_size=evaluation_batch)
    atomic_json(run_dir / "evaluation.json", result)
    if args.stage == "overfit":
        atomic_json(run_dir / "training_evaluation.json", evaluate(model, processor, collator, train, references, device=args.device, dtype=dtype, batch_size=evaluation_batch))
    atomic_json(run_dir / "runtime_summary.json", {"stage": args.stage, "steps": step, "epochs": epoch, "wall_sec": time.time() - started, "train_items": len(train), "validation_items": len(valid)})
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__": main()
