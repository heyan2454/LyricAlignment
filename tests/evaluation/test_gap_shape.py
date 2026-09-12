"""Tests for the gap-shape / truncation-trigger analysis (synthetic envelopes)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import gap_shape as GS

SR = 1000  # samples/second, so win=25 -> 25 ms and hop=10 -> 10 ms (as in the real envelope)


def _env(seg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hop = 10
    win = 25
    n = 1 + max(0, (seg.size - win) // hop)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(seg[idx] ** 2, axis=1))
    t = (np.arange(n) * hop + win / 2) / float(SR)
    return t, rms


def _signal(profile: str) -> np.ndarray:
    t = np.arange(SR * 4) / SR
    base = np.zeros_like(t)
    core = (t >= 0.2) & (t < 1.0)
    base[core] = 0.4
    if profile == "rising":                     # next unit's onset bleeding into the gap
        base[(t >= 1.0) & (t < 1.4)] = np.linspace(0.02, 0.4, int(0.4 * SR))
        base[core] = 0.4
    elif profile == "falling":                  # this unit's own decaying tail
        base[(t >= 1.0) & (t < 1.4)] = 0.4 * np.exp(-4 * (t[(t >= 1.0) & (t < 1.4)] - 1.0))
    elif profile == "flat":                     # steady residual (truncation signature in the audit)
        base[(t >= 1.0) & (t < 1.4)] = 0.35
    return base


def _panel(profile: str, gt_end: float) -> pd.DataFrame:
    return pd.DataFrame({"item": ["x"], "model": ["r2"], "audio_input": ["vocal"],
                         "mode": ["windowed"], "unit_index": [0],
                         "pred_start_sec": [0.2], "pred_end_sec": [1.0],
                         "gt_start_sec": [0.2], "gt_end_sec": [gt_end],
                         "gt_dur_sec": [gt_end - 0.2]})


def test_shape_features_separate_rising_falling_and_flat():
    """With the boundary guard, each synthetic profile must land in its own shape class."""
    for profile, expected in (("rising", "rising"), ("falling", "falling"), ("flat", "flat")):
        t, env = _env(_signal(profile))
        sh = GS.shape_features(t, env, gap_lo=1.0 + GS.GUARD_SEC, gap_hi=1.4, core_rms=0.4)
        assert GS.classify(sh) == expected, (profile, sh)
        assert np.isfinite(sh["gap_rms"]) and sh["gap_over_core"] > 0


def test_boundary_straddling_window_is_why_the_guard_exists():
    """Without the guard a *constant* residual measures as decaying (the artifact we removed)."""
    t, env = _env(_signal("flat"))
    unguarded = GS.shape_features(t, env, gap_lo=1.0, gap_hi=1.4, core_rms=0.4)
    guarded = GS.shape_features(t, env, gap_lo=1.0 + GS.GUARD_SEC, gap_hi=1.4, core_rms=0.4)
    assert unguarded["rise_ratio"] < guarded["rise_ratio"]
    assert GS.classify(guarded) == "flat"


def test_short_gaps_return_unknown_shape():
    t, env = _env(_signal("flat"))
    sh = GS.shape_features(t, env, gap_lo=1.0, gap_hi=1.02)
    assert GS.classify(sh) == "unknown"


def test_grouped_auc_beats_pooled_mixing_and_returns_per_group():
    rng = np.random.default_rng(7)
    rows = []
    for item in range(6):
        for _ in range(30):
            truncated = bool(rng.random() < (0.2 if item % 2 else 0.8))
            score = rng.normal(0.3 if not truncated else 0.9, 0.25)
            rows.append({"item": f"i{item}", "gap_over_core": score, "truncated": truncated})
    d = pd.DataFrame(rows)
    out = GS.grouped_auc(d, score_col="gap_over_core", group_col="item", min_units=10)
    assert out["groups_evaluated"] == 6
    assert out["pooled_auc"] > 0.9
    assert all(v > 0.85 for v in out["per_group_auc"].values())
    assert out["within_group_median_auc"] > 0.9
    assert out["cluster_bootstrap_median_ci95"][0] > 0.85


def test_grouped_auc_degrades_gracefully():
    d = pd.DataFrame({"item": ["a"] * 5, "gap_over_core": [1, 2, 3, 4, 5],
                      "truncated": [True] * 5})
    out = GS.grouped_auc(d, score_col="gap_over_core", group_col="item")
    assert out["groups_evaluated"] == 0 and out["pooled_auc"] == 1.0 or out["groups_evaluated"] == 0


def test_prevalence_by_shape_counts_all_three():
    rows = [{"rise_ratio": 2.0, "gap_over_core": 0.5, "gap_sec": 0.2},
            {"rise_ratio": 0.2, "gap_over_core": 0.9, "gap_sec": 0.1},
            {"rise_ratio": 1.0, "gap_over_core": 0.7, "gap_sec": 0.15},
            {"rise_ratio": 3.0, "gap_over_core": 0.4, "gap_sec": 0.2}]
    res = GS.prevalence_by_shape(pd.DataFrame(rows))
    assert res["available"] is True and res["units"] == 4
    assert res["by_shape"]["rising"]["units"] == 2
    assert res["by_shape"]["falling"]["units"] == 1
    assert res["by_shape"]["flat"]["units"] == 1
