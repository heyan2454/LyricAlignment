# -*- coding: utf-8 -*-
"""review7-4 C3 canonical text-span adapter 单测。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.c3_text_adapter import bind_to_manifest_row, bind_window


def _canon(n, start=0.0, step=1.0, dur=0.8):
    return [{"global_index": i, "start_sec": start + i * step, "end_sec": start + i * step + dur} for i in range(n)]


def test_bind_window_aligned_when_overlap():
    units = _canon(10)
    b = bind_window([dict(u, text=f"字{i}") for i, u in enumerate(units)], window_start=2.5, window_end=4.5)
    assert b.aligned is True
    assert b.text_start == 2 and b.text_end == 5  # 落在 [2.5,4.5) 的 canon 2..4 → range [2,5)
    assert len(b.bound_units) == 3


def test_bind_window_probe_when_no_overlap():
    units = _canon(10)
    b = bind_window(units, window_start=50.0, window_end=52.0)
    assert b.aligned is False and b.text_start is None


def test_bind_window_probe_when_missing_time():
    units = [{"global_index": i, "start_sec": None, "end_sec": None} for i in range(3)]
    b = bind_window(units, 0.0, 2.0)
    assert b.aligned is False
    assert "missing time" in b.reason


def test_bind_to_manifest_row_sets_role():
    units = _canon(10)
    row = {"item_id": "x", "audio_start_sec": 0.5, "audio_end_sec": 2.5, "mutation": "weak"}
    out = bind_to_manifest_row(row, [dict(u, text=f"字{i}") for i, u in enumerate(units)])
    assert out["text_window_aligned"] is True
    assert out["evaluation_role"] == "lyrics_aligned"
    assert out["text_units"] and out["text_start_index"] == 0 and out["text_end_index"] == 3
    # 无 overlap → probe
    out2 = bind_to_manifest_row(dict(row, audio_start_sec=50.0, audio_end_sec=52.0), units)
    assert out2["text_window_aligned"] is False
    assert out2["evaluation_role"] == "acoustic_probe"
