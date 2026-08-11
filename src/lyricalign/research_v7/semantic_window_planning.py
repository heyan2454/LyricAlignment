"""semantic_window_planning —— 含重复元音 run 的语义窗口切分规则 v2。

对应 EXPLORATION_NOTES §12 验证的规则 v2（GPU 实测 start_hit_1s（start-only 1s MAE 命中，
即 legacy `hit100`）≈ 人工切分；该指标仅 start 边界，勿与 100ms 双边界命中混淆）：
- 重复 run = maximal 相同字符段：len >= RUN_MIN(3) 且字符 ∈ VOWELS，或 len >= ANY_CHAR_RUN_MIN(4) 任意字符；
- run 段按“与窗口索引区间相交”判定（跨窗 run 不丢）；
- 含 run 窗口时长上限 RUN_WIN_CAP=20s，无 run 窗口上限 MAX_DUR=30s；
- run 段后 gap > GAP_RUN_SPLIT=0.5s 即切；新 run 开始时若当前窗口已含 run 则先关窗。

纯函数、纯 CPU（仅标准库）；输出 window dict 结构供 requests / window-plan 消费。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

# 规则参数（默认值对应规则 v2 冻结值）
DEFAULT_VOWELS = set("啊啦嗯哟哦噢诶哎呜哈呀哇嘿嚯咯")
RUN_MIN = 3
ANY_CHAR_RUN_MIN = 4
MAX_DUR = 30.0
RUN_WIN_CAP = 20.0
GAP_RUN_SPLIT = 0.5


def serialize_window(start: float, end: float, exact_duration: float) -> tuple[float, float]:
    """把窗口边界序列化为 4 位小数，保证不越出 exact_duration（WP2 边界 clamp）。

    语义：先按 exact duration clamp（0 <= start < end <= exact_duration），再
    round 到 4 位小数，round 后再 clamp 一次——防止 round(x, 4) 把合法精确端点
    推出音频时长之外（如 end=181.34975 -> round=181.35 > duration）。

    若 round 让合法极短窗塌缩（start >= end），扩到包含原窗 [start, end] 的最小
    4dp 网格窗（floor(start), ceil(end) 再 clamp），保留一个合法可表示端点；网格
    不可行（exact_duration 小于一个 4dp 步长）时保留 (0, min(end, exact_duration))；
    仍不可能才抛 ValueError（结构化失败原因），绝不产出非法请求。

    参数全为有限数且须满足 0 <= start < end <= exact_duration，否则抛 ValueError。
    """
    for name, v in (("start", start), ("end", end), ("exact_duration", exact_duration)):
        if not math.isfinite(v):
            raise ValueError(f"serialize_window: {name} must be finite, got {v!r}")
    if not (0.0 <= start < end <= exact_duration):
        raise ValueError(
            f"serialize_window: requires 0 <= start < end <= exact_duration, "
            f"got start={start!r}, end={end!r}, exact_duration={exact_duration!r}")
    start4 = min(max(round(start, 4), 0.0), exact_duration)
    end4 = min(max(round(end, 4), start4), exact_duration)
    if start4 < end4:
        return (start4, end4)
    # round 让合法极短窗塌缩：扩到包含原窗的最小 4dp 网格窗
    lo = max(0.0, math.floor(start * 1e4) / 1e4)
    hi = min(math.ceil(end * 1e4) / 1e4, exact_duration)
    if lo < hi:
        return (lo, hi)
    # 网格不可行：保留原始 end 端点（start=0 收拢），仍满足 start < end <= exact
    if 0.0 < end <= exact_duration:
        return (0.0, end)
    raise ValueError(
        f"serialize_window: window ({start!r}, {end!r}) cannot be represented as "
        f"a non-empty boundary within exact_duration={exact_duration!r}")


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

    def to_dict(self, exact_duration: float | None = None) -> dict:
        """与 requests.py 的 AlignmentRequest 字段对齐：canonical_text_start/end 为不含端点。

        canonical_ids 可直接填入 AlignmentRequest.canonical_ids；
        canonical_text_start/end（不含端点，end = ids[-1]+1）可直接填 canonical_text_start/end。

        exact_duration：可选精确音频时长。提供时 start_sec/end_sec 经 serialize_window
        clamp（防 round(,4) 把合法端点推出音频时长之外）；缺省时行为与历史一致
        （round 4dp，不改变 planner 分割策略）。
        """
        if exact_duration is None:
            start_sec = round(self.start_sec, 4)
            end_sec = round(self.end_sec, 4)
            duration_sec = round(self.duration_sec, 4)
        else:
            start_sec, end_sec = serialize_window(self.start_sec, self.end_sec, exact_duration)
            duration_sec = round(end_sec - start_sec, 4)
        return {
            "canonical_ids": list(self.canonical_ids),
            "canonical_text_start": self.canonical_ids[0] if self.canonical_ids else None,
            "canonical_text_end": (self.canonical_ids[-1] + 1) if self.canonical_ids else None,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "duration_sec": duration_sec,
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


def plan_request_windows(
    units: Sequence[Mapping],
    windows,
    *,
    max_dur: float = MAX_DUR,
    run_window_cap: float = RUN_WIN_CAP,
    gap_run_split: float = GAP_RUN_SPLIT,
    run_min: int = RUN_MIN,
    vowels: set[str] = DEFAULT_VOWELS,
    any_char_run_min: int = ANY_CHAR_RUN_MIN,
    exact_duration: float | None = None,
) -> list[dict]:
    """纯函数接线入口：把候选超长窗口切为 requests.py 对齐的子窗口 dict 列表。

    输入：units = canonical units（含 text/start_sec/end_sec/canonical_unit_id，
    与 _canonical_units_for_window 同语义）；windows = 候选窗口（(lo,hi) 位置索引
    或 dict：canonical_text_start/end、canonical_start/end、canonical_range、
    canonical_ids，见 _window_bounds）。输出 dict 可直接填充 AlignmentRequest：
    - canonical_ids / canonical_text_start / canonical_text_end（不含端点）
    - source_window_sec = (首个 unit start_sec, 末个 unit end_sec)（与 unit 时间一致）
    - 辅助字段 start_sec/end_sec/duration_sec/has_run/text

    exact_duration：可选精确音频时长，透传给 PlannedWindow.to_dict 做序列化边界
    clamp（不改变分割策略）；缺省 None 时行为与历史一致。

    纯函数、纯 CPU、无 I/O；不触碰 slot_planning/requests 现有合同。
    """
    wins = plan_semantic_windows(
        units, windows, max_dur=max_dur, run_window_cap=run_window_cap,
        gap_run_split=gap_run_split, run_min=run_min, vowels=vowels,
        any_char_run_min=any_char_run_min,
    )
    return [w.to_dict(exact_duration=exact_duration)
            | {"source_window_sec": (w.start_sec, w.end_sec)} for w in wins]
