#!/usr/bin/env python3
"""WP2 runner 1 — V1 two-track render: B4 vs Current (07 plan §9).

Renders two tracks sharing the same global timeline with per-track window plans
that never swap, then encodes a review MP4.  B4 and Current rows are projected
from the *same frozen forward evidence* through ``track_view.rows_from_forward_evidence``
(smoke stand-in: no B4 alignment.json exists yet, so B4 = historical ``raw``
argmax geometry, Current = ``official`` fixed geometry of the same forward —
genuinely different timelines exercising the two-track wiring).

Order driven by the controller: collection -> analysis_complete -> visualization
(static) -> encode.  No model forward, no GT access.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_b4_vs_current.py \
      --forward-root <test_demo>/forward \
      --plan <test_demo>/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl \
      --item "Chinese/此处通往天空.mp3" \
      --audio <Side by Side>.wav \
      --out <run> \
      [--window-idx 0] [--duration 3] [--page-seconds 30]
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
    page_ranges_for,
    render_static_group,
    render_video,
    write_analysis_complete,
    write_collection,
    write_render_manifest,
)


def plan_requests_for_item(plan: list[dict], item: str, kind: str = "narrow") -> list[dict]:
    return [r for r in plan if r.get("item") == item and r.get("kind") == kind]


def main() -> int:
    parser = argparse.ArgumentParser(description="V1 two-track render: B4 vs Current")
    parser.add_argument("--forward-root", required=True, type=Path,
                        help=".../04_test_demo/forward (evidence/ dir inside)")
    parser.add_argument("--plan", required=True, type=Path,
                        help="TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl")
    parser.add_argument("--item", default="Chinese/此处通往天空.mp3")
    parser.add_argument("--audio", required=True, type=Path,
                        help="audio track (e.g. transcoded Side by Side.wav)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--window-idx", type=int, default=0,
                        help="index of the narrow window to render")
    parser.add_argument("--duration", type=float, default=None,
                        help="clip the page to this many seconds (smoke short-cut)")
    parser.add_argument("--page-seconds", type=float, default=30.0)
    parser.add_argument("--font", default="Noto Sans CJK SC")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    evidence_dir = args.forward_root / "evidence"
    plan = load_plan(args.plan)
    reqs = plan_requests_for_item(plan, args.item)
    if not reqs:
        plan_items = sorted({r.get("item") for r in plan})
        raise SystemExit(f"no {args.item!r} requests in plan ({len(plan)} rows); available items: {plan_items}")

    window_idx = min(args.window_idx, len(reqs) - 1)
    wins = reqs[window_idx:window_idx + 1]
    rid = str(wins[0].get("request_id"))

    evidence_index = load_evidence_index(evidence_dir)
    ru = evidence_payloads_for_family(evidence_index, [rid], family="R-U")
    if not ru:
        rs = evidence_payloads_for_family(evidence_index, [rid], family="R-S")
        ru = rs
    if not ru:
        rus = evidence_payloads_for_family(evidence_index, [rid])
        ru = rus
    if not ru:
        raise SystemExit(f"no ok evidence for window {rid}; indexed={len(evidence_index)}")

    payload = ru[0]
    request = (payload.get("attempt") or {}).get("request") or {}
    from visualization_controller import window_trace_from_request
    win_trace = [window_trace_from_request(request)]

    # Rows from the same forward: B4 = raw argmax geometry, Current = official.
    current_track = build_track_from_evidence(
        ru, label="Current", decoder_kind="official", window_trace=win_trace,
        metadata={"family": "official_fixed"},
    )
    b4_track = build_track_from_evidence(
        ru, label="B4", decoder_kind="raw", window_trace=win_trace,
        metadata={"family": "raw_argmax_standin"},
    )
    tracks = [b4_track, current_track]

    # Global timeline from Current (official) rows, clipped to a smoke slice.
    rows = current_track.get("rows") or []
    if not rows:
        raise SystemExit(f"no projected rows for window {rid}")
    start = min(float(r["start_sec"]) for r in rows)
    end = max(float(r["end_sec"]) for r in rows)
    if args.duration:
        end = min(end, start + args.duration)
    if end <= start:
        end = start + 0.5
    windows = list(win_trace)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    # 1) collection (frozen evidence inventory, read-only)
    write_collection(out, plan, items=[args.item])
    # 2) analysis_complete
    write_analysis_complete(out, n_items=1, n_requests=len(wins),
                            resources={"window": rid, "evidence": str(evidence_dir)})

    # 3) static visualization
    group_meta = render_static_group(
        out, group="b4_vs_current", tracks=tracks, windows=windows,
        start=start, end=end,
        title="B4 vs Current — %s" % Path(args.item).name,
        font=args.font, video_layout=True, page_seconds=args.page_seconds,
    )

    # 4) encode review MP4 (KTV karaoke subtitle from Current rows)
    alignment = build_karaoke_alignment(rows, duration_sec=end - start)
    video_meta = render_video(
        out, group="b4_vs_current", pages_meta=group_meta["pages"],
        alignment=alignment, audio_track=args.audio, title="B4 vs Current",
        font=args.font, force=args.force,
    )

    manifest = write_render_manifest(
        out, visual_groups=[group_meta], videos=[video_meta],
    )
    summary = {
        "runner": "render_b4_vs_current.py",
        "window": rid, "item": args.item,
        "start_sec": start, "end_sec": end,
        "tracks": [t["label"] for t in tracks],
        "group": group_meta, "video": video_meta,
        "manifest": manifest,
    }
    (out / "b4_vs_current_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "ok": True, "window": rid, "tracks": [t["label"] for t in tracks],
        "full_timeline": group_meta["full_timeline"],
        "pages": len(group_meta["pages"]),
        "video": video_meta.get("path"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
