from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.audio_separation import evaluate_separation


def test_rejects_near_copy_vocal_output() -> None:
    sample_rate = 16000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    mix = 0.4 * np.sin(2 * np.pi * 220 * time)
    diagnostics = evaluate_separation(
        mix,
        mix.copy(),
        mix.copy(),
        sample_rate=sample_rate,
    )
    assert diagnostics.passed is False
    assert "vocals_is_near_copy_of_mix" in diagnostics.failures
    assert "vocals_and_accompaniment_are_near_identical" in diagnostics.failures


def test_accepts_distinct_two_stem_reconstruction() -> None:
    sample_rate = 16000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    vocals = 0.25 * np.sin(2 * np.pi * 440 * time)
    accompaniment = 0.3 * np.sin(2 * np.pi * 220 * time)
    mix = vocals + accompaniment
    diagnostics = evaluate_separation(
        mix,
        vocals,
        accompaniment,
        sample_rate=sample_rate,
    )
    assert diagnostics.passed is True
    assert diagnostics.failures == ()
    assert diagnostics.reconstruction_residual_ratio < 1e-6
