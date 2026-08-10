"""真实 GT 投影加载器（安全版）：用 pinyin overlay 真实 GT 替换 synthetic-uniform。

真实 GT 来源：derived/20260723_m4singer_overlay_slur_time_v1/prepare/m4singer_character_annotations.jsonl
- 每行：{song_id, item_id(=singer#song#segment), character_index(段内索引),
  start_sec(段局部), end_sec(段局部), mapping_status, normalized_character, ...}
- 段局部时间需 + segment_offsets.global_start_sec 才为全局时间（manifest canonical 轴）。
- 只有两个 accepted status 是 GT；review_required_* / 缺时间 / 坏区间 / 缺偏移 /
  source_unit_index 无对应行或文本不匹配，均为 unlabeled。
- 严禁 synthetic-uniform 作为真实 GT fallback（load_uniform_gt 仅用于非 GT 构造诊断）。

用法：
  real_gt, audit = load_real_gt_with_audit(annotations_path, manifest_path)
  real_gt = load_real_gt(annotations_path, manifest_path)   # 向后兼容薄封装

  real_gt[song_id][canonical_unit_id] = {'start_sec', 'end_sec', 'text',
                                          'status', 'source_segment_id', 'source_unit_index'}
  audit[song_id][reason] -> int
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

GT_STATUS_WHITELIST: frozenset[str] = frozenset({
    "accepted_rule_based_pinyin_validated",
    "accepted_rule_validated_held_vowel",
})

EXCLUSION_REASONS: tuple[str, ...] = (
    "review_status",
    "missing_overlay",
    "missing_time",
    "bad_interval",
    "missing_segment_offset",
    "text_or_index_mismatch",
)


def _load_manifest(manifest_path: Path) -> tuple[dict[str, dict[int, dict]], dict[tuple[str, str], float]]:
    """manifest -> (song -> {canonical_unit_id: meta}, (song, seg) -> global_start_sec)。"""
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
    return canonical, seg_offset


def _load_annotations(annotations_path: Path) -> dict[str, dict[str, dict[int, dict]]]:
    """overlay -> {song: {item_id: {character_index: row}}}（保留原始时间，缺失记 None）。"""
    ann: dict[str, dict[str, dict[int, dict]]] = {}
    for line in annotations_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        song = r.get("song_id")
        item = r.get("item_id")
        idx = r.get("character_index")
        if song is None or item is None or idx is None:
            continue
        row = {
            "status": r.get("mapping_status"),
            "start_sec": r.get("start_sec"),
            "end_sec": r.get("end_sec"),
            "normalized_character": r.get("normalized_character"),
            "raw_character": r.get("raw_character"),
        }
        ann.setdefault(song, {}).setdefault(item, {})[int(idx)] = row
    return ann


def load_real_gt_with_audit(
    annotations_path: str | Path,
    manifest_path: str | Path,
) -> tuple[dict[str, dict[int, dict]], dict[str, dict[str, int]]]:
    """把 overlay 真实 GT 投影到 manifest canonical 轴，并返回逐 song 的排除审计。

    返回 (real_gt, audit)：
    - real_gt: {song_id: {canonical_unit_id: {start_sec, end_sec, text, status,
        source_segment_id, source_unit_index}}}，只含 accepted status 且两侧时间均来自 overlay。
    - audit: {song_id: {reason: count}}，reason ∈ EXCLUSION_REASONS。
    """
    annotations_path = Path(annotations_path)
    manifest_path = Path(manifest_path)
    canonical, seg_offset = _load_manifest(manifest_path)
    ann = _load_annotations(annotations_path)

    real_gt: dict[str, dict[int, dict]] = {}
    audit: dict[str, dict[str, int]] = {}
    for song, units in canonical.items():
        real_gt[song] = {}
        audit[song] = {reason: 0 for reason in EXCLUSION_REASONS}
        for cid, meta in units.items():
            seg = meta["source_segment_id"]
            idx = meta["source_unit_index"]
            canonical_text = meta.get("text")
            seg_start = seg_offset.get((song, seg))
            if seg_start is None:
                audit[song]["missing_segment_offset"] += 1
                continue
            rows = ann.get(song, {}).get(seg)
            if not rows:
                audit[song]["missing_overlay"] += 1
                continue
            row = rows.get(idx)
            if row is None:
                audit[song]["text_or_index_mismatch"] += 1
                continue
            status = row.get("status")
            if status not in GT_STATUS_WHITELIST:
                audit[song]["review_status"] += 1
                continue
            start = row.get("start_sec")
            end = row.get("end_sec")
            if start is None or end is None:
                audit[song]["missing_time"] += 1
                continue
            start = float(start)
            end = float(end)
            if end < start or end == start:
                audit[song]["bad_interval"] += 1
                continue
            overlay_char = row.get("normalized_character")
            if overlay_char is None:
                overlay_char = row.get("raw_character")
            if canonical_text is None or overlay_char is None or overlay_char != canonical_text:
                audit[song]["text_or_index_mismatch"] += 1
                continue
            real_gt[song][cid] = {
                "start_sec": start + seg_start,
                "end_sec": end + seg_start,
                "text": canonical_text,
                "status": status,
                "source_segment_id": seg,
                "source_unit_index": idx,
            }
    return real_gt, audit


def load_real_gt(
    annotations_path: str | Path,
    manifest_path: str | Path,
    allow_uniform: bool = False,
) -> dict[str, dict[int, dict]]:
    """向后兼容薄封装：只返回 real_gt dict。

    correctness-labeling 路径禁止 uniform fallback：显式传入 allow_uniform=True 即抛 ValueError。
    """
    if allow_uniform:
        raise ValueError(
            "uniform fallback is forbidden for correctness labeling: "
            "load_real_gt never substitutes synthetic-uniform GT as real GT"
        )
    real_gt, _audit = load_real_gt_with_audit(annotations_path, manifest_path)
    return real_gt


def load_uniform_gt(manifest_path: str | Path) -> dict[str, dict[int, dict]]:
    """LONG_TIMELINE_MANIFEST（synthetic-uniform）仅用于非 GT 构造诊断。

    明确非人工 GT，不得用于 correctness 标注/选模型/oracle。
    """
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_real_gt_outputs(
    annotations_path: str | Path,
    manifest_path: str | Path,
    out_root: str | Path,
) -> dict[str, Path]:
    """Runner 输出：REAL_GT_PROJECTION_AUDIT.json + 逐 song inventory JSONL + SHA-256 manifest。"""
    annotations_path = Path(annotations_path)
    manifest_path = Path(manifest_path)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    real_gt, audit = load_real_gt_with_audit(annotations_path, manifest_path)

    total = 0
    accepted = 0
    summary_unlabeled: dict[str, int] = {r: 0 for r in EXCLUSION_REASONS}
    per_song: dict[str, dict[str, Any]] = {}
    inventory_lines: list[dict[str, Any]] = []
    for song in sorted(audit):
        per_song_total = len(real_gt[song]) + sum(audit[song].values())
        per_song_accepted = len(real_gt[song])
        total += per_song_total
        accepted += per_song_accepted
        for r in EXCLUSION_REASONS:
            summary_unlabeled[r] += audit[song][r]
        accepted_units = [
            {
                "canonical_unit_id": cid,
                "start_sec": m["start_sec"],
                "end_sec": m["end_sec"],
                "text": m["text"],
                "status": m["status"],
            }
            for cid, m in sorted(real_gt[song].items())
        ]
        per_song[song] = {
            "total": per_song_total,
            "accepted": per_song_accepted,
            "unlabeled": per_song_total - per_song_accepted,
            "unlabeled_by_reason": audit[song],
        }
        inventory_lines.append({
            "song_id": song,
            "total": per_song_total,
            "accepted": per_song_accepted,
            "unlabeled": per_song_total - per_song_accepted,
            "unlabeled_by_reason": audit[song],
            "accepted_units": accepted_units,
        })

    audit_doc = {
        "summary": {
            "total_canonical_units": total,
            "accepted_gt_units": accepted,
            "unlabeled_total": total - accepted,
            "unlabeled_by_reason": summary_unlabeled,
        },
        "per_song": per_song,
    }
    audit_path = out_root / "REAL_GT_PROJECTION_AUDIT.json"
    inventory_path = out_root / "REAL_GT_PROJECTION_INVENTORY.jsonl"
    sha_path = out_root / "REAL_GT_PROJECTION_SHA256.json"

    audit_path.write_text(json.dumps(audit_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with inventory_path.open("w", encoding="utf-8") as f:
        for line in inventory_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    sha_manifest = {
        "inputs": {
            str(annotations_path): _sha256_file(annotations_path),
            str(manifest_path): _sha256_file(manifest_path),
        },
        "outputs": {
            str(audit_path): _sha256_file(audit_path),
            str(inventory_path): _sha256_file(inventory_path),
        },
    }
    sha_path.write_text(json.dumps(sha_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"audit": audit_path, "inventory": inventory_path, "sha256": sha_path}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", required=True, help="overlay annotations jsonl")
    parser.add_argument("--timeline-manifest", required=True, help="LONG_TIMELINE_MANIFEST.jsonl")
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args(argv)
    outputs = write_real_gt_outputs(args.annotations, args.timeline_manifest, args.out_root)
    print("REAL_GT_PROJECTION_AUDIT:", outputs["audit"])
    print("REAL_GT_PROJECTION_INVENTORY:", outputs["inventory"])
    print("REAL_GT_PROJECTION_SHA256:", outputs["sha256"])


if __name__ == "__main__":
    main()
