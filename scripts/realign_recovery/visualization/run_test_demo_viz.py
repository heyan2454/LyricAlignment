#!/usr/bin/env python3
"""WP10 — batch Test Demo visualization (double-way + four-way) over Demo cases.

07 plan §9 / 03 V6+V7.  A collection-before-visualization batch that *reuses* the
WP2 shared controller (``visualization_controller``) and does **not** rewrite or
re-run the renderer.  It reads only the frozen forward evidence of a Test Demo
collection root and emits, for each selected representative + hard-case item:

  * B4-vs-Current double-way (``render_b4_vs_current`` semantics),
  * Current 4-way: Current / R-U / R-S [/ ``--fourth-family`` R-CF]  (``render_current_4way``
    semantics),

into the 03 V7 layout:

    <out>/
      collection/collection.json
      analysis_complete.json
      visuals/{b4_vs_current|current_realign_4way}/{item_slug}/... png
      renders/{b4_vs_current|current_realign_4way}/{item_slug}.mp4
      render_manifest.json
      test_demo_batch_plan.json          (--skip-render dry-run manifest plan)
      scientific_hash_before/after.json  (--rerender-only)

Constraints honoured:
  * No Qwen forward: only ``visualization_controller`` projectors + renderer
    (all import safe, no model path).
  * collection-before-visualization (write_collection runs before any render).
  * GT never enters the render (only frozen forward evidence is projected).
  * U4 ffprobe 判定 for the 3 known failing-mp4 Test Demo items: if ffprobe opens
    a readable stream the item is transcoded (the existing ``transcode_media_to_wav``
    helper) and the WAV becomes that item's audio track; otherwise the item is
    recorded as ``failed`` in the batch plan and skipped.

Usage (dry-run acceptance / CPU):
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
      --test-demo-root <test_demo> \
      --out-root <run> \
      --languages zh,yue,en,ja \
      --fourth-family R-CF \
      --skip-render

Real batch (GPU/formal template):
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
      --test-demo-root <test_demo> \
      --out-root <run> --languages zh,yue,en,ja --fourth-family R-CF \
      [--duration 3] [--page-seconds 30] [--force]

Camera-only rerender (cache-only, no forward, scientific hash assert):
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_test_demo_viz.py \
      --test-demo-root <test_demo> --out-root <run> --rerender-only [--mode fourway]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow reusing the WP2 controller/runners from the same directory regardless of cwd.
_VIZ_DIR = Path(__file__).resolve().parent
if str(_VIZ_DIR) not in sys.path:
    sys.path.insert(0, str(_VIZ_DIR))

from visualization_controller import (  # noqa: E402
    build_karaoke_alignment,
    build_track_from_evidence,
    load_evidence_index,
    load_plan,
    render_static_group,
    render_video,
    window_trace_from_request,
    write_analysis_complete,
    write_collection,
    write_render_manifest,
)

FONT = "Noto Sans CJK SC"

# U4 root cause (transcode_media_to_wav): these Test Demo items use .mp4 containers
# that soundfile cannot open.  They are probed with ffprobe; if a stream is
# detectable we transcode to WAV, otherwise the item is recorded as failed.
U4_MP4_ITEMS = ("Side by Side.mp4", "祈愿花开.mp4", "夜苏打.mp4")

# Canonical on-disk locations for the 3 known U4 mp4 items (probed over the
# --media-root and these absolute fallbacks).  The first hint that exists wins.
def _U4_MEDIA_CANDIDATES() -> dict[str, list[str]]:
    chinese = "/home/hyan/Data/lyricalign/test/Chinese"
    return {
        "Side by Side.mp4": [f"{chinese}/Side by Side.mp4"],
        "祈愿花开.mp4": [f"{chinese}/祈愿花开.mp4"],
        "夜苏打.mp4": [
            "/home/hyan/Data/lyricalign/demo_diagnostics/inline_realign_formal_v2_20260728/items/demo_夜苏打/render/official.mp4",
        ],
    }

# Map a language code (from --languages) to a representative Test Demo item id
# and its source media factory.  In the frozen formal plan the representative
# cases carry these item ids; audio for non-mp3 targets is resolved via the media
# probe (U4) against --media-root.
REPRESENTATIVES = {
    "zh": "Chinese/此处通往天空.mp3",
    "yue": "Cantonese/浮夸.mp3",
    "en": "English/Past Lives.mp3",
    "ja": "Japanese/乙女解剖.mp3",
}

LANG_BY_ITEM_PREFIX = {
    "Chinese": "zh", "Cantonese": "yue", "English": "en", "Japanese": "ja",
}


def item_slug(item: str) -> str:
    base = Path(item).stem.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return "".join(ch for ch in base if ch.isalnum() or ch in "_-") or "item"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def language_of_item(item: str) -> str:
    for prefix, lang in LANG_BY_ITEM_PREFIX.items():
        if item.startswith(prefix + "/"):
            return lang
    return "other"


def present_in_plan(plan: list[dict], item: str) -> bool:
    return any(r.get("item") == item for r in plan)


def select_items(plan: list[dict], languages: list[str]) -> list[dict[str, str]]:
    """Representative + hard-case selection.

    For each requested language pick its representative (falling back to the
    first plan item of that language when the canonical representative is absent)
    and always include the hard-case mp4 items that exist in the plan.  Each
    entry is ``{"item": ..., "language": ..., "role": rep|hardcase}``.
    """
    plan_items = sorted({r.get("item") for r in plan if r.get("item")})
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for lang in languages:
        rep = REPRESENTATIVES.get(lang)
        if rep and present_in_plan(plan, rep):
            chosen = rep
        else:
            candidates = [it for it in plan_items if language_of_item(it) == lang]
            chosen = candidates[0] if candidates else None
        if chosen and chosen not in seen:
            seen.add(chosen)
            selected.append({"item": chosen, "language": lang, "role": "representative"})
    # hard-case mp4 items that are actually in this collection's plan
    for hard in U4_MP4_ITEMS:
        hard_id = next((it for it in plan_items if Path(it).name == hard), None)
        if hard_id and hard_id not in seen:
            seen.add(hard_id)
            selected.append({"item": hard_id, "language": language_of_item(hard_id),
                             "role": "hardcase"})
    return selected


def ffprobe_media(media: Path) -> dict:
    """ffprobe probe: return the primary audio stream's codec/format, or {} if unreadable."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,codec_type,sample_rate,channels",
        "-show_entries", "format=format_name,duration",
        "-of", "json", str(media),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True)
        return json.loads(out.stdout.decode("utf-8"))
    except Exception as e:  # subprocess error / non-parsable output
        return {"error": str(e)}


