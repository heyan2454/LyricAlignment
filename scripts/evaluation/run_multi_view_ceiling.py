#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-decode selection headroom: per unit, how many of the k decodes are already correct?

    PYTHONPATH=src python scripts/evaluation/run_multi_view_ceiling.py
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
from lyricalign.analysis import gtsinger_multiview as MV
from lyricalign.analysis import multi_view_ceiling as M

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_multi_view_ceiling"


def strata_of(d: pd.DataFrame, last_col: str, first_col: str) -> dict[str, np.ndarray]:
    dur = pd.to_numeric(d["gt_dur_sec"], errors="coerce").to_numpy(dtype=float)
    return {"all_units": np.ones(len(d), dtype=bool),
            "long_note": dur >= 1.0,
            "short_note": dur < 0.4,
            last_col: d[last_col].to_numpy(dtype=bool) if last_col in d else np.zeros(len(d), bool),
            first_col: d[first_col].to_numpy(dtype=bool) if first_col in d else np.zeros(len(d), bool)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, object] = {"schema": "multi_view_ceiling_v1",
                              "discipline": "MIR-1K numbers are retrospective bounds on test-only data; "
                                            "nothing is selected with them (checkpoint/view/threshold "
                                            "selection stays on GTSinger and M4)", "panels": {}}

    # --- GTSinger: 12 recorded views per unit, human word-level GT (not test-only)
    g = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    v = MV.build_view_frame(g, pipeline="official")
    # the unit key must include unit_index: dropping it silently collapses the analysis to item level
    v["is_last"] = v.groupby(["item"], observed=True)["unit_index"].transform("max") == v["unit_index"]
    v["is_first"] = v.groupby(["item"], observed=True)["unit_index"].transform("min") == v["unit_index"]
    res["panels"]["gtsinger_12_views"] = M.ceiling_by_stratum(
        v, unit_key=MV.UNIT_KEY, view_col="view",
        production_view="|".join(MV.PRODUCTION_VIEW),
        strata=strata_of(v, "is_last", "is_first"))

    # --- MIR-1K: 6 checkpoints on the same items, human per-character GT (test-only -> bound only)
    m = pd.read_csv(RUNS / "20260912_mir1k_natural_panel/panel.csv.gz")
    m = M.build_long_from_wide(m, view_prefix_col="predictor", unit_key=["item_id", "character_index"],
                               gt_start="gt_start_sec", gt_end="gt_end_sec")
    res["panels"]["mir1k_6_checkpoints"] = M.ceiling_by_stratum(
        m, unit_key=["item_id", "character_index"], view_col="predictor",
        production_view="r2_full_20260723",
        strata={"all_units": np.ones(len(m), dtype=bool),
                "long_note": (pd.to_numeric(m["gt_dur_sec"], errors="coerce").to_numpy(float) >= 1.0),
                "last_char": m["is_last_char"].to_numpy(dtype=float) == 1.0,
                "first_char": m["is_first_char"].to_numpy(dtype=float) == 1.0})

    (args.out_dir / "MULTI_VIEW_CEILING.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, blk in res["panels"].items():
        print(f"\n== {name}: views={len(blk['views'])} tol={blk['tolerance_sec']}s ==")
        print(f"   {'stratum':12s} {'units':>7s} {'prod':>7s} {'best1':>7s} {'union':>7s} "
              f"{'regret':>7s} {'0ofk':>6s} {'allk':>6s} {'mean#':>6s} {'corr':>6s}")
        for sname, st in blk["strata"].items():
            print(f"   {sname:12s} {st['units']:7,} {100*st.get('production_view_hit', 0):6.2f}% "
                  f"{100*st['best_single_view_hit']:6.2f}% {100*st['union_oracle_hit']:6.2f}% "
                  f"{st.get('regret_recoverable_by_selection_pp', 0):+6.2f}pp "
                  f"{100*st['no_view_correct_share']:5.1f}% {100*st['all_views_correct_share']:5.1f}% "
                  f"{st['mean_views_correct']:6.2f} "
                  f"{st.get('mean_pairwise_error_correlation_with_production') if st.get('mean_pairwise_error_correlation_with_production') is not None else float('nan'):6.3f}")
        print("   tolerance sensitivity (all units):",
              json.dumps(blk["tolerance_sensitivity"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
