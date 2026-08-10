"""真实 GT 投影加载器（二次补充：用 pinyin overlay 真实 GT 替换 synthetic-uniform）。

真实 GT 来源：derived/20260723_m4singer_overlay_slur_time_v1/prepare/m4singer_character_annotations.jsonl
- 每行：{song_id, item_id(=singer#song#segment), character_index(段内索引), start_sec(段局部时间), ...}
- 段局部时间需 + segment_offsets.global_start_sec 才为全局时间（manifest canonical 轴）。

用法：
  real_gt = load_real_gt(annotations_path, manifest_path)
  real_gt[song_id][canonical_unit_id] = {'start_sec': float, 'end_sec': float|None}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _parse_item_id(item_id: str) -> str | None:
    """'Alto-1#newboy#0000' -> 'Alto-1#newboy#0000'（item_id 即段 id，原样返回）。"""
    return item_id


def load_real_gt(annotations_path: str | Path, manifest_path: str | Path) -> dict[str, dict[int, dict]]:
    """把 overlay 真实 GT 投影到 manifest canonical 轴。

    返回 {song_id: {canonical_unit_id: {'start_sec', 'end_sec', 'text'}}}。
    - segment 局部时间 + segment_offsets.global_start_sec 转全局。
    - character_index -> source_unit_index 投影到 canonical_unit_id。
    """
    annotations_path = Path(annotations_path)
    manifest_path = Path(manifest_path)

    # 1. manifest：segment_offset + canonical_units -> canonical axis
    seg_offset: dict[tuple[str, str], float] = {}
    canonical: dict[str, dict[int, dict]] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        song = r["song_id"]
        for o in r.get("segment_offsets", []):
            seg_offset[(song, o["source_segment_id"])] = float(o["global_start_sec"])
        canonical[song] = {}
        for u in r.get("canonical_units", []):
            canonical[song][int(u["canonical_unit_id"])] = {
                "source_segment_id": u["source_segment_id"],
                "source_unit_index": int(u["source_unit_index"]),
                "start_sec": float(u["start_sec"]),
                "end_sec": float(u["end_sec"]),
                "text": u.get("text"),
            }

    # 2. overlay annotations：段局部时间 -> {song: {item_id: {idx: start}}}
    ann: dict[str, dict[str, dict[int, float]]] = {}
    for line in annotations_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        song = r.get("song_id")
        item = _parse_item_id(r.get("item_id") or "")
        idx = r.get("character_index")
        s = r.get("start_sec")
        if song is None or item is None or idx is None or s is None:
            continue
        ann.setdefault(song, {}).setdefault(item, {})[int(idx)] = float(s)

    # 3. 投影：canonical_unit_id -> real start
    real_gt: dict[str, dict[int, dict]] = {}
    for song, units in canonical.items():
        real_gt[song] = {}
        for cid, meta in units.items():
            seg = meta["source_segment_id"]
            idx = meta["source_unit_index"]
            seg_start = seg_offset.get((song, seg))
            local = ann.get(song, {}).get(seg, {}).get(idx)
            if seg_start is None or local is None:
                continue
            real_gt[song][cid] = {
                "start_sec": float(local) + seg_start,
                "end_sec": meta["end_sec"],
                "text": meta["text"],
            }
    return real_gt


def load_uniform_gt(manifest_path: str | Path) -> dict[str, dict[int, dict]]:
    """LONG_TIMELINE_MANIFEST（synthetic-uniform）作为对照/fallback。"""
    manifest_path = Path(manifest_path)
    out: dict[str, dict[int, dict]] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[r["song_id"]] = {
            int(u["canonical_unit_id"]): {"start_sec": float(u["start_sec"]),
                                          "end_sec": float(u["end_sec"]),
                                          "text": u.get("text")}
            for u in r.get("canonical_units", [])
        }
    return out
