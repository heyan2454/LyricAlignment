"""Tests for the re-decode budget bounds (tiny hand-checkable frames)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import redecode_budget as RB

STEP = RB.STEP_SEC


def _frame(n: int = 200) -> pd.DataFrame:
    """Half the units correct, a quarter wrong-but-fixable, a quarter wrong-and-unreachable."""
    rng = np.random.default_rng(11)
    gt_end_bin = np.arange(n) * 10.0
    fixable = np.arange(n) % 4 < 2                     # 50 % reachable
    cand_end_bin = gt_end_bin + np.where(fixable, 0.0, 40.0)      # unreachable ones are far away
    idx = np.arange(n) % 4
    err = np.where(np.isin(idx, [1, 3]), 0.3, 0.02)               # half the units are wrong
    return pd.DataFrame({
        "raw_start_bin": gt_end_bin - 10, "raw_end_bin": cand_end_bin,
        "raw_top2cls_end": cand_end_bin + 1,
        "gt_end_bin": gt_end_bin, "gt_start_bin": gt_end_bin - 10,
        "raw_top2cls_start": gt_end_bin - 10,
        "both_abs_err_sec": err,
        "score": np.where(idx == 1, 0.9, np.where(idx == 3, 0.8, rng.uniform(0, 0.5, n))),
    })


def test_reachability_counts_within_one_bin():
    out = RB.reachability(_frame(), end_bin_col="raw_end_bin", second_col="raw_top2cls_end",
                          gt_bin_col="gt_end_bin")
    assert out["available"] is True
    assert out["reachable_share"] == pytest.approx(0.5, abs=0.01)


def test_bounds_separate_recoverable_from_unreachable_gain():
    d = _frame()
    d["fixable"] = (np.abs(d.raw_end_bin - d.gt_end_bin) <= 1) | \
                   (np.abs(d.raw_top2cls_end - d.gt_end_bin) <= 1)
    res = RB.bound_budget_value(d, score_col="score")
    assert res["available"] is True and res["units"] == 200
    assert res["baseline_hit"] == pytest.approx(0.5, abs=0.02)
    assert res["wrong_but_unreachable"] > 0
    big = res["budgets"]["20pct"]
    # the optimistic bound must be >= the reachable bound, and the trigger beats random here
    assert big["fused_trigger_optimistic_gain_pp"] >= big["fused_trigger_reachable_gain_pp"]
    assert big["fused_trigger_reachable_gain_pp"] > big["random_reachable_gain_pp"]
    assert big["oracle_by_recoverable_reachable_gain_pp"] >= big["fused_trigger_reachable_gain_pp"]
    assert big["oracle_by_error_reachable_gain_pp"] <= big["oracle_by_recoverable_reachable_gain_pp"]
    assert 0.0 <= big["fused_trigger_precision_on_wrong"] <= 1.0
    assert res["headroom"]["unrecoverable_share_of_wrong_units"] > 0.2
    assert res["headroom"]["trigger_capture_of_recoverable_oracle"] <= 1.0


def test_small_frames_report_unavailable():
    d = _frame(40)
    assert RB.bound_budget_value(d, score_col="score")["available"] is False


def test_reachability_missing_columns():
    d = _frame().drop(columns=["gt_end_bin"])
    assert RB.reachability(d, end_bin_col="raw_end_bin", second_col="raw_top2cls_end",
                           gt_bin_col="gt_end_bin")["available"] is False
