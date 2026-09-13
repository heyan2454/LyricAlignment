from __future__ import annotations

import importlib.util
import statistics as st
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "window_consensus_probe", ROOT / "scripts" / "evaluation" / "window_consensus_probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def test_window_bounds_cover_the_stream_and_overlap_by_half():
    bounds = PROBE.window_bounds(60.0, 25.0, 12.5)
    assert bounds[0] == (0.0, 25.0)
    assert bounds[-1][1] == 60.0
    assert all(bounds[i + 1][0] - bounds[i][0] == 12.5 or bounds[i + 1][1] == 60.0 for i in range(len(bounds) - 1))
    # mid-stream moments must be seen by at least two windows; edges are a known cost of the design
    for moment in (20.0, 30.0, 40.0, 45.0):
        assert sum(1 for start, end in bounds if start <= moment < end) >= 2, moment
    assert sum(1 for start, end in bounds if start <= 0.5 < end) == 1


def test_assemble_stream_places_parts_at_their_recorded_bin_offsets(monkeypatch, tmp_path: Path):
    import lyricalign.training.qwen_fa_runtime as runtime

    def fake_decode(_path):
        return np.ones(int(0.5 * 16000), dtype=np.float32)

    monkeypatch.setattr(PROBE, "decode_audio", fake_decode)
    timeline = PROBE.assemble_stream(["a.wav", "b.wav"], [0, 68], 20.0, tmp_path)
    assert timeline[0] == 1.0                                  # part 0 starts at bin 0
    silent_until = int(round(68 * 0.08 * 16000))
    assert timeline[silent_until - 1] == 0.0                   # gap stays silent up to the bin offset
    assert timeline[silent_until] == 1.0                       # part 1 lands exactly on its label grid


def test_paired_vs_single_returns_no_stats_below_the_sample_floor():
    accepted = {("s", 0): (1.0, 2.0), ("s", 2): (5.0, 6.0)}
    estimates = {("s", 0): {"start": [1.0, 1.02], "end": [2.0, 2.02]},
                 ("s", 2): {"start": [5.1, 5.2], "end": [6.1, 6.2]}}
    central = {("s", 0): (1.0, 2.0, 0.5), ("s", 2): (5.3, 6.3, 0.5)}
    result = PROBE.paired_vs_single(accepted, estimates, central, min_windows=2)
    assert result == {"n": 2}                    # 样本太少时明确拒绝给统计量


def test_paired_vs_single_uses_median_and_only_multi_covered_units():
    accepted = {}
    estimates = {}
    central = {}
    for index in range(10):
        key = ("s", index)
        accepted[key] = (float(index), float(index) + 1.0)
        if index % 2 == 0:                       # 只有偶数号被两窗覆盖
            estimates[key] = {"start": [float(index) + 0.1, float(index) + 0.1],
                              "end": [float(index) + 1.1, float(index) + 1.1]}
        else:                                    # 奇数号单窗覆盖，必须被排除
            estimates[key] = {"start": [float(index)], "end": [float(index) + 1.0]}
        central[key] = (float(index) + 0.2, float(index) + 1.2, 0.5)
    result = PROBE.paired_vs_single(accepted, estimates, central, min_windows=2)
    assert result["n"] == 5 and result["coverage_median_windows"] == 2   # 只取被两窗覆盖的 0/2/4/6/8
    # 共识误差 0.1，单窗误差 0.2 ⇒ 每个差 -0.1s
    assert result["mean_delta_ms"] == -100.0
    assert result["better"] == 5 and result["worse"] == 0
    assert result["z"] is None                     # 零方差 ⇒ 明确不给 z，而不是编造一个
