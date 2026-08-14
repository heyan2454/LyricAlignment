"""Tests for WP7 E5 no-GT candidate selector / safety (no_gt_selector)."""
from __future__ import annotations

import pytest

from lyricalign.unit_realign.no_gt_selector import (
    assert_no_label_leak,
    evaluate_heldout_once,
    freeze_simple_selector,
    disjoint_check,
)


# --------------------------------------------------------------------------- #
# assert_no_label_leak (W-review P1-4)
# --------------------------------------------------------------------------- #
def test_assert_no_label_leak_allows_gt_free_row():
    assert_no_label_leak({"request_id": "r", "canonical_unit_id": 3, "error_ms": 5.0,
                          "detector_p_bad": 0.1})


@pytest.mark.parametrize("payload", [
    {"verdict": "bad"},
    {"oracle_disp": 1.0},
    {"gt_eval": None},
    {"evaluator_row": {}},
    {"attempt": {"gt_eval": {"ok": True}}},   # nested under evaluator-only wrapper
    {"raw_rows": [{"verdict": 1}]},            # nested inside an allowed-array key
])
def test_assert_no_label_leak_blocks_evaluator_fields(payload):
    with pytest.raises(ValueError):
        assert_no_label_leak(payload)


def test_assert_no_label_leak_allows_repeat_gt_starts_wrapper():
    # request-construction parameter, not an evaluator outcome -> must be allowed.
    assert_no_label_leak({"repeat_gt_starts": True, "request_id": "r"})


# --------------------------------------------------------------------------- #
# freeze / heldout (P1-2 true-85th + P1-3 disjoint guard)
# --------------------------------------------------------------------------- #
def _feat_rows(n=20, p_bad=0.3):
    return [
        {"song_id": "s", "region_id": f"r{i % 4}", "canonical_unit_id": i,
         "request_id": f"req-{i}", "detector_p_bad": p_bad,
         "entropy": 1.0, "margin": 0.1, "raw_official_disagreement_ms": 10.0}
        for i in range(n)
    ]


def test_freeze_selector_uses_true_85th_percentile():
    rows = [{"detector_p_bad": float(i)} for i in range(20)]  # 20 single-key rows 0..19
    frozen = freeze_simple_selector(rows, split="discovery")
    # p85 of 0..19 -> index int(0.85*20)=17 -> value 17.0
    assert frozen["rules"]["p_bad_threshold"] == 17.0
    assert frozen["split"] == "discovery"


def test_disjoint_check_detects_freeze_leak():
    sel = {"split": "discovery"}
    heldout = [{"split": "heldout"}, {"split": "discovery"}]  # leaks freeze split
    assert disjoint_check(sel, heldout) is True
    clean = [{"split": "heldout"}, {"split": "heldout"}]
    assert disjoint_check(sel, clean) is False


def test_evaluate_heldout_once_two_operating_points():
    rows = _feat_rows(20)
    frozen = freeze_simple_selector(rows, split="discovery")
    eval_ = evaluate_heldout_once(frozen, rows)
    assert eval_["evaluated_once"] is True
    ops = eval_["operating_points"]
    assert "recovery_first" in ops and "safety_first" in ops
    # safety-first requires the proxy (detector_p_bad) which is present in _feat_rows.
    assert "recovery_first" in ops and "safety_first" in ops
