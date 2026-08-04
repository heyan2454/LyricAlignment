"""C3 canonical text-span adapter（review7-4 → review8 三层契约重做）。

将 C3 弱人声样本与原曲 canonical GT 时间轴绑定，产出**可序列化、可运行**的 request text schema。
三层契约（对应 review8 阻塞项 1–4）：

- **第 1 层 · source-song timeline span**：用**原曲窗口** `source_window=[w0,w1]`（不是生成 WAV 的局部
  `audio_start/end`）与 canonical time 相交，得到 canonical global range `[canon_start, canon_end)`；
  两坐标系的混用是 review8-2 指出的 bug，必须用原曲坐标。
- **第 2 层 · bound string units**：输出 `bound_units: list[str]`（保留 `text`，拒绝缺 text 的单位），
  可 JSON 序列化（review8-3）。
- **第 3 层 · request-local indices + canonical mapping**：`text_start/end_index` 是 request-local
  `0..len(bound_units)`；另存 `canonical_text_start/end`（原曲 GT 全局 id）与 `canonical_to_local`
  映射，二者不可混用（review8-4）。

纯函数、不依赖磁盘/模型；`request_from_bound()` 把契结果写成 REQUESTS 行。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence


@dataclass
class CanonicalUnit:
    global_index: int
    text: str
    start_sec: float
    end_sec: float


@dataclass
class BoundResult:
    aligned: bool
    bound_units: list                     # list[str]，bound literal text
    text_start: int                       # request-local 0..len
    text_end: int                         # request-local exclusive
    canonical_text_start: int | None      # original-song GT global id
    canonical_text_end: int | None        # exclusive
    canonical_to_local: dict              # {canonical global_id -> request-local idx}
    canonical_ids: list | None = None     # review9-4：bound 字的逐字 canonical global id（id 不连续时用列表表达，避免 range 失真）
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce(canonical: Sequence[CanonicalUnit | dict]) -> list[CanonicalUnit]:
    units: list[CanonicalUnit] = []
    prev: int | None = None
    prev_start: float | None = None
    prev_end: float | None = None
    for u in canonical:
        d = u if isinstance(u, dict) else None
        text = d.get("text") if d else getattr(u, "text", None)
        start = d.get("start_sec") if d else getattr(u, "start_sec", None)
        end = d.get("end_sec") if d else getattr(u, "end_sec", None)
        gidx = d.get("global_index") if d else getattr(u, "global_index", None)
        # 第 2 层：拒绝缺 text 或缺时间坐标的单位（无证据不可 bind）
        if text is None or (not isinstance(text, str)) or not text.strip():
            raise ValueError(f"canonical unit missing text (global_index={gidx})")
        if start is None or end is None:
            raise ValueError(f"canonical unit missing time (global_index={gidx})")
        start, end, gidx = float(start), float(end), int(gidx)
        # review9-4：global id 必须唯一且严格递增（拒绝重复/非递增 → canonical_to_local 不会被覆盖）
        if prev is not None and gidx <= prev:
            raise ValueError(f"canonical global_index not strictly increasing: {prev} then {gidx}")
        # review11-2：时间必须随 global id 单调（拒绝时间倒序的 timeline，
        # 否则 range [g0..g1) 会编入 id 在中间但时间在窗外的单位）
        if prev_start is not None and (start < prev_start or end < prev_end):
            raise ValueError(
                f"canonical time not monotonic with global_index: "
                f"id {gidx} [{start:.3f},{end:.3f}) after id {prev} "
                f"[{prev_start:.3f},{prev_end:.3f})")
        # review9-4：拒绝负时长（end<=start）与负时间坐标
        if end <= start:
            raise ValueError(f"canonical unit time invalid (end<=start): id={gidx} [{start},{end}]")
        prev, prev_start, prev_end = gidx, start, end
        units.append(CanonicalUnit(global_index=gidx, text=str(text), start_sec=start, end_sec=end))
    return units


def _overlap(u: CanonicalUnit, w0: float, w1: float) -> bool:
    return max(u.start_sec, w0) < min(u.end_sec, w1)


def bind_canonical_to_window(
    canonical: Sequence[CanonicalUnit | dict],
    source_window: tuple[float, float],
) -> BoundResult:
    """第 1+2+3 层：用【原曲窗口】与 canonical 相交，产出 bound 文本与 local/canonical 索引。"""
    units = _coerce(canonical)
    w0, w1 = float(source_window[0]), float(source_window[1])
    if w1 <= w0:
        return BoundResult(False, [], 0, 0, None, None, {}, reason="invalid source_window")
    in_win = [u for u in units if _overlap(u, w0, w1)]
    if not in_win:
        return BoundResult(False, [], 0, 0, None, None, {}, reason="no canonical unit overlaps source_window")
    # review11-2：bound/mapping 严格限定为【实际落入窗】的单位，用 explicit ids 表达，
    # 不再用 id-range [g0..g1) 把窗外/缺口单位编入 bound text。
    in_win.sort(key=lambda u: u.global_index)
    g0 = in_win[0].global_index
    g1 = in_win[-1].global_index + 1                          # exclusive (canonical global)
    local_of: dict = {u.global_index: i for i, u in enumerate(in_win)}
    return BoundResult(
        aligned=True,
        bound_units=[u.text for u in in_win],
        text_start=0,
        text_end=len(in_win),
        canonical_text_start=g0,
        canonical_text_end=g1,
        canonical_to_local=local_of,
        canonical_ids=[u.global_index for u in in_win],       # review9-4：逐字 canonical global id
        reason=f"overlap_source_window[{w0:.2f},{w1:.2f})",
    )


def request_from_bound(
    bound: BoundResult,
    *,
    base: dict,
    audio_start_sec: float = 0.0,
    audio_end_sec: float = 0.0,
) -> dict:
    """把契结果写为 REQUESTS 行：注意两套坐标原子并存、不混用。"""
    out = dict(base)
    out["text_window_aligned"] = bool(bound.aligned)
    out["canonical_text_start"] = bound.canonical_text_start
    out["canonical_text_end"] = bound.canonical_text_end
    out["canonical_to_local"] = dict(bound.canonical_to_local)
    out["canonical_ids"] = list(bound.canonical_ids) if bound.canonical_ids else None  # review10-1
    out["audio_start_sec"] = audio_start_sec      # 局部 [0,wav_dur]
    out["audio_end_sec"] = audio_end_sec
    if bound.aligned:
        out["text_units"] = list(bound.bound_units)
        out["text_start_index"] = bound.text_start          # request-local
        out["text_end_index"] = bound.text_end              # request-local exclusive
        out["evaluation_role"] = "lyrics_aligned"
        out["text_span_reason"] = bound.reason
    else:
        out["text_units"] = []
        out["text_start_index"] = 0
        out["text_end_index"] = 0
        out["evaluation_role"] = "acoustic_probe"
        out["text_span_reason"] = bound.reason
    return out
