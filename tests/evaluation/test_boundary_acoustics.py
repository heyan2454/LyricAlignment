"""CPU tests for the boundary-acoustics measurement (Track 1 step ②a)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "measure_boundary_acoustics", ROOT / "scripts" / "evaluation" / "measure_boundary_acoustics.py")
assert SPEC and SPEC.loader
AC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AC)


def test_novelty_is_flat_for_a_steady_tone():
    rate = 16000
    time = np.arange(int(rate * 1.0)) / rate
    tone = 0.3 * np.sin(2 * np.pi * 220 * time)
    flux, d_rms, hop = AC.novelty_frames(tone.astype(np.float32), rate)
    assert flux.size > 10 and d_rms.size == flux.size
    # A stationary tone still has a small positive spectral-flux floor (~0.07 measured) because the
    # STFT frame does not hold a whole number of periods; the decisive claim is the *contrast*
    # against a real change, which the next test checks.
    assert np.median(flux) < 0.5 and np.median(d_rms) < 1e-6
    assert hop == pytest.approx(AC.HOP_SEC, rel=0.05)


def test_novelty_spikes_where_the_level_changes():
    rate = 16000
    quiet = np.zeros(int(rate * 0.5), dtype=np.float32)
    loud = (0.5 * np.sin(2 * np.pi * 330 * np.arange(int(rate * 0.5)) / rate)).astype(np.float32)
    signal = np.concatenate([quiet, loud])
    flux, d_rms, _ = AC.novelty_frames(signal, rate)
    jump = int(0.5 / AC.HOP_SEC)
    assert d_rms[jump] > 10 * np.median(d_rms)
    assert flux[jump] > 5 * np.median(flux[flux > 0])


def test_prominence_is_high_at_a_peak_and_zero_on_a_flat_interior():
    signal = np.zeros(200, dtype=np.float32)
    signal[100] = 10.0
    assert AC.prominence(signal, 1.0, (1.3, 1.9), context_sec=0.06, scale=1.0) == pytest.approx(10.0)
    flat = np.full(200, 2.0, dtype=np.float32)
    assert AC.prominence(flat, 1.0, (1.3, 1.9), context_sec=0.06, scale=1.0) == pytest.approx(0.0)


def test_prominence_uses_only_the_requested_interior_side():
    """A loud next note must not become the baseline of this note's offset."""
    signal = np.zeros(400, dtype=np.float32)
    signal[100] = 5.0                                   # this note's offset peak
    signal[220:] = 50.0                                 # the *next* note, outside the interior
    value = AC.prominence(signal, 1.0, (0.4, 0.9), context_sec=0.06, scale=1.0)
    assert value == pytest.approx(5.0)


def test_summarise_reports_share_without_evidence():
    out = AC.summarise([2.0, -1.0, 0.0, 4.0])
    assert out["n"] == 4 and out["share_not_above_interior"] == pytest.approx(0.5)
    assert AC.summarise([]) == {}
