#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is an evaluation set itself contaminated by the zero-length defect?

MIR-1K (human per-character GT) and GTSinger (human word-level GT) both pass through the official
processor, so both inherit the upstream collapse.  If a headline hit rate is partly measuring that
damage, a post-fix re-run would look like an improvement in the model when it is really a repair of
the pipeline.  This reports, per predictor: the degenerate share, the hit rates with and without the
degenerate units, and how the degenerate units cluster.

    PYTHONPATH=src python scripts/evaluation/run_eval_contamination.py
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
from lyricalign.analysis import label_noise_ceiling as LN

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_eval_contamination"
TOLS = (0.10, 0.20, 0.25)


def identical_start_runs(frame: pd.DataFrame, *, group: str, min_run: int = 5) -> dict:
    """Longest run of consecutive units sharing one start timestamp, per group."""
    runs: list[int] = []
    total_in = 0
    for _, sub in frame.groupby(group, observed=True):
        starts = pd.to_numeric(sub["pred_start_sec"], errors="coerce").to_numpy(dtype=float)
        zero = (pd.to_numeric(sub["pred_end_sec"], errors="coerce")
                - pd.to_numeric(sub["pred_start_sec"], errors="coerce")).to_numpy(dtype=float) <= 1e-9
        i = 0
        while i < len(starts):
            j = i
            while (j + 1 < len(starts) and abs(starts[j + 1] - starts[i]) <= 1e-9
                   and zero[j + 1]):
                j += 1
            length = j - i + 1
            if length >= min_run and zero[i]:
                runs.append(length)
                total_in += length
            i = j + 1
    return {"runs_ge_{}".format(min_run): len(runs), "units_in_runs": total_in,
            "longest_run": int(max(runs)) if runs else 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"schema": "eval_contamination_v1", "tolerances_sec": list(TOLS),
                 "question": "how much of each reported hit rate is the upstream zero-length collapse?",
                 "panels": {}}

    # ---- MIR-1K: human per-character GT, one predictor at a time
    mir = pd.read_csv(RUNS / "20260912_mir1k_natural_panel/panel.csv.gz")
    mir_zero = (mir["pred_end_sec"] - mir["pred_start_sec"]) <= 1e-9
    mir = mir.assign(_zero=mir_zero)
    mir_out: dict = {"units": int(len(mir)), "items": int(mir["item_id"].nunique()),
                     "predictors": {}}
    for name, sub in mir.groupby("predictor", observed=True):
        blk = LN.degeneracy_contamination(sub["both_err"], sub["_zero"], tolerances=TOLS)
        blk["identical_start_blocks"] = identical_start_runs(sub, group="item_id")
        mir_out["predictors"][str(name)] = blk
    res["panels"]["mir1k_human_gt"] = mir_out

    # ---- GTSinger: human word-level GT, per checkpoint (official pipeline rows)
    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    off = panel[panel["pipeline"] == "official"].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec"]).copy()
    off["err"] = np.maximum((off["pred_start_sec"] - off["gt_start_sec"]).abs(),
                            (off["pred_end_sec"] - off["gt_end_sec"]).abs())
    off["_zero"] = (off["pred_end_sec"] - off["pred_start_sec"]) <= 1e-9
    gs_out: dict = {"units": int(len(off)), "predictors": {}}
    for name, sub in off.groupby("model", observed=True):
        blk = LN.degeneracy_contamination(sub["err"], sub["_zero"], tolerances=TOLS)
        blk["identical_start_blocks"] = identical_start_runs(
            sub.rename(columns={"item": "item_id"}), group="item_id")
        gs_out["predictors"][str(name)] = blk
    res["panels"]["gtsinger_human_gt"] = gs_out

    (args.out_dir / "EVAL_CONTAMINATION.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for panel_name, blk in res["panels"].items():
        print(f"\n== {panel_name} (units {blk['units']:,}) ==")
        print(f"   {'predictor':28s} {'零长占比':>9s} {'<0.2s':>8s} {'<0.2s(去零长)':>14s} "
              f"{'零长占失败':>11s} {'零长块':>7s} {'最长块':>7s}")
        for name, v in blk["predictors"].items():
            print(f"   {name:28s} {100 * (v['degenerate_share'] or 0):8.2f}% "
                  f"{100 * (v['hit_at_200ms'] or 0):7.2f}% "
                  f"{100 * (v['hit_at_200ms_excluding_degenerate'] or 0):13.2f}% "
                  f"{100 * (v['degenerate_share_of_misses_at_200ms'] or 0):10.1f}% "
                  f"{v['identical_start_blocks']['runs_ge_5']:7d} "
                  f"{v['identical_start_blocks']['longest_run']:7d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
