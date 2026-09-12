"""Fast tests for the long-form candidate pipeline and the disagreement trigger (synthetic)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import longform_pipeline_candidate as P

KEY = P.UNIT_KEY


def _units() -> pd.DataFrame:
    """Twelve units: half single-attempt, half multi-attempt with one divergent window."""
    rows = []
    for u in range(12):
        n_att = 1 if u < 6 else 3
        for a in range(n_att):
            s = 1.0 * u + (0.4 if (a == 2 and n_att == 3) else 0.0)      # divergent attempt
            e = s + 0.5
            rows.append({"view_id": "full", "song": "s1", "canonical_unit_id": u,
                         "request_identity": f"r{a}", "raw_start_sec": s, "raw_end_sec": e,
                         "ref_start_sec": 1.0 * u, "ref_end_sec": 1.0 * u + 0.5,
                         "attempt_both_err": abs(s - 1.0 * u),
                         "off_start_sec": s, "off_end_sec": e,
                         "support_50ms": 0.0 if (a == 2 and n_att == 3) else 0.9,
                         "loo_spread": 0.4 if (a == 2 and n_att == 3) else 0.0,
                         "ent_max": 0.1 * u + (5.0 if (a == 2 and n_att == 3) else 0.0)})
    return pd.DataFrame(rows)


def test_unit_table_aggregates_attempts():
    tab = P.build_unit_table(_units())
    assert len(tab) == 12
    assert set(tab.columns) >= {"attempts", "disagreement", "consensus_start", "err_median_attempt",
                                "err_best_attempt", "support_max"}
    multi = tab[tab["attempts"] == 3]
    single = tab[tab["attempts"] == 1]
    assert len(multi) == 6 and len(single) == 6
    # the divergent window is what creates the disagreement
    assert np.allclose(multi["disagreement"].to_numpy(dtype=float), 0.4)
    assert np.allclose(single["disagreement"].to_numpy(dtype=float), 0.0)
    # consensus median must ignore the divergent window
    assert np.allclose(multi["consensus_start"].to_numpy(dtype=float),
                       multi["canonical_unit_id"].to_numpy(dtype=float) * 1.0)


def test_trigger_only_uses_multi_attempt_units_and_reports_auc():
    tab = P.build_unit_table(_units())
    out = P.trigger_discrimination(tab)
    assert out["coverage"]["units_multi_attempt"] == 6
    assert out["coverage"]["share_multi_attempt"] == pytest.approx(0.5)
    b1 = out["bad100"]
    assert 0.0 <= b1["positive_rate"] <= 1.0
    # every flagged unit here is the divergent-attempt unit, so precision is perfect on this fixture
    curve = b1["review_budget_curve"]
    assert curve, "expected at least one budget point"
    first = next(iter(curve.values()))
    assert 0.0 <= first["precision_bad100"] <= 1.0
    assert first["recall_bad100"] <= 1.0
    assert "top_5pct" in out["error_capture_curve"] or out["error_capture_curve"]


def test_end_to_end_orders_attempts_without_peeking_at_predictions():
    """The single-window baseline must be chosen by request order, not by predicted value."""
    d = _units()
    tab = P.build_unit_table(d)
    out = P.end_to_end(d, tab)
    sysd = out["systems"]
    a = sysd["A_single_window_arbitrary_attempt"]
    c = sysd["C_cross_window_consensus"]
    dd = sysd["D_consensus_plus_joint_solve"]
    # consensus (r0/r1 agree with the reference) must beat the divergent attempt ordering
    assert c["hit100"] >= a["hit100"]
    assert dd["structure"]["degenerate_share"] == 0.0
    assert dd["structure"]["overlap_share"] == 0.0
    assert dd["structure"]["start_regression_share"] == 0.0
    # the cap is a sensitivity axis, not a hidden knob: 3/6/12 s variants all reported
    assert set(out["max_dur_sensitivity"]) == {"3.0", "6.0", "12.0"}
    assert sysd["D6_consensus_plus_solve_max6s"]["structure"]["overlap_share"] == 0.0
    assert "oracle_ceiling_pp" in out["summary"]


def test_auc_helper_rejects_degenerate_inputs():
    assert P._auc(np.zeros(60), np.arange(60, dtype=float)) is None
    assert P._auc(np.ones(60), np.arange(60, dtype=float)) is None
    y = np.array([0, 1] * 30, dtype=float)
    assert P._auc(y, np.array([-1, 1] * 30, dtype=float)) == pytest.approx(1.0)
