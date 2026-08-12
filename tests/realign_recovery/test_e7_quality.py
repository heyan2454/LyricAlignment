"""E7 pure-metric unit tests (synthetic data, no real run dependencies)."""
from __future__ import annotations

import pytest

from lyricalign.realign_recovery.e7_metrics import (
    accept_reject_metrics,
    auroc,
    classify_repair,
    classify_unit_repair,
    pairwise_metrics,
    rank_metrics,
    unit_accept_reject_metrics,
)


def test_auroc_perfect_separation():
    scores = [0.1, 0.2, 0.3, 0.8, 0.9, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    assert auroc(scores, labels) == pytest.approx(1.0)


def test_auroc_random_equals_half():
    scores = [0.1, 0.4, 0.6, 0.9, 0.2, 0.7, 0.3, 0.8]
    labels = [0, 0, 0, 0, 1, 1, 1, 1]
    pos_sum = 2 + 3 + 6 + 7
    expected = (pos_sum - 4 * 5 / 2) / (4 * 4)
    assert auroc(scores, labels) == pytest.approx(expected)
    assert expected == pytest.approx(0.5)


def test_auroc_reversed():
    scores = [0.9, 0.8, 0.7, 0.2, 0.1, 0.05]
    labels = [0, 0, 0, 1, 1, 1]
    assert auroc(scores, labels) == pytest.approx(0.0)


def test_auroc_ties():
    scores = [0.5, 0.5, 0.5, 0.5]
    labels = [0, 0, 1, 1]
    assert auroc(scores, labels) == pytest.approx(0.5)


def test_auroc_single_class_none():
    assert auroc([1.0, 2.0], [1, 1]) is None
    assert auroc([1.0, 2.0], [0, 0]) is None
    assert auroc([], []) is None


def test_pairwise_metrics_perfect():
    deltas = [0.3, 0.2, 0.1, -0.1, -0.2]
    improved = [True, True, True, False, False]
    old_errs = [0.5, 0.6, 0.4, 0.3, 0.9]
    out = pairwise_metrics(deltas, improved, old_errs)
    assert out["n"] == 5
    assert out["accuracy"] == pytest.approx(1.0)
    assert out["auroc"] == pytest.approx(1.0)
    assert out["catastrophic_n"] == 0


def test_pairwise_metrics_catastrophic_subset():
    deltas = [0.3, 0.2, 0.1, -0.1, -0.2]
    improved = [True, True, True, False, False]
    old_errs = [1.5, 0.6, 0.4, 0.3, 2.0]
    out = pairwise_metrics(deltas, improved, old_errs)
    assert out["catastrophic_n"] == 2
    assert out["catastrophic_accuracy"] == pytest.approx(1.0)
    assert out["catastrophic_auroc"] == pytest.approx(1.0)


def test_pairwise_metrics_none_old_error_skipped():
    deltas = [0.3, 0.2]
    improved = [True, True]
    old_errs = [None, 0.5]
    out = pairwise_metrics(deltas, improved, old_errs)
    assert out["n"] == 1


def test_rank_metrics_basic():
    eps = [
        {"scored_variants": [("a", 0.9), ("b", 0.5), ("c", 0.2)],
         "gt_best": "a", "gt_best_is_oracle": True},
        {"scored_variants": [("a", 0.1), ("b", 0.5), ("c", 0.9)],
         "gt_best": "b", "gt_best_is_oracle": False},
    ]
    out = rank_metrics(eps)
    assert out["n_episodes"] == 2
    assert out["top1_hit_rate"] == pytest.approx(0.5)
    assert out["top2_hit_rate"] == pytest.approx(1.0)
    assert out["ranking_regret_mean"] == pytest.approx(0.5)
    assert out["oracle_best_correct_rate"] == pytest.approx(1.0)


def test_rank_metrics_misses():
    eps = [
        {"scored_variants": [("a", 0.1), ("b", 0.5), ("c", 0.9)],
         "gt_best": "a", "gt_best_is_oracle": False},
        {"scored_variants": [("a", 0.9), ("b", 0.5)],
         "gt_best": "b", "gt_best_is_oracle": False},
    ]
    out = rank_metrics(eps)
    assert out["n_episodes"] == 2
    assert out["top1_hit_rate"] == pytest.approx(0.0)
    assert out["top2_hit_rate"] == pytest.approx(0.5)
    assert out["ranking_regret_mean"] == pytest.approx(1.5)


def test_rank_metrics_skips_no_score_gt_best():
    eps = [
        {"scored_variants": [("a", 0.9), ("c", 0.2)],
         "gt_best": "b", "gt_best_is_oracle": False},
    ]
    out = rank_metrics(eps)
    assert out["n_episodes"] == 0


def test_classify_repair_successful():
    old = [2.5, 1.5, 0.4]
    new = [0.3, 0.2, 0.1]
    assert classify_repair(old, new) == "successful_repair"


def test_classify_repair_harmful_new_unsafe():
    old = [0.3, 0.2]
    new = [2.5, 0.1]
    assert classify_repair(old, new) == "harmful"


def test_classify_repair_harmful_no_fix():
    old = [2.5, 0.2]
    new = [2.0, 0.1]
    assert classify_repair(old, new) == "harmful"


def test_classify_repair_neutral():
    old = [0.3, 0.2]
    new = [0.4, 0.1]
    assert classify_repair(old, new) == "neutral"


def test_classify_repair_partial_fix_neutral():
    old = [2.5, 2.0]
    new = [2.0, 0.1]
    assert classify_repair(old, new) == "neutral"


def test_classify_repair_none_old():
    old = [None, None, 0.3]
    new = [0.2, 0.3, 0.1]
    assert classify_repair(old, new) == "neutral"


def test_accept_reject_metrics():
    rows = [
        {"repair_class": "successful_repair", "detector_accept": True},
        {"repair_class": "successful_repair", "detector_accept": True},
        {"repair_class": "successful_repair", "detector_accept": False},
        {"repair_class": "harmful", "detector_accept": True},
        {"repair_class": "harmful", "detector_accept": False},
        {"repair_class": "neutral", "detector_accept": False},
    ]
    out = accept_reject_metrics(rows)
    assert out["tp"] == 2 and out["fn"] == 1
    assert out["fp"] == 1 and out["tn"] == 1
    assert out["successful_repair_accept_rate_tpr"] == pytest.approx(2 / 3)
    assert out["good_repair_rejected_rate_fnr"] == pytest.approx(1 / 3)
    assert out["harmful_repair_accepted_rate_fpr"] == pytest.approx(0.5)
    assert out["neutral_total"] == 1


def test_classify_unit_repair_successful():
    assert classify_unit_repair(2.5, 0.5) == "successful_repair"


def test_classify_unit_repair_harmful_safe_to_unsafe():
    assert classify_unit_repair(0.5, 2.5) == "harmful"


def test_classify_unit_repair_unsafe_unsafe_neutral():
    assert classify_unit_repair(2.5, 3.5) == "neutral"


def test_classify_unit_repair_none_inputs():
    assert classify_unit_repair(None, 0.5) == "neutral"
    assert classify_unit_repair(2.5, None) == "neutral"


def test_unit_accept_reject_metrics_basic():
    rows = [
        {"repair_class": "successful_repair", "detector_accept": True},
        {"repair_class": "successful_repair", "detector_accept": False},
        {"repair_class": "harmful", "detector_accept": True},
        {"repair_class": "harmful", "detector_accept": False},
        {"repair_class": "neutral", "detector_accept": False},
    ]
    out = unit_accept_reject_metrics(rows, n_all_gt_units=10, n_all_det_units=8)
    assert out["tp"] == 1 and out["fn"] == 1
    assert out["fp"] == 1 and out["tn"] == 1
    assert out["n_covered_status"] == 4
    assert out["n_all_gt_units"] == 10 and out["n_all_det_units"] == 8
    assert out["coverage_gt"] == pytest.approx(0.5)
