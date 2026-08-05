#!/usr/bin/env python3
"""Dev-G：真实 run → Detector V2 三态标签（raw/official 双目标）CLI。

输入：
  --run-root            evidence/ + manifests/ANOMALY_MANIFEST.jsonl（+ MULTIVIEW_MANIFEST.jsonl，
                        best-effort）preflight/GT_LABEL_AUDIT.json + SOURCE_SONG_SPLIT.json
  --timeline-manifest   LONG_TIMELINE_MANIFEST.jsonl（canonical 文本序；synthetic-uniform 时间轴
                        不作 GT，21 §1）
  --gt-labels           m4singer_qwen_fa_labels.jsonl（真实逐字 GT：timestamp_class_ids ×
                        timestamp_segment_sec，按 song 分组 + mapping_status 过滤 + 时间有效性检查）

流程：
  timeline 的 canonical 文本与同歌 GT 字符序列有序匹配 → 每个 canonical_unit_id 获得真实
  gt_start/gt_end；匹配不上的 unit 标 gt_unavailable（不进 label 训练）。每份 attempt.ok 的
  evidence → converter（EvidenceRow v2）→ 平铺 same-source 几何行 → labels.label_request_units
  按 raw/official 双目标独立生成 LabeledUnit（M2：同源键，不跨 target 回退）。

防泄漏：只写 LABELS.jsonl / LABEL_SUMMARY.json，绝不写 evidence_v2。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.research_v7.detector_v2_evidence_converter import convert_evidence  # noqa: E402
from lyricalign.research_v7.detector_v2_labels import LabeledUnit, label_request_units, summarize_labels  # noqa: E402

GTLABEL_VALID_STATUSES = {
    "accepted_rule_based_pinyin_validated",
    "accepted_rule_validated_held_vowel",
}
TARGETS = ("raw", "official")


def align_units_to_gt(canonical_chars, gt_chars):
    """有序字符对齐：返回 canonical 每单位对应的 gt 字符下标（None=无 GT，即 gt_unavailable）。

    gt 中多出的字符（GT 有而 canonical 无）直接跳过；canonical 中无 GT 对应的字符 → None。
    """
    out = [None] * len(canonical_chars)
    gi = 0
    for ci, ch in enumerate(canonical_chars):
        if not ch:
            continue
        while gi < len(gt_chars) and gt_chars[gi] != ch:
            gi += 1
        if gi < len(gt_chars):
            out[ci] = gi
            gi += 1
    return out


def build_song_gt(rows, valid_statuses=GTLABEL_VALID_STATUSES) -> dict:
    """按 song 拼接真实逐字 GT；非法行进 excluded（不进训练标签）。"""
    chars, starts, ends = [], [], []
    excluded = []
    for r in rows:
        status = r.get("mapping_status")
        if status not in valid_statuses:
            excluded.append({"item_id": r.get("item_id"), "reason": f"status:{status}"})
            continue
        ids = list(r.get("timestamp_class_ids") or [])
        lyrics = str(r.get("lyrics_normalized") or "")
        if len(ids) != 2 * len(lyrics):
            excluded.append({"item_id": r.get("item_id"), "reason": "class_ids_len_mismatch"})
            continue
        seg = float(r.get("timestamp_segment_sec") or 0.08)
        for i, ch in enumerate(lyrics):
            s = float(ids[2 * i]) * seg
            e = float(ids[2 * i + 1]) * seg
            if not (e > s >= 0):
                excluded.append({"item_id": r.get("item_id"), "reason": "invalid_time",
                                 "start_sec": s, "end_sec": e})
                break
            chars.append(ch)
            starts.append(s)
            ends.append(e)
    return {"chars": chars, "starts": starts, "ends": ends, "excluded": excluded}


def gt_map_for_request(timeline_row, song_gt, request_canonical_ids):
    """canonical unit → 真实 (gt_start, gt_end)；无匹配的 unit → gt_unavailable。"""
    canon_units = list(timeline_row.get("canonical_units") or [])
    chars = [str(u.get("text") or "") for u in canon_units]
    binds = align_units_to_gt(chars, song_gt["chars"])
    request_ids = set(int(c) for c in (request_canonical_ids or []))
    canon_gt: dict[int, tuple[float, float]] = {}
    unavailable: set[int] = set()
    for u, gi in zip(canon_units, binds):
        cid = int(u["canonical_unit_id"])
        if cid not in request_ids:
            continue
        if gi is None:
            unavailable.add(cid)
        else:
            canon_gt[cid] = (song_gt["starts"][gi], song_gt["ends"][gi])
    return canon_gt, unavailable


def ambiguous_ids(request_row) -> set[int]:
    """gt_ambiguity：False/缺省 → 空；list → 列出的 canonical ids；True → 整请求。"""
    ga = request_row.get("gt_ambiguity")
    if ga in (None, False, "False", "false"):
        return set()
    if isinstance(ga, (list, tuple)):
        return set(int(x) for x in ga)
    return set(int(c) for c in (request_row.get("canonical_ids") or []))


def flat_labeling_rows(evidence_rows) -> list[dict]:
    """EvidenceRow → label_request_units 消费的 same-source 平铺行（M2，绝不跨 target 回退）。"""
    out = []
    for er in evidence_rows:
        out.append({
            "canonical_unit_id": er.canonical_unit_id,
            "raw_global_start_sec": er.raw.start_sec,
            "raw_global_end_sec": er.raw.end_sec,
            "official_fixed_global_start_sec": er.official.start_sec,
            "official_fixed_global_end_sec": er.official.end_sec,
        })
    return out


def label_one_request(request_row, evidence_json, timeline_row, song_gt,
                      multiview_rows, *, split_override=None) -> tuple[list[dict], list[LabeledUnit], int]:
    """单请求打标；返回 (输出行, LabeledUnit 列表, gt_unavailable 数)。"""
    rid = (evidence_json.get("content_identity")
           or request_row.get("request_id") or (evidence_json.get("attempt") or {}).get("request", {}).get("request_id"))
    view_id = request_row.get("view_id")
    family = request_row.get("family")
    split = split_override or request_row.get("split")
    song_id = (timeline_row or {}).get("song_id")
    request_ids = set(int(c) for c in (request_row.get("canonical_ids") or []))
    amb = ambiguous_ids(request_row)

    def row_for(cid, target, label, audit, gt_unavailable):
        return {
            "request_identity": rid, "view_id": view_id, "canonical_unit_id": int(cid),
            "target": target, "label": label, "audit": audit,
            "gt_unavailable": bool(gt_unavailable),
            "family": family, "split": split, "song_id": song_id,
        }

    out: list[dict] = []
    if not timeline_row or not song_gt or not song_gt["chars"]:
        for cid in sorted(request_ids):
            for t in TARGETS:
                out.append(row_for(cid, t, "gt_unavailable",
                                   {"reason": "song_gt_unavailable"}, True))
        return out, [], len(request_ids) * len(TARGETS)

    canon_gt, unavailable = gt_map_for_request(timeline_row, song_gt, request_ids)
    rows = convert_evidence(evidence_json, request_row, multiview_groups=multiview_rows)
    flat = flat_labeling_rows(rows)
    labeled: list[LabeledUnit] = []
    for t in TARGETS:
        for lu in label_request_units(
                request_identity=rid, target=t, rows=flat,
                canonical_gt=canon_gt, occurrence_ambiguous_ids=amb):
            out.append(row_for(lu.canonical_unit_id, t, lu.label, lu.audit, False))
            labeled.append(lu)
    for cid in sorted(unavailable):
        for t in TARGETS:
            out.append(row_for(cid, t, "gt_unavailable", {"reason": "gt_unavailable"}, True))
    return out, labeled, len(unavailable) * len(TARGETS)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def read_json_optional(*candidates) -> dict | None:
    for p in candidates:
        if Path(p).exists():
            return json.loads(Path(p).read_text())
    return None


def resolve_timeline_row(request_row, timeline_by_song, timeline_by_path):
    item = str(request_row.get("item_id") or "")
    song = item.split(":", 1)[0]
    if song in timeline_by_song:
        return timeline_by_song[song]
    audio = Path(str(request_row.get("audio_path") or "")).name
    if audio in timeline_by_path:
        return timeline_by_path[audio]
    return None


def extract_song_split(split_payload) -> dict | None:
    if not isinstance(split_payload, dict):
        return None
    songs = split_payload.get("songs")
    if isinstance(songs, dict) and all(isinstance(v, str) for v in songs.values()):
        return {str(k): v for k, v in songs.items()}
    return None


def build_summary(out_rows, labeled_units, stats, gt_audit, split_used) -> dict:
    n_gu = sum(1 for r in out_rows if r["label"] == "gt_unavailable")
    strata: dict[tuple, Counter] = defaultdict(Counter)
    family_ct: dict[str, Counter] = defaultdict(Counter)
    for r in out_rows:
        strata[(str(r.get("family")), str(r.get("split")), r["target"])][r["label"]] += 1
        family_ct[str(r.get("family"))][r["label"]] += 1
    by_family_split_target = {
        f"{fam}|{sp}|{t}": {"n_units": sum(c.values()), **dict(c)}
        for (fam, sp, t), c in sorted(strata.items())
    }
    by_family = {
        fam: {"n_units": sum(c.values()), **dict(c)}
        for fam, c in sorted(family_ct.items())
    }
    return {
        "schema_version": "research_v7_detector_v2_labels_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pooled": {**summarize_labels(labeled_units), "n_gt_unavailable": n_gu},
        "by_family_split_target": by_family_split_target,
        "by_family": by_family,
        "n_requests_labeled": stats["requests_labeled"],
        "skipped": {k: v for k, v in stats.items() if k.startswith("evidence_") or k.startswith("requests_song_")},
        "gt_label_audit": gt_audit,
        "source_song_split_used": bool(split_used),
    }


def label_run(run_root, timeline_manifest, gt_labels, out_root,
              valid_statuses: set[str] | None = None) -> dict:
    run_root = Path(run_root)
    out_root = Path(out_root)
    evidence_dir = run_root / "evidence"
    if not evidence_dir.is_dir():
        raise FileNotFoundError(f"{evidence_dir} 不存在")

    manifest_rows = load_jsonl(run_root / "manifests" / "ANOMALY_MANIFEST.jsonl")
    multiview_rows = load_jsonl(run_root / "manifests" / "MULTIVIEW_MANIFEST.jsonl")
    timeline_rows = load_jsonl(Path(timeline_manifest))
    timeline_by_song = {str(r.get("song_id")): r for r in timeline_rows if r.get("song_id")}
    timeline_by_path = {Path(str(r.get("concat_audio_path") or "")).name: r
                        for r in timeline_rows if r.get("concat_audio_path")}

    gt_by_song: dict[str, list] = defaultdict(list)
    for line in Path(gt_labels).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("song_id"):
            gt_by_song[str(r["song_id"])].append(r)
    song_gt = {song: build_song_gt(rows, valid_statuses or GTLABEL_VALID_STATUSES)
               for song, rows in gt_by_song.items()}

    gt_audit = read_json_optional(run_root / "preflight" / "GT_LABEL_AUDIT.json",
                                  run_root / "manifests" / "GT_LABEL_AUDIT.json")
    split_payload = read_json_optional(run_root / "preflight" / "SOURCE_SONG_SPLIT.json",
                                       run_root / "manifests" / "SOURCE_SONG_SPLIT.json")
    split_map = extract_song_split(split_payload)

    request_by_id = {str(r.get("request_id")): r for r in manifest_rows if r.get("request_id")}
    stats: Counter = Counter()
    out_rows: list[dict] = []
    labeled_units: list[LabeledUnit] = []
    for f in sorted(evidence_dir.glob("*.json")):
        ev = json.loads(f.read_text())
        attempt = ev.get("attempt") or {}
        rid = ((attempt.get("request") or {}).get("request_id")
               or ev.get("content_identity") or ev.get("request_identity"))
        if not rid:
            stats["evidence_no_identity"] += 1
            continue
        if attempt.get("ok") is False:
            stats["evidence_not_ok"] += 1
            continue
        req = request_by_id.get(rid)
        if req is None:
            stats["evidence_unmatched_request"] += 1
            continue
        tl_row = resolve_timeline_row(req, timeline_by_song, timeline_by_path)
        sg = song_gt.get(tl_row["song_id"]) if tl_row else None
        song_split = (split_map or {}).get(str(tl_row.get("song_id"))) if tl_row else None
        try:
            rows, labeled, n_gu = label_one_request(
                req, ev, tl_row, sg, multiview_rows, split_override=song_split)
            out_rows.extend(rows)
            labeled_units.extend(labeled)
            stats["requests_labeled"] += 1
            stats["n_gt_unavailable_rows"] += n_gu
        except Exception as e:  # noqa: BLE001 —— 单请求失败不中断整个 run
            stats["evidence_conversion_error"] += 1
            if "conversion_error_example" not in stats:
                stats["conversion_error_example"] = f"{f.name}: {e}"

    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "LABELS.jsonl", "w") as fh:
        for r in out_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = build_summary(out_rows, labeled_units, stats, gt_audit, split_map)
    (out_root / "LABEL_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--gt-labels", required=True)
    p.add_argument("--out-root", default=None, help="缺省 = --run-root（只写 LABELS.jsonl/LABEL_SUMMARY.json）")
    p.add_argument("--gt-valid-statuses", default=None, help="逗号分隔的 GT mapping_status 白名单（缺省 M4 集合）")
    args = p.parse_args(argv)
    out_root = Path(args.out_root or args.run_root)
    if args.gt_valid_statuses:
        valid_statuses = {s.strip() for s in args.gt_valid_statuses.split(",") if s.strip()}
    else:
        valid_statuses = None
    summary = label_run(args.run_root, args.timeline_manifest, args.gt_labels, out_root,
                        valid_statuses=valid_statuses)
    pooled = summary["pooled"]
    print(json.dumps({
        "ok": True,
        "out": str(out_root),
        "n_requests_labeled": summary["n_requests_labeled"],
        "n_units": pooled["n_units"], "n_safe": pooled["n_safe"],
        "n_unsafe": pooled["n_unsafe"], "n_grey": pooled["n_grey"],
        "n_ambiguous": pooled["n_ambiguous"], "n_gt_unavailable": pooled["n_gt_unavailable"],
        "by_family": summary["by_family"],
        "skipped": summary["skipped"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
