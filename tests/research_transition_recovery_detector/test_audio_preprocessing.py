from __future__ import annotations

import numpy as np
import pytest

from lyricalign.research_transition_recovery_detector.audio_preprocessing import (
    compress_long_silence_retained,
    map_compressed_to_original,
    map_original_to_compressed,
)

SR = 16000
HOP = 0.1


def make_profile(duration_sec: float, silences: list[tuple[float, float]]) -> dict:
    n = int(round(duration_sec / HOP))
    mask = np.ones(n, dtype=bool)
    for s, e in silences:
        i0, i1 = int(round(s / HOP)), int(round(e / HOP))
        mask[i0:i1] = False
    return {"hop_sec": HOP, "sustained": mask}


def make_audio(duration_sec: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.normal(size=int(round(duration_sec * SR))) * 0.05).astype(np.float32)


def _removed_len(r: dict) -> float:
    return (r["keep_start_sec"] - r["start_sec"]) + (r["end_sec"] - r["keep_end_sec"])


def test_no_silence_unchanged():
    audio = make_audio(20.0)
    profile = make_profile(20.0, [])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR)
    assert len(comp) == len(audio)
    assert mapping["compressed_duration_sec"] == pytest.approx(20.0, abs=1e-9)
    assert mapping["removed_intervals"] == []
    assert len(mapping["kept_segments"]) == 1
    assert mapping["schema_version"] == "silence_compression_retained_v1"
    for key in ("parameters", "original_duration_sec", "compressed_duration_sec"):
        assert key in mapping


def test_short_silence_untouched():
    audio = make_audio(20.0)
    profile = make_profile(20.0, [(10.0, 13.0)])  # 3.0s < 5.0s threshold
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR)
    assert len(comp) == len(audio)
    assert mapping["removed_intervals"] == []


def test_exact_threshold_silence_compressed():
    audio = make_audio(30.0)
    profile = make_profile(30.0, [(10.0, 15.0)])  # exactly 5.0s
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0)
    assert len(mapping["removed_intervals"]) == 1
    r = mapping["removed_intervals"][0]
    assert (r["keep_end_sec"] - r["keep_start_sec"]) == pytest.approx(3.0, abs=1e-9)
    expected = 30.0 - _removed_len(r)
    assert mapping["compressed_duration_sec"] == pytest.approx(expected, abs=1e-6)


def test_long_silence_retained_total_3():
    audio = make_audio(50.0)
    profile = make_profile(50.0, [(20.0, 30.0)])  # 10s
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0)
    r = mapping["removed_intervals"][0]
    assert (r["keep_end_sec"] - r["keep_start_sec"]) == pytest.approx(3.0, abs=1e-9)
    assert r["keep_start_sec"] == pytest.approx(25.0 - 1.5, abs=1e-9)
    assert r["keep_end_sec"] == pytest.approx(25.0 + 1.5, abs=1e-9)
    assert mapping["compressed_duration_sec"] == pytest.approx(50.0 - _removed_len(r), abs=1e-6)


def test_long_silence_retained_total_5():
    audio = make_audio(50.0)
    profile = make_profile(50.0, [(20.0, 30.0)])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=5.0)
    r = mapping["removed_intervals"][0]
    assert (r["keep_end_sec"] - r["keep_start_sec"]) == pytest.approx(5.0, abs=1e-9)
    assert mapping["compressed_duration_sec"] == pytest.approx(50.0 - _removed_len(r), abs=1e-6)


def test_two_adjacent_long_silences():
    audio = make_audio(60.0)
    profile = make_profile(60.0, [(10.0, 15.0), (16.0, 22.0)])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0)
    assert len(mapping["removed_intervals"]) == 2
    total_removed = sum(_removed_len(r) for r in mapping["removed_intervals"])
    assert mapping["compressed_duration_sec"] == pytest.approx(60.0 - total_removed, abs=1e-6)
    assert mapping["compressed_duration_sec"] < 60.0


def test_leading_trailing_silence_boundary_guard():
    audio = make_audio(60.0)
    profile = make_profile(60.0, [(0.0, 8.0), (40.0, 60.0)])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0,
                                                   boundary_guard_sec=0.5)
    assert len(mapping["removed_intervals"]) == 2
    leading = mapping["removed_intervals"][0]
    trailing = mapping["removed_intervals"][1]
    assert leading["start_sec"] == pytest.approx(0.0)
    assert leading["keep_start_sec"] == pytest.approx(0.0)
    assert (leading["keep_end_sec"] - leading["keep_start_sec"]) == pytest.approx(3.0, abs=1e-9)
    assert trailing["end_sec"] == pytest.approx(60.0)
    assert trailing["keep_end_sec"] == pytest.approx(60.0)
    assert (trailing["keep_end_sec"] - trailing["keep_start_sec"]) == pytest.approx(0.5, abs=1e-9)
    assert trailing["keep_start_sec"] == pytest.approx(59.5, abs=1e-9)


def test_roundtrip_within_kept_segments():
    audio = make_audio(60.0)
    profile = make_profile(60.0, [(10.0, 15.0), (25.0, 35.0), (45.0, 55.0)])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0)
    assert len(mapping["kept_segments"]) == 7
    for seg in mapping["kept_segments"]:
        for t_orig in (seg["original_start_sec"], (seg["original_start_sec"] + seg["original_end_sec"]) / 2.0):
            t_comp = map_original_to_compressed(mapping, t_orig)
            back = map_compressed_to_original(mapping, t_comp)
            assert abs(back - t_orig) < 1e-6
        assert map_original_to_compressed(mapping, seg["original_end_sec"]) == pytest.approx(
            seg["compressed_end_sec"], abs=1e-9
        )
    assert map_original_to_compressed(mapping, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert map_original_to_compressed(mapping, 60.0) == pytest.approx(mapping["compressed_duration_sec"], abs=1e-9)


def test_splice_continuity():
    audio = make_audio(60.0)
    profile = make_profile(60.0, [(10.0, 15.0), (25.0, 35.0), (45.0, 55.0)])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0)
    segs = mapping["kept_segments"]
    for prev, cur in zip(segs, segs[1:]):
        assert cur["compressed_start_sec"] - prev["compressed_end_sec"] < 1e-9
    assert segs[-1]["compressed_end_sec"] == pytest.approx(mapping["compressed_duration_sec"], abs=1e-9)


def test_total_duration_equals_original_minus_removed():
    audio = make_audio(60.0)
    profile = make_profile(60.0, [(10.0, 15.0), (25.0, 35.0), (45.0, 55.0)])
    comp, mapping = compress_long_silence_retained(audio, profile, sample_rate=SR,
                                                   retained_total_sec=3.0)
    total_removed = sum(_removed_len(r) for r in mapping["removed_intervals"])
    assert mapping["compressed_duration_sec"] == pytest.approx(60.0 - total_removed, abs=1e-6)
    assert len(comp) == int(round(mapping["compressed_duration_sec"] * SR))
    assert len(comp) < len(audio)
