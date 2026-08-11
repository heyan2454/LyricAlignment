"""WP2：窗口边界序列化 clamp 测试（round(,4) 不得把合法精确端点推出音频时长之外）。

覆盖：serialize_window 校验与 clamp 语义（非整数 duration 181.34975、round 向上越界
120.00006、极短合法窗塌缩、round trip 幂等、非法输入 ValueError）；build_requests
fixed/semantic 尾窗的【最终序列化请求 dict】满足 0 <= start < end <= exact_duration。
"""
from __future__ import annotations

import math

import pytest

from lyricalign.research_v7.semantic_window_planning import (
    plan_request_windows,
    serialize_window,
)

_FILLER = "一路芬芳满山崖世上好花有朵英雄滴那是青春放光华载亲人们请记住当年解放军的队伍走向前方边关风雪永不忘这茫茫天地之间是谁写下壮丽篇章"

EXACT = 181.34975  # round(EXACT, 4) = 181.3498 > EXACT，向上越界


def _filler(n):
    return [_FILLER[i % len(_FILLER)] for i in range(n)]


def build_units(items):
    units = []
    t = 0.0
    for text, dur, gap in items:
        t += gap
        units.append({
            "canonical_unit_id": len(units),
            "text": text,
            "start_sec": round(t, 6),
            "end_sec": round(t + dur, 6),
        })
        t += dur
    return units


def _units_to_duration(duration, step=0.9):
    """构造末 unit 恰好 end == duration 的 units（filler 互异避免误判 run）。"""
    items = []
    acc = 0.0
    fill = _filler(10)
    i = 0
    while acc < duration:
        d = min(step, duration - acc)
        if d <= 1e-9:
            break
        items.append((fill[i % len(fill)], d, 0.0))
        acc += d
        i += 1
    return build_units(items)


class _Timeline:
    def __init__(self, units):
        self.canonical_units = units
        self.duration_sec = units[-1]["end_sec"]


def _tl():
    return {"song_id": "test_song", "segs_audio": ["test.wav"],
            "manifest_sha": "sha:test", "source_split": "validation"}


def _build_requests(use_semantic_windows, duration=EXACT, windows_per_song=3):
    from scripts.research_v7.build_long_timeline_manifest import build_requests
    units = _units_to_duration(duration)
    timeline = _Timeline(units)
    return build_requests(_tl(), timeline, windows_per_song=windows_per_song,
                          row_sha="sha:row", use_semantic_windows=use_semantic_windows)


# ---------- serialize_window 纯函数 ----------

def test_non_integer_duration_181_34975_bounds():
    for s, e in ((0.0, EXACT), (60.0, EXACT), (121.0, EXACT), (121.34975, EXACT)):
        s4, e4 = serialize_window(s, e, EXACT)
        assert 0.0 <= s4 < e4 <= EXACT, (s4, e4)


def test_round_up_overflow_clamped():
    exact = 120.00006
    assert round(exact, 4) > exact  # 前置：round(,4) 确实向上越界
    s, e = serialize_window(100.0, exact, exact)
    assert 0.0 <= s < e <= exact
    assert e == exact


def test_short_tail_window_collapse_preserves_legal_endpoint():
    s, e = serialize_window(181.34970, 181.34972, EXACT)
    assert 0.0 <= s < e <= EXACT
    assert round(s, 4) == round(181.34970, 4)


def test_short_window_collapse_near_zero():
    s, e = serialize_window(0.00006, 0.00007, EXACT)
    assert 0.0 <= s < e <= EXACT


def test_serialize_round_trip_idempotent():
    for start, end in ((0.0, 60.0), (12.3456, 78.9012), (0.0, EXACT), (121.34975, EXACT)):
        s1, e1 = serialize_window(start, end, EXACT)
        assert 0.0 <= s1 < e1 <= EXACT
        s2, e2 = serialize_window(s1, e1, EXACT)
        assert (s2, e2) == (s1, e1)


def test_serialize_rejects_invalid():
    with pytest.raises(ValueError):
        serialize_window(60.0, 60.0, EXACT)            # start == end
    with pytest.raises(ValueError):
        serialize_window(0.0, EXACT + 0.1, EXACT)      # end > exact
    with pytest.raises(ValueError):
        serialize_window(-1.0, 60.0, EXACT)            # start < 0
    with pytest.raises(ValueError):
        serialize_window(0.0, 60.0, math.inf)          # 非有限 exact
    with pytest.raises(ValueError):
        serialize_window(math.nan, 60.0, EXACT)        # 非有限 start


# ---------- 最终序列化请求（而非中间对象）----------

def _assert_request_bounds(reqs, exact):
    assert reqs
    for r in reqs:
        assert 0.0 <= r["audio_start_sec"] < r["audio_end_sec"] <= exact, r["request_id"]
        assert 0.0 <= r["source_window_start_sec"] < r["source_window_end_sec"] <= exact
        assert r["duration_sec"] == round(r["audio_end_sec"] - r["audio_start_sec"], 4)


def test_fixed_tail_window_clamped_in_final_requests():
    reqs = _build_requests(use_semantic_windows=False)
    _assert_request_bounds(reqs, EXACT)
    assert all("window_mode" not in r for r in reqs)  # fixed 冻结口径未加字段


def test_semantic_tail_window_clamped_in_final_requests():
    reqs = _build_requests(use_semantic_windows=True)
    _assert_request_bounds(reqs, EXACT)
    assert all(r["window_mode"] == "semantic" for r in reqs)
    # 存在逼近精确尾端的语义子窗（末 unit end == duration），且 end 不越界
    assert max(r["audio_end_sec"] for r in reqs) <= EXACT


def test_plan_request_windows_exact_duration_clamps_end():
    units = _units_to_duration(EXACT)
    wins = plan_request_windows(units, (0, len(units)), exact_duration=EXACT)
    assert wins
    for w in wins:
        assert 0.0 <= w["start_sec"] < w["end_sec"] <= EXACT
