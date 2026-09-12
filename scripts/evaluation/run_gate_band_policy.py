#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measured gate behaviour vs the label-side ceiling, at each candidate SAFE edge.

Round 35 established what a *perfect* predictor could wave through at SAFE ≤100/160/200 ms.  This
round measures what an actual confidence-based gate achieves on the same edges, with the threshold
fitted only on a fit slice and evaluated on a disjoint evaluation slice, so the reported numbers are
not in-sample.  Two corpora are used because each has posteriors: GTSinger (human word-level GT,
studio a-cappella, split by item into two halves and run both directions) and M4Singer long-form
(weak labels; fit on the train split, evaluate on validation, and report the test split as a frozen
transfer only — never used for fitting).

The gap between measured and ceiling is the detector's remaining headroom: the number a budget
request should quote, where the ceiling alone is not.

    PYTHONPATH=src python scripts/evaluation/run_gate_band_policy.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as GG
from lyricalign.analysis import label_noise_ceiling as LN
from lyricalign.analysis import redecode_budget as RB
from lyricalign.analysis import trigger_fusion as TF

# score ladder: each rung is the previous one plus one more free signal, so the columns of the
# "reverse requirement table" are directly comparable increments rather than unrelated models
SCORE_RUNGS = ("r1_entropy", "r2_entropy_inversion", "r3_entropy_inversion_gap", "r4_fused_rank",
              "r5_oracle_error_bound")

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_gate_band_policy"
EDGES = (0.10, 0.16, 0.20)
FALSE_SAFE_BUDGETS = (0.02, 0.05)


def ceiling_for(err: np.ndarray) -> dict[str, Any]:
    return LN.gate_operating_points(pd.Series(err), safe_edges=EDGES, unsafe_edge=0.25)


