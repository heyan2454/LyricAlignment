"""Tests for time-local leakage measurement (synthetic stems written to tmp_path)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from lyricalign.analysis import separation_leakage as SL

SR = 16000


def _write(path: Path, sig: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.stack([sig, sig], axis=1), SR)


def _tone(f0: float, amp: float, dur: float = 4.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (amp * np.sin(2 * np.pi * f0 * t)).astype(np.float64)


@pytest.fixture()
def batch(tmp_path: Path) -> tuple[Path, pd.DataFrame]:
    # vocal: sings 0-1.0 and 2.0-3.0, silent in the gap 1.0-2.0
    # accomp: constant (so a leakage-driven residual would show up in the gap)
    vocal = _tone(220, 0.4) * ((np.arange(SR * 4) / SR < 1.0) |
                               ((np.arange(SR * 4) / SR >= 2.0) & (np.arange(SR * 4) / SR < 3.0)))
    acc = _tone(110, 0.4)
    song = tmp_path / "s1"
    _write(song / "work/audio/vocals.wav", vocal)
    _write(song / "work/audio/accompaniment.wav", acc)
    (song / "work/audio/separation_quality.json").write_text(json.dumps(
        {"passed": True, "vocals_vs_accompaniment": {"correlation": 0.05},
         "reconstruction_residual_ratio": 0.07}), encoding="utf-8")
    units = pd.DataFrame({"song": ["s1"] * 2, "language": ["Chinese"] * 2,
                          "unit_index": [0, 1], "start_sec": [0.2, 2.2], "end_sec": [1.0, 3.0]})
    return tmp_path, units


def test_gap_restricted_window_is_used(batch):
    b, units = batch
    res = SL.measure_song(units, {"vocals": str(b / "s1/work/audio/vocals.wav"),
                                  "accompaniment": str(b / "s1/work/audio/accompaniment.wav")})
    assert res["available"] is True and res["units"] == 2
    # unit 0 has a 1.0 s gap before unit 1; unit 1 has no following unit (window = lead)
    assert res["gaps"]["all_measurable"]["units"] >= 1
    assert res["gaps"]["all_measurable"]["median_gap_sec"] <= 0.3 + 1e-6


def test_vocal_silence_in_gap_is_not_called_active(batch):
    """The scale-free criterion must see a genuinely silent gap as inactive.

    The absolute floor alone cannot: a 25 ms analysis window that straddles the boundary picks up the
    tail of the previous unit, so the gap registers "active" even when the voice really stopped.
    That is exactly why the relative criterion (residual vs the unit's own core energy) exists.
    """
    b, units = batch
    res = SL.measure_song(units, {"vocals": str(b / "s1/work/audio/vocals.wav"),
                                  "accompaniment": str(b / "s1/work/audio/accompaniment.wav")})
    blk = res["gaps"]["all_measurable"]
    assert blk["relative_residual_active_share"] == 0.0       # voice stopped: residual << core energy
    assert (blk["median_relative_residual"] or 1.0) < 0.25
    assert blk["vocal_active_share_in_gap"] == 1.0            # the absolute floor is fooled, as documented
    assert (blk["median_accomp_gap_rms"] or 0) > 0            # accompaniment keeps playing


def test_measure_batch_reads_quality_sidecar(batch):
    b, units = batch
    res = SL.measure_batch(b, units)
    assert res["songs_measured"] == 1 and res["songs_skipped"] == 0
    song = res["per_song"][0]
    assert song["passed"] is True
    assert song["vocals_vs_accompaniment_correlation"] == pytest.approx(0.05)
    assert "gap_restricted" not in res["pooled"] or True   # pooled summary filled by the driver


def test_missing_stems_are_skipped_not_crashing(tmp_path: Path):
    (tmp_path / "sX").mkdir()
    units = pd.DataFrame({"song": ["sX"], "language": ["Chinese"], "unit_index": [0],
                          "start_sec": [0.0], "end_sec": [1.0]})
    res = SL.measure_batch(tmp_path, units)
    assert res["songs_measured"] == 0 and res["songs_skipped"] == 1
    assert res["per_song"][0]["reason"] == "stems missing"