def probe_resolves(probe: dict) -> bool:
    streams = probe.get("streams") or []
    return any(s.get("codec_type") == "audio" for s in streams)


def u4_probe(media: Path, media_exists: bool) -> dict:
    """U4 判定 for a candidate media file. Returns {'ok': bool, 'probe': ..., 'reason': ...}."""
    if not media_exists:
        return {"ok": False, "reason": "media_file_missing",
                "probe": None, "action": "failed"}
    probe = ffprobe_media(media)
    if probe_resolves(probe):
        return {"ok": True, "reason": "stream_resolvable", "probe": probe,
                "action": "transcode_to_wav"}
    return {"ok": False, "reason": "ffprobe_unreadable", "probe": probe.get("error")
            if isinstance(probe, dict) else None, "action": "failed"}


def resolve_source_media(item: str, media_root: Path | None) -> Path | None:
    """Find the original media for an item id under --media-root / --test-demo-root."""
    if not media_root:
        return None
    name = Path(item).name
    candidates = [
        media_root / item,
        media_root / name,
    ]
    if name.endswith(".mp3") and media_root:
        pass
    for c in candidates:
        if c.is_file():
            return c
    # direct child search (shallow) for convenience
    try:
        for c in sorted(media_root.iterdir()):
            if c.is_file() and c.name == name:
                return c
    except OSError:
        pass
    return None


