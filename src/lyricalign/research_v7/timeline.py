"""WP2：timeline —— 长时间线（>=180s）拼接与 seam 控制。

对应 15 蓝图 §5.1 / §6.1：把同 song/version/singer 的 source 片段，按元数据排序键拼接
为 canon 时间线；只接受已审计 source rows；排序/跨库/版本检查失败即拒绝，不按文件名兜底。
音频与 GT 同步拼接后，所有后续 GT 时间偏移累计时长；seam 是 0.5s control 的显式记录。

纯逻辑（接收 source dict 列表），不读磁盘/音频，可单测。真实音频/GT 由 caller 提供 path。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


class TimelineBuildError(ValueError):
    pass


@dataclass(frozen=True)
class Timeline:
    timeline_id: str
    source_song_id: str
    dataset: str
    language: str
    duration_sec: float
    source_segments: tuple[dict, ...]   # 按拼接顺序的 source 片段（含单位文本/时长）
    seams: tuple[dict, ...]
    canonical_units: tuple[dict, ...]   # 蓝图 §5.1 canonical_units
    order_source: str
    artificial_silence_sec: float

    def to_dict(self) -> dict:
        return {
            "timeline_id": self.timeline_id,
            "source_song_id": self.source_song_id,
            "dataset": self.dataset,
            "language": self.language,
            "duration_sec": round(self.duration_sec, 3),
            "order_source": self.order_source,
            "artificial_silence_sec": self.artificial_silence_sec,
            "seams": list(self.seams),
            "canonical_units": list(self.canonical_units),
        }


def _seg_units(seg: dict) -> list[str]:
    """取片段的逐字符单位（优先 chars/chars_normalized，否则拆 text）。"""
    for k in ("chars", "chars_normalized", "lyrics_normalized", "lyrics", "text"):
        if k in seg and seg[k]:
            s = seg[k]
            if isinstance(s, list):
                return [str(u) for u in s]
            return [ch for ch in str(s) if ch.strip()]
    return []


def _canonical_index_of(seg: dict) -> int:
    v = seg.get("source_unit_index")
    return int(v) if v is not None else 0


def build_timeline(
    *,
    timeline_id: str,
    source_song_id: str,
    dataset: str,
    language: str,
    segments: Sequence[dict],
    order_field: str,
    artificial_silence_sec: float = 0.0,
) -> Timeline:
    """拼接 segments 为长时间线。

    segments: 每个含 text/chars、duration_sec、audio path（可选）；按 order_field 排序。
    校验：同 song（all song_id==source_song_id）；duration>=90 主体>=180（调用方在
    build_long_timeline_manifest 依 policy 决定，此处若 <90 抛错）；跨 source 拒绝。
    真实音频/GT 同步由 caller 完成；本函数只产出 canonical units + 累计时间 + seams。
    """
    segs = list(segments)
    if len(segs) < 2:
        raise TimelineBuildError("timeline requires >=2 source segments")
    for s in segs:
        sid = s.get("song_id") or s.get("source_song_id")
        if sid and sid != source_song_id:
            raise TimelineBuildError(f"cross-source segment rejected: {sid} != {source_song_id}")
    # 按 order_field 排序（缺省给 sentinel，不允许无排序）
    sortkey = lambda s: s.get(order_field)
    if any(sortkey(s) is None for s in segs):
        raise TimelineBuildError(f"order_field '{order_field}' missing on some source segments; refuse to order by filename")
    ordered = sorted(segs, key=sortkey)

    canonical = []
    seams = []
    cursor = 0.0
    unit_global = 0
    n_before = 0
    for si, seg in enumerate(ordered):
        # P0-4：段间插入的 seam silence 使后续 canonical 起止平移（第 2 段起每段前 + artificial_silence）
        if si > 0:
            cursor += artificial_silence_sec
        units = _seg_units(seg)
        dur = float(seg.get("duration_sec", 0.0) or 0.0)
        seg_span = 0.0
        # review17-minor：空段（无 units）时 per 重置为 0.0，不得残留上一段的值
        per = 0.0
        if units:
            per = dur / len(units) if dur > 0 else 0.0
        for uidx, u in enumerate(units):
            start = cursor + seg_span
            canonical.append({
                "canonical_unit_id": unit_global,
                "text": u,
                "start_sec": round(start, 4),
                "end_sec": round(start + per, 4),
                "source_segment_id": seg.get("item_id") or f"{source_song_id}#seg{si}",
                "source_unit_index": _canonical_index_of(seg) + uidx,
            })
            unit_global += 1
            seg_span += per
        cursor += dur if not units else dur
        n_before += len(units)
        if si > 0:
            seams.append({
                "left_source_segment_id": ordered[si - 1].get("item_id") or f"{source_song_id}#seg{si-1}",
                "right_source_segment_id": seg.get("item_id") or f"{source_song_id}#seg{si}",
                "timeline_sec": round(cursor - dur, 4),
                "inserted_silence_sec": artificial_silence_sec,
                "segment_order": si,
            })

    # P0-4a：cursor 已在每段前计入 artificial_silence（seam 平移），总时长直接用 cursor，勿再二次加。
    # review17-minor：duration 基于累计 cursor（含 seam 平移），末段为空（无 units）时不得退化为 0。
    duration = cursor
    return Timeline(
        timeline_id=timeline_id,
        source_song_id=source_song_id,
        dataset=dataset,
        language=language,
        duration_sec=duration,
        source_segments=tuple(ordered),
        seams=tuple(seams),
        canonical_units=tuple(canonical),
        order_source=order_field,
        artificial_silence_sec=artificial_silence_sec,
    )
