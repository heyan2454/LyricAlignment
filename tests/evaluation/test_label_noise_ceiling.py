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


def test_band_edge_stability_flags_a_grid_fragile_edge():
    """A dense error distribution under the grid makes the 100 ms edge carry no decision."""
    rng = np.random.default_rng(12)
    err = np.abs(rng.normal(0.03, 0.04, 1000))          # median well below the 80 ms grid
    out = LN.band_edge_stability(pd.Series(err), edges=(0.1, 0.25), quantum_sec=0.08)
    e100, e250 = out["by_edge"]["100ms"], out["by_edge"]["250ms"]
    assert e100["swing_pp"] > e250["swing_pp"]
    assert "100ms" in out["grid_fragile_edges"]
    assert e100["band_inside_share_if_edge_one_quantum_stricter"] < e100["band_inside_share"] < \
        e100["band_inside_share_if_edge_one_quantum_looser"]


def test_band_edge_stability_with_sparse_errors_is_stable():
    err = np.abs(np.random.default_rng(13).normal(0.5, 0.3, 800))   # mostly far beyond both edges
    out = LN.band_edge_stability(pd.Series(err), edges=(0.1, 0.25), quantum_sec=0.08)
    assert out["by_edge"]["100ms"]["swing_pp"] < 15.0
    assert "100ms" not in out["grid_fragile_edges"] or out["by_edge"]["100ms"]["swing_pp"] > 10.0
    assert out["units"] == 800


def test_band_edge_stability_empty_input():
    out = LN.band_edge_stability(pd.Series([], dtype=float))
    assert out["units"] == 0 and out["by_edge"] == {}


def test_detector_label_stability_flags_the_fragile_edge_only():
    rng = np.random.default_rng(21)
    n = 4000
    err = np.concatenate([np.abs(rng.normal(0.06, 0.02, n - 400)),      # dense near the 100 ms edge
                          np.abs(rng.normal(0.60, 0.10, 400))])          # clearly unsafe
    frozen = np.where(err < 0.10, "safe", np.where(err >= 0.25, "unsafe", "grey"))
    out = LN.detector_label_stability(pd.Series(err), pd.Series(frozen))
    assert out["available"] is True and out["units"] == n
    assert out["agreement_frozen_vs_recomputed"] == 1.0
    assert out["edges"]["safe_grey_100ms"]["verdict"] == "grid-fragile"
    assert "grey_unsafe_250ms" in out["usable_gate_edges"]


def test_detector_label_stability_detects_lineage_mismatch():
    err = np.linspace(0.0, 0.5, 2000)
    wrong = np.where(err < 0.15, "safe", "unsafe")      # a different edge than the recomputation uses
    out = LN.detector_label_stability(pd.Series(err), pd.Series(wrong))
    assert out["agreement_frozen_vs_recomputed"] < 0.95


def test_detector_label_stability_small_input():
    assert LN.detector_label_stability(pd.Series([0.1] * 10),
                                       pd.Series(["safe"] * 10))["available"] is False


def test_gate_operating_points_makes_all_three_axes_better_when_edge_moves_out():
    """Dense errors under the grid: a 100 ms edge waves less through *and* is less determined."""
    rng = np.random.default_rng(31)
    err = np.concatenate([np.abs(rng.normal(0.05, 0.05, 3000)),      # good system, sub-quantum median
                          np.abs(rng.normal(0.60, 0.15, 300))])       # a few clearly unsafe
    out = LN.gate_operating_points(pd.Series(err), safe_edges=(0.10, 0.20), unsafe_edge=0.25)
    assert out["units"] == err.size
    a, b = out["by_safe_edge"]["100ms"], out["by_safe_edge"]["200ms"]
    assert b["safe_share"] > a["safe_share"]                       # more auto-accept
    assert b["robust_safe_share"] > a["robust_safe_share"]         # and far more of it determined
    assert b["safe_share_robustness"] > a["safe_share_robustness"]
    assert b["grey_share"] < a["grey_share"]                       # smaller review queue
    assert b["swing_pp_if_edge_moved_one_quantum"] < a["swing_pp_if_edge_moved_one_quantum"]
    assert out["by_safe_edge"]["200ms"]["unsafe_share"] == out["unsafe_share"]


def test_gate_operating_points_shares_sum_to_one_and_handle_empty():
    err = pd.Series(np.linspace(0.0, 0.5, 501))
    out = LN.gate_operating_points(err, safe_edges=(0.1,), unsafe_edge=0.25)
    v = out["by_safe_edge"]["100ms"]
    assert abs(v["safe_share"] + v["grey_share"] + v["unsafe_share"] - 1.0) < 1e-6
    empty = LN.gate_operating_points(pd.Series([], dtype=float))
    assert empty["units"] == 0 and empty["by_safe_edge"] == {}


def test_degeneracy_contamination_separates_structural_from_timing_error():
    import numpy as np
    import pandas as pd
    from lyricalign.analysis import label_noise_ceiling as LN

    n = 1000
    err = np.full(n, 0.02)                      # healthy units are accurate
    deg = np.zeros(n, dtype=bool)
    deg[:100] = True                            # 100 units have no position at all
    err[deg] = 3.0
    out = LN.degeneracy_contamination(pd.Series(err), pd.Series(deg))
    assert out["units"] == n and out["degenerate_units"] == 100
    assert out["degenerate_share"] == pytest.approx(0.1, abs=1e-4)
    assert out["hit_at_200ms"] == pytest.approx(0.9, abs=1e-4)
    assert out["hit_at_200ms_excluding_degenerate"] == pytest.approx(1.0, abs=1e-4)
    assert out["degenerate_share_of_misses_at_200ms"] == pytest.approx(1.0, abs=1e-4)
    assert out["degenerate_median_err_ms"] == pytest.approx(3000.0, abs=1.0)


def test_degeneracy_contamination_handles_empty_and_all_degenerate():
    import numpy as np
    import pandas as pd
    from lyricalign.analysis import label_noise_ceiling as LN

    empty = LN.degeneracy_contamination(pd.Series([], dtype=float), pd.Series([], dtype=bool))
    assert empty["units"] == 0 and empty["degenerate_share"] is None
    all_deg = LN.degeneracy_contamination(pd.Series([1.0, 2.0]), pd.Series([True, True]))
    assert all_deg["hit_at_200ms_excluding_degenerate"] is None
    assert all_deg["degenerate_share"] == 1.0