def add_score_ladder(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the five rung scores (higher = more suspicious) to a per-unit frame."""
    d = TF.build_features(frame)
    ent = TF._num(d, "raw_entropy_end")
    if not ent.notna().any():
        ent = TF._num(d, "end_entropy")
    inv = TF._num(d, "f_inversion").fillna(0.0)
    gap = TF._num(d, "gap_over_core")
    gap_n = gap.rank(pct=True)
    ent_n = ent.rank(pct=True)
    d["r1_entropy"] = ent_n
    d["r2_entropy_inversion"] = 0.5 * ent_n + 0.5 * inv
    d["r3_entropy_inversion_gap"] = pd.concat(
        [ent_n, inv, gap_n], axis=1).mean(axis=1, skipna=True)
    d["r4_fused_rank"] = TF._num(d, "fused_mean_rank")
    d["r5_oracle_error_bound"] = pd.to_numeric(d["err"], errors="coerce")
    return d


def fold(frame: pd.DataFrame, *, err_col: str, fit_mask: np.ndarray, label: str,
         rungs: Sequence[str] = SCORE_RUNGS) -> dict[str, Any]:
    """Evaluate every score rung on the same fit/eval split and the same ceiling."""
    fit = frame[fit_mask]
    ev = frame[~fit_mask]
    if len(fit) < 200 or len(ev) < 200:
        return {"label": label, "available": False, "fit_units": int(len(fit)),
                "eval_units": int(len(ev))}
    ceil = ceiling_for(ev[err_col].to_numpy(dtype=float))
    res: dict[str, Any] = {"label": label, "available": True, "fit_units": int(len(fit)),
                           "eval_units": int(len(ev)),
                           "eval_true_unsafe_share": ceil["unsafe_share"],
                           "rung_coverage": {r: round(float(ev[r].notna().mean()), 4) for r in rungs
                                             if r in ev.columns},
                           "by_rung": {}}
    for rung in rungs:
        if rung not in ev.columns or ev[rung].notna().sum() < 200:
            res["by_rung"][rung] = {"available": False}
            continue
        per_budget: dict[str, Any] = {}
        for budget in FALSE_SAFE_BUDGETS:
            per_budget[f"{int(budget * 100)}pct"] = RB.band_policy_table(
                ev[err_col], ev[rung], edges=EDGES,
                fit_err=fit[err_col], fit_score=fit[rung],
                false_safe_budget=budget, ceiling=ceil)
        res["by_rung"][rung] = {"available": True, "by_budget": per_budget}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    gts = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    go = gts[gts["pipeline"] == "official"].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec",
                "raw_entropy_end"]).copy()
    go["err"] = np.maximum((go["pred_start_sec"] - go["gt_start_sec"]).abs(),
                           (go["pred_end_sec"] - go["gt_end_sec"]).abs())
    go["score"] = pd.to_numeric(go["raw_entropy_end"], errors="coerce")
    go = go.dropna(subset=["err", "score"])
    # the gap rung exists only where a measurable inter-unit gap exists, so it is joined as a
    # partial-coverage feature and the ladder degrades gracefully where it is missing
    gk = ["item", "model", "audio_input", "mode", "unit_index"]
    try:
        gf = pd.read_csv(RUNS / "20260912_gap_shape/gtsinger_gap_features.csv.gz")
        go = go.merge(gf[gk + ["gap_over_core"]], on=gk, how="left")
    except FileNotFoundError:
        go["gap_over_core"] = np.nan
    go = add_score_ladder(go)
    items = sorted(go["item"].astype(str).unique())
    half = {it: (i % 2) for i, it in enumerate(items)}
    go["half"] = go["item"].map(half)

    m4 = pd.read_json(RUNS / "20260912_m4_longform_weakgt/longform_units.jsonl.gz", lines=True)
    m4 = m4.dropna(subset=["off_start_sec", "off_end_sec", "gt_start_sec", "gt_end_sec",
                           "end_entropy"]).copy()
    m4["err"] = np.maximum((m4["off_start_sec"] - m4["gt_start_sec"]).abs(),
                           (m4["off_end_sec"] - m4["gt_end_sec"]).abs())
    m4["score"] = pd.to_numeric(m4["end_entropy"], errors="coerce")
    m4 = m4.dropna(subset=["err", "score"])
    m4 = add_score_ladder(m4)

    m4_val = m4[m4["split"].isin(["train", "validation"])]
    m4_test = m4[m4["split"].isin(["train", "test"])]
    res: dict[str, Any] = {"schema": "gate_band_policy_v1", "edges": list(EDGES),
                           "unsafe_edge": 0.25,
                           "false_safe_budgets": list(FALSE_SAFE_BUDGETS),
                           "discipline": "threshold fitted on the fit slice only and evaluated on a "
                                         "disjoint slice; the ceiling is recomputed on the same "
                                         "evaluation slice so measured and ceiling are comparable; "
                                         "M4 test split is reported as frozen transfer only",
                           "score_used": "raw end-boundary entropy (the only confidence signal both "
                                         "corpora record)",
                           "corpora": {
                               "gtsinger_half_a_fit_half_b_eval": fold(
                                   go, err_col="err",
                                   fit_mask=(go["half"] == 0).to_numpy(dtype=bool), label="A->B"),
                               "gtsinger_half_b_fit_half_a_eval": fold(
                                   go, err_col="err",
                                   fit_mask=(go["half"] == 1).to_numpy(dtype=bool), label="B->A"),
                               "m4_train_fit_validation_eval": fold(
                                   m4_val, err_col="err",
                                   fit_mask=(m4_val["split"] == "train").to_numpy(dtype=bool),
                                   label="train->validation"),
                               "m4_train_fit_test_eval_transfer_only": fold(
                                   m4_test, err_col="err",
                                   fit_mask=(m4_test["split"] == "train").to_numpy(dtype=bool),
                                   label="train->test (transfer only)")}}
    (args.out_dir / "GATE_BAND_POLICY.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name, blk in res["corpora"].items():
        if not blk.get("available"):
            print(f"\n== {name}: unavailable (fit {blk.get('fit_units')} / eval {blk.get('eval_units')}) ==")
            continue
        print(f"\n== {name}: fit={blk['fit_units']:,} eval={blk['eval_units']:,} "
              f"eval true-unsafe(>=250ms)={100 * blk['eval_true_unsafe_share']:.2f}% ==")
        print("   coverage: " + ", ".join(f"{k}={100*v:.0f}%" for k, v in blk.get("rung_coverage", {}).items()))
        for rung, rb in blk["by_rung"].items():
            if not rb.get("available"):
                print(f"   {rung}: unavailable")
                continue
            for bkey, table in rb["by_budget"].items():
                for edge, v in table["by_edge"].items():
                    if "note" in v:
                        print(f"      {rung:24s} b{bkey:5s} {edge:6s} 不可行")
                        continue
                    print(f"      {rung:24s} b{bkey:5s} {edge:6s} accept={100*v['auto_accept_share']:6.2f}% "
                          f"ceiling={100*(v.get('ceiling_auto_accept_share') or 0):6.2f}% "
                          f"headroom={v.get('headroom_pp')}pp false_safe={100*(v.get('false_safe_share') or 0):4.2f}%")
        continue
        for bkey, table in blk["by_budget"].items():
            if not table.get("units"):
                print(f"   budget {bkey}: unavailable")
                continue
            print(f"   false-safe budget {bkey}:")
            print(f"      {'SAFE边':8s} {'实测放行':>9s} {'天花板放行':>11s} {'余量':>8s} "
                  f"{'实测误放':>9s} {'漏放(错但被拦)':>14s}")
            for edge, v in table["by_edge"].items():
                if "note" in v:
                    print(f"      {edge:8s} {v['note']}")
                    continue
                head = v.get("headroom_pp")
                print(f"      {edge:8s} {100 * v['auto_accept_share']:8.2f}% "
                      f"{100 * (v.get('ceiling_auto_accept_share') or 0):10.2f}% "
                      f"{head if head is not None else '—':>8} "
                      f"{100 * (v.get('false_safe_share') or 0):8.2f}% "
                      f"{100 * v['missed_unsafe_share']:13.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
