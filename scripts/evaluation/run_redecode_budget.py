#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How many points can a re-decode budget buy, once reachability is taken into account?

    PYTHONPATH=src python scripts/evaluation/run_redecode_budget.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as GG
from lyricalign.analysis import redecode_budget as RB
from lyricalign.analysis import trigger_fusion as TF

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_redecode_budget"
KEY = ["item", "model", "audio_input", "mode", "unit_index"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    off = panel[panel["pipeline"] == "official"].dropna(
        subset=["raw_start_sec", "raw_end_sec", "raw_top2cls_start", "raw_top2cls_end",
                "gt_start_sec", "gt_end_sec", "pred_start_sec", "pred_end_sec"]).copy()
    gaps = pd.read_csv(RUNS / "20260912_gap_shape/gtsinger_gap_features.csv.gz")
    feats = TF.build_features(off.merge(gaps[KEY + ["gap_over_core"]], on=KEY, how="left"))
    # bin indices on the decoder's 0.08 s grid: reachability asks whether a top-1/top-2 candidate
    # class sits within one bin of the ground-truth bin, per boundary
    def _bin(col: str) -> pd.Series:
        return (pd.to_numeric(feats[col], errors="coerce") / RB.STEP_SEC).round()

    def _near(a: pd.Series, b: pd.Series) -> pd.Series:
        d = (a - b).abs()
        return (d <= 1) & d.notna()

    reach_start = (_near(_bin("raw_start_sec"), _bin("gt_start_sec"))
                   | _near(pd.to_numeric(feats["raw_top2cls_start"], errors="coerce"),
                           _bin("gt_start_sec")))
    reach_end = (_near(_bin("raw_end_sec"), _bin("gt_end_sec"))
                 | _near(pd.to_numeric(feats["raw_top2cls_end"], errors="coerce"),
                         _bin("gt_end_sec")))
    feats["reachable_start"] = reach_start
    feats["reachable_end"] = reach_end
    feats["fixable"] = (reach_start & reach_end).to_numpy(dtype=bool)
    feats["both_abs_err_sec"] = np.maximum(
        (feats["pred_start_sec"] - feats["gt_start_sec"]).abs(),
        (feats["pred_end_sec"] - feats["gt_end_sec"]).abs())
    r_start = {"available": True, "units": int(len(feats)),
               "reachable_share": round(float(reach_start.mean()), 4),
               "unreachable_share": round(float(1.0 - reach_start.mean()), 4)}
    r_end = {"available": True, "units": int(len(feats)),
             "reachable_share": round(float(reach_end.mean()), 4),
             "unreachable_share": round(float(1.0 - reach_end.mean()), 4)}

    res: dict[str, Any] = {"schema": "redecode_budget_v1",
                           "discipline": "bounds, not promises: the optimistic bound assumes a "
                                         "re-decode repairs every selected unit, the reachable bound "
                                         "only credits units whose GT bin is within one bin of a "
                                         "top-2 candidate on BOTH boundaries (round 19 evidence)",
                           "reachability": {"end": r_end, "start": r_start},
                           "fixable_share": round(float(feats["fixable"].mean()), 4),
                           "panels": {}}
    dur = pd.to_numeric(feats["gt_dur_sec"], errors="coerce").to_numpy(dtype=float)
    prod = ((feats["model"] == "r2") & (feats["audio_input"] == "vocal")
             & (feats["mode"] == "windowed")).to_numpy(dtype=bool)
    for name, sub in (("all_views", feats),
                      ("production_view_r2_vocal_windowed", feats[prod]),
                      ("long_note", feats[dur >= 1.0])):
        if len(sub) < 100:
            res["panels"][name] = {"available": False, "units": int(len(sub))}
            continue
        res["panels"][name] = RB.bound_budget_value(sub, score_col="fused_mean_rank")
        res["panels"][name]["also_entropy_only"] = RB.bound_budget_value(sub, score_col="f_entropy_end")
    (args.out_dir / "REDECODE_BUDGET.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"units with reachability data: {int(len(feats)):,}  "
          f"fixable (both boundaries reachable): {100*res['fixable_share']:.2f}%")
    print(f"  end reachable {100*r_end['reachable_share']:.2f}% / start reachable {100*r_start['reachable_share']:.2f}%")
    for name, blk in res["panels"].items():
        if not blk.get("available", True) or "budgets" not in blk:
            print(f"\n== {name}: skipped ({blk.get('units')})")
            continue
        print(f"\n== {name}: units={blk['units']:,} baseline hit@100={100*blk['baseline_hit']:.2f}% "
              f"wrong={blk['wrong_units']:,} of which unrecoverable={blk['wrong_but_unreachable']:,} "
              f"({100*blk['headroom']['unrecoverable_share_of_wrong_units']:.1f}%) ==")
        print(f"   {'budget':7s} {'trig opt':>9s} {'trig reach':>11s} {'rand reach':>11s} "
              f"{'orac reach':>11s} {'capture':>8s} {'trig vs rand':>13s}")
        for b, v in blk["budgets"].items():
            print(f"   {b:7s} {v['fused_trigger_optimistic_gain_pp']:+8.2f}pp "
                  f"{v['fused_trigger_reachable_gain_pp']:+10.2f}pp "
                  f"{v['random_reachable_gain_pp']:+10.2f}pp "
                  f"{v['oracle_by_recoverable_reachable_gain_pp']:+13.2f}pp "
                  f"{v['fused_trigger_reachable_gain_pp']/max(v['oracle_by_recoverable_reachable_gain_pp'],1e-9):7.2f} "
                  f"{v['fused_trigger_reachable_gain_pp']-v['random_reachable_gain_pp']:+12.2f}pp")
        print(f"   entropy-only trigger: " + " ".join(
            f"{k}={v['fused_trigger_reachable_gain_pp']:+.2f}pp"
            for k, v in (blk.get("also_entropy_only") or {}).get("budgets", {}).items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
