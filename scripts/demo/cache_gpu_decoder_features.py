#!/usr/bin/env python3
"""Cache compact M4Singer Qwen timestamp evidence for GPU decoder training.

Qwen inference and feature extraction run on CUDA.  Only compact per-slot
features, raw/official/GT timestamp classes, and identities are saved.  Full
logits and audio are never copied into the cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.gpu_boundary_decoder import FEATURE_SCHEMA, build_slot_features
from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, move_inputs, read_jsonl


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_kind(requested: str, checkpoint: Path | None) -> str:
    if requested != "auto":
        return requested
    if checkpoint is None:
        return "raw"
    if (checkpoint / "adapter" / "adapter_config.json").is_file():
        return "lora"
    if (checkpoint / "projector.pt").is_file():
        return "projector"
    raise ValueError(f"cannot infer checkpoint kind: {checkpoint}")


def load_projector(model: Any, checkpoint: Path) -> None:
    import torch

    saved = torch.load(checkpoint / "projector.pt", map_location="cpu", weights_only=True)
    parameters = dict(model.named_parameters())
    missing = sorted(set(saved) - set(parameters))
    if missing:
        raise RuntimeError(f"projector parameters missing from model: {missing[:5]}")
    for name, value in saved.items():
        parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))


def load_model(args: argparse.Namespace) -> tuple[Any, Any, dict[str, Any]]:
    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor

    if not args.device.startswith("cuda") or not torch.cuda.is_available():
        raise RuntimeError("feature caching is GPU-only; CUDA is required")
    kind = resolve_kind(args.checkpoint_kind, args.checkpoint)
    kwargs: dict[str, Any] = {
        "revision": args.revision,
        "local_files_only": args.local_files_only or os.environ.get("HF_HUB_OFFLINE") == "1",
    }
    if args.cache_dir:
        kwargs["cache_dir"] = str(args.cache_dir)
    processor = AutoProcessor.from_pretrained(args.model, **kwargs)
    base = AutoModelForTokenClassification.from_pretrained(args.model, dtype="bfloat16", **kwargs)
    identity: dict[str, Any] = {"checkpoint_kind": kind, "model": args.model, "revision": args.revision}
    if kind == "lora":
        from peft import PeftModel

        if args.checkpoint is None:
            raise ValueError("LoRA cache requires --checkpoint")
        model = PeftModel.from_pretrained(base, args.checkpoint / "adapter")
        load_projector(model, args.checkpoint)
        identity["checkpoint"] = str(args.checkpoint.resolve())
    elif kind == "projector":
        if args.checkpoint is None:
            raise ValueError("projector cache requires --checkpoint")
        model = base
        load_projector(model, args.checkpoint)
        identity["checkpoint"] = str(args.checkpoint.resolve())
    elif kind == "raw":
        model = base
    else:
        raise ValueError(kind)
    return processor, model.to(args.device).eval(), identity



def select_records(
    records: list[dict[str, Any]],
    *,
    requested_splits: list[str],
    max_items: int,
    min_items_per_split: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select a deterministic, split-aware subset without dropping validation.

    The previous implementation sorted train+validation together and truncated the
    merged list.  Small smoke limits could therefore contain only train items.
    This selector guarantees representation for every requested non-empty split,
    then allocates the remaining budget approximately in proportion to available
    split sizes.
    """
    if max_items < 0:
        raise ValueError("--max-items must be >= 0")
    if min_items_per_split < 1:
        raise ValueError("--min-items-per-split must be >= 1")

    wanted = list(dict.fromkeys(str(value) for value in requested_splits))
    if wanted:
        wanted_set = set(wanted)
        filtered = [row for row in records if str(row.get("split")) in wanted_set]
    else:
        filtered = list(records)
        wanted = sorted({str(row.get("split")) for row in filtered})

    grouped: dict[str, list[dict[str, Any]]] = {}
    for split in wanted:
        rows = sorted(
            (row for row in filtered if str(row.get("split")) == split),
            key=lambda row: str(row["item_id"]),
        )
        if rows:
            grouped[split] = rows

    available_counts = {split: len(rows) for split, rows in grouped.items()}
    total_available = sum(available_counts.values())
    if max_items == 0 or max_items >= total_available:
        selected = [row for split in wanted for row in grouped.get(split, [])]
        return selected, {
            "strategy": "all_requested",
            "available_split_counts": available_counts,
            "selected_split_counts": available_counts,
            "max_items": max_items,
            "min_items_per_split": min_items_per_split,
        }

    non_empty = [split for split in wanted if split in grouped]
    if max_items < len(non_empty):
        raise ValueError(
            f"--max-items {max_items} cannot represent all requested non-empty splits {non_empty}"
        )

    quota = {split: 1 for split in non_empty}
    budget = max_items - len(non_empty)

    # First raise every represented split toward the requested minimum using a
    # round-robin pass, so a 16-item smoke has enough validation to execute.
    target_minimum = {split: min(min_items_per_split, available_counts[split]) for split in non_empty}
    while budget > 0 and any(quota[split] < target_minimum[split] for split in non_empty):
        progressed = False
        for split in non_empty:
            if budget == 0:
                break
            if quota[split] < target_minimum[split]:
                quota[split] += 1
                budget -= 1
                progressed = True
        if not progressed:
            break

    # Allocate the remaining budget to the most under-sampled split relative to
    # its available population.  This approximates proportional allocation while
    # remaining deterministic and respecting caps.
    order = {split: index for index, split in enumerate(non_empty)}
    while budget > 0:
        candidates = [split for split in non_empty if quota[split] < available_counts[split]]
        if not candidates:
            break
        chosen = min(
            candidates,
            key=lambda split: (quota[split] / available_counts[split], order[split]),
        )
        quota[chosen] += 1
        budget -= 1

    selected = [row for split in non_empty for row in grouped[split][: quota[split]]]
    return selected, {
        "strategy": "split_aware_proportional",
        "available_split_counts": available_counts,
        "selected_split_counts": quota,
        "max_items": max_items,
        "min_items_per_split": min_items_per_split,
    }


