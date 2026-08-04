"""C3 canonical text-span adapter（review7-4）。

把 C3 生成的弱人声 WAV（音频窗 [w0,w1]）与 canonical GT 时间轴绑定：
- 若其窗口与某段 canonical 歌词时间 overlap（有 >=1 个 unit 落在窗内），请求才可判为
  `text_window_aligned=True`，并写出忠实文本 range（text_start/end=该窗内的 canonical 全局索引）+ bound units；
- 否则保持 `text_window_aligned=False`（acoustic_probe，禁止进 alignment/train/eval）。

纯函数、可单测；不依赖模型/磁盘。真实 canonical GT 时间由调用方（manifest/GT）提供。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CanonicalUnit:
    global_index: int
    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class BoundSpan:
    aligned: bool
    text_start: int | None
    text_end: int | None        # exclusive
    bound_units: tuple[str, ...]
    reason: str


def _overlap(unit_start: float, unit_end: float, w0: float, w1: float) -> bool:
    return max(unit_start, w0) < min(unit_end, w1)  # 非零重叠


def bind_window(
    canonical_units: Sequence[CanonicalUnit or dict],
    window_start: float,
    window_end: float,
) -> BoundSpan:
    """把 audio 窗与 canonical units 绑定；返回 aligned 与否 + 忠实文本 range。

    canonical_units: 每 unit 需含 global_index/start_sec/end_sec(+可选 text)。
    """
    units: list[CanonicalUnit] = []
    for u in canonical_units:
        if isinstance(u, dict):
            # 兼容 dict：text 用 unit 的 text/char；若无时间字段则无法证明 overlap → 未对齐
            if u.get("start_sec") is None or u.get("end_sec") is None:
                return BoundSpan(False, None, None, (), "canonical unit missing time")
            units.append(CanonicalUnit(
                global_index=int(u.get("global_index", u.get("canonical_unit_id", 0))),
                start_sec=float(u["start_sec"]), end_sec=float(u["end_sec"])))
        else:
            units.append(u)
    in_window = [u for u in units if _overlap(u.start_sec, u.end_sec, window_start, window_end)]
    in_window.sort(key=lambda u: u.global_index)
    if not in_window:
        return BoundSpan(False, None, None, (), "no canonical unit overlaps window")
    g0 = in_window[0].global_index
    g1 = in_window[-1].global_index + 1  # exclusive
    # 补全落在 [g0,g1) 内所有 units（连续性由调用方 canonical 保证）
    full = [u for u in units if g0 <= u.global_index < g1]
    full.sort(key=lambda u: u.global_index)
    return BoundSpan(
        aligned=True,
        text_start=g0,
        text_end=g1,
        bound_units=tuple(getattr(u, "text", None) or u for u in full),
        reason=f"overlap_window[{window_start:.2f},{window_end:.2f})",
    )


def bind_to_manifest_row(row: dict, canonical_units: Sequence[dict]) -> dict:
    """把 adapter 结果写回 REQUESTS/manifest 行：aligned → text_units/range + text_window_aligned=True。"""
    w0 = float(row.get("audio_start_sec", 0.0))
    w1 = float(row.get("audio_end_sec", row.get("duration_sec", 1.0)))
    b = bind_window(canonical_units, w0, w1)
    out = dict(row)
    out["text_window_aligned"] = b.aligned
    if b.aligned:
        out["text_units"] = list(b.bound_units)
        out["text_start_index"] = b.text_start
        out["text_end_index"] = b.text_end
        out["evaluation_role"] = "lyrics_aligned"
        out["text_span_reason"] = b.reason
    else:
        out["evaluation_role"] = "acoustic_probe"
        out["text_span_reason"] = b.reason
    return out
