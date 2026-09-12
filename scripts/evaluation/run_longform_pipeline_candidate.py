#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Realign-trigger value of cross-window disagreement + end-to-end long-form candidate output.

    PYTHONPATH=src python scripts/evaluation/run_longform_pipeline_candidate.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import cross_window_selection as X
from lyricalign.analysis import longform_pipeline_candidate as P


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=X.PANEL.parent)
    args = ap.parse_args()
    d, info = X.load_attempts()
    d = X.add_features(d)
    units = P.build_unit_table(d)
    trig = P.trigger_discrimination(units)
    cand = P.end_to_end(d, units)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "REALIGN_TRIGGER.json").write_text(
        json.dumps({"attempts_panel": info, **trig}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (args.out_dir / "PIPELINE_CANDIDATE.json").write_text(
        json.dumps(cand, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    units.to_csv(args.out_dir / "per_unit_disagreement.csv.gz", index=False, compression="gzip")
    print("coverage:", json.dumps(trig["coverage"], ensure_ascii=False))
    for tag in ("bad100", "bad250"):
        t = trig[tag]
        print(f"{tag}: pos_rate={t['positive_rate']} AUC disag={t['auc_disagreement']} "
              f"support={t['auc_support_max']} loo={t['auc_loo_spread_min']} ent={t['auc_ent_min']} "
              f"attempts={t['auc_attempts']}")
        for k, v in t["review_budget_curve"].items():
            print(f"   {k:12s} thr={v['threshold_sec']:.2f}s n={v['flagged_units']:5d} "
                  f"prec={v['precision_bad100']:.3f} recall={v['recall_bad100']:.3f} "
                  f"hit100_after_rechosen={v['hit100_of_flagged_if_rechosen']:.3f} "
                  f"overall={v['overall_hit100_if_only_flagged_rechosen']:.4f} "
                  f"gain={v['gain_pp_vs_single_window']:+.2f}pp")
    print("error capture curve:", json.dumps(trig["error_capture_curve"], ensure_ascii=False))
    print()
    for k, v in cand["systems"].items():
        st = v.get("structure") or {}
        print(f"  {k:38s} hit100={v['hit100']:.4f} hit250={v['hit250']:.4f} mae={v['mae_both_sec']:.4f} "
              f"degen={st.get('degenerate_share','-')} overlap={st.get('overlap_share','-')} "
              f"regr={st.get('start_regression_share','-')}")
    print("summary:", json.dumps(cand["summary"], ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
