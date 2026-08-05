# -*- coding: utf-8 -*-
"""Phase3-2 detector_v2_serial tests（合成 fixture，纯内存）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

import pytest

from detector_v2_serial import simulate_route


def _win(wi, rows, unsafe_ids, song="song_x"):
    """rows: [(canonical_unit_id, p_bad_official, p_bad_raw)]；unsafe_ids 需与 canonical 匹配。"""
    r = []
    flags = []
    for cid, _po, _pr in rows:
        r.append({"canonical_unit_id": cid})
        flags.append(cid in unsafe_ids)
    return {"wi": wi, "song": song, "rows": r, "unsafe_flags": flags,
            "_rows_raw": rows}


class _FakeScorer:
    """per-window 固定 p_bad；official 与 raw 视图。"""

    def __init__(self):
        self.p_by_wi_official = {}
        self.p_by_wi_raw = {}

    def score(self, win, view):
        rows = win["_rows_raw"]
        if view == "official":
            return [po for _cid, po, _pr in rows]
        return [pr for _cid, _po, pr in rows]


def _series():
    """3 歌 × 4 窗，第 2 窗（wi=1）unsafe（错误提交源），wi=3 含传播单元 cid 11。"""
    series = []
    for song in ("song_a", "song_b", "song_c"):
        windows = [
            _win(0, [(10, 0.01, 0.01), (11, 0.01, 0.01)], set(), song),
            _win(1, [(11, 0.99, 0.99), (12, 0.95, 0.95)], {11, 12}, song),
            _win(2, [(12, 0.85, 0.01), (13, 0.01, 0.01)], set(), song),
            # official 0.50 → accept（committed，携带未提交 unsafe 11 → 传播）；
            # raw 0.50 在 alt [0.30,0.70) → multi_view 循环耗尽 unresolved
            _win(3, [(11, 0.50, 0.50), (14, 0.01, 0.01)], {11}, song),
        ]
        series.append({"song": song, "windows": windows})
    return series


def _run(route, budget=2):
    windows = [w for s in _series() for w in s["windows"]]
    return simulate_route(
        route=route, windows=windows, scorer=_FakeScorer(),
        t_accept=0.80, t_reject=0.90,
        t_accept_alt=0.30, t_reject_alt=0.70,
        budget_requests=budget)


def test_all_commit_commits_everything():
    out = _run("all_commit")
    assert out["total_commits"] == 12
    assert out["error_commit_rate"] == pytest.approx(6 / 12)  # wi=1 + wi=3（含 cid 11）各 3 歌
    assert out["n_unresolved"] == 0
    assert out["extra_requests"] == 0


def test_gt_oracle_rejects_unsafe():
    out = _run("gt_oracle")
    assert out["error_commit_rate"] == 0.0
    assert out["error_commits"] == 0
    assert out["total_commits"] == 6  # wi=0/2 提交，wi=1/3 reject


def test_single_view_rejects_unsafe_window():
    out = _run("single_view")
    assert out["total_commits"] == 6  # wi=0 + wi=3 提交；wi=1 reject、wi=2 unresolved
    assert out["error_commit_rate"] == pytest.approx(3 / 6)  # wi=3 携带未提交 unsafe 11
    assert out["n_unresolved"] == 3  # wi=2 × 3 歌
    assert out["extra_requests"] == 0


def test_multi_view_uses_budget_and_delays_commit():
    out = _run("multi_view")
    assert out["total_commits"] == 9  # wi=0 accept；wi=2 验证后延迟 accept；wi=3 accept
    assert out["error_commit_rate"] == pytest.approx(3 / 9)  # wi=3 携带未提交 unsafe 11
    assert out["n_unresolved"] == 0
    assert out["extra_requests"] == 3  # wi=2 × 3 歌各消耗 1 次预算
    assert set(out["delayed_commits"]) == {2}
    assert 11 in out["propagated_units"]  # committed 窗传播（P1-2 修复后口径）


def test_budget_exhausted_marks_unresolved():
    windows = [
        _win(0, [(10, 0.01, 0.01)], set(), "song_x"),
        _win(1, [(11, 0.99, 0.99)], {11}, "song_x"),
        # official 0.85 → uncertain → raw 0.01 → accept（延迟，1 次预算）
        _win(2, [(12, 0.85, 0.01)], set(), "song_x"),
        # official 0.86 → uncertain → raw 0.50 在 [0.30,0.70) → 循环 2 次耗尽 → unresolved
        _win(3, [(11, 0.86, 0.50)], {11}, "song_x"),
    ]
    out = simulate_route(
        route="multi_view", windows=windows, scorer=_FakeScorer(),
        t_accept=0.80, t_reject=0.90, t_accept_alt=0.30, t_reject_alt=0.70,
        budget_requests=2)
    assert out["n_unresolved"] == 1  # wi=3 预算耗尽
    assert out["delayed_commits"] == [2]
    assert out["extra_requests"] == 3  # wi=2 消耗 1 + wi=3 循环 2


def test_propagation_of_uncommitted_unsafe():
    out = _run("single_view")
    # wi=1 的 unsafe cid 11/12 在 wi=3 再次出现（cid 11）→ 传播
    assert 11 in out["propagated_units"]
    assert out["n_propagated_windows"] >= 1
    # 传播发生在未提交集合仍持有 unsafe 时
    assert out["propagated_windows"][0] > 1


def test_reentry_after_reject():
    out = _run("gt_oracle")
    # wi=1 reject（不提交）→ wi=2 accept（重新入轨）
    assert set(out["re_entries"]) == {2}
    # single_view：wi=2 unresolved、wi=3 accept → re-entry 在 wi=3
    sv = _run("single_view")
    assert set(sv["re_entries"]) == {3}


def test_no_cross_song_false_propagation():
    """uncommitted 集合按歌重置：song_a 的 unsafe 不传播到 song_b。"""
    out = _run("single_view")
    # 3 歌各独立：每歌 wi=1 reject 后 wi=3 传播 cid 11（每歌一次），但无跨歌伪传播
    assert sorted(out["propagated_units"]) == [11]
    assert out["n_propagated_windows"] == 3  # 每歌 wi=3 一次