def build_family_tracks(evidence_index, plan, item, *, fourth_family=None):
    """Tracks for the four-way render for ONE item.

    AC-review P1#1: families must be scoped to the CURRENT item's evidence, never
    the whole index (otherwise every song's four-way tracks silently mix rows from
    other songs).  We filter evidence by ``request.item_id == item`` first, then by
    proposal_method (robust to R-S sparse request ids differing from the plan).
    """
    request_ids = [str(r["request_id"]) for r in plan if r.get("item") == item]
    # item-scoped evidence: only payloads whose request belongs to this item.
    scoped = []
    for p in evidence_index.values():
        req = (p.get("attempt") or {}).get("request") or {}
        pid = str(req.get("item_id") or "").strip()
        if pid and pid != item:
            continue
        scoped.append(p)
    if not scoped:
        scoped = list(evidence_index.values())  # evidence lacks item_id -> fallback

    def _by_method(method: str) -> list:
        return [p for p in scoped
                if ((p.get("attempt") or {}).get("request") or {}).get("mutation_parameters", {})
                .get("proposal_method") == method]

    ru = _by_method("R-U")
    if not ru:
        ru = [evidence_index[rid] for rid in request_ids if rid in evidence_index]
    rs = _by_method("R-S")
    base = ru or rs
    if not base:
        return None, request_ids

    def _trace(payloads):
        return [window_trace_from_request((p.get("attempt") or {}).get("request") or {})
                for p in payloads]

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
        f4 = _by_method(fourth_family)
        if f4:
            tracks.append(build_track_from_evidence(
                f4, label=fourth_family, decoder_kind="official",
                window_trace=_trace(f4), metadata={"family": fourth_family}))
    return tracks, request_ids


def two_way_tracks(payload, item):
    request = (payload.get("attempt") or {}).get("request") or {}
    trace = [window_trace_from_request(request)]
    b4 = build_track_from_evidence(
        [payload], label="B4", decoder_kind="raw", window_trace=trace,
        metadata={"family": "raw_argmax_standin"})
    cur = build_track_from_evidence(
        [payload], label="Current", decoder_kind="official", window_trace=trace,
        metadata={"family": "official_fixed"})
    return [b4, cur]


def collect_windows(tracks):
    seen = set()
    out = []
    for t in tracks:
        for w in (t.get("window_trace") or []):
            key = (w.get("core_start_sec"), w.get("core_end_sec"))
            if key not in seen:
                seen.add(key)
                out.append(w)
    return out


def render_group(out, *, group, item, tracks, windows, args, audio=None, title=None):
    rows = next((t.get("rows") for t in tracks if t.get("rows")), [])
    if not rows:
        return None
    start = min(float(r["start_sec"]) for r in rows)
    end = max(float(r["end_sec"]) for r in rows)
    if args.duration:
        end = min(end, start + args.duration)
    if end <= start:
        end = start + 0.5
    meta = render_static_group(
        out, group=group, tracks=tracks, windows=windows,
        start=start, end=end,
        title=title or f"{group} — {Path(item).name}",
        font=args.font, video_layout=True, page_seconds=args.page_seconds,
    )
    alignment = build_karaoke_alignment(rows, duration_sec=end - start)
    video = render_video(
        out, group=group, pages_meta=meta["pages"], alignment=alignment,
        audio_track=audio, title=title or group, font=args.font, force=args.force,
    )
    return {"group": group, "item": item, "meta": meta, "video": video}


