"""契约测试：semantic_window_planning 规则 v2（EXPLORATION_NOTES §12）。

覆盖：重复 run 检测阈值、run 时间相交判定、含 run 窗 ≤20s / 无 run 窗 ≤30s 切分、
run 边界 GAP_RUN_SPLIT 切分、正常短窗不拆、绒花 w1/w2 简化样例窗数（各 4 子窗）。
"""
from __future__ import annotations

from lyricalign.research_v7.semantic_window_planning import (
    GAP_RUN_SPLIT,
    MAX_DUR,
    RUN_WIN_CAP,
    clip_runs_to_window,
    detect_repeat_runs,
    plan_semantic_windows,
    plan_window,
    window_contains_run,
)
from lyricalign.research_v7.semantic_window_planning import RepeatRun


def build_units(items):
    """items: list[(text, dur, gap_before)] -> canonical units dict（含 start/end）。"""
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


def seg(items):
    """[(text, dur, gap_before)] 便捷构造。"""
    return build_units(items)


_FILLER = "一路芬芳满山崖世上好花有朵英雄滴那是青春放光华载亲人们请记住当年解放军的队伍走向前方边关风雪永不忘这茫茫天地之间是谁写下壮丽篇章"


def _filler(n):
    """n 个互不相同的填充字符（避免被 len>=4 任意字符规则误判为 run）。"""
    return [_FILLER[i % len(_FILLER)] for i in range(n)]


# ---------- 重复 run 检测 ----------

def test_detect_run_vowel_ge3():
    units = build_units([
        ("啊", 0.5, 0.0), ("啊", 0.5, 0.0), ("啊", 0.5, 0.0),
        ("一", 0.5, 0.0), ("路", 0.5, 0.0),
    ])
    runs = detect_repeat_runs(units)
    assert len(runs) == 1
    assert (runs[0].start_index, runs[0].end_index, runs[0].length) == (0, 2, 3)
    assert runs[0].text == "啊"


def test_detect_run_vowel_lt3_not_detected():
    units = build_units([("啊", 0.5, 0.0), ("啊", 0.5, 0.0), ("一", 0.5, 0.0)])
    assert detect_repeat_runs(units) == []


def test_detect_run_any_char_ge4():
    units = build_units([("的", 0.5, 0.0)] * 4)
    runs = detect_repeat_runs(units)
    assert [(r.start_index, r.end_index) for r in runs] == [(0, 3)]


def test_detect_run_any_char_lt4_not_detected():
    units = build_units([("的", 0.5, 0.0)] * 3)
    assert detect_repeat_runs(units) == []


# ---------- run 时间相交判定 ----------

def test_window_contains_run_overlap_true():
    run = RepeatRun(0, 2, "啊", 3, 10.0, 20.0)
    assert window_contains_run(run, 15.0, 25.0) is True
    assert window_contains_run(run, 20.0, 25.0) is True   # 端点相接算相交
    assert window_contains_run(run, 5.0, 10.0) is True


def test_window_contains_run_overlap_false():
    run = RepeatRun(0, 2, "啊", 3, 10.0, 20.0)
    assert window_contains_run(run, 0.0, 5.0) is False
    assert window_contains_run(run, 25.0, 30.0) is False


def test_clip_runs_cross_window():
    units = build_units([("啊", 0.5, 0.0)] * 10)
    runs = detect_repeat_runs(units)          # 全局 run [0,9]
    segs = clip_runs_to_window(units, runs, 3, 8)   # 裁剪到 [3,8)
    assert [(r.start_index, r.end_index) for r in segs] == [(3, 7)]
    assert segs[0].start_sec == units[3]["start_sec"]
    assert segs[0].end_sec == units[7]["end_sec"]


# ---------- 切分规则 ----------

def test_short_window_not_split():
    units = build_units([("路", 1.0, 0.0), ("芳", 1.0, 0.0), ("花", 1.0, 0.0),
                         ("山", 1.0, 0.0), ("崖", 1.0, 0.0)])
    wins = plan_window(units, 0, 5)
    assert len(wins) == 1
    assert wins[0].duration_sec == 5.0
    assert wins[0].has_run is False


def test_run_window_split_to_cap_20():
    items = [("啊", 0.5, 0.0)] * 8 + [(t, 0.7, 0.0) for t in _filler(25)]
    units = build_units(items)
    wins = plan_window(units, 0, len(units))
    assert len(wins) == 2
    for w in wins:
        assert w.duration_sec <= RUN_WIN_CAP + 1e-6
    assert sum(1 for w in wins if w.has_run) == 1      # run 段只属于一个窗


