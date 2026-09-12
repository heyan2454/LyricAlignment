"""Tests for the quantisation-aware AUC diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import label_noise_ceiling as LN


def _synthetic(n: int = 600, seed: int = 4):
    """Score separates error perfectly; errors cluster near the threshold to exercise ambiguity."""
    rng = np.random.default_rng(seed)
    score = rng.uniform(0, 1, n)
    err = 0.05 + 0.3 * score + rng.normal(0, 0.005, n)
    return pd.DataFrame({"err": err, "score": score})


def test_threshold_sensitivity_is_monotone_for_a_clean_signal():
    d = _synthetic()
    out = LN.threshold_sensitivity(d["err"], d["score"])
    aucs = [v["auc"] for v in out["by_threshold"].values() if v["auc"] is not None]
    assert len(aucs) >= 4
    prevs = [v["prevalence"] for v in out["by_threshold"].values()]
    assert prevs == sorted(prevs, reverse=True)      # looser tolerance -> more positives
    assert aucs[0] > 0.9                             # near-perfect score on clean synthetic data


def test_ambiguous_exclusion_drops_units_and_reports_both_auc_views():
    """Errors are spread wide enough that both classes survive the exclusion (else AUC is None)."""
    rng = np.random.default_rng(6)
    n = 800
    score = rng.uniform(0, 1, n)
    d = pd.DataFrame({"err": 0.02 + 0.4 * score + rng.normal(0, 0.01, n), "score": score})
    res = LN.ambiguous_label_impact(d["err"], d["score"], threshold=0.2, label_quantum_sec=0.08)
    assert res["available"] is True and res["ambiguous_units"] > 0
    assert 0.05 < res["ambiguous_share"] < 0.8
    assert res["auc_all"] is not None and res["auc_excluding_ambiguous"] is not None
    assert res["auc_excluding_ambiguous"] >= res["auc_all"] - 0.02   # cannot get much worse
    assert res["auc_change"] is not None
    assert res["prevalence_excluding_ambiguous"] is not None


def test_slice_decomposition_reports_prevalence_and_auc():
    d = _synthetic()
    d["family"] = ["a"] * 300 + ["b"] * (len(d) - 300)
    out = LN.slice_decomposition(d, err_col="err", score_col="score",
                                slices={"all": np.ones(len(d), dtype=bool),
                                        "family_a": (d["family"] == "a").to_numpy(dtype=bool),
                                        "tiny": (np.arange(len(d)) < 5)})
    assert out["all"]["units"] == len(d) and out["all"]["auc"] > 0.9
    assert out["family_a"]["units"] == 300
    assert out["tiny"].get("units") == 5 and out["tiny"].get("note") == "too few units"


def test_degenerate_inputs_return_none_not_crash():
    d = pd.DataFrame({"err": [np.nan] * 5, "score": [1, 2, 3, 4, 5]})
    assert LN.threshold_sensitivity(d["err"], d["score"])["by_threshold"]["100ms"]["auc"] is None
    res = LN.ambiguous_label_impact(d["err"], d["score"], threshold=0.1, label_quantum_sec=0.08)
    assert res["available"] is False


def test_metric_stability_reports_shift_bound_and_knife_edge_share():
    rng = np.random.default_rng(9)
    n = 500
    err = np.abs(rng.normal(0.04, 0.05, n))          # median well below the 80 ms grid
    out = LN.metric_stability(pd.Series(err), tolerances=(0.05, 0.1, 0.2),
                              label_quantum_sec=0.08, prediction_quantum_sec=0.08)
    assert out["units"] == n
    t50, t200 = out["by_tolerance"]["50ms"], out["by_tolerance"]["200ms"]
    assert t50["knife_edge_share"] > t200["knife_edge_share"]        # tighter threshold is more fragile
    assert t50["systematic_shift_bound_pp"] > t200["systematic_shift_bound_pp"]
    assert t50["hit_share_if_errors_shifted_plus_quantum"] >= t50["hit_share"] >= \
        t50["hit_share_if_errors_shifted_minus_quantum"]


def test_gap_artifact_bound_only_counts_losers_with_one_quantum_slack():
    n = 400
    rng = np.random.default_rng(10)
    a = np.abs(rng.normal(0.05, 0.02, n))                  # A comfortably inside
    b = np.abs(rng.normal(0.105, 0.004, n))                # B misses by ~5 ms -> inside one quantum
    res = LN.gap_artifact_bound(pd.Series(a), pd.Series(b), tol=0.1, quantum_sec=0.08)
    assert res["available"] is True
    assert res["gap_pp"] > 0
    # the whole gap is explainable by grid slack here, because B misses by less than one quantum
    assert res["gap_exceeds_grid_slack"] is False
    assert res["a_ahead_by_grid_slack_units"] > 0
    assert res["solid_disagreement_units"] == 0 or res["a_ahead_solid_units"] == 0

    # a clearly-worse B (errors far beyond the quantum) produces an attributable gap
    b_far = np.abs(rng.normal(0.4, 0.05, n))
    res2 = LN.gap_artifact_bound(pd.Series(a), pd.Series(b_far), tol=0.1, quantum_sec=0.08)
    assert res2["gap_exceeds_grid_slack"] is True
    assert res2["a_ahead_solid_units"] > 100
    assert res2["max_spurious_gap_pp"] < res2["gap_pp"]


def test_gap_artifact_bound_degenerate_inputs():
    res = LN.gap_artifact_bound(pd.Series([np.nan] * 5), pd.Series([0.1] * 5), tol=0.1)
    assert res["available"] is False
