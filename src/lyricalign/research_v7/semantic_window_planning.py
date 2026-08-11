"""semantic_window_planning —— 含重复元音 run 的语义窗口切分规则 v2。

对应 EXPLORATION_NOTES §12 验证的规则 v2（GPU 实测 hit100 ≈ 人工切分）：
- 重复 run = maximal 相同字符段：len >= RUN_MIN(3) 且字符 ∈ VOWELS，或 len >= ANY_CHAR_RUN_MIN(4) 任意字符；
- run 段按“与窗口索引区间相交”判定（跨窗 run 不丢）；
- 含 run 窗口时长上限 RUN_WIN_CAP=20s，无 run 窗口上限 MAX_DUR=30s；
- run 段后 gap > GAP_RUN_SPLIT=0.5s 即切；新 run 开始时若当前窗口已含 run 则先关窗。

纯函数、纯 CPU（仅标准库）；输出 window dict 结构供 requests / window-plan 消费。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# 规则参数（默认值对应规则 v2 冻结值）
DEFAULT_VOWELS = set("啊啦嗯哟哦噢诶哎呜哈呀哇嘿嚯咯")
RUN_MIN = 3
ANY_CHAR_RUN_MIN = 4
MAX_DUR = 30.0
RUN_WIN_CAP = 20.0
GAP_RUN_SPLIT = 0.5


@dataclass(frozen=True)
class RepeatRun:
    """歌词中一段 maximal 重复 run（含全局起止 index 与其音频时间区间）。"""

    start_index: int          # 全局 unit index（含）
    end_index: int            # 全局 unit index（含）
    text: str
    length: int
    start_sec: float
    end_sec: float

    def to_dict(self) -> dict:
        return {
            "start_index": self.start_index, "end_index": self.end_index,
            "text": self.text, "length": self.length,
            "start_sec": self.start_sec, "end_sec": self.end_sec,
        }


@dataclass(frozen=True)
class PlannedWindow:
    """一条切分后的子窗口（canonical id 范围 + 时间范围）。"""

    canonical_ids: tuple[int, ...]   # 含窗口内全部 canonical unit id
    start_sec: float
    end_sec: float
    duration_sec: float
    has_run: bool                    # 窗口时间区间是否含重复 run 段
    text: str

    def to_dict(self) -> dict:
        """与 requests.py 的 AlignmentRequest 字段对齐：canonical_text_start/end 为不含端点。

        canonical_ids 可直接填入 AlignmentRequest.canonical_ids；
        canonical_text_start/end（不含端点，end = ids[-1]+1）可直接填 canonical_text_start/end。
        """
        return {
            "canonical_ids": list(self.canonical_ids),
            "canonical_text_start": self.canonical_ids[0] if self.canonical_ids else None,
            "canonical_text_end": (self.canonical_ids[-1] + 1) if self.canonical_ids else None,
            "start_sec": round(self.start_sec, 4),
            "end_sec": round(self.end_sec, 4),
            "duration_sec": round(self.duration_sec, 4),
            "has_run": self.has_run,
            "text": self.text,
        }


def _get(unit: Mapping, key: str):
    """统一取 unit 字段（支持 dict 或 dataclass）。"""
    if isinstance(unit, Mapping):
        return unit[key]
    return getattr(unit, key)


def _unit_id(unit: Mapping, index: int) -> int:
    if isinstance(unit, Mapping):
        return unit.get("canonical_unit_id", index)
    return getattr(unit, "canonical_unit_id", index)


def _find_run_index_pairs(
    texts: Sequence[str],
    *,
    run_min: int = RUN_MIN,
    vowels: set[str] = DEFAULT_VOWELS,
    any_char_run_min: int = ANY_CHAR_RUN_MIN,
) -> list[tuple[int, int]]:
    """在文本序列上找 maximal 相同字符段（(start,end) 含端点）。

    段长 >= run_min 且字符 ∈ vowels，或段长 >= any_char_run_min 任意字符。
    """
    runs = []
    i, n = 0, len(texts)
    while i < n:
        j = i
        while j + 1 < n and texts[j + 1] == texts[i]:
            j += 1
        length = j - i + 1
        if length >= run_min and (texts[i] in vowels or length >= any_char_run_min):
            runs.append((i, j))
        i = j + 1
    return runs


def detect_repeat_runs(
    units: Sequence[Mapping],
    *,
    run_min: int = RUN_MIN,
    vowels: set[str] = DEFAULT_VOWELS,
    any_char_run_min: int = ANY_CHAR_RUN_MIN,
) -> list[RepeatRun]:
    """检测 canonical unit 序列中的重复 run，返回含音频时间区间的 run 列表。"""
    texts = [_get(u, "text") for u in units]
    out = []
    for s, e in _find_run_index_pairs(texts, run_min=run_min, vowels=vowels,
                                      any_char_run_min=any_char_run_min):
        out.append(RepeatRun(
            start_index=s, end_index=e, text=texts[s], length=e - s + 1,
            start_sec=_get(units[s], "start_sec"), end_sec=_get(units[e], "end_sec"),
        ))
    return out


def window_contains_run(
    run: RepeatRun,
    window_start_sec: float,
    window_end_sec: float,
) -> bool:
    """run 时间区间 [run.start_sec, run.end_sec] 与窗口时间区间相交。"""
    return run.end_sec >= window_start_sec and run.start_sec <= window_end_sec


def clip_runs_to_window(
    units: Sequence[Mapping],
    runs: Sequence[RepeatRun],
    lo: int,
    hi: int,
) -> list[RepeatRun]:
    """把全局 run 列表裁剪到 [lo, hi) 索引区间（区间相交，跨窗 run 保留相交部分）。"""
    segs = []
    for r in runs:
        ss, ee = max(r.start_index, lo), min(r.end_index, hi - 1)
        if ss <= ee:
            segs.append(RepeatRun(
                start_index=ss, end_index=ee, text=r.text, length=ee - ss + 1,
                start_sec=_get(units[ss], "start_sec"), end_sec=_get(units[ee], "end_sec"),
            ))
    return segs


def plan_window(
    units: Sequence[Mapping],
    lo: int,
    hi: int,
    runs: Sequence[RepeatRun] | None = None,
    *,
    max_dur: float = MAX_DUR,
    run_window_cap: float = RUN_WIN_CAP,
    gap_run_split: float = GAP_RUN_SPLIT,
    run_min: int = RUN_MIN,
    vowels: set[str] = DEFAULT_VOWELS,
    any_char_run_min: int = ANY_CHAR_RUN_MIN,
) -> list[PlannedWindow]:
    """按规则 v2 把 [lo, hi) 的超长窗口切分为子窗口列表。

    lo/hi 是 units 列表的位置索引（含 lo、不含 hi）。runs 缺省时对窗口内文本自动检测。
    贪心：run 段整体成窗（不跨窗）；run 段后 gap>gap_run_split 即关窗；
     run 段整体成窗（不跨窗）；run 起点处无条件关当前窗；其余按 cap（含 run 20s / 无 run 30s）关窗。
    """
    lo = max(0, lo)
    hi = min(len(units), hi)
    if hi <= lo:
        return []
    if runs is None:
        sub = detect_repeat_runs(units[lo:hi], run_min=run_min, vowels=vowels,
                                 any_char_run_min=any_char_run_min)
        runs = [RepeatRun(
            start_index=r.start_index + lo, end_index=r.end_index + lo,
            text=r.text, length=r.length, start_sec=r.start_sec, end_sec=r.end_sec,
        ) for r in sub]
    segs = clip_runs_to_window(units, runs, lo, hi)
    in_run = set()
    for r in segs:
        in_run.update(range(r.start_index, r.end_index + 1))

    windows: list[list[int]] = []
    cur: list[int] = []
    cur_run = False
    i = lo
    while i < hi:
        if i in in_run:
            if cur:
                windows.append(cur)
            r = next(r for r in segs if r.start_index <= i <= r.end_index)
            cur = list(range(r.start_index, r.end_index + 1))
            cur_run = True
            i = r.end_index + 1
            if i < hi and _get(units[i], "start_sec") - _get(units[r.end_index], "end_sec") > gap_run_split:
                windows.append(cur)
                cur = []
                cur_run = False
            continue
        if not cur:
            cur = [i]
            cur_run = False
            i += 1
            continue
        dur = _get(units[i], "end_sec") - _get(units[cur[0]], "start_sec")
        cap = run_window_cap if cur_run else max_dur
        if dur <= cap:
            cur.append(i)
            i += 1
        else:
            windows.append(cur)
            cur = []
            cur_run = False
    if cur:
        windows.append(cur)

    result = []
    for w in windows:
        ids = tuple(_unit_id(units[k], k) for k in w)
        s0 = _get(units[w[0]], "start_sec")
        e0 = _get(units[w[-1]], "end_sec")
        result.append(PlannedWindow(
            canonical_ids=ids, start_sec=s0, end_sec=e0,
            duration_sec=e0 - s0, has_run=any(k in in_run for k in w),
            text="".join(_get(units[k], "text") for k in w),
        ))
    return result


def _window_bounds(window) -> tuple[int, int]:
    """解析单个窗口描述为 (lo, hi) 位置索引（含 lo、不含 hi）。

    接受 (lo, hi) 二元组；或 dict 含 canonical_text_start/canonical_text_end（不含端点，与
    requests.py 一致）、canonical_start/canonical_end（含端点）、canonical_range（含端点）、
    canonical_ids（含端点，取首尾）。
    """
    if isinstance(window, Mapping):
        if "canonical_text_start" in window and "canonical_text_end" in window:
            return window["canonical_text_start"], window["canonical_text_end"]
        if "canonical_start" in window and "canonical_end" in window:
            return window["canonical_start"], window["canonical_end"] + 1
        if "canonical_range" in window:
            s, e = window["canonical_range"]
            return s, e + 1
        if "canonical_ids" in window:
            ids = window["canonical_ids"]
            if not ids:
                return 0, 0
            return ids[0], ids[-1] + 1
        raise ValueError(f"unsupported window dict: {sorted(window)}")
    lo, hi = window
    return lo, hi


def plan_semantic_windows(
    units: Sequence[Mapping],
    windows,
    *,
    max_dur: float = MAX_DUR,
    run_window_cap: float = RUN_WIN_CAP,
    gap_run_split: float = GAP_RUN_SPLIT,
    run_min: int = RUN_MIN,
    vowels: set[str] = DEFAULT_VOWELS,
    any_char_run_min: int = ANY_CHAR_RUN_MIN,
) -> list[PlannedWindow]:
    """顶层入口：对给定一个或多个超长窗口做语义规则切分，返回全部子窗口。

    自动对全序列检测 run 一次后复用（跨窗 run 判定正确）。
    """
    runs = detect_repeat_runs(units, run_min=run_min, vowels=vowels,
                              any_char_run_min=any_char_run_min)
    if isinstance(windows, Mapping) or (not isinstance(windows, Sequence)) or (
        len(windows) and isinstance(windows[0], int)
    ):
        windows = [windows]
    out: list[PlannedWindow] = []
    for w in windows:
        lo, hi = _window_bounds(w)
        out.extend(plan_window(
            units, lo, hi, runs, max_dur=max_dur, run_window_cap=run_window_cap,
            gap_run_split=gap_run_split, run_min=run_min, vowels=vowels,
            any_char_run_min=any_char_run_min,
        ))
    return out
