#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What does the review gate's SAFE edge buy, and how much of it is grid-determined?

Reads the frozen detector_v2 ``LABELS.jsonl`` audit errors (no forwards, CPU only) and reports, for
each candidate SAFE edge, the three-way split the gate would produce and how much of the
"auto-accept" side is robust to moving the edge by one 80 ms grid step.

    PYTHONPATH=src python scripts/evaluation/run_gate_operating_points.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import label_noise_ceiling as LN

OUT = Path("/home/hyan/Data/lyricalign/runs/20260912_gate_operating_points")
DETECTOR_ROOT = Path("/home/hyan/Data/lyricalign/runs/research_v7_detector_v2")
EDGES = (0.10, 0.16, 0.20, 0.25)


def errors_of(path: Path, split: str | None = None) -> np.ndarray:
    vals: list[float] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if split and str(d.get("split")) != split:
                continue
            a = d.get("audit") or {}
            se, ee = a.get("start_abs_error_sec"), a.get("end_abs_error_sec")
            if se is None or ee is None:
                continue
            vals.append(max(abs(float(se)), abs(float(ee))))
    return np.asarray(vals, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    per_file: list[dict] = []
    pooled: list[np.ndarray] = []
    for path in sorted(DETECTOR_ROOT.glob("*/LABELS.jsonl")):
        e = errors_of(path)
        if e.size < 50:
            continue
        pooled.append(e)
        per_file.append({"file": path.parent.name, "path": str(path.parent),
                         **LN.gate_operating_points(pd.Series(e), safe_edges=EDGES)})
    allerr = np.concatenate(pooled) if pooled else np.array([])
    res: dict = {"schema": "gate_operating_points_v1", "unsafe_edge_sec": 0.25, "quantum_sec": 0.08,
                 "source": str(DETECTOR_ROOT), "files": len(per_file),
                 "pooled": {"units": int(allerr.size),
                            **LN.gate_operating_points(pd.Series(allerr), safe_edges=EDGES)},
                 "per_file": per_file}
    # the frozen bands are fitted on train, so the honest operating point is the held-out slice
    test_files = [p for p in sorted(DETECTOR_ROOT.glob("*/LABELS.jsonl"))]
    held: list[np.ndarray] = []
    for path in test_files:
        held.append(errors_of(path, "test"))
    held_all = np.concatenate([h for h in held if h.size]) if held else np.array([])
    res["held_out_test_slice"] = {"units": int(held_all.size),
                                  **LN.gate_operating_points(pd.Series(held_all), safe_edges=EDGES)}
    # pooling every LABELS file mixes research runs that are ~95 % unsafe into the operating point,
    # which is not the product regime; report a "non-broken" pooling as the headline view
    broken = {f["file"] for f in per_file if (f.get("unsafe_share") or 0) > 0.5}
    good = [f for f in per_file if f["file"] not in broken]
    good_errs = [errors_of(Path(f["path"]) / "LABELS.jsonl") for f in good]
    good_all = np.concatenate([g for g in good_errs if g.size]) if good_errs else np.array([])
    res["pooled_non_broken"] = {"units": int(good_all.size),
                                "excluded_files": sorted(broken),
                                **LN.gate_operating_points(pd.Series(good_all), safe_edges=EDGES)}
    blk = res["pooled_non_broken"]
    if blk.get("units"):
        print(f"\n== pooled_non_broken: units={blk['units']:,} "
              f"excluded={blk['excluded_files']} unsafe={100 * blk['unsafe_share']:.2f}% ==")
        print(f"   {'SAFE边':8s} {'自动通过':>9s} {'其中稳健':>9s} {'稳健占SAFE':>11s} {'待复核':>8s} {'一格摆幅':>10s}")
        for k, v in blk["by_safe_edge"].items():
            print(f"   {k:8s} {100 * v['safe_share']:8.2f}% {100 * v['robust_safe_share']:8.2f}% "
                  f"{100 * v['safe_share_robustness']:10.1f}% {100 * v['grey_share']:7.2f}% "
                  f"{v['swing_pp_if_edge_moved_one_quantum']:9.1f}pp")
    (args.out_dir / "GATE_OPERATING_POINTS.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for scope in ("pooled", "held_out_test_slice"):
        blk = res[scope]
        if not blk.get("units"):
            print(f"\n== {scope}: no units ==")
            continue
        print(f"\n== {scope}: units={blk['units']:,} "
              f"unsafe(>=250ms)={100 * blk['unsafe_share']:.2f}% "
              f"(其刀尖 {100 * blk.get('unsafe_knife_edge_share', 0):.1f}%) ==")
        print(f"   {'SAFE边':8s} {'自动通过':>9s} {'其中稳健':>9s} {'稳健占SAFE':>11s} {'待复核':>8s} {'一格摆幅':>10s}")
        for k, v in blk["by_safe_edge"].items():
            print(f"   {k:8s} {100 * v['safe_share']:8.2f}% {100 * v['robust_safe_share']:8.2f}% "
                  f"{100 * v['safe_share_robustness']:10.1f}% {100 * v['grey_share']:7.2f}% "
                  f"{v['swing_pp_if_edge_moved_one_quantum']:9.1f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
