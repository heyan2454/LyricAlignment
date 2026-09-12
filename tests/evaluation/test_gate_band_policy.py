"""Tests for the measured-vs-ceiling band policy (redecode_budget.band_policy_table)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import redecode_budget as RB


def _corpus(n: int = 4000, seed: int = 3):
    """Good system: dense sub-quantum errors; score correlates with the *rare* gross errors."""
    rng = np.random.default_rng(seed)
    score = rng.uniform(0, 1.8, n)
    err = 0.02 + 0.05 * score / 1.8 + rng.normal(0, 0.01, n)
    gross = rng.random(n) < 0.12
    err = np.where(gross, 0.15 + 0.5 * score / 1.8, np.abs(err))
    return pd.DataFrame({"err": err, "score": score})


def test_threshold_is_fit_on_fit_slice_and_measured_on_the_other():
    d = _corpus()
    fit, ev = d.iloc[:2000], d.iloc[2000:]
    ceil = {"by_safe_edge": {"200ms": {"safe_share": 0.99, "robust_safe_share": 0.95}}}
    out = RB.band_policy_table(ev["err"], ev["score"], edges=(0.20,),
                              fit_err=fit["err"], fit_score=fit["score"],
                              false_safe_budget=0.05, ceiling=ceil)
    assert out["available"] is True and out["units"] == len(ev)
    v = out["by_edge"]["200ms"]
    assert 0.0 < v["auto_accept_share"] <= 1.0
    assert v["ceiling_auto_accept_share"] == 0.99
    assert v["headroom_pp"] == pytest.approx(100 * (0.99 - v["auto_accept_share"]), abs=0.05)
    # the fit-slice guarantee holds on the fit slice by construction
    assert v["fit_false_safe_share"] <= 0.05 + 1e-9


def test_infeasible_budget_is_reported_not_silently_forced():
    d = _corpus()
    bad = d.assign(err=lambda x: x["err"] + 0.5)          # everything above every edge
    out = RB.band_policy_table(bad["err"], bad["score"], edges=(0.10, 0.20),
                              fit_err=bad["err"][:1000], fit_score=bad["score"][:1000],
                              false_safe_budget=0.02)
    for v in out["by_edge"].values():
        assert "note" in v and "no threshold meets the budget" in v["note"]


def test_tighter_budget_never_accepts_more_than_looser_one():
    d = _corpus()
    fit, ev = d.iloc[:2000], d.iloc[2000:]
    tight = RB.band_policy_table(ev["err"], ev["score"], edges=(0.20,), fit_err=fit["err"],
                                 fit_score=fit["score"], false_safe_budget=0.01)
    loose = RB.band_policy_table(ev["err"], ev["score"], edges=(0.20,), fit_err=fit["err"],
                                 fit_score=fit["score"], false_safe_budget=0.10)
    assert loose["by_edge"]["200ms"]["auto_accept_share"] >= \
        tight["by_edge"]["200ms"]["auto_accept_share"]


def test_small_eval_slice_is_unavailable():
    d = _corpus(40)
    out = RB.band_policy_table(d["err"], d["score"], edges=(0.2,))
    assert out["available"] is False
