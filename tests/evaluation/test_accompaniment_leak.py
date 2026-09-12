"""Tests for the accompaniment-bleed mechanism analysis (synthetic envelopes, no audio files)."""

from __future__ import annotations

import numpy as np
import pytest

from lyricalign.analysis import accompaniment_leak as AL


def _env():
    t = np.arange(0.0, 4.0, 0.01)
    vocal = np.where(t < 2.0, 0.5, 0.005)           # voice stops at 2.0 s (strict: that frame is off)
    accomp = np.where(t > 1.9, 0.4, 0.05)           # accompaniment continues
    return t, vocal, accomp


def test_unit_features_locate_the_bleed_region():
    t, vocal, accomp = _env()
    f = AL.unit_features(t, vocal, accomp, gt_end=2.0, pred_end=2.4, gt_start=1.0)
    assert f["ends_late"] == 1.0
    assert f["overextension_sec"] == pytest.approx(0.4, abs=1e-6)
    # right after the lyric ends the channel is almost entirely accompaniment
    assert f["accomp_share_in_lead"] > 0.9
    assert f["vocal_rms_at_pred_end"] < f["vocal_rms_at_gt_end"]
    assert f["accomp_rms_at_pred_end"] >= f["accomp_rms_at_gt_end"] - 1e-9


def test_unit_features_for_an_early_prediction():
    t, vocal, accomp = _env()
    f = AL.unit_features(t, vocal, accomp, gt_end=2.0, pred_end=1.6, gt_start=1.0)
    assert f["ends_late"] == 0.0
    assert f["overextension_sec"] == pytest.approx(0.4, abs=1e-6)
    # at 1.6 s the voice is still singing: much less bleed share at the boundary itself
    assert f["vocal_rms_at_pred_end"] > f["accomp_rms_at_pred_end"]


def test_paired_stats_sign_and_rank():
    diffs = np.array([0.5, 0.4, 0.3, -0.1, np.nan, 0.2])
    out = AL._paired_stats(diffs)
    assert out["n"] == 5
    assert out["share_higher_in_pred"] == 0.8
    assert out["median_diff"] > 0
    assert out["rank_biserial"] > 0
    assert 0.0 <= out["sign_test_p_two_sided"] <= 1.0


def test_binom_two_sided_bounds_and_symmetry():
    assert AL._binom_two_sided(0, 0) == 1.0
    p_extreme = AL._binom_two_sided(200, 200)
    assert p_extreme < 1e-6                       # no overflow at n=200 (an earlier version crashed)
    assert AL._binom_two_sided(100, 50) > 0.2      # balanced -> not significant


def test_rms_at_outside_audio_is_nan():
    t, vocal, _ = _env()
    assert np.isnan(AL._rms_at(t, vocal, 99.0))
