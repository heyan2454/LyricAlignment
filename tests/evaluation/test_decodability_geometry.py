"""Tests for the unreachable-geometry and cross-domain bias-direction helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import decodability_ceiling as D

STEP = D.TIMESTAMP_STEP_SEC


def _frame(rows: list[tuple[int, int, int]]) -> pd.DataFrame:
    """rows are (top1_bin, top2_bin, gt_bin) for an end boundary."""
    return pd.DataFrame({"raw_end_sec": [r[0] * STEP for r in rows],
                         "raw_top2cls_end": [r[1] for r in rows],
                         "gt_end_sec": [r[2] * STEP for r in rows]})


def test_gt_between_candidates_is_counted_as_span_reachable():
    f = _frame([(100, 110, 105), (100, 110, 105)])
    out = D.unreachable_geometry(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                                 gt_sec="gt_end_sec", tol_bins=1)
    assert out["available"] is True and out["unreachable_units"] == 2
    assert out["between_candidates_share_of_unreachable"] == 1.0
    assert out["outside_span_share_of_unreachable"] == 0.0


def test_gt_outside_span_is_split_left_right():
    f = _frame([(100, 101, 90), (100, 101, 130)])      # left, right
    out = D.unreachable_geometry(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                                 gt_sec="gt_end_sec", tol_bins=1)
    assert out["between_candidates_share_of_unreachable"] == 0.0
    assert out["outside_left_share_of_unreachable"] == 0.5
    assert out["outside_right_share_of_unreachable"] == 0.5
    assert out["distance_outside_bins"]["median_sec_when_outside"] > 0


def test_top2cls_is_treated_as_a_bin_index_not_seconds():
    """Regression guard: dividing the class index by the step inflated spans to ~1/step."""
    f = _frame([(50, 51, 500)])                          # adjacent candidates, far GT
    out = D.unreachable_geometry(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                                 gt_sec="gt_end_sec", tol_bins=1)
    span = out["candidate_span_bins_when_unreachable"]["median_sec"]
    assert span == pytest.approx(STEP)                   # one bin, not 1/step bins


def test_signed_bias_and_transfer_direction_check():
    studio = {"long_note": {"end": {"available": True, "median_ms": -40.0, "mean_ms": -20.0,
                                    "late_share": 0.24, "abs_median_ms": 40.0}}}
    target = {"long_note": {"end": {"available": True, "median_ms": 32.4, "mean_ms": 45.0,
                                    "late_share": 0.74, "abs_median_ms": 32.4}}}
    chk = D.transfer_direction_check(studio, target, "long_note")
    assert chk["available"] is True and chk["same_direction"] is False
    assert "NOT transferable" in chk["verdict"]
    assert chk["late_share_gap"] == pytest.approx(0.5, abs=0.01)
    # target is already keyed by stratum, so pass it directly (wrapping it once more yields
    # available=False, which is the correct graceful-degradation path exercised below)
    same = D.transfer_direction_check(target, target)
    assert same["same_direction"] is True and same["verdict"] == "transferable"
    missing = D.transfer_direction_check({}, target)
    assert missing == {"available": False}


def test_signed_bias_from_columns():
    f = pd.DataFrame({"pred_end_sec": [1.0, 2.0, 3.0], "gt_end_sec": [1.02, 1.9, 3.0]})
    out = D.signed_bias(f, pred_col="pred_end_sec", gt_col="gt_end_sec")
    assert out["n"] == 3
    assert out["median_ms"] == pytest.approx(0.0, abs=1.0)
    assert out["late_share"] == pytest.approx(1 / 3, abs=1e-3)
