#!/usr/bin/env python3
"""Summarize raw backward jumps, repair blocks, uncertainty and error severity."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def mean(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    return statistics.fmean(finite) if finite else None


def contiguous_blocks(indices: list[int]) -> list[tuple[int, int]]:
    if not indices:
        return []
    ordered = sorted(set(indices))
    blocks: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        blocks.append((start, previous))
        start = previous = value
    blocks.append((start, previous))
    return blocks


def summarize_variant(rows: list[dict[str, Any]], timestamp_segment_sec: float) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: int(row["character_index"]))
    flattened_classes: list[int] = []
    flattened_gt: list[int] = []
    entropy: list[float] = []
    margin: list[float] = []
    fixed_errors: list[float] = []
    raw_errors: list[float] = []
    repaired_chars: list[int] = []
    for row in rows:
        flattened_classes.extend([int(row["raw_start_class"]), int(row["raw_end_class"])])
        flattened_gt.extend([int(row["gt_start_class"]), int(row["gt_end_class"])])
        entropy.extend([float(row["raw_start_entropy"]), float(row["raw_end_entropy"])])
        margin.extend([float(row["raw_start_margin"]), float(row["raw_end_margin"])])
        fixed_errors.extend([float(row["fixed_start_abs_error_sec"]), float(row["fixed_end_abs_error_sec"])])
        raw_errors.extend([float(row["raw_start_abs_error_sec"]), float(row["raw_end_abs_error_sec"])])
        if bool(row["start_repaired"]) or bool(row["end_repaired"]):
            repaired_chars.append(int(row["character_index"]))

    backward_jumps: list[dict[str, Any]] = []
    for slot in range(1, len(flattened_classes)):
        delta = flattened_classes[slot] - flattened_classes[slot - 1]
        if delta < 0:
            backward_jumps.append(
                {
                    "slot_index": slot,
                    "from_class": flattened_classes[slot - 1],
                    "to_class": flattened_classes[slot],
                    "jump_classes": delta,
                    "jump_sec": delta * timestamp_segment_sec,
                }
            )
    blocks = contiguous_blocks(repaired_chars)
    block_rows: list[dict[str, Any]] = []
    for start, end in blocks:
        selected = [row for row in rows if start <= int(row["character_index"]) <= end]
        block_rows.append(
            {
                "start_character_index": start,
                "end_character_index": end,
                "character_count": end - start + 1,
                "gt_start_sec": min(float(row["gt_start_sec"]) for row in selected),
                "gt_end_sec": max(float(row["gt_end_sec"]) for row in selected),
                "raw_mae_sec": mean(
                    [
                        value
                        for row in selected
                        for value in (
                            float(row["raw_start_abs_error_sec"]),
                            float(row["raw_end_abs_error_sec"]),
                        )
                    ]
                ),
                "fixed_mae_sec": mean(
                    [
                        value
                        for row in selected
                        for value in (
                            float(row["fixed_start_abs_error_sec"]),
                            float(row["fixed_end_abs_error_sec"]),
                        )
                    ]
                ),
                "entropy_mean": mean(
                    [
                        value
                        for row in selected
                        for value in (
                            float(row["raw_start_entropy"]),
                            float(row["raw_end_entropy"]),
                        )
                    ]
                ),
                "margin_mean": mean(
                    [
                        value
                        for row in selected
                        for value in (
                            float(row["raw_start_margin"]),
                            float(row["raw_end_margin"]),
                        )
                    ]
                ),
            }
        )
    block_rows.sort(key=lambda row: (row["character_count"], row["raw_mae_sec"] or 0.0), reverse=True)
    return {
        "character_count": len(rows),
        "slot_count": len(flattened_classes),
        "raw_mae_sec": mean(raw_errors),
        "fixed_mae_sec": mean(fixed_errors),
        "entropy_mean": mean(entropy),
        "margin_mean": mean(margin),
        "backward_jump_count": len(backward_jumps),
        "largest_backward_jump_classes": min((row["jump_classes"] for row in backward_jumps), default=0),
        "largest_backward_jump_sec": min((row["jump_sec"] for row in backward_jumps), default=0.0),
        "largest_backward_jumps": sorted(backward_jumps, key=lambda row: row["jump_classes"])[:10],
        "repaired_character_count": len(set(repaired_chars)),
        "repaired_character_rate": len(set(repaired_chars)) / len(rows) if rows else None,
        "repair_block_count": len(block_rows),
        "max_repair_block_characters": max((row["character_count"] for row in block_rows), default=0),
        "largest_repair_blocks": block_rows[:10],
        "raw_signed_class_error_mean": mean(
            [float(predicted - gt) for predicted, gt in zip(flattened_classes, flattened_gt, strict=True)]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    args = parser.parse_args()

    files = sorted(
        path
        for path in args.input_root.rglob("diagnostic_rows.jsonl")
        if "derived_audio" not in path.parts
    )
    if not files:
        raise FileNotFoundError(f"no diagnostic_rows.jsonl under {args.input_root}")
    result: dict[str, Any] = {
        "schema_version": "qwen_fa_error_block_summary_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input_root),
        "timestamp_segment_sec": args.timestamp_segment_sec,
        "source_files": [str(path) for path in files],
        "groups": {},
    }
    for path in files:
        rows = read_jsonl(path)
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    str(row.get("model_name")),
                    str(row.get("experiment")),
                    str(row.get("variant_item_id")),
                )
            ].append(row)
        for (model, experiment, variant), variant_rows in grouped.items():
            key = f"{model}::{experiment}::{variant}"
            result["groups"][key] = {
                "model_name": model,
                "experiment": experiment,
                "variant_item_id": variant,
                "source_file": str(path),
                **summarize_variant(variant_rows, args.timestamp_segment_sec),
            }
    ranked = sorted(
        result["groups"].values(),
        key=lambda row: (
            row["max_repair_block_characters"],
            abs(row["largest_backward_jump_sec"]),
            row["fixed_mae_sec"] or 0.0,
        ),
        reverse=True,
    )
    result["largest_failure_groups"] = ranked[:40]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"out": str(args.out), "group_count": len(result["groups"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
