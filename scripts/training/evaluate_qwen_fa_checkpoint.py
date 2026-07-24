#!/usr/bin/env python3
"""Evaluate raw, projector-only, or projector+LoRA Qwen FA models.

The evaluator is intentionally checkpoint-kind aware so R0, R1 and R2 use the
same processor, label, decode and metric path.  Output is written to a caller
provided directory; orchestration code should use a temporary directory and an
atomic rename when a final artifact is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate_tolerant
from lyricalign.training.qwen_fa_runtime import (
    QwenFABatchCollator,
    decoded_character_predictions,
    move_inputs,
    read_jsonl,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_kind(requested: str, checkpoint: Path | None) -> str:
    if requested != "auto":
        return requested
    if checkpoint is None:
        return "raw"
    if (checkpoint / "adapter" / "adapter_config.json").is_file():
        return "lora"
    if (checkpoint / "projector.pt").is_file():
        return "projector"
    raise ValueError(f"cannot infer checkpoint kind from: {checkpoint}")


def load_projector(model: Any, checkpoint: Path) -> dict[str, str]:
    import torch

    projector_path = checkpoint / "projector.pt"
    if not projector_path.is_file():
        raise FileNotFoundError(f"projector checkpoint missing: {projector_path}")
    saved = torch.load(projector_path, map_location="cpu", weights_only=True)
    parameters = dict(model.named_parameters())
    missing = set(saved) - set(parameters)
    if missing:
        raise RuntimeError(f"projector checkpoint names not found: {sorted(missing)[:5]}")
    for name, value in saved.items():
        parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))
    return {"projector_path": str(projector_path), "projector_sha256": sha256(projector_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-ForcedAligner-0.6B-hf")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument(
        "--checkpoint-kind",
        choices=("auto", "raw", "projector", "lora"),
        default="auto",
        help="auto infers raw/projector/LoRA from checkpoint contents",
    )
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--split", help="Evaluate only this frozen split, for example test.")
    parser.add_argument("--max-items", type=int, default=0, help="Deterministic item limit for smoke only.")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--evaluation-role", default="qwen_fa_evaluation")
    args = parser.parse_args()

    if args.batch_size < 1:
        raise ValueError("--batch-size must be positive")
    if args.max_items < 0:
        raise ValueError("--max-items must be non-negative")

    checkpoint_kind = resolve_kind(args.checkpoint_kind, args.checkpoint)
    if checkpoint_kind == "raw" and args.checkpoint is not None:
        raise ValueError("raw evaluation must not receive --checkpoint")
    if checkpoint_kind != "raw" and args.checkpoint is None:
        raise ValueError(f"{checkpoint_kind} evaluation requires --checkpoint")

    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor

    cache_dir = args.cache_dir or (
        Path(os.environ["HF_HUB_CACHE"]) if os.environ.get("HF_HUB_CACHE") else None
    )
    local_files_only = args.local_files_only or env_true("HF_HUB_OFFLINE")
    load_kwargs: dict[str, Any] = {
        "revision": args.revision,
        "local_files_only": local_files_only,
    }
    if cache_dir is not None:
        load_kwargs["cache_dir"] = str(cache_dir)

    processor = AutoProcessor.from_pretrained(args.model, **load_kwargs)
    base = AutoModelForTokenClassification.from_pretrained(
        args.model,
        dtype="bfloat16",
        **load_kwargs,
    )

    checkpoint_identity: dict[str, Any] = {}
    if checkpoint_kind == "lora":
        from peft import PeftModel

        assert args.checkpoint is not None
        adapter_dir = args.checkpoint / "adapter"
        adapter_model = adapter_dir / "adapter_model.safetensors"
        adapter_config = adapter_dir / "adapter_config.json"
        if not adapter_model.is_file() or not adapter_config.is_file():
            raise FileNotFoundError(f"incomplete LoRA adapter: {adapter_dir}")
        model = PeftModel.from_pretrained(base, adapter_dir)
        checkpoint_identity.update(
            {
                "adapter_dir": str(adapter_dir),
                "adapter_model_sha256": sha256(adapter_model),
                "adapter_config_sha256": sha256(adapter_config),
            }
        )
        checkpoint_identity.update(load_projector(model, args.checkpoint))
    elif checkpoint_kind == "projector":
        assert args.checkpoint is not None
        model = base
        checkpoint_identity.update(load_projector(model, args.checkpoint))
    else:
        model = base

    model = model.to(args.device)
    dtype = torch.bfloat16

    records = read_jsonl(args.labels)
    if args.split:
        records = [row for row in records if row.get("split") == args.split]
    records = sorted(records, key=lambda row: str(row["item_id"]))
    if args.max_items:
        records = records[: args.max_items]
    if not records:
        raise ValueError("evaluation selection is empty")
    missing_label_fields = [
        str(row.get("item_id"))
        for row in records
        if "timestamp_class_ids" not in row or "lyrics_normalized" not in row
    ]
    if missing_label_fields:
        raise ValueError(
            "labels are not Qwen FA derived labels; missing timestamp_class_ids/lyrics_normalized "
            f"for examples: {missing_label_fields[:3]}"
        )

    character_rows = read_jsonl(args.characters)
    by_item: dict[str, list[dict[str, Any]]] = {}
    for row in character_rows:
        by_item.setdefault(str(row["item_id"]), []).append(row)
    missing_references = [str(row["item_id"]) for row in records if str(row["item_id"]) not in by_item]
    if missing_references:
        raise ValueError(f"missing character references for: {missing_references[:3]}")

    collator = QwenFABatchCollator(
        processor,
        audio_root=args.audio_root,
        language=args.language,
        timestamp_token_id=model.config.timestamp_token_id,
    )
    predictions: list[dict[str, Any]] = []
    losses: list[float] = []
    model.eval()
    total_batches = (len(records) + args.batch_size - 1) // args.batch_size
    with torch.no_grad():
        for batch_index, start in enumerate(range(0, len(records), args.batch_size), start=1):
            chunk = records[start : start + args.batch_size]
            inputs, words = collator(chunk)
            batch = move_inputs(inputs, args.device, dtype)
            output = model(**batch)
            losses.append(float(output.loss))
            predictions.extend(
                decoded_character_predictions(
                    processor,
                    output.logits,
                    batch["input_ids"],
                    words,
                    model.config.timestamp_token_id,
                    chunk,
                )
            )
            if batch_index == 1 or batch_index % 100 == 0 or batch_index == total_batches:
                print(
                    json.dumps(
                        {
                            "evaluation_batches_completed": batch_index,
                            "evaluation_batches_total": total_batches,
                            "checkpoint_kind": checkpoint_kind,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    reference = [
        row
        for record in records
        for row in sorted(
            by_item[str(record["item_id"])], key=lambda item: int(item["character_index"])
        )
    ]
    metrics = evaluate_tolerant(reference, predictions)
    result = {"loss": sum(losses) / len(losses), "metric": metrics}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions),
        encoding="utf-8",
    )
    (args.out_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    identity: dict[str, Any] = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_role": args.evaluation_role,
        "model_id": args.model,
        "model_revision": args.revision,
        "checkpoint_kind": checkpoint_kind,
        "checkpoint_path": str(args.checkpoint) if args.checkpoint else None,
        "labels_path": str(args.labels),
        "labels_sha256": sha256(args.labels),
        "characters_path": str(args.characters),
        "characters_sha256": sha256(args.characters),
        "audio_root": str(args.audio_root),
        "split": args.split,
        "max_items": args.max_items,
        "item_count": len(records),
        "character_count": len(reference),
        "batch_size": args.batch_size,
        "device": args.device,
        "language": args.language,
        "cache_dir": str(cache_dir) if cache_dir else None,
        "local_files_only": local_files_only,
        "timestamp_token_id": int(model.config.timestamp_token_id),
        "num_labels": int(model.config.num_labels),
    }
    identity.update(checkpoint_identity)
    if args.checkpoint is not None:
        checkpoint_file = args.checkpoint / "checkpoint_identity.json"
        if checkpoint_file.is_file():
            identity["checkpoint_identity_sha256"] = sha256(checkpoint_file)
    (args.out_dir / "evaluation_identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
