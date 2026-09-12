#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is the ground-truth boundary even a candidate?  Ceiling probe on GTSinger (human GT).

    PYTHONPATH=src python scripts/evaluation/run_decodability_ceiling.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import decodability_ceiling as D
from lyricalign.analysis import gtsinger_gt_deep as GG

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_decodability_ceiling"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--pipeline", default="official", choices=("official", "raw"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    df = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    sub = df[(df["pipeline"] == args.pipeline)].dropna(
        subset=["raw_start_sec", "raw_end_sec", "raw_top2cls_start", "raw_top2cls_end",
                "gt_start_sec", "gt_end_sec", "item"]).copy()
    res = {"schema": "decodability_ceiling_v1", "pipeline": args.pipeline,
           "timestamp_step_sec": D.TIMESTAMP_STEP_SEC,
           "units": int(len(sub)), "items": int(sub["item"].nunique()),
           "note": "exact containment is measurable for k=1 and k=2 only (the panel stores the "
                   "runner-up class, not the full posterior); k>=3 is reported as unknown",
           "strata": D.strata_analysis(sub), "by_checkpoint": D.compare_checkpoints(sub)}
    (args.out_dir / "CEILING.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    print(f"pipeline={args.pipeline} units={res['units']:,} items={res['items']} "
          f"step={D.TIMESTAMP_STEP_SEC}s")
    print(f"\n{'stratum':14s} {'units':>7s} {'end top1 exact':>15s} {'end in top2':>12s} "
          f"{'end outside':>12s} {'top1 ±1bin':>11s} {'in top2 ±1':>11s}")
    for name, blk in res["strata"].items():
        e = blk["end"]
        print(f"{name:14s} {blk['units']:7,} {100*e.get('top1_within_0bins', 0):14.2f}% "
              f"{100*e.get('in_top2_union_within_0bins', 0):11.2f}% "
              f"{100*e.get('outside_top2_within_0bins', 0):11.2f}% "
              f"{100*e.get('top1_within_1bins', 0):10.2f}% "
              f"{100*e.get('in_top2_union_within_1bins', 0):10.2f}%")
    print("\nby checkpoint (long_note stratum, end boundary):")
    for name, blk in res["by_checkpoint"].items():
        ln = blk.get("long_note", {})
        allu = blk.get("all_units", {})
        print(f"   {name:6s} units={blk['units']:6,} | all end_top1={allu.get('end_top1_exact'):.4f} "
              f"in_top2={allu.get('end_in_top2_exact'):.4f} | long end_top1={ln.get('end_top1_exact')} "
              f"in_top2={ln.get('end_in_top2_exact')} outside={ln.get('end_outside_top2_exact')} "
              f"(n={ln.get('units')})")
    print("\nlast_unit stratum by checkpoint (end):")
    for name, blk in res["by_checkpoint"].items():
        lu = blk.get("last_unit", {})
        print(f"   {name:6s} n={lu.get('units')} top1={lu.get('end_top1_exact')} "
              f"in_top2={lu.get('end_in_top2_exact')} outside_top2={lu.get('end_outside_top2_exact')}")
    print("\ncan confidence flag unreachable GT? AUC(top1_prob -> GT within 1 bin of a candidate):")
    for name, blk in res["strata"].items():
        print(f"   {name:14s} end={blk['end'].get('auc_top1_prob_predicts_gt_within_1bin_of_candidate')} "
              f"start={blk['start'].get('auc_top1_prob_predicts_gt_within_1bin_of_candidate')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
