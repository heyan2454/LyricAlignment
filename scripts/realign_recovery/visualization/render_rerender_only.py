#!/usr/bin/env python3
"""WP2 runner 4 — camera-only rerender (07 plan §9).

Re-projects frozen forward evidence and re-renders visuals/MP4s **without ever
running a model forward**, and **without rewriting any scientific artifact**
(``scientific/``, ``collection/``, ``analysis_complete.json``).  It asserts the
scientific JSON/JSONL hashes are unchanged before/after and records them as
``scientific_hash_before.json`` / ``scientific_hash_after.json`` at ``<out>``.

This module has no model/forward import path, so it is trigger-free by
construction.

Usage:
  # analysis phase (one-time): render_current_4way / render_b4_vs_current produce
  # scientific/static structures + analysis_complete.json.

  # camera-only rerender of an existing <out> (same frozen evidence):
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_rerender_only.py \
      --out <run> \
      --forward-root <test_demo>/forward \
      --plan <test_demo>/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl \
      --item "Chinese/此处通往天空.mp3" \
      --audio <Side by Side>.wav \
      --mode fourway \
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
    snapshot_scientific_hashes,
    window_trace_from_request,
    write_render_manifest,
)


def _trace(payloads):
    return [window_trace_from_request((p.get("attempt") or {}).get("request") or {}) for p in payloads]


def main() -> int:
    parser = argparse.ArgumentParser(description="Camera-only rerender (no forward, no scientific rewrite)")
    parser.add_argument("--out", required=True, type=Path, help="existing run out root")
    parser.add_argument("--forward-root", type=Path, default=None)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--item", default=None)
    parser.add_argument("--audio", type=Path, default=None)
    parser.add_argument("--mode", choices=["twoway", "fourway"], default="fourway")
    parser.add_argument("--page-seconds", type=float, default=30.0)
    parser.add_argument("--font", default="Noto Sans CJK SC")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="snapshot + compare only, do not re-render")
    args = parser.parse_args()

    out = args.out
    before = snapshot_scientific_hashes(out)
    (out / "scientific_hash_before.json").write_text(
        json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")

    changed_after = {}
    if not args.dry_run:
        if not (args.forward_root and args.plan and args.audio and args.item):
            raise SystemExit("--forward-root/--plan/--item/--audio required for a real camera-only rerender")
        plan = load_plan(args.plan)
        request_ids = [str(r["request_id"]) for r in plan if r.get("item") == args.item]
        evidence_index = load_evidence_index(args.forward_root / "evidence")
        if not request_ids:
            raise SystemExit(f"no requests for item {args.item!r}")
        ru = evidence_payloads_for_family(evidence_index, request_ids, family="R-U")
        rs = evidence_payloads_for_family(evidence_index, request_ids, family="R-S")
        base = ru or rs
        if not base:
            raise SystemExit("no ok evidence for item")
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
        if args.mode == "twoway":
            payload0 = next((p for p in (ru or rs) if p), None)
            rq = (payload0.get("attempt") or {}).get("request") or {}
            trace = [window_trace_from_request(rq)]
            tracks = [
                build_track_from_evidence([payload0], label="B4", decoder_kind="raw",
                                          window_trace=trace, metadata={"family": "raw_argmax_standin"}),
                build_track_from_evidence([payload0], label="Current", decoder_kind="official",
                                          window_trace=trace, metadata={"family": "official_fixed"}),
            ]
        group = "current_realign_4way" if args.mode == "fourway" else "b4_vs_current"
        rows = next((t.get("rows") for t in tracks if t.get("rows")), [])
        if not rows:
            raise SystemExit("no projected rows")
        start = min(float(r["start_sec"]) for r in rows)
        end = max(float(r["end_sec"]) for r in rows)
        if end <= start:
            end = start + 0.5
        windows = []
        seen = set()
        for t in tracks:
            for w in (t.get("window_trace") or []):
                key = (w.get("core_start_sec"), w.get("core_end_sec"))
                if key not in seen:
                    seen.add(key); windows.append(w)
        group_meta = render_static_group(
            out, group=group, tracks=tracks, windows=windows,
            start=start, end=end, title=f"camera-only rerender — {Path(args.item).name}",
            font=args.font, video_layout=True, page_seconds=args.page_seconds,
        )
        alignment = build_karaoke_alignment(rows, duration_sec=end - start)
        video_meta = render_video(
            out, group=group, pages_meta=group_meta["pages"], alignment=alignment,
            audio_track=args.audio, title=group, font=args.font, force=args.force,
        )
        write_render_manifest(out, visual_groups=[group_meta], videos=[video_meta])
        changed_after = {"visual_groups": [group], "video": video_meta.get("path")}

    after = snapshot_scientific_hashes(out)
    (out / "scientific_hash_after.json").write_text(
        json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8")

    changed = {k: (before.get(k), after.get(k)) for k in before if before.get(k) != after.get(k)}
    if changed:
        print(json.dumps({"ok": False, "changed": changed}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "ok": True, "camera_only": True, "forward_triggered": 0,
        "scientific_hashes_unchanged": True,
        "n_scientific_artifacts": len(before),
        "scientific_hash_before": str(out / "scientific_hash_before.json"),
        "scientific_hash_after": str(out / "scientific_hash_after.json"),
        "rerendered": changed_after,
        "changed": list(changed),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
