#!/usr/bin/env python3
"""Summarize synthetic-long Qwen FA evaluation, including seam exclusion."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate_tolerant


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seam-margin-sec", type=float, default=0.5)
    args = parser.parse_args()

    manifests = read_jsonl(args.manifest)
    references = read_jsonl(args.characters)
    predictions = read_jsonl(args.predictions)
    if not manifests:
        result = {"status": "data_limited", "item_count": 0}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return

    joins = {str(row["item_id"]): [float(value) for value in row.get("join_points_sec", [])] for row in manifests}
    keep_keys: set[tuple[str, int]] = set()
    excluded = 0
    for row in references:
        item_id = str(row["item_id"])
        start, end = float(row["start_sec"]), float(row["end_sec"])
        near = any(start <= seam + args.seam_margin_sec and end >= seam - args.seam_margin_sec for seam in joins.get(item_id, []))
        key = (item_id, int(row["character_index"]))
        if near:
            excluded += 1
        else:
            keep_keys.add(key)

    seam_refs = [row for row in references if (str(row["item_id"]), int(row["character_index"])) in keep_keys]
    seam_preds = [row for row in predictions if (str(row["item_id"]), int(row["character_index"])) in keep_keys]
    durations = [float(row["duration_sec"]) for row in manifests]
    result = {
        "status": "passed",
        "item_count": len(manifests),
        "character_count": len(references),
        "seam_margin_sec": args.seam_margin_sec,
        "seam_excluded_character_count": excluded,
        "seam_retained_character_count": len(seam_refs),
        "duration_sec": {
            "minimum": min(durations),
            "maximum": max(durations),
            "mean": sum(durations) / len(durations),
        },
        "all_characters": evaluate_tolerant(references, predictions),
        "seam_excluded": evaluate_tolerant(seam_refs, seam_preds) if seam_refs else None,
    }
    for key in ("minimum", "maximum", "mean"):
        if not math.isfinite(result["duration_sec"][key]):
            raise ValueError("non-finite duration summary")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
