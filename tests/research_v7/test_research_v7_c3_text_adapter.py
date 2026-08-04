# -*- coding: utf-8 -*-
"""review7-4/review8 C3 canonical text-span adapter 三层契约单测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from lyricalign.research_v7.c3_text_adapter import (
    CanonicalUnit,
    bind_canonical_to_window,
    request_from_bound,
)


def _canon(n=10, text=None, base=40.0, step=1.0, dur=0.8):
    """原曲坐标 40s 起的 10 个 canonical 字（review8-2：非 0 起点，验证坐标系）。"""
    return [
        CanonicalUnit(global_index=i, text=(text or [f"字{i}" for _ in range(n)])[i],
                      start_sec=base + i * step, end_sec=base + i * step + dur)
        for i in range(n)
    ]


def test_layer1_uses_source_window_not_local():
    # review8-2：必须用【原曲窗】40–44 相交；若误用局部 0–8 会绑到歌曲开头。
    units = _canon()
    b = bind_canonical_to_window(units, source_window=(40.5, 43.5))
    assert b.aligned is True
    assert b.canonical_text_start == 0 and b.canonical_text_end == 4  # 40.5..43.5 overlap 字0..3
    # 局部坐标 [0,8] 与原曲 40s GT 无 overlap → 在更正后的契约里应传 source_window；此处验证误用局部会 probe
    b_local = bind_canonical_to_window(units, source_window=(0.0, 8.0))
    assert b_local.aligned is False


def test_layer2_bound_units_are_strings_and_serializable():
    units = _canon()
    b = bind_canonical_to_window(units, source_window=(41.5, 44.5))
    assert all(isinstance(t, str) for t in b.bound_units)
    # review8-3：输出必须可 JSON 序列化（无 CanonicalUnit 对象泄漏）
    json.dumps(b.to_dict())
    payload = request_from_bound(b, base={"item_id": "x"})
    json.dumps(payload)  # round-trip 成功即通过
    assert payload["text_units"] == b.bound_units


def test_missing_text_rejected():
    with pytest.raises(ValueError, match="missing text"):
        bind_canonical_to_window([{"global_index": 0, "start_sec": 0.0, "end_sec": 1.0}],
                                 source_window=(0.0, 1.0))


def test_layer3_local_vs_canonical_indices_distinct():
    # review8-4：text_start/end 为 request-local 0..len；canonical_text_* 为原曲全局 id
    units = _canon(text=None)
    b = bind_canonical_to_window(units, source_window=(42.0, 46.0))
    assert b.text_start == 0 and b.text_end == len(b.bound_units)
    assert b.canonical_text_start == 2 and b.canonical_text_end == 6
    assert b.canonical_to_local == {2: 0, 3: 1, 4: 2, 5: 3}
    assert b.bound_units == ["字2", "字3", "字4", "字5"]


def test_request_from_bound_full_row():
    units = _canon()
    b = bind_canonical_to_window(units, source_window=(40.0, 43.0))
    base = {"item_id": "s", "sample_rate": 44100, "window_sec": [40.0, 43.0]}
    row = request_from_bound(b, base=base, audio_start_sec=0.0, audio_end_sec=3.0)
    assert row["text_window_aligned"] is True
    assert row["evaluation_role"] == "lyrics_aligned"
    assert row["text_start_index"] == 0 and row["text_end_index"] == 3
    assert row["canonical_text_start"] == 0 and row["canonical_text_end"] == 3
    assert row["canonical_to_local"] == {0: 0, 1: 1, 2: 2}
    # probe 分支
    b2 = bind_canonical_to_window(units, source_window=(100.0, 102.0))
    row2 = request_from_bound(b2, base=base, audio_start_sec=0.0, audio_end_sec=2.0)
    assert row2["text_window_aligned"] is False
    assert row2["evaluation_role"] == "acoustic_probe"
    assert row2["text_units"] == []


def test_reject_duplicate_global_index():
    # review9-4：重复 id 会覆盖 canonical_to_local → 拒绝
    dups = [
        {"global_index": 0, "text": "乙", "start_sec": 0.0, "end_sec": 0.5},
        {"global_index": 0, "text": "女", "start_sec": 0.6, "end_sec": 1.0},
    ]
    with pytest.raises(ValueError, match="strictly increasing"):
        bind_canonical_to_window(dups, source_window=(0.0, 1.0))


def test_reject_non_increasing_global_index():
    bad = [
        {"global_index": 1, "text": "乙", "start_sec": 0.0, "end_sec": 0.5},
        {"global_index": 0, "text": "女", "start_sec": 0.6, "end_sec": 1.0},
    ]
    with pytest.raises(ValueError, match="strictly increasing"):
        bind_canonical_to_window(bad, source_window=(0.0, 1.0))


def test_reject_end_le_start():
    bad = [{"global_index": 0, "text": "乙", "start_sec": 0.5, "end_sec": 0.5}]
    with pytest.raises(ValueError, match="end<=start"):
        bind_canonical_to_window(bad, source_window=(0.0, 1.0))


def test_noncontiguous_ids_use_explicit_list():
    # gap id（0,1,2,5）：canonical_ids 逐字列表准确；range 表达仍 min/max+1（consumer 应优先 canonical_ids）
    units = [
        {"global_index": i, "text": f"字{i}", "start_sec": 40 + i, "end_sec": 40 + i + 0.8}
        for i in (0, 1, 2, 5)
    ]
    b = bind_canonical_to_window(units, source_window=(40.0, 43.5))
    assert b.aligned is True
    assert b.canonical_ids == [0, 1, 2]       # 只含窗内字，按序
    assert b.canonical_to_local == {0: 0, 1: 1, 2: 2}


def test_reject_time_reversed_timeline():
    # review11-2：id 0 在 0s、id 1 在 10s、id 2 在 1s → 时间不随 global id 单调，必须拒绝
    bad = [
        {"global_index": 0, "text": "甲", "start_sec": 0.0, "end_sec": 1.0},
        {"global_index": 1, "text": "乙", "start_sec": 10.0, "end_sec": 11.0},
        {"global_index": 2, "text": "丙", "start_sec": 1.0, "end_sec": 2.0},
    ]
    with pytest.raises(ValueError, match="time not monotonic"):
        bind_canonical_to_window(bad, source_window=(0.0, 2.0))


def test_reject_nested_non_monotonic_time():
    # 时间倒序的另一种形式：id 1 的 end 早于 id 0 的 end（end 不单调）
    bad = [
        {"global_index": 0, "text": "甲", "start_sec": 0.0, "end_sec": 5.0},
        {"global_index": 1, "text": "乙", "start_sec": 1.0, "end_sec": 2.0},
    ]
    with pytest.raises(ValueError, match="time not monotonic"):
        bind_canonical_to_window(bad, source_window=(0.0, 5.0))


def test_bound_units_limited_to_actual_overlap():
    # review11-2：窗口只含 id0/2，id1 时间在窗外（但 id 顺序位于中间）→ 不得编入 bound
    units = [
        {"global_index": 0, "text": "甲", "start_sec": 0.0, "end_sec": 0.5},
        {"global_index": 1, "text": "乙", "start_sec": 10.0, "end_sec": 10.5},
        {"global_index": 2, "text": "丙", "start_sec": 20.0, "end_sec": 20.5},
    ]
    b = bind_canonical_to_window(units, source_window=(0.0, 1.0))
    assert b.aligned is True
    assert b.bound_units == ["甲"]
    assert b.canonical_ids == [0]
    assert b.canonical_text_start == 0 and b.canonical_text_end == 1
    assert b.canonical_to_local == {0: 0}
    # 局部与 canonical 索引完全一致（0..N-1 连续，validate 可接受）
    assert b.text_start == 0 and b.text_end == len(b.bound_units)
