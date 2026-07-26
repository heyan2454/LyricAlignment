#!/usr/bin/env python3
"""Summarize GT timestamp-class coverage without loading a model."""
from __future__ import annotations
import argparse, json, math
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def parse_dataset(spec: str) -> tuple[str, Path, str | None]:
    parts = spec.split("::")
    if len(parts) not in (2, 3):
        raise ValueError("dataset spec must be NAME::PATH[::SPLIT]")
    return parts[0], Path(parts[1]), parts[2] if len(parts) == 3 and parts[2] else None


def time_bin(value: float) -> str:
    edges = (0, 30, 60, 90, 120, 150, 180, 240, 300, 400)
    for left, right in zip(edges, edges[1:]):
        if left <= value < right:
            return f"{left:03d}-{right:03d}"
    return "400+"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", action="append", required=True, help="NAME::PATH[::SPLIT]")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output: dict[str, Any] = {"schema_version": "qwen_fa_timestamp_coverage_v1", "datasets": {}}
    for spec in args.dataset:
        name, path, split = parse_dataset(spec)
        rows = read_jsonl(path)
        if split:
            rows = [row for row in rows if row.get("split") == split]
        if not rows:
            raise ValueError(f"empty selection: {name}")
        histogram: Counter[str] = Counter()
        class_histogram: Counter[int] = Counter()
        max_gt = 0.0
        for row in rows:
            segment = float(row.get("timestamp_segment_sec", 0.08))
            for class_id in row["timestamp_class_ids"]:
                class_id = int(class_id)
                time_sec = class_id * segment
                histogram[time_bin(time_sec)] += 1
                class_histogram[class_id] += 1
                max_gt = max(max_gt, time_sec)
        total = sum(histogram.values())
        output["datasets"][name] = {
            "path": str(path), "split": split, "record_count": len(rows),
            "character_count": sum(int(row["character_count"]) for row in rows),
            "timestamp_slot_count": total, "maximum_gt_timestamp_sec": max_gt,
            "occupied_class_count": len(class_histogram),
            "maximum_occupied_class": max(class_histogram),
            "time_bins": {key: {"count": value, "fraction": value / total} for key, value in sorted(histogram.items())},
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "datasets": list(output["datasets"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
