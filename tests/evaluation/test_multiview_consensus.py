"""Fast tests for the offline multi-view consensus simulation (synthetic frames only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import multiview_consensus as C


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    gt_s = np.arange(10) * 1.0
    for m, bias in (("a", 0.0), ("b", 0.02), ("c", -0.03), ("d", 0.30)):
        for i in range(10):
            noise = 0.30 if (m == "d" and i == 3) else rng.normal(0, 0.01)
            rows.append({"predictor": m, "item_id": "songA", "character_index": i,
                         "gt_start_sec": gt_s[i], "gt_end_sec": gt_s[i] + 0.5,
                         "pred_start_sec": gt_s[i] + bias + noise,
                         "pred_end_sec": gt_s[i] + 0.5 + bias + noise,
                         "both_err": max(abs(bias + noise), abs(bias + noise)),
                         "hit100": 1.0 if abs(bias + noise) <= 0.1 else 0.0,
                         "is_last_char": 1.0 if i == 9 else 0.0,
                         "is_first_char": 1.0 if i == 0 else 0.0,
                         "frac_pos": i / 9, "gt_dur_sec": 0.5, "item_duration_sec": 12.0})
    return pd.DataFrame(rows)


def test_ensemble_frame_and_membership():
    wide = C.ensemble_frame(_frame(), ["a", "b", "c", "d"])
    assert wide.attrs["members"] == ["a", "b", "c", "d"]
    assert len(wide) == 10
    assert np.isfinite(wide["a__s"].to_numpy(dtype=float)).all()
    with pytest.raises(ValueError):
        C.ensemble_frame(_frame(), ["a"])               # a single member is not an ensemble
    two = C.ensemble_frame(_frame(), ["a", "b"])
    assert two.attrs["members"] == ["a", "b"]


def test_strategies_rank_and_budget_is_tracked():
    out = C.simulate(C.ensemble_frame(_frame(), ["a", "b", "c", "d"]), reference="a")
    strat = out["strategies"]
    assert out["reference_predictor"] == "a"
    assert strat["S0_single_reference"]["realignment_budget"] == 0.0
    assert strat["S1_median_all"]["realignment_budget"] == 1.0
    assert strat["S4_gate_p80_median"]["realignment_budget"] <= 1.0
    # member "a" is the best single system, so consensus cannot beat it by much; the GT oracle must
    assert strat["S7_oracle_member_pick"]["deployable"] is False
    assert strat["S7_oracle_member_pick"]["hit100"] >= strat["S1_median_all"]["hit100"]
    assert out["summary"]["gap_closed_by_consensus_share"] is None or \
        0.0 <= out["summary"]["gap_closed_by_consensus_share"] <= 1.5


def test_vote_bucket_picks_the_majority():
    a = np.array([[0.00, 0.01, 0.02, 0.90], [0.10, 0.11, 0.60, 0.61]])
    v = C._vote_bucket(a)
    assert abs(v[0] - 0.02) <= 0.021
    # no strict majority (2 vs 2) -> falls back to the median of the tied buckets
    assert abs(v[1] - 0.3) <= 0.31


def test_agreement_cluster_is_outlier_robust():
    a = np.array([[0.0, 0.01, 0.02, 5.0]])
    w = C._agreement_weighted(a)
    assert abs(w[0] - 0.01) < 1e-6        # the 5.0 outlier is excluded from the cluster
    # the naive weighted mean was dragged to ~0.5: keep that regression documented
    naive = np.average(a[0], weights=[3, 3, 3, 1])
    assert naive > 0.4


def test_median_and_trimmed_mean_reject_outliers():
    a = np.array([[1.0, 1.02, 0.98, 50.0, 1.01]])
    assert abs(float(C._median(a)[0]) - 1.01) < 0.05
    assert abs(float(C._trimmed_mean(a)[0]) - 1.0) < 0.05
