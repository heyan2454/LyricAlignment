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