def test_non_run_window_split_to_cap_30():
    units = build_units([(t, 0.7, 0.0) for t in _filler(50)])       # 总 35s > 30s
    wins = plan_window(units, 0, 50)
    assert len(wins) >= 2
    for w in wins:
        assert w.duration_sec <= MAX_DUR + 1e-6
        assert w.has_run is False


def test_run_boundary_split_by_gap():
    units = build_units([("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 2.0) for t in _filler(5)])
    wins = plan_window(units, 0, 13)
    assert len(wins) == 2
    assert wins[0].has_run is True
    assert wins[0].canonical_ids == (0, 1, 2, 3, 4, 5, 6, 7)   # run 单独成窗
    assert wins[1].has_run is False
    assert wins[1].canonical_ids[0] == 8


def test_run_boundary_no_split_when_gap_small():
    units = build_units([("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 0.2) for t in _filler(5)])
    wins = plan_window(units, 0, 13)
    assert len(wins) == 1
    assert wins[0].has_run is True


def test_split_at_next_run_start():
    # run A + 尾词 + run B：窗口须在 run B 起点处切开（每窗 ≤1 个 run）
    units = build_units([("啊", 0.5, 0.0)] * 6 + [(t, 0.6, 0.2) for t in _filler(4)]
                        + [("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 0.2) for t in _filler(3)])
    wins = plan_window(units, 0, 21)
    assert len(wins) == 2
    assert wins[0].has_run is True
    assert wins[1].has_run is True
    assert wins[1].canonical_ids[0] == 10            # run B 起点
    # 不变式：每个 run 段整体落在单个窗口内
    for r in detect_repeat_runs(units):
        owners = [i for i, w in enumerate(wins)
                  if r.start_index >= w.canonical_ids[0] and r.end_index <= w.canonical_ids[-1]]
        assert len(owners) == 1


# ---------- 绒花 w1/w2 简化样例（§12 规则窗数 = 4） ----------

def _ronghua_w1():
    # 4 个 啊-run 段（每段后 gap<0.5 不拆），窗口在下一 run 起点切开 -> 恰好 4 子窗
    items = []
    for i in range(4):
        items += [("啊", 0.5, 0.0)] * 8
        items += [(t, 0.6, 0.2) for t in _filler(8)]
    return build_units(items)


def test_ronghua_w1_rule_window_count():
    units = _ronghua_w1()
    runs = detect_repeat_runs(units)
    assert len(runs) == 4
    wins = plan_window(units, 0, len(units))
    assert len(wins) == 4                        # §12 规则窗数一致
    for w in wins:
        assert w.duration_sec <= RUN_WIN_CAP + 1e-6
        assert w.has_run is True


def test_ronghua_w2_rule_window_count():
    # 3 个 run 段，第 3 个 run 后 gap=2.0>GAP_RUN_SPLIT -> run 单独成窗 -> 恰好 4 子窗
    items = [("啊", 0.5, 0.0)] * 7 + [(t, 0.6, 0.2) for t in _filler(7)]
    items += [("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 0.2) for t in _filler(4)]
    items += [("啊", 0.5, 0.0)] * 8
    items += [(t, 0.6, 2.0 if j == 0 else 0.0) for j, t in enumerate(_filler(20))]
    units = build_units(items)
    runs = detect_repeat_runs(units)
    assert len(runs) == 3
    wins = plan_window(units, 0, len(units))
    assert len(wins) == 4                        # §12 规则窗数一致
    run_windows = [w for w in wins if w.has_run]
    assert len(run_windows) == 3                 # 3 个窗各含 1 个 run，尾词窗无 run
    assert wins[-1].has_run is False
    for w in wins:
        assert w.duration_sec <= RUN_WIN_CAP + 1e-6 or not w.has_run


def test_top_level_plan_semantic_windows_dicts():
    units = build_units([("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 0.2) for t in _filler(10)]
                        + [("啊", 0.5, 0.0)] * 8 + [(t, 0.6, 2.0) for t in _filler(6)])
    wins = plan_semantic_windows(units, {"canonical_start": 0, "canonical_end": 31})
    assert len(wins) == 3
    wins2 = plan_semantic_windows(units, [(0, 32)])
    assert len(wins2) == len(wins)
    for w in wins:
        assert w.duration_sec <= RUN_WIN_CAP + 1e-6
