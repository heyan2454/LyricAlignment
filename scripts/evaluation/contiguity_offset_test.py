#!/usr/bin/env python3
"""Borrow the next character's onset as this character's offset (contiguity prior), and price it.

M4Singer's character tier is contiguous: inside a phrase the next syllable starts exactly where this
one ends.  The model predicts onsets better than offsets (`label_rank_headroom.py`: 46% top-1 for
long offsets versus 76% for short ones), so for a contiguous pair the *neighbour's* onset is a better
estimate of this offset than the model's own offset slot.  The filter below keeps only pairs where the
annotation really is contiguous, which is the honest way to price the rule; where a rest or breath
separates the characters there is nothing to borrow — and that is exactly the long-note case, since
91.5% of ≥2 s characters end against a silence.

    PYTHONPATH=src python scripts/evaluation/contiguity_offset_test.py \
        --dump results/by_run/20260914_long_mech_new12000/per_character.jsonl \
        --out results/by_run/20260914_contiguity_offset/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
CONTIGUOUS_SEC = 0.02          # the annotation touches within a rounding slack of one 20 ms frame
BUCKET_NAMES = ("0-0.5s", "0.5-1s", "1-2s", "2s+")


def characters(path: Path) -> dict[str, dict[int, dict[str, Any]]]:
    per: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    by_item: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for (item, index), kinds in per.items():
        if len(kinds) == 2:
            by_item[item][index] = kinds
    return by_item


def annotated_time(row: dict[str, Any]) -> float:
    """The absolute label time, recovered from the prediction and its signed error."""
    return float(row["pred_sec"]) - float(row["signed_err"])


def bucket_of(duration: float) -> str:
    if duration < 0.5:
        return "0-0.5s"
    if duration < 1.0:
        return "0.5-1s"
    if duration < 2.0:
        return "1-2s"
    return "2s+"


def price(by_item: dict[str, dict[int, dict[str, Any]]], *, tolerance: float = TOL) -> dict[str, Any]:
    samples: list[tuple[str, float, float]] = []
    skipped_noncontiguous = 0
    for kinds in by_item.values():
        for index in sorted(kinds):
            following = kinds.get(index + 1)
            if following is None:
                continue
            current = kinds[index]
            annotated_end = annotated_time(current["offset"])
            next_start = annotated_time(following["onset"])
            if abs(annotated_end - next_start) > CONTIGUOUS_SEC:
                skipped_noncontiguous += 1
                continue
            samples.append((bucket_of(float(current["offset"]["duration"])),
                            abs(float(current["offset"]["pred_sec"]) - annotated_end),
                            abs(float(following["onset"]["pred_sec"]) - annotated_end)))
    out: dict[str, Any] = {"pairs": len(samples), "skipped_noncontiguous": skipped_noncontiguous,
                           "tolerance_sec": tolerance, "buckets": {}}
    for name in BUCKET_NAMES:
        group = [row for row in samples if row[0] == name]
        block = _stats(group, tolerance)
        if block:
            out["buckets"][name] = block
    overall = _stats([(name, argmax, borrowed) for name, argmax, borrowed in samples], tolerance)
    if overall:
        out["overall"] = overall
    return out


def _stats(group: list[tuple[str, float, float]], tolerance: float) -> dict[str, Any] | None:
    if len(group) < 20:
        return None
    diff = [1000.0 * (borrowed - argmax) for _, argmax, borrowed in group]
    mean = st.mean(diff)
    se = st.stdev(diff) / len(diff) ** 0.5 if len(diff) > 1 else 0.0
    return {"characters": len(group),
            "median_argmax_err_ms": round(1000 * st.median(row[1] for row in group), 1),
            "median_borrowed_err_ms": round(1000 * st.median(row[2] for row in group), 1),
            "mean_delta_ms": round(mean, 2), "se_ms": round(se, 2),
            "z": round(mean / se, 2) if se else None,
            "miss_rate_argmax": round(sum(1 for row in group if row[1] > tolerance) / len(group), 4),
            "miss_rate_borrowed": round(sum(1 for row in group if row[2] > tolerance) / len(group), 4)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = {"schema_version": "contiguity_offset_v1", "dump": str(args.dump), **price(characters(args.dump))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
