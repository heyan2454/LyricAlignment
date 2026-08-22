#!/usr/bin/env python3
"""Build SHORT-WINDOW full-slot manifests with NO alignment-timestamp input.

Window geometry and unit ownership are derived purely from the audio and the
lyric ORDER (no B4 / Current timestamps anywhere):

  1. vocal activity profile from the audio (energy-based, same as B4 planner)
  2. window split points = silence gaps (>= gap_sec) in the activity profile;
     windows longer than max_core_sec are split again at their quietest point
  3. unit ownership = lyric-order cursor + duration-share budget:
       target_i = round(total_units * window_active_sec / total_active_sec)
     so each window gets as many lyrics as its active audio share justifies
     (a window can always "hold" its units: no timestamp lookup involved)
  4. audio crop = window [start, end] (silence-aware boundaries, no pads)

Consumable by run_testdemo_slot_infer.py (needs text_units, window_unit_ids,
audio_start_sec/end_sec, timeline_align_path only for the DOCUMENT — the
document is the lyric text, which is identical regardless of who aligned it).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_audio_short_manifest.py \
      --songs "song=lang=lyrics.txt=vocals.wav" ... \
      --out <manifest.jsonl> [--gap-sec 2.0] [--max-core-sec 12.0]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio  # noqa: E402
from align_qwen_fa_serial_demo import build_vocal_activity_profile  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


import numpy as np  # noqa: E402


def _profile_intervals(profile: dict) -> list[tuple[float, float]]:
    """Active intervals from the frame-level activity array.

    active[i] covers time [i*hop_sec, (i+1)*hop_sec) — index 0 is t=0
    (see build_vocal_activity_profile: starts = arange(count)*hop).
    """
    active = np.asarray(profile["active"])
    hop = float(profile["hop_sec"])
    intervals: list[tuple[float, float]] = []
    start = None
    for i, a in enumerate(active):
        t = i * hop
        if a and start is None:
            start = t
        elif not a and start is not None:
            intervals.append((start, t))
            start = None
    if start is not None:
        intervals.append((start, len(active) * hop))
    return intervals


def split_windows(profile: dict, duration: float, gap_sec: float, max_core_sec: float) -> list[tuple[float, float]]:
    """Windows from the activity profile: cut at silence gaps, then split
    oversized windows at their quietest interior point."""
    intervals = _profile_intervals(profile)
    # silence gaps between active intervals
    silences: list[tuple[float, float]] = []
    for (a1, b1), (a2, b2) in zip(intervals, intervals[1:]):
        if a2 - b1 >= gap_sec:
            silences.append((b1, a2))
    bounds = sorted(set([0.0, duration] + [e for _, e in silences]))
    windows: list[tuple[float, float]] = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a <= 0:
            continue
        if b - a <= max_core_sec:
            windows.append((a, b))
        else:
            # split oversized window at quietest interior point
            n = int((b - a) // max_core_sec) + 1
            seg = (b - a) / n
            for i in range(n):
                windows.append((a + i * seg, min(b, a + (i + 1) * seg)))
    return windows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[],
                    help="song=lang=lyrics.txt=vocals.wav")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--gap-sec", type=float, default=2.0)
    ap.add_argument("--max-core-sec", type=float, default=12.0)
    args = ap.parse_args()

    rows = []
    for spec in args.songs:
        song, lang, lyrics_path, vocal_path = spec.split("=")
        text = Path(lyrics_path).read_text(encoding="utf-8")
        doc = parse_lyrics_text(text, language=lang)
        units = list(doc.characters)
        all_cids = [u.global_index for u in units]
        texts = [u.text for u in units]
        audio = decode_audio(str(vocal_path))
        sr = 16000
        duration = float(len(audio) / sr)
        profile = build_vocal_activity_profile(audio)
        windows = split_windows(profile, duration, args.gap_sec, args.max_core_sec)
        # active duration per window (from profile intervals)
        active_intervals = _profile_intervals(profile)
        active_total = sum(b - a for a, b in active_intervals)
        # budget by duration share
        cursor = 0
        rows_song = []
        for wi, (ws, we) in enumerate(windows):
            # active seconds inside this window
            act = 0.0
            for a, b in active_intervals:
                act += max(0.0, min(we, b) - max(ws, a))
            share = max(act / max(active_total, 1e-9), 0.0)
            target = int(round(len(units) * share))
            target = max(target, 1)
            if wi == len(windows) - 1:
                target = len(units) - cursor
            in_units = units[cursor: cursor + target]
            cursor += len(in_units)
            if not in_units:
                continue
            cids = [u.global_index for u in in_units]
            wstart = min(cids)
            wend = max(cids) + 1
            # contiguous by construction (lyric-order slice)
            slot_local = list(range(wend - wstart))
            local = {cid: i for i, cid in enumerate(cids)}
            row = {
                "schema_version": "testdemo_audio_short_manifest_v1",
                "request_id": f"{song}:A{wi}:audioshort",
                "item_id": f"{song}:A{wi}:audioshort",
                "song_id": song,
                "parent_request_id": None,
                "audio_source": str(Path(vocal_path).resolve()),
                "audio_start_sec": round(ws, 4),
                "audio_end_sec": round(we, 4),
                "duration_sec": round(we - ws, 4),
                "text_source": "lyrics_txt",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": texts,
                "timestamp_slot_indices": slot_local,
                "workflow_mode": "audio_short_slot",
                "mutation_type": "baseline",
                "mutation_parameters": {"position": "whole", "requested_ratio": 0.0},
                "model_id": "Qwen3-ForcedAligner-0.6B-hf",
                "checkpoint_id": "r2-step-000750",
                "input_variant": "text_mutation",
                "language": lang,
                "canonical_text_start": min(all_cids),
                "canonical_text_end": max(all_cids) + 1,
                "canonical_to_local": {str(c): i for c, i in local.items()},
                "canonical_ids": all_cids,
                "window_unit_ids": cids,
                "canonical_timeline_file_sha": "sha256:none",
                "timeline_align_path": "",
                "lyrics_path": str(Path(lyrics_path).resolve()),
                "canonical_adapter_version": "lyrics_txt_v1",
                "source_window_sec": [round(ws, 4), round(we, 4)],
                "slot_plan_id": f"audioshort:A{wi}",
                "comparison_group_id": f"{song}:A{wi}:audioshort",
                "phase": "full",
                "audio_sha256": "sha256:" + _sha(Path(vocal_path)),
                "status": "ok",
                "core_start_sec": round(ws, 4),
                "core_end_sec": round(we, 4),
                "window_index": wi,
                "is_final_core": wi == len(windows) - 1,
                "variant": "audioshort",
                "window_plan_policy": f"audio_active_gap{args.gap_sec}_max{args.max_core_sec}",
                "window_unit_count": len(cids),
            }
            rows_song.append(row)
        print(f"{song}: {len(windows)} windows, units assigned {cursor}/{len(units)} "
              f"active {active_total:.1f}s / {duration:.1f}s", flush=True)
        if cursor < len(units):
            print(f"  WARN {song}: {len(units) - cursor} units unassigned", flush=True)
        rows.extend(rows_song)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
