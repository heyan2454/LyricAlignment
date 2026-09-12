#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-derive the load-bearing unreachability numbers without the collapsed units.

Rounds 19/21 established: for long-note endings, the ground-truth bin is not even among the decoder's
top-2 candidates in 40 % of cases, and training moved that from 70.8 % (r0) to 21.7 % (r2).  Those
figures were computed over *all* units, including the ones the upstream repair had flattened to zero
duration (rounds 44-45).  Since that damage is a pipeline artefact and not a decoder limitation, the
number that should drive route decisions is the one measured on units the pipeline did not destroy.

Four filters per checkpoint: all units, excluding shipped-degenerate, excluding raw inversions, and
excluding both.

    PYTHONPATH=src python scripts/evaluation/run_unreachable_recheck.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import decodability_ceiling as DC
from lyricalign.analysis import gtsinger_gt_deep as GG

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_unreachable_recheck"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    off = panel[panel["pipeline"] == "official"].dropna(
        subset=["raw_start_sec", "raw_end_sec", "raw_top2cls_start", "raw_top2cls_end",
                "pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec", "gt_dur_sec"]).copy()
    off["degenerate_shipped"] = (
        pd.to_numeric(off["pred_end_sec"], errors="coerce")
        - pd.to_numeric(off["pred_start_sec"], errors="coerce") <= 1e-9)
    off["raw_inverted"] = (
        pd.to_numeric(off["raw_end_sec"], errors="coerce")
        - pd.to_numeric(off["raw_start_sec"], errors="coerce") < -1e-9)
    gt_dur = pd.to_numeric(off["gt_dur_sec"], errors="coerce")

    filters = {
        "all_units": pd.Series(True, index=off.index),
        "excluding_shipped_degenerate": ~off["degenerate_shipped"],
        "excluding_raw_inverted": ~off["raw_inverted"],
        "excluding_both": (~off["degenerate_shipped"]) & (~off["raw_inverted"]),
    }
    res: dict[str, Any] = {"schema": "unreachable_recheck_v1",
                           "meaning": "end_outside_top2 = share of long notes whose ground-truth end "
                                      "bin is not within one bin of either the top-1 or top-2 "
                                      "candidate, so no selection could recover it",
                           "counts": {k: {"units": int(v.sum()),
                                          "share_of_panel": round(float(v.mean()), 4)}
                                      for k, v in filters.items()},
                           "by_checkpoint": {}}
    for model, sub in off.groupby("model", observed=True):
        entry: dict[str, Any] = {"units": int(len(sub)),
                                 "degenerate_share": round(float(sub["degenerate_shipped"].mean()), 4),
                                 "raw_inverted_share": round(float(sub["raw_inverted"].mean()), 4),
                                 "filters": {}}
        long_mask = (pd.to_numeric(sub["gt_dur_sec"], errors="coerce") >= 1.0)
        for fname, fmask in filters.items():
            keep = (fmask.reindex(sub.index).fillna(False)).to_numpy(dtype=bool)
            for stratum, mask in (("all", np.ones(len(sub), dtype=bool)),
                                  ("long_note", long_mask.to_numpy(dtype=bool))):
                sel = sub[keep & mask]
                if len(sel) < 30:
                    continue
                end = DC.containment(sel, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                                     gt_sec="gt_end_sec")
                start = DC.containment(sel, pred_sec="raw_start_sec", top2cls="raw_top2cls_start",
                                       gt_sec="gt_start_sec")
                entry["filters"].setdefault(fname, {})[stratum] = {
                    "units": int(len(sel)),
                    "end_outside_top2_within1bin": end.get("outside_top2_within_1bins"),
                    "end_outside_top2_exact": end.get("outside_top2_within_0bins"),
                    "start_outside_top2_within1bin": start.get("outside_top2_within_1bins"),
                    "end_distance_median_bins": (end.get("distance_to_nearest_candidate_bins") or {}).get("median"),
                }
        res["by_checkpoint"][str(model)] = entry

    # the headline comparison: r0 vs r2 progression under each filter
    prog: dict[str, Any] = {}
    for fname in filters:
        vals: dict[str, float] = {}        # exact-bin tolerance (the one rounds 19/21 quoted)
        for model in ("r0", "r1", "r2"):
            blk = res["by_checkpoint"].get(model, {}).get("filters", {}).get(fname, {}).get("long_note")
            if blk:
                vals[model] = blk["end_outside_top2_exact"]
        # two tolerances, named explicitly: rounds 19/21 quoted the EXACT bin match (70.8/27.5/21.7),
        # so anything compared against those numbers must use the same column, not the +-1-bin one
        vals1: dict[str, float] = {}      # +-1 bin tolerance, kept alongside so the two are never mixed
        for model in ("r0", "r1", "r2"):
            blk = res["by_checkpoint"].get(model, {}).get("filters", {}).get(fname, {}).get("long_note")
            if blk:
                vals1[model] = blk["end_outside_top2_within1bin"]
        if len(vals) == 3 and len(vals1) == 3:
            prog[fname] = {
                "long_note_end_outside_top2_exact": vals,
                "long_note_end_outside_top2_within1bin": vals1,
                "improvement_r0_to_r2_pp": round(100.0 * (vals["r0"] - vals["r2"]), 2),
                "improvement_r0_to_r2_pp_within1bin": round(100.0 * (vals1["r0"] - vals1["r2"]), 2),
                "units_per_checkpoint": [
                    res["by_checkpoint"][m]["filters"][fname]["long_note"]["units"]
                    for m in ("r0", "r1", "r2")]}
    res["progression_by_filter"] = prog
    (args.out_dir / "UNREACHABLE_RECHECK.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("filter coverage: " + json.dumps(res["counts"], ensure_ascii=False))
    for fname, blk in prog.items():
        v = blk["long_note_end_outside_top2_exact"]
        print(f"   {fname:30s} long-note end outside top-2 (exact): "
              f"r0 {100 * v['r0']:.1f}% -> r1 {100 * v['r1']:.1f}% -> r2 {100 * v['r2']:.1f}% "
              f"(improvement {blk['improvement_r0_to_r2_pp']:+.1f}pp; units {blk['units_per_checkpoint']})")
    for model in ("r0", "r1", "r2"):
        e = res["by_checkpoint"][model]
        print(f"   {model}: degenerate_share={e['degenerate_share']:.4f} raw_inverted_share={e['raw_inverted_share']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
