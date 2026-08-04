# -*- coding: utf-8 -*-
"""WP2 timeline 单测（15 蓝图 §6.1 最低单测）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.timeline import build_timeline, TimelineBuildError


def _segs(n=8):
    return [
        {"item_id": f"s1#seg{i}", "song_id": "演员", "text": "春风又绿江南岸明月"[: 3 + (i % 3)],
         "duration_sec": 2.0, "order": i}
        for i in range(n)
    ]


def test_build_timeline_concat_and_duration():
    t = build_timeline(timeline_id="t1", source_song_id="演员", dataset="m4", language="zh",
                       segments=_segs(), order_field="order")
    assert t.duration_sec >= 2.0 * len(_segs())
    assert len(t.canonical_units) >= 2 * len(_segs())
    # canonical unit 唯一递增 id
    ids = [c["canonical_unit_id"] for c in t.canonical_units]
    assert ids == sorted(set(ids))
    # seam 数 = 片段数-1
    assert len(t.seams) == len(_segs()) - 1
    # 时间单调递增
    starts = [c["start_sec"] for c in t.canonical_units]
    assert starts == sorted(starts) and (len(set(starts)) == len(starts) or all(starts[i] <= starts[i + 1] for i in range(len(starts) - 1)))


def test_reject_cross_source():
    segs = _segs()
    segs[3] = dict(segs[3], song_id="其他歌")
    with pytest.raises(TimelineBuildError):
        build_timeline(timeline_id="t2", source_song_id="演员", dataset="m4", language="zh",
                       segments=segs, order_field="order")


def test_reject_missing_order_field():
    segs = _segs()
    segs[0].pop("order")
    with pytest.raises(TimelineBuildError):
        build_timeline(timeline_id="t3", source_song_id="演员", dataset="m4", language="zh",
                       segments=segs, order_field="order")


def test_order_uses_metadata_sortkey_not_filename():
    # 打乱输入顺序，结果应仍按 order_field 排序
    segs = _segs()
    rev = list(reversed(segs))
    t = build_timeline(timeline_id="t4", source_song_id="演员", dataset="m4", language="zh",
                       segments=rev, order_field="order")
    first = t.source_segments[0]["order"]
    last = t.source_segments[-1]["order"]
    assert first < last


def test_seam_carries_inserted_silence():
    t = build_timeline(timeline_id="t5", source_song_id="演员", dataset="m4", language="zh",
                       segments=_segs(), order_field="order", artificial_silence_sec=0.5)
    assert all(round(s["inserted_silence_sec"], 3) == 0.5 for s in t.seams)


def test_seam_silence_shifts_subsequent_timestamps():
    # P0-4：0.5s seam 使第2段起 canonical start 相对无 seam 平移 0.5*(段序)
    segs = _segs(3)  # 3 段各 dur 2.0
    t_sil = build_timeline(timeline_id="s", source_song_id="演员", dataset="m4", language="zh",
                           segments=segs, order_field="order", artificial_silence_sec=0.5)
    t_none = build_timeline(timeline_id="n", source_song_id="演员", dataset="m4", language="zh",
                            segments=segs, order_field="order", artificial_silence_sec=0.0)
    # 第3段第一个 canonical 的 start 应比无 seam 版本偏移 0.5*2 (两段 seam)
    # 找到第3段(segment_order==2)首个 canonical
    def first_of_seg(tl, order):
        for c in tl.canonical_units:
            if c["source_segment_id"] == f"s1#seg{order}":
                return c["start_sec"]
        return None
    s2_sil = first_of_seg(t_sil, 2); s2_none = first_of_seg(t_none, 2)
    assert s2_sil is not None and s2_none is not None
    assert abs((s2_sil - s2_none) - 1.0) < 1e-6  # 两段 seam ×0.5 =1.0


def test_seam_duration_not_double_counted():
    # P0-4a：总时长 == 最后一 canonical end == sum(dur) + silence*(n-1)，不双计
    n = 3
    segs = _segs(n)  # 每段 dur=2.0
    t = build_timeline(timeline_id="d", source_song_id="演员", dataset="m4", language="zh",
                       segments=segs, order_field="order", artificial_silence_sec=0.5)
    last_end = max(c["end_sec"] for c in t.canonical_units)
    expect = n * 2.0 + 0.5 * (n - 1)  # sum dur + 2×seam silence
    assert abs(t.duration_sec - expect) < 1e-6
    assert abs(t.duration_sec - last_end) < 1e-6  # 不双计 → 总时长==末 unit end


def test_duration_not_degraded_by_empty_last_segment():
    # review17-minor：末段无 units 时 duration 不得退化为 0，仍为累计 cursor（含 seam）
    segs = _segs(3)
    segs[2] = {"item_id": "s1#seg2", "song_id": "演员", "duration_sec": 2.0, "order": 2}  # 无 text
    t = build_timeline(timeline_id="e1", source_song_id="演员", dataset="m4", language="zh",
                       segments=segs, order_field="order", artificial_silence_sec=0.5)
    expect = 3 * 2.0 + 0.5 * 2  # sum dur + 2×seam silence
    assert t.duration_sec > 0
    assert abs(t.duration_sec - expect) < 1e-6
    # canonical units 时间正常：末 unit end == 前两段累计（seg0 2.0 + seam0.5 + seg1 2.0）
    last_end = max(c["end_sec"] for c in t.canonical_units)
    assert abs(last_end - (2.0 + 0.5 + 2.0)) < 1e-6
    # seam 仍记录（含空段前的 seam，位于累计 cursor 5.0）
    assert len(t.seams) == 2
    assert abs(t.seams[-1]["timeline_sec"] - 5.0) < 1e-6


def test_empty_middle_segment_keeps_cursor_and_resets_per():
    # review17-minor：中间空段不残留上一段 per，后续段 canonical 时间仍按累计 cursor 平移
    segs = _segs(4)
    segs[1] = {"item_id": "s1#seg1", "song_id": "演员", "duration_sec": 2.0, "order": 1}  # 无 text
    t = build_timeline(timeline_id="e2", source_song_id="演员", dataset="m4", language="zh",
                       segments=segs, order_field="order", artificial_silence_sec=0.5)
    # 第3段(seg2)首个 unit start = 2.0 + 0.5 + 2.0 + 0.5 = 5.0（空段时长仍计入平移）
    first_seg2 = [c["start_sec"] for c in t.canonical_units
                  if c["source_segment_id"] == "s1#seg2"][0]
    assert abs(first_seg2 - 5.0) < 1e-6
    # 末段有 units 时 duration 仍为累计 cursor（4*2.0 + 3*0.5）
    assert abs(t.duration_sec - (4 * 2.0 + 0.5 * 3)) < 1e-6
    starts = [c["start_sec"] for c in t.canonical_units]
    assert starts == sorted(starts)
