#!/usr/bin/env python3
"""WP2 runner 2 — V2 four-way render: Current / R-U / R-S [/ R-U->sparse] (07 plan §9).

Renders the current unit-realign request families as side-by-side tracks on one
global timeline and encodes a review MP4.  Each family's rows come from frozen
forward evidence projected via ``track_view.rows_from_forward_evidence`` with that
family's own window_trace, so window plans never cross tracks.

The fourth track (R-U -> sparse refinement) is not implemented yet (WP6), so by
default only the three implemented families (Current baseline, R-U, R-S) are
rendered; pass ``--fourth-family`` once WP6 lands to include it.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_current_4way.py \
      --forward-root <test_demo>/forward \
      --plan <test_demo>/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl \
      --item "Chinese/此处通往天空.mp3" \
      --audio <Side by Side>.wav \
      --out <run> \
      [--duration 3] [--page-seconds 30]
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


def plan_request_ids_for_item(plan: list[dict], item: str) -> list[dict]:
    return [r for r in plan if r.get("item") == item]


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 four/three-way render")
    parser.add_argument("--forward-root", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--item", default="Chinese/此处通往天空.mp3")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=None,
                        help="clip the shared page to this many seconds (smoke short-cut)")
    parser.add_argument("--page-seconds", type=float, default=30.0)
    parser.add_argument("--font", default="Noto Sans CJK SC")
    parser.add_argument("--fourth-family", default=None,
                        help="family label for the 4th track (WP6 R-U->sparse); omitted = 3 tracks")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan = load_plan(args.plan)
    reqs = plan_request_ids_for_item(plan, args.item)
    if not reqs:
        raise SystemExit(f"no requests for item {args.item!r}")
    request_ids = [str(r["request_id"]) for r in reqs]

    evidence_index = load_evidence_index(args.forward_root / "evidence")
    ru_payloads = evidence_payloads_for_family(evidence_index, request_ids, family="R-U")
    rs_payloads = evidence_payloads_for_family(evidence_index, request_ids, family="R-S")
    if not ru_payloads and not rs_payloads:
        raise SystemExit("no ok R-U/R-S evidence for item")

    def _trace_for(payloads):
        traces = []
        for p in payloads:
            rq = (p.get("attempt") or {}).get("request") or {}
            traces.append(window_trace_from_request(rq))
        return traces

    # Current baseline: official geometry of the union of realigned windows.
    base_payloads = ru_payloads or rs_payloads
    current_track = build_track_from_evidence(
        base_payloads, label="Current baseline", decoder_kind="official",
        window_trace=_trace_for(base_payloads),
        metadata={"family": "official_fixed_baseline"},
    )
    ru_track = build_track_from_evidence(
        ru_payloads, label="R-U", decoder_kind="official",
        window_trace=_trace_for(ru_payloads),
        metadata={"family": "R-U"},
    )
    rs_track = build_track_from_evidence(
        rs_payloads, label="R-S", decoder_kind="official",
        window_trace=_trace_for(rs_payloads),
        metadata={"family": "R-S"},
    )
    tracks = [current_track, ru_track, rs_track]

    fourth_family = args.fourth_family
    if fourth_family:
        # U-review P1-2: do not depend on the external plan's request_ids containing
        # the 4th-route id (it usually doesn't, since the plan comes from the R-U/R-S
        # pipeline).  Collect every payload whose proposal_method == fourth_family
        # directly from the frozen evidence index; if none exist, fail explicitly
        # (explicit --fourth-family with no evidence is a config error, not a silent
        # 3-track fallback).
        f4 = [p for p in evidence_index.values()
              if ((p.get("attempt") or {}).get("request") or {}).get("mutation_parameters", {})
              .get("proposal_method") == fourth_family]
        if f4:
            tracks.append(build_track_from_evidence(
                f4, label=fourth_family, decoder_kind="official",
                window_trace=_trace_for(f4), metadata={"family": fourth_family},
            ))
        else:
            raise SystemExit(
                f"[error] --fourth-family {fourth_family!r} specified but no evidence has "
                f"proposal_method=={fourth_family!r} in forward-root; refusing to render a "
                f"silent 3-track fallback"
            )

    rows = current_track.get("rows") or []
    if not rows:
        rows = ru_track.get("rows") or []
    if not rows:
        raise SystemExit("no projected rows for any family")
    start = min(float(r["start_sec"]) for r in rows)
    end = max(float(r["end_sec"]) for r in rows)
    if args.duration:
        end = min(end, start + args.duration)
    if end <= start:
        end = start + 0.5
    windows = {}
    # windows for draw_windows: union of per-track window_traces on the global axis.
    seen = set()
    win_list = []
    for t in tracks:
        for w in (t.get("window_trace") or []):
            key = (w.get("core_start_sec"), w.get("core_end_sec"))
            if key in seen:
                continue
            seen.add(key)
            win_list.append(w)
    windows = win_list

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    write_collection(out, plan, items=[args.item])
    write_analysis_complete(out, n_items=1, n_requests=len(reqs), resources={
        "item": args.item, "n_requests": len(reqs),
    })

    group_meta = render_static_group(
        out, group="current_realign_4way", tracks=tracks, windows=windows,
        start=start, end=end,
        title="Current 4-way — %s" % Path(args.item).name,
        font=args.font, video_layout=True, page_seconds=args.page_seconds,
    )
    alignment = build_karaoke_alignment(rows, duration_sec=end - start)
    video_meta = render_video(
        out, group="current_realign_4way", pages_meta=group_meta["pages"],
        alignment=alignment, audio_track=args.audio, title="Current 4-way",
        font=args.font, force=args.force,
    )
    write_render_manifest(out, visual_groups=[group_meta], videos=[video_meta])
    summary = {
        "runner": "render_current_4way.py",
        "item": args.item, "start_sec": start, "end_sec": end,
        "tracks": [t["label"] for t in tracks],
        "n_families": len(tracks),
        "group": group_meta, "video": video_meta,
        "fourth_family": fourth_family,
    }
    (out / "current_realign_4way_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "ok": True, "tracks": [t["label"] for t in tracks],
        "n_families": len(tracks), "full_timeline": group_meta["full_timeline"],
        "pages": len(group_meta["pages"]), "video": video_meta.get("path"),
        "note": "fourth family R-U->sparse not implemented; 3 tracks rendered" if not fourth_family else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
