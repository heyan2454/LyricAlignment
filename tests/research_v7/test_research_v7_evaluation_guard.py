# -*- coding: utf-8 -*-
"""review6-2 evaluation-role 硬隔离单测。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.evaluation_guard import guard_role, partition_by_role, require_trainable


def test_guard_role_lyrics_aligned_allowed():
    assert guard_role("lyrics_aligned").allowed


def test_guard_role_probe_demo_rejected():
    assert not guard_role("acoustic_probe").allowed
    assert not guard_role("demo_challenge").allowed


def test_guard_role_missing_rejected():
    assert not guard_role(None).allowed
    assert not guard_role("").allowed
    assert "probe" in guard_role(None).reject_reason  # 缺失视为 probe，不静默放行


def test_guard_unknown_rejected():
    assert not guard_role("mystery").allowed


def test_partition_by_role():
    recs = [
        {"item_id": "a", "evaluation_role": "lyrics_aligned", "text_window_aligned": True},
        {"item_id": "b", "evaluation_role": "acoustic_probe"},
        {"item_id": "c", "evaluation_role": "demo_challenge"},
        {"item_id": "d", "evaluation_role": "mystery"},
    ]
    allowed, probe, other = partition_by_role(recs)
    assert [r["item_id"] for r in allowed] == ["a"]
    # d(role=mystery 且缺 text_window_aligned→未对齐) 也归 probe；真 other 需 role unknown 且 text 对齐
    assert {r["item_id"] for r in probe} == {"b", "c", "d"}
    assert other == []


def test_require_trainable_excludes_non_lyrics():
    out = require_trainable([
        {"item_id": "ok", "evaluation_role": "lyrics_aligned", "text_window_aligned": True},
        {"item_id": "probe1", "evaluation_role": "acoustic_probe"},
        {"item_id": "demo1", "evaluation_role": "demo_challenge"},
    ])
    assert [r["item_id"] for r in out["trainable"]] == ["ok"]
    assert out["rejected_count"] == 2
    assert set(out["rejected_probe"]) == {"probe1", "demo1"}


def test_partition_rejects_text_not_window_aligned():
    from lyricalign.research_v7.evaluation_guard import partition_by_role
    recs = [
        {"item_id": "a", "evaluation_role": "lyrics_aligned", "text_window_aligned": True, "text_window_aligned": True},
        {"item_id": "b", "evaluation_role": "lyrics_aligned", "text_window_aligned": False},  # review6-1：文本未对齐→拒
        {"item_id": "c", "evaluation_role": "acoustic_probe"},
    ]
    allowed, probe, other = partition_by_role(recs)
    assert [r["item_id"] for r in allowed] == ["a"]
    assert {r["item_id"] for r in probe} == {"b", "c"}  # 未对齐文本也当作 probe 拒
    assert other == []
