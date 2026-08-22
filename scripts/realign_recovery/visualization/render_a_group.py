#!/usr/bin/env python3
"""Render the A group (B4 vs Slot, incl. text-mode-3 third panel):

  images/B4_vs_Slot_<song>.png          2-lane full-song timeline (B4 | Slot)
  videos/B4_vs_Slot_<song>.mp4          2-lane timeline video
  videos/B4_vs_Slot_KTV_<song>.mp4      KTV 2+1 panels (B4 | Slot / textmode3)

textmode3 = 13 §4.3 historical-best text providing (32-unit slot region +
history context + 16-unit lookahead), run by run_testdemo_slot_infer.py.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_a_group.py \
      --deliver /home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4_DELIVER [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "realign_recovery" / "visualization"))

from batch_ktv_compare import LANG_LOOKUP, resolve_b4  # noqa: E402
from lyricalign.demo.media_render import render_alignment_comparison  # noqa: E402

SLOT_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4/align"
TM3_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/align_textmode3"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST = "/home/hyan/Data/lyricalign/test"


def resolve_vocal(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        p = Path(base) / lang / f"{song}_qwen_fa/work/audio/vocals.wav"
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    videos = args.deliver / "videos"
    images = args.deliver / "images"
    videos.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    render_script = REPO / "scripts/realign_recovery/visualization/render_full_song.py"
    tmp = args.deliver / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    songs = sorted(p.name for p in Path(SLOT_ROOT).iterdir() if p.is_dir())
    if args.end:
        songs = songs[args.start:args.end]
    else:
        songs = songs[args.start:]

    done, failed = [], []
    for song in songs:
        lang = LANG_LOOKUP.get(song)
        if lang is None:
            continue
        slot = Path(SLOT_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        b4 = resolve_b4(song)
        tm3 = Path(TM3_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        audio = resolve_vocal(song, lang)
        if not (slot.is_file() and b4 and audio and tm3.is_file()):
            print(f"{song}: missing slot/b4/audio/tm3", flush=True)
            failed.append(song)
            continue
        slug = song.replace(" ", "_")

        # Slot lane needs window boundaries: C1 windows == B4 windows (C1
        # manifest reuses the B4 window_trace), but the runner writes an empty
        # window_trace — inject the B4 trace into a copy for the timeline lanes.
        slot_inj = tmp / f"{slug}_slot.alignment.json"
        sd = json.loads(slot.read_text(encoding="utf-8"))
        b4d = json.loads(b4.read_text(encoding="utf-8"))
        sd["window_trace"] = list(b4d.get("window_trace") or [])
        slot_inj.write_text(json.dumps(sd, ensure_ascii=False), encoding="utf-8")

        # 1) timeline 2 lanes (B4 | Slot) — static + video
        out = tmp / f"{slug}_a"
        r = subprocess.run(
            [sys.executable, str(render_script),
             "--baseline-align", f"B4 历史pre-slot串行={b4}",
             "--baseline-align", f"Slot full-slot={slot_inj}",
             "--item", f"{lang}/{song}.mp3", "--audio", str(audio),
             "--out", str(out), "--page-seconds", str(args.page_seconds),
             "--no-global-windows"],
            capture_output=True, text=True, timeout=7200)
        ft = out / "visuals/current_full_song/full_timeline.png"
        mp = out / "renders/current_full_song.mp4"
        if ft.is_file():
            shutil.copyfile(ft, images / f"B4_vs_Slot_{slug}.png")
        if mp.is_file():
            shutil.copyfile(mp, videos / f"B4_vs_Slot_{slug}.mp4")

        # 2) KTV 2+1 (B4 | Slot / textmode3)
        ktv = videos / f"B4_vs_Slot_KTV_{slug}.mp4"
        try:
            render_alignment_comparison(
                alignment_paths=[b4, slot, tm3],
                labels=["B4 · pre-slot", "Slot · full-slot", "Slot · textmode3"],
                visual_source=None, audio_track=audio,
                output_path=ktv, ass_root=args.deliver / "_ktv_ass" / slug,
                font="Noto Sans CJK SC", layout="three", profile="final", force=True)
        except Exception as e:  # noqa: BLE001
            print(f"{song}: KTV FAIL {e}", flush=True)
        ok = ft.is_file() and mp.is_file() and ktv.is_file()
        print(f"{song}: {'OK' if ok else 'PARTIAL'} (exit={r.returncode})", flush=True)
        (done if ok else failed).append(song)
    print(json.dumps({"RENDER_DONE": len(done), "failed": failed, "total": len(songs)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
