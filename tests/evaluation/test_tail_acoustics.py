"""Tests for the tail-acoustics machinery using synthetic signals (no audio files needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import tail_acoustics as T


def _synthetic_env() -> T.Envelope:
    """A unit that sustains 0.0-1.0 s with full energy and then decays to silence."""
    t = np.arange(0.0, 2.0, T.HOP_SEC)
    rms = np.where(t <= 1.0, 1.0, np.exp(-8.0 * (t - 1.0)))
    return T.Envelope(t=t, rms=rms, zcr=np.zeros_like(t))


def test_decay_anchor_fires_at_the_synthetically_placed_decay():
    env = _synthetic_env()
    a50 = T.decay_anchor(env, 0.2, 1.0, 0.5)
    a15 = T.decay_anchor(env, 0.2, 1.0, 0.15)
    assert np.isfinite(a50) and np.isfinite(a15)
    assert a50 < a15                      # a stricter threshold triggers later
    assert 1.0 <= a50 <= 1.15 and 1.2 <= a15 <= 1.45


def test_decay_anchor_returns_nan_when_no_evidence():
    env = _synthetic_env()
    assert np.isnan(T.decay_anchor(env, 0.2, 1.0, 0.5, search_end_sec=0.9))
    assert np.isnan(T.decay_anchor(env, 1.0, 0.5, 0.5))          # inverted interval
    assert np.isnan(T.decay_anchor(T.Envelope(np.array([]), np.array([]), np.array([])), 0.0, 1.0, 0.5))


def test_ratio_anchor_prefers_vocal_drop():
    t = np.arange(0.0, 2.0, T.HOP_SEC)
    vocal = np.where(t <= 1.0, 1.0, 0.02)
    accomp = np.full_like(t, 0.5)                # accompaniment keeps playing
    ratio = vocal / (accomp + 1e-9)
    a = T.ratio_anchor(t, ratio, 0.2, 1.0, 0.5)
    assert np.isfinite(a) and 1.0 <= a <= 1.1


def test_apply_rules_and_scoring_shapes():
    rows = pd.DataFrame({"item": ["a", "a", "b"],
                         "audio_path": ["x", "x", "x"],
                         "pred_start_sec": [0.2, 1.2, 0.2],
                         "pred_end_sec": [1.0, 1.8, 1.0],
                         "gt_end_sec": [1.05, 1.9, 1.6],
                         "gt_dur_sec": [0.85, 0.7, 1.4],
                         "is_last": [0.0, 1.0, 0.0]})
    envs = {"x": _synthetic_env()}
    out = T.apply_rules(rows, envs, thetas=(0.5, 0.15))
    assert {"model_end_sec", "anchor_theta50", "anchor_theta15", "blend_close100",
            "control_next_onset"} <= set(out.columns)
    sc = T.score_ends(out, "model_end_sec")
    assert sc["n"] == 3 and 0.0 <= sc["hit100"] <= 1.0
    ev = T.evaluate(out, "synthetic")
    assert ev["set"] == "synthetic" and ev["units"] == 3
    assert "anchor_theta50" in ev["delta_pp_hit100_vs_model"]
    assert ev["rules"]["model_end_sec"]["all_units"]["mae_end_sec"] == pytest.approx(
        float(np.mean([0.05, 0.1, 0.6])), abs=1e-3)


def test_long_note_stratum_is_separated():
    rows = pd.DataFrame({"item": ["a", "a"], "audio_path": ["x", "x"],
                         "pred_start_sec": [0.0, 0.0], "pred_end_sec": [0.5, 1.0],
                         "gt_end_sec": [0.5, 1.0], "gt_dur_sec": [0.5, 1.5],
                         "is_last": [0.0, 1.0]})
    ev = T.evaluate(T.apply_rules(rows, {"x": _synthetic_env()}, thetas=(0.5,)), "s")
    assert ev["long_note_units"] == 1
    assert ev["rules"]["model_end_sec"]["long_notes"]["n"] == 1
