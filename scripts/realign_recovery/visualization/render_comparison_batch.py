#!/usr/bin/env python3
"""WP2 runner 3 — comparison batch over an items list (07 plan §9).

Iterates a JSONL list of ``{item, mode}`` entries and renders each item's
two-way (B4 vs Current) and/or four-way (Current/R-U/R-S) static + MP4 into the
same 03 V7 output layout.  Pure CPU: reads frozen forward evidence only.

Items file format (JSONL):
    {"item": "Chinese/此处通往天空.mp3", "mode": "fourway"}
    {"item": "Chinese/此处通往天空.mp3", "mode": "twoway"}
    {"item": "English/Past Lives.mp3", "mode": "both"}

``audio_map`` maps an item id to an audio track path (JSONL of
``{"item": ..., "audio": "/abs/path.wav"}``).  When missing, the runner falls
back to the item's own source audio given in the plan/evidence.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_comparison_batch.py \
      --items items.jsonl \
      --forward-root <test_demo>/forward \
      --plan <test_demo>/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl \
      --audio-map audio_map.jsonl \
      --out <run> \
      [--page-seconds 30]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from visualization_controller import (
    build_karaoke_alignment,
    build_track_from_evidence,
    evidence_payloads_for_family,
    load_evidence_index,
    load_plan,
    render_static_group,
    render_video,
    window_trace_from_request,
    write_analysis_complete,
    write_collection,
    write_render_manifest,
)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def build_family_tracks(plan, evidence_index, item, *, fourth_family=None):
    request_ids = [str(r["request_id"]) for r in plan if r.get("item") == item]
    ru = evidence_payloads_for_family(evidence_index, request_ids, family="R-U")
    rs = evidence_payloads_for_family(evidence_index, request_ids, family="R-S")
    if not ru and not rs:
        return None, None

    def _trace(payloads):
        return [window_trace_from_request((p.get("attempt") or {}).get("request") or {}) for p in payloads]

    base = ru or rs
    current = build_track_from_evidence(
        base, label="Current baseline", decoder_kind="official",
        window_trace=_trace(base), metadata={"family": "official_fixed_baseline"})
    tracks = [current]
    if ru:
        tracks.append(build_track_from_evidence(
            ru, label="R-U", decoder_kind="official", window_trace=_trace(ru),
            metadata={"family": "R-U"}))
    if rs:
        tracks.append(build_track_from_evidence(
            rs, label="R-S", decoder_kind="official", window_trace=_trace(rs),
            metadata={"family": "R-S"}))
    if fourth_family:
        f4 = evidence_payloads_for_family(evidence_index, request_ids, family=fourth_family)
        if f4:
            tracks.append(build_track_from_evidence(
                f4, label=fourth_family, decoder_kind="official",
                window_trace=_trace(f4), metadata={"family": fourth_family}))
    return tracks, request_ids


def two_way_tracks(entry, item):
    payload = entry
    request = (payload.get("attempt") or {}).get("request") or {}
    trace = [window_trace_from_request(request)]
    b4 = build_track_from_evidence(
        [payload], label="B4", decoder_kind="raw", window_trace=trace,
        metadata={"family": "raw_argmax_standin"})
    cur = build_track_from_evidence(
        [payload], label="Current", decoder_kind="official", window_trace=trace,
        metadata={"family": "official_fixed"})
    return [b4, cur]


def item_slug(item: str) -> str:
    """Derive a filesystem-safe slug from an item id to namespace batch outputs."""
    base = Path(item).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return "".join(ch for ch in base if ch.isalnum() or ch in "_-") or "item"


def render_group(out, *, group, item, tracks, windows, args, mode, audio=None):
    rows = next((t.get("rows") for t in tracks if t.get("rows")), [])
    if not rows:
        return None
    start = min(float(r["start_sec"]) for r in rows)
    end = max(float(r["end_sec"]) for r in rows)
    if end <= start:
        end = start + 0.5
    meta = render_static_group(
        out, group=group, tracks=tracks, windows=windows,
        start=start, end=end,
        title=f"{mode} — {Path(item).name}", font=args.font,
        video_layout=True, page_seconds=args.page_seconds,
    )
    alignment = build_karaoke_alignment(rows, duration_sec=end - start)
    video = render_video(
        out, group=group, pages_meta=meta["pages"], alignment=alignment,
        audio_track=audio or args.audio, title=mode, font=args.font, force=args.force,
    )
    return {"group": group, "item": item, "meta": meta, "video": video}


def main() -> int:
    parser = argparse.ArgumentParser(description="Comparison batch over an items list")
    parser.add_argument("--items", required=True, type=Path, help="JSONL of {item, mode}")
    parser.add_argument("--forward-root", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--audio-map", type=Path, default=None, help="JSONL of {item, audio}")
    parser.add_argument("--audio", type=Path, default=None, help="fallback audio track")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--page-seconds", type=float, default=30.0)
    parser.add_argument("--font", default="Noto Sans CJK SC")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fourth-family", default=None)
    args = parser.parse_args()

    entries = load_jsonl(args.items)
    audio_map = {e["item"]: Path(e["audio"]) for e in load_jsonl(args.audio_map)} if args.audio_map else {}
    plan = load_plan(args.plan)
    evidence_index = load_evidence_index(args.forward_root / "evidence")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    all_items = sorted({e["item"] for e in entries})
    write_collection(out, plan, items=all_items)
    write_analysis_complete(out, n_items=len(all_items), n_requests=len(plan), resources={})

    groups = []
    videos = []
    for entry in entries:
        item = entry["item"]
        mode = entry.get("mode", "both")
        audio = audio_map.get(item) or args.audio
        if audio is None or not audio.is_file():
            print(f"[warn] no audio for {item}; skipping {mode}")
            continue
        fourway_tracks, request_ids = build_family_tracks(plan, evidence_index, item, fourth_family=args.fourth_family)

        if mode in ("twoway", "both"):
            if not request_ids or not evidence_index.get(request_ids[0]):
                print(f"[warn] {item}: no ok evidence for two-way; skipping")
            else:
                tracks = two_way_tracks(evidence_index[request_ids[0]], item)
                res = render_group(out, group=f"b4_vs_current/{item_slug(item)}", item=item,
                                   tracks=tracks, windows=[], args=args, mode="twoway", audio=audio)
                if res:
                    groups.append(res["meta"]); videos.append(res["video"])

        if mode in ("fourway", "both"):
            if not fourway_tracks:
                print(f"[warn] {item}: no R-U/R-S evidence for four-way; skipping")
            else:
                windows = []
                seen = set()
                for t in fourway_tracks:
                    for w in (t.get("window_trace") or []):
                        key = (w.get("core_start_sec"), w.get("core_end_sec"))
                        if key not in seen:
                            seen.add(key); windows.append(w)
                res = render_group(out, group=f"current_realign_4way/{item_slug(item)}", item=item,
                                   tracks=fourway_tracks, windows=windows, args=args, mode="fourway", audio=audio)
                if res:
                    groups.append(res["meta"]); videos.append(res["video"])

    write_render_manifest(out, visual_groups=groups, videos=videos)
    print(json.dumps({
        "ok": True, "n_groups": len(groups), "n_videos": len(videos),
        "renders": str(args.out / "renders"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