def completed_ids(out_root: Path) -> set[str]:
    result: set[str] = set()
    for path in sorted((out_root / "shards").glob("*.index.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        result.update(str(value) for value in payload.get("item_ids", []))
    return result


def official_classes(processor: Any, logits: Any, input_ids: Any, words: list[str], timestamp_token_id: int, segment_sec: float) -> list[int]:
    decoded = processor.decode_forced_alignment(
        logits.unsqueeze(0), input_ids.unsqueeze(0), [words], timestamp_token_id
    )[0]
    values: list[int] = []
    for row in decoded:
        values.extend([
            int(round(float(row["start_time"]) / segment_sec)),
            int(round(float(row["end_time"]) / segment_sec)),
        ])
    return values


def save_shard(out_root: Path, ordinal: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    import torch

    shard_dir = out_root / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    stem = f"shard-{ordinal:05d}"
    path = shard_dir / f"{stem}.pt"
    temporary = shard_dir / f".{stem}.tmp.pt"
    torch.save({"schema_version": FEATURE_SCHEMA, "items": items}, temporary)
    temporary.replace(path)
    index = {
        "schema_version": FEATURE_SCHEMA,
        "shard": path.name,
        "item_count": len(items),
        "slot_count": sum(int(item["slot_count"]) for item in items),
        "item_ids": [str(item["item_id"]) for item in items],
        "sha256": sha256(path),
    }
    atomic_json(shard_dir / f"{stem}.index.json", index)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-kind", choices=("auto", "raw", "projector", "lora"), default="auto")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--min-items-per-split", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--shard-items", type=int, default=256)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.shard_items < 1:
        raise ValueError("batch and shard sizes must be positive")
    if args.top_k != 4:
        raise ValueError("feature schema v1 requires --top-k 4")

    import torch

    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    all_records = read_jsonl(args.labels)
    records, selection = select_records(
        all_records,
        requested_splits=list(args.split),
        max_items=args.max_items,
        min_items_per_split=args.min_items_per_split,
    )
    done = completed_ids(out_root)
    pending = [row for row in records if str(row["item_id"]) not in done]
    processor, model, model_identity = load_model(args)
    collator = QwenFABatchCollator(
        processor,
        audio_root=args.audio_root,
        language=args.language,
        timestamp_token_id=model.config.timestamp_token_id,
    )
    shard_ordinal = len(list((out_root / "shards").glob("*.index.json")))
    buffer: list[dict[str, Any]] = []
    indices: list[dict[str, Any]] = []
    processed = 0
    started = datetime.now(timezone.utc)
    with torch.inference_mode():
        for offset in range(0, len(pending), args.batch_size):
            chunk = pending[offset : offset + args.batch_size]
            inputs, words = collator(chunk)
            batch = move_inputs(inputs, args.device, torch.bfloat16)
            output = model(**batch)
            for batch_index, record in enumerate(chunk):
                input_ids = batch["input_ids"][batch_index]
                positions = (input_ids == model.config.timestamp_token_id).nonzero(as_tuple=False).flatten()
                slot_logits = output.logits[batch_index, positions].float()
                expected_slots = len(record["timestamp_class_ids"])
                if int(slot_logits.shape[0]) != expected_slots:
                    raise RuntimeError(
                        f"slot mismatch for {record['item_id']}: {slot_logits.shape[0]} != {expected_slots}"
                    )
                features, evidence = build_slot_features(slot_logits, top_k=args.top_k)
                official = official_classes(
                    processor,
                    output.logits[batch_index],
                    batch["input_ids"][batch_index],
                    list(words[batch_index]),
                    model.config.timestamp_token_id,
                    float(record["timestamp_segment_sec"]),
                )
                item = {
                    "schema_version": FEATURE_SCHEMA,
                    "item_id": str(record["item_id"]),
                    "song_id": str(record["song_id"]),
                    "singer_id": record.get("singer_id"),
                    "split": str(record["split"]),
                    "character_count": int(record["character_count"]),
                    "slot_count": expected_slots,
                    "timestamp_segment_sec": float(record["timestamp_segment_sec"]),
                    "num_timestamp_labels": int(record["num_timestamp_labels"]),
                    "features": features.detach().to("cpu", dtype=torch.float16),
                    "raw_classes": evidence["raw_classes"].detach().to("cpu", dtype=torch.int32),
                    "official_classes": torch.tensor(official, dtype=torch.int32),
                    "target_classes": torch.tensor(record["timestamp_class_ids"], dtype=torch.int32),
                }
                buffer.append(item)
                processed += 1
                if len(buffer) >= args.shard_items:
                    index = save_shard(out_root, shard_ordinal, buffer)
                    indices.append(index)
                    append_jsonl(out_root / "cache_status.jsonl", [{"status": "shard_complete", **index}])
                    buffer = []
                    shard_ordinal += 1
            print(json.dumps({"pending_completed": min(offset + len(chunk), len(pending)), "pending_total": len(pending), "cached_total": len(done) + processed}), flush=True)
    if buffer:
        index = save_shard(out_root, shard_ordinal, buffer)
        indices.append(index)
        append_jsonl(out_root / "cache_status.jsonl", [{"status": "shard_complete", **index}])

    all_indices = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((out_root / "shards").glob("*.index.json"))]
    selected_ids = {str(row["item_id"]) for row in records}
    cached_ids = {str(item_id) for index in all_indices for item_id in index.get("item_ids", [])}
    summary = {
        "schema_version": FEATURE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started.isoformat(),
        "model_identity": model_identity,
        "labels": str(args.labels.resolve()),
        "labels_sha256": sha256(args.labels),
        "requested_record_count": len(records),
        "selection": selection,
        "previously_completed_count": len(done),
        "newly_completed_count": processed,
        "cached_item_count": sum(int(row["item_count"]) for row in all_indices),
        "selected_item_count": len(selected_ids),
        "cached_selected_item_count": len(cached_ids & selected_ids),
        "cached_out_of_selection_item_count": len(cached_ids - selected_ids),
        "cached_slot_count": sum(int(row["slot_count"]) for row in all_indices),
        "shard_count": len(all_indices),
        "split_counts": {split: sum(str(row.get("split")) == split for row in records) for split in sorted({str(row.get("split")) for row in records})},
        "unique_song_count": len({str(row["song_id"]) for row in records}),
        "unique_singer_count": len({str(row.get("singer_id")) for row in records}),
        "notes": [
            "Counts refer to M4Singer items, songs and singers separately.",
            "No assumption is made that 1000 independent natural decoder anomalies exist.",
            "Full timestamp logits are not stored; compact float16 features are cached.",
        ],
    }
    atomic_json(out_root / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
