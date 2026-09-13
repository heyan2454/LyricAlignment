#!/usr/bin/env python3
"""Error as a function of labelled character duration — where does the cliff sit?

One row per duration bucket, per checkpoint, from the per-character dumps written by
`measure_predicted_boundary_acoustics.py`.  This is the measurement that decides *what* to
re-weight: a flat curve means the model is uniformly weak, a cliff means the tail of the label
distribution is under-represented in training.

    PYTHONPATH=src python scripts/evaluation/error_vs_duration.py \
        --dump "old-r2-750=results/by_run/20260913_boundary_pred_vs_gt_old750_v3/per_character.jsonl" \
        --dump "new-12000=results/by_run/20260914_boundary_pred_vs_gt_new12000/per_character.jsonl" \
        --out results/by_run/20260914_error_vs_duration/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

BUCKETS: tuple[tuple[float, float], ...] = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 1.5),
                                             (1.5, 2.0), (2.0, 3.0), (3.0, 99.0))
TOLERANCE_SEC = 0.2


def characters(path: Path) -> list[dict[str, Any]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    out = []
    for (item, index), kinds in per.items():
        if "onset" not in kinds or "offset" not in kinds:
            continue
        out.append({"item_id": item, "index": index, "duration": float(kinds["onset"]["duration"]),
                    "err": max(float(kinds["onset"]["abs_err_argmax"]), float(kinds["offset"]["abs_err_argmax"])),
                    "err_offset": float(kinds["offset"]["abs_err_argmax"]),
                    "err_onset": float(kinds["onset"]["abs_err_argmax"])})
    return out


def bucket_of(duration: float) -> tuple[float, float]:
    for low, high in BUCKETS:
        if low <= duration < high:
            return low, high
    return BUCKETS[-1]


def profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[bucket_of(row["duration"])].append(row)
    out: dict[str, Any] = {}
    for bounds in BUCKETS:
        bucket = groups.get(bounds)
        if not bucket:
            continue
        errors = [row["err"] for row in bucket]
        out[f"{bounds[0]:g}-{bounds[1]:g}" if bounds[1] < 99 else "3.0+"] = {
            "characters": len(bucket),
            "miss_rate": round(sum(1 for e in errors if e > TOLERANCE_SEC) / len(errors), 4),
            "median_max_err_ms": round(1000 * st.median(errors), 1),
            "median_offset_err_ms": round(1000 * st.median(row["err_offset"] for row in bucket), 1),
            "median_onset_err_ms": round(1000 * st.median(row["err_onset"] for row in bucket), 1),
            "se_miss": round(100 * (st.mean([e > TOLERANCE_SEC for e in errors]) *
                                    (1 - st.mean([e > TOLERANCE_SEC for e in errors])) / len(errors)) ** 0.5, 2)}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", action="append", default=[], help="label=path to per_character.jsonl")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE_SEC)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload: dict[str, Any] = {"schema_version": "error_vs_duration_v1", "tolerance_sec": args.tolerance,
                               "checkpoints": {}}
    for spec in args.dump:
        if "=" not in spec:
            raise SystemExit(f"--dump needs label=path, got {spec!r}")
        label, path = spec.split("=", 1)
        rows = characters(Path(path))
        payload["checkpoints"][label] = {"items": len({r["item_id"] for r in rows}),
                                         "characters": len(rows), "buckets": profile(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    labels = list(payload["checkpoints"])
    header = sorted({bucket for label in labels for bucket in payload["checkpoints"][label]["buckets"]},
                    key=lambda name: float(name.split("-")[0].rstrip("+")))
    print(f"{'时长桶':>8} " + " ".join(f"{label + ' 数/超差率':>22}" for label in labels))
    for bucket in header:
        cells = []
        for label in labels:
            block = payload["checkpoints"][label]["buckets"].get(bucket)
            cells.append(f"{block['characters']:6d} {100 * block['miss_rate']:5.1f}% ±{block['se_miss']:.1f}"
                         if block else " " * 22)
        print(f"{bucket:>8} " + " ".join(f"{cell:>22}" for cell in cells))


if __name__ == "__main__":
    main()