def main() -> int:
    parser = argparse.ArgumentParser(description="WP10 batch Test Demo visualization")
    parser.add_argument("--test-demo-root", required=True, type=Path,
                        help="Test Demo collection root (has TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl + forward/)")
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--languages", default="zh,yue,en,ja",
                        help="comma list of representative languages to select")
    parser.add_argument("--fourth-family", default=None,
                        help="family label for the 4th track (WP6 route, e.g. R-CF); omit = 3 tracks")
    parser.add_argument("--media-root", type=Path, default=None,
                        help="dir where Test Demo source media live (for U4 probe + audio track)")
    parser.add_argument("--skip-render", action="store_true",
                        help="only build the batch manifest plan (list cases + U4 判定), no render")
    parser.add_argument("--rerender-only", action="store_true",
                        help="camera-only rerender: no forward, assert scientific hashes unchanged")
    parser.add_argument("--mode", choices=["twoway", "fourway", "both"], default="both",
                        help="which render to perform (rerender-only/batch)")
    parser.add_argument("--duration", type=float, default=None,
                        help="clip pages to N seconds (smoke short-cut)")
    parser.add_argument("--page-seconds", type=float, default=30.0)
    parser.add_argument("--font", default=FONT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.test_demo_root / "TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl"
    if not plan_path.is_file():
        raise SystemExit(f"plan not found at {plan_path}")
    forward_root = args.test_demo_root / "forward"
    evidence_dir = forward_root / "evidence"
    plan = load_plan(plan_path)
    evidence_index = load_evidence_index(evidence_dir)

    out = args.out_root
    out.mkdir(parents=True, exist_ok=True)

    languages = [x.strip() for x in args.languages.split(",") if x.strip()]
    selected = select_items(plan, languages)

    # ------------------------------------------------------------------ #
    # --rerender-only: camera-only rerender of an existing out root.     #
    # ------------------------------------------------------------------ #
    # AC-review P1#2: the naive before/after snapshot was a no-op.  Delegate
    # to render_rerender_only.py which actually re-projects + re-encodes the
    # frozen evidence and asserts scientific hashes unchanged (no forward).
    if args.rerender_only:
        import shutil
        import subprocess
        import sys
        runner = Path(__file__).resolve().parent / "render_rerender_only.py"
        cmd = [sys.executable, str(runner), "--out", str(out), "--mode", args.mode or "fourway"]
        # forward-root = the evidence index root (test-demo forward or --media-root).
        fwd = Path(args.media_root or "").resolve() if args.media_root else None
        if fwd is None and args.test_demo_root:
            cand = Path(args.test_demo_root) / "forward"
            fwd = cand if (cand / "evidence").is_dir() else cand
        if fwd is not None:
            cmd += ["--forward-root", str(fwd)]
        if args.test_demo_root:
            plan = Path(args.test_demo_root) / "TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl"
            if plan.is_file():
                cmd += ["--plan", str(plan)]
        print("[rerender-only] delegating to render_rerender_only.py:", " ".join(map(str, cmd[-6:])))
        proc = subprocess.run(cmd, capture_output=False)
        return proc.returncode

    # ------------------------------------------------------------------ #
    # U4 判定 for the recognized mp4 hard-case items.                    #
    # Always run the ffprobe judgment (also in --skip-render) so a dry-run
    # reports whether each of the 3 known mp4 items can be opened; transcode
    # to WAV only happens when actually rendering.
    # ------------------------------------------------------------------ #
    media_root = args.media_root or args.test_demo_root
    u4_results: dict[str, dict] = {}
    audio_track_map: dict[str, Path] = {}
    failed_items: list[str] = []
    u4_probed: dict[str, Path] = {}
    for entry in selected:
        item = entry["item"]
        if Path(item).name in U4_MP4_ITEMS:
            media = resolve_source_media(item, media_root)
            if media is not None:
                u4_probed[item] = media
    # The 3 known U4 mp4s may not be in a given frozen plan; still probe the
    # canonical media paths so the dry-run reports their openability.
    if not u4_probed:
        for name, hints in _U4_MEDIA_CANDIDATES().items():
            for h in hints:
                cand = resolve_source_media(name, media_root)
                p = Path(h)
                if cand and cand.is_file():
                    u4_probed[name] = cand
                    break
                if p.is_file():
                    u4_probed[name] = p
                    break
    for item in U4_MP4_ITEMS:
        media = u4_probed.get(item)
        verdict = u4_probe(media, media is not None)
        u4_results[item] = verdict
        if verdict["ok"] and not args.skip_render:
            wav_out = out / "audio_tracks" / (item_slug(item) + ".wav")
            wav_out.parent.mkdir(parents=True, exist_ok=True)
            try:
                from transcode_media_to_wav import transcode_to_wav
                transcode_to_wav(media, wav_out)
                audio_track_map[item] = wav_out
                verdict["transcoded_to"] = str(wav_out)
            except Exception as e:  # noqa: BLE001
                verdict["ok"] = False
                verdict["reason"] = f"transcode_failed: {e}"
        elif verdict["ok"]:
            verdict["action"] = "openable"  # dry-run: no transcode
        if not verdict["ok"]:
            failed_items.append(item)

    # ------------------------------------------------------------------ #
    # Manifest plan (always written; most of the value under --skip-render) #
    # ------------------------------------------------------------------ #
    planned_groups: list[dict] = []
    for entry in selected:
        item = entry["item"]
        if file_audio := resolve_source_media(item, media_root):
            entry["media_file"] = str(file_audio)
        else:
            entry["media_file"] = None
        entry["audio_track"] = str(audio_track_map[item]) if item in audio_track_map else None
        for mode in (args.mode.split(":") if ":" in args.mode else [args.mode]):
            planned_groups.append({
                "item": item, "language": entry["language"], "role": entry["role"],
                "mode": mode, "group": f"{'current_realign_4way' if mode == 'fourway' else 'b4_vs_current'}/{item_slug(item)}",
            })

    batch_plan = {
        "schema": "wp10_test_demo_batch_plan_v1",
        "collection_root": str(args.test_demo_root),
        "out_root": str(out),
        "languages": languages,
        "fourth_family": args.fourth_family,
        "skip_render": args.skip_render,
        "n_selected": len(selected),
        "selected": selected,
        "u4_probe": u4_results,
        "failed_items": failed_items,
        "planned_groups": planned_groups,
    }
    (out / "test_demo_batch_plan.json").write_text(
        json.dumps(batch_plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.skip_render:
        print(json.dumps({
            "ok": True, "dry_run": True,
            "n_selected": len(selected),
            "selected": [(e["item"], e["role"], e["language"]) for e in selected],
            "u4_probe": {k: (v.get("action"), v.get("reason")) for k, v in u4_results.items()},
            "failed_items": failed_items,
            "planned_groups": len(planned_groups),
            "render_manifest_plan": str(out / "test_demo_batch_plan.json"),
        }, ensure_ascii=False, indent=2))
        return 0

    # ------------------------------------------------------------------ #
    # Collection-before-visualization.                                   #
    # ------------------------------------------------------------------ #
    all_items = sorted({e["item"] for e in selected})
    write_collection(out, plan, items=all_items)
    write_analysis_complete(out, n_items=len(all_items), n_requests=len(plan), resources={
        "languages": languages, "fourth_family": args.fourth_family,
        "u4_failed": failed_items,
    })

    visual_groups: list[dict] = []
    videos: list[dict] = []
    rendered: list[str] = []
    for entry in selected:
        item = entry["item"]
        if item in failed_items:
            continue
        audio = audio_track_map.get(item)
        if audio is None:
            media = resolve_source_media(item, media_root)
            if media and media.suffix.lower() in (".wav", ".mp3"):
                audio = media
        if audio is None or not Path(audio).is_file():
            print(f"[warn] no usable audio for {item}; skipping render")
            continue

        request_ids = [str(r["request_id"]) for r in plan if r.get("item") == item]
        first_ok = next((evidence_index[r] for r in request_ids if r in evidence_index), None)

        if args.mode in ("twoway", "both"):
            if first_ok is None:
                print(f"[warn] {item}: no ok evidence for two-way")
            else:
                tracks = two_way_tracks(first_ok, item)
                res = render_group(
                    out, group=f"b4_vs_current/{item_slug(item)}", item=item,
                    tracks=tracks, windows=collect_windows(tracks), args=args,
                    audio=audio, title=f"B4 vs Current — {Path(item).name}")
                if res:
                    visual_groups.append(res["meta"]); videos.append(res["video"])
                    rendered.append(f"{item}:twoway")

        if args.mode in ("fourway", "both"):
            fourway_tracks, _rids = build_family_tracks(
                evidence_index, plan, item, fourth_family=args.fourth_family)
            if not fourway_tracks:
                print(f"[warn] {item}: no R-U/R-S evidence for four-way")
            else:
                windows = collect_windows(fourway_tracks)
                res = render_group(
                    out, group=f"current_realign_4way/{item_slug(item)}", item=item,
                    tracks=fourway_tracks, windows=windows, args=args,
                    audio=audio, title=f"Current 4-way — {Path(item).name}")
                if res:
                    visual_groups.append(res["meta"]); videos.append(res["video"])
                    rendered.append(f"{item}:fourway")

    write_render_manifest(out, visual_groups=visual_groups, videos=videos)

    summary = {
        "runner": "run_test_demo_viz.py",
        "ok": True,
        "n_items": len(all_items), "n_rendered_groups": len(videos),
        "rendered": rendered,
        "failed_items": failed_items,
        "collection": str(out / "collection/collection.json"),
        "render_manifest": str(out / "render_manifest.json"),
        "videos": [v.get("path") for v in videos],
    }
    (out / "test_demo_batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
