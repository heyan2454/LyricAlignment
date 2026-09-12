"""Tests for the decodability-ceiling probe (analytic fixtures on the 0.08 s bin grid)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import decodability_ceiling as D

STEP = D.TIMESTAMP_STEP_SEC


def _frame(bins: list[tuple[int, int, int, int]], dur: list[float], prob: list[float]) -> pd.DataFrame:
    """bins rows are (pred_start_bin, pred_end_bin, top2_start_bin, top2_end_bin)."""
    return pd.DataFrame({
        "item": ["a"] * len(bins),
        "raw_start_sec": [b[0] * STEP for b in bins],
        "raw_end_sec": [b[1] * STEP for b in bins],
        "raw_top2cls_start": [b[2] for b in bins],
        "raw_top2cls_end": [b[3] for b in bins],
        "raw_top1_start": prob,
        "raw_top1_end": prob,
        "gt_start_sec": [b[0] * STEP for b in bins],
        "gt_end_sec": [b[1] * STEP for b in bins],
        "gt_dur_sec": dur,
    })


def test_containment_recognises_exact_top1_and_top2():
    gt_end_bin, pred_end_bin, second_end_bin = 50, 50, 60
    f = _frame([(10, pred_end_bin, 10, second_end_bin)], [1.2], [0.9])
    f["gt_end_sec"] = gt_end_bin * STEP
    out = D.containment(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                        gt_sec="gt_end_sec")
    assert out["top1_within_0bins"] == 1.0
    assert out["in_top2_union_within_0bins"] == 1.0
    assert out["outside_top2_within_0bins"] == 0.0
    assert out["distance_to_nearest_candidate_bins"]["median"] == 0.0


def test_containment_marks_unreachable_gt():
    # GT end bin 50; candidates are 40 (top-1) and 45 (top-2) -> outside both, > 1 bin away
    f = _frame([(10, 40, 10, 45)], [1.5], [0.9])
    f["gt_end_sec"] = 50 * STEP
    out = D.containment(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                        gt_sec="gt_end_sec")
    assert out["top1_within_0bins"] == 0.0
    assert out["in_top2_union_within_0bins"] == 0.0
    assert out["outside_top2_within_0bins"] == 1.0
    assert out["distance_to_nearest_candidate_bins"]["median"] == 5.0
    assert out["distance_to_nearest_candidate_sec"]["median"] == pytest.approx(5 * STEP)


def test_within_one_bin_tolerance_is_generous_to_grid_noise():
    f = _frame([(10, 40, 10, 41)], [1.5], [0.9])
    f["gt_end_sec"] = 41 * STEP                       # exactly the runner-up bin
    out = D.containment(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end", gt_sec="gt_end_sec")
    assert out["top1_within_0bins"] == 0.0
    assert out["top2_within_0bins"] == 1.0
    assert out["in_top2_union_within_1bins"] == 1.0


def test_strata_analysis_splits_long_and_short_notes():
    f = _frame([(10, 40, 12, 41), (20, 60, 22, 61), (30, 80, 32, 81)],
               [0.2, 1.4, 0.3], [0.8, 0.6, 0.9])
    f["gt_end_sec"] = [40 * STEP, 60 * STEP, 80 * STEP]
    f["gt_start_sec"] = f["raw_start_sec"]
    res = D.strata_analysis(f, strides=("all_units", "long_note", "short_note"))
    assert res["all_units"]["units"] == 3
    assert res["long_note"]["units"] == 1
    assert res["short_note"]["units"] == 2
    assert res["long_note"]["end"]["top1_within_0bins"] == 1.0


def test_confidence_auc_is_reported_in_the_positive_orientation():
    # 20 units: half reachable, and the reachable ones carry higher top-1 probability
    rows, probs, gt = [], [], []
    for i in range(20):
        reachable = i % 2 == 0
        pred_bin = 100 if reachable else 100 + 20 + i
        rows.append((10, pred_bin, 11, pred_bin + 1))
        probs.append(0.9 if reachable else 0.2)
        gt.append(100 * STEP)
    f = _frame(rows, [1.0] * 20, probs)
    f["gt_end_sec"] = gt
    out = D.containment(f, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                        gt_sec="gt_end_sec", top1_prob="raw_top1_end")
    auc = out.get("auc_top1_prob_predicts_gt_within_1bin_of_candidate")
    assert auc is not None and auc > 0.9, out
    assert "label=1 means" in out["auc_orientation"]


def test_compare_checkpoints_groups_by_model():
    f = _frame([(10, 40, 11, 41), (20, 60, 21, 61)], [1.2, 1.4], [0.9, 0.7])
    f["gt_end_sec"] = [40 * STEP, 60 * STEP]
    f["model"] = ["r0", "r2"]
    out = D.compare_checkpoints(f)
    assert set(out) == {"r0", "r2"}
    assert out["r0"]["long_note"]["units"] == 1
    assert out["r2"]["all_units"]["end_top1_exact"] == 1.0
