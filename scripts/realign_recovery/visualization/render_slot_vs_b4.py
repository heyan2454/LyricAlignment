#!/usr/bin/env python3
"""Render B4-vs-Slot(full-slot Current) comparisons into a NEW deliver folder:
static full-song timeline PNGs + timeline MP4s + KTV dual-panel MP4s.

Slot alignments: runs/20260815_slot_vs_b4/align/<song>/alignments/r2/vocal/windowed/
B4: existing B4 roots (viz_B4 / b4review / ktv_B4).

Output: <deliver>/images/B4_vs_Slot_<song>.png
        <deliver>/videos/B4_vs_Slot_<song>.mp4            (timeline dual)
        <deliver>/videos/B4_vs_Slot_KTV_<song>.mp4        (karaoke dual panel)

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_slot_vs_b4.py \
      --deliver /home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4_DELIVER \
      [--start N] [--end N] [--page-seconds 15]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SLOT_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4/align"


def _load_ktv_module():
    spec = importlib.util.spec_from_file_location(
        "bkc", Path(__file__).resolve().parent / "batch_ktv_compare.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    M = _load_ktv_module()
    videos = args.deliver / "videos"
    images = args.deliver / "images"
    videos.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)

    # songs = all with a slot alignment
    songs = []
    for song_dir in sorted(Path(SLOT_ROOT).iterdir()):
        if not song_dir.is_dir():
            continue
        song = song_dir.name
        lang = M.LANG_LOOKUP.get(song)
        if lang is None:
            continue
        slot = song_dir / "alignments/r2/vocal/windowed/alignment.json"
        b4 = M.resolve_b4(song)
        audio = M.resolve_audio(song, lang)
        if slot.is_file() and b4 and audio:
            songs.append((song, lang))
    if args.end:
        songs = songs[args.start:args.end]
    else:
        songs = songs[args.start:]

    render_script = REPO / "scripts/realign_recovery/visualization/render_full_song.py"
    from lyricalign.demo.media_render import render_alignment_comparison  # noqa: E402

    done, failed = [], []
    for song, lang in songs:
        slot = Path(SLOT_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        b4 = M.resolve_b4(song)
        audio = M.resolve_audio(song, lang)
        slug = song.replace(" ", "_")
        # 1) static full-song timeline + timeline mp4 (render_full_song)
        out = args.deliver / "_tmp" / slug
        r = subprocess.run(
            [sys.executable, str(render_script),
             "--baseline-align", f"B4 历史pre-slot串行={b4}",
             "--baseline-align", f"Slot full-slot={slot}",
             "--item", f"{lang}/{song}.mp3", "--audio", str(audio),
             "--out", str(out), "--page-seconds", str(args.page_seconds)],
            capture_output=True, text=True, timeout=3600)
        ft = out / "visuals/current_full_song/full_timeline.png"
        mp = out / "renders/current_full_song.mp4"
        if ft.is_file():
            (images / f"B4_vs_Slot_{slug}.png").write_bytes(ft.read_bytes())
        if mp.is_file():
            (videos / f"B4_vs_Slot_{slug}.mp4").write_bytes(mp.read_bytes())
        # 2) KTV dual-panel (B4 | Slot)
        ktv = videos / f"B4_vs_Slot_KTV_{slug}.mp4"
        try:
            render_alignment_comparison(
                alignment_paths=[b4, slot],
                labels=["B4 · pre-slot", "Slot · full-slot"],
                visual_source=None, audio_track=audio,
                output_path=ktv, ass_root=args.deliver / "_ktv_ass" / slug,
                font="Noto Sans CJK SC", layout="two", profile="final", force=True)
        except Exception as e:  # noqa: BLE001
            print(f"{song}: KTV FAIL {e}", flush=True)
        ok = ft.is_file() and ktv.is_file()
        print(f"{song}: {'OK' if ok else 'PARTIAL'} (exit={r.returncode})", flush=True)
        if ok:
            done.append(song)
        else:
            failed.append(song)
    print(json.dumps({"RENDER_DONE": len(done), "failed": failed, "total": len(songs)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
