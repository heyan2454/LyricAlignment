#!/usr/bin/env python3
"""Render the A-group v2 comparison: FOUR lanes, all self-propagating.

  images/A_v2_<song>.png            4-lane full-song timeline
  videos/A_v2_<song>.mp4            4-lane timeline video
  videos/A_v2_KTV_<song>.mp4        4-panel KTV subtitle comparison

Lanes: B4 历史pre-slot串行 | Full-slot fix60 串行 | Full-slot soft 串行 | Full-slot strict 串行
All full-slot lanes come from run_independent_60s.py (self-propagating, no B4 reuse).
textmode3 is REMOVED (2026-08-16 decision).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_agroup_v2.py \
      --deliver <dir> [--page-seconds 12]
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
sys.path.insert(0, str(REPO / "scripts" / "demo"))
sys.path.insert(0, str(REPO / "scripts" / "realign_recovery" / "visualization"))

from batch_ktv_compare import LANG_LOOKUP, resolve_b4, slug_to_song  # noqa: E402

V2_ROOT = "/home/hyan/Data/lyricalign/runs/20260816_agroup_v2_legal"
TEST = "/home/hyan/Data/lyricalign/test"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"


def resolve_vocal(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        p = Path(base) / lang / f"{song}_qwen_fa/work/audio/vocals.wav"
        if p.is_file():
            return p
    return None


def resolve_audio(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        for sub in ("mix.wav", "vocals.wav"):
            p = Path(base) / lang / f"{song}_qwen_fa/work/audio/{sub}"
            if p.is_file():
                return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--page-seconds", type=float, default=12.0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    args = ap.parse_args()

    images = args.deliver / "images"
    videos = args.deliver / "videos"
    images.mkdir(parents=True, exist_ok=True)
    videos.mkdir(parents=True, exist_ok=True)
    render_script = REPO / "scripts/realign_recovery/visualization/render_full_song.py"
    from lyricalign.demo.media_render import render_alignment_comparison  # noqa: E402

    songs = [p.name for p in Path(V2_ROOT).joinpath("fix60").iterdir() if p.is_dir()]
    songs.sort()
    if args.end:
        songs = songs[args.start:args.end]
    else:
        songs = songs[args.start:]

    for song in songs:
        lang = LANG_LOOKUP.get(song)
        if lang is None:
            continue
        b4 = resolve_b4(song)
        f60 = Path(V2_ROOT) / "fix60" / song / "alignments/r2/vocal/windowed/alignment.json"
        soft = Path(V2_ROOT) / "soft" / song / "alignments/r2/vocal/windowed/alignment.json"
        strict = Path(V2_ROOT) / "strict" / song / "alignments/r2/vocal/windowed/alignment.json"
        audio = resolve_audio(song, lang)
        if not (b4 and f60.is_file() and soft.is_file() and strict.is_file() and audio):
            print(f"{song}: missing lanes (b4={bool(b4)} f60={f60.is_file()} "
                  f"soft={soft.is_file()} strict={strict.is_file()} audio={bool(audio)})", flush=True)
            continue
        # timeline: 4 lanes, official only (raw lanes removed per user 2026-08-16;
        # timeline VIDEO removed — only the static PNG is kept, plus KTV).
        out = args.deliver / "_tmp" / song
        if out.exists():
            shutil.rmtree(out)
        lanes = [
            ("B4 历史pre-slot串行", str(b4)),
            ("Full-slot fix60 串行", str(f60)),
            ("Full-slot soft 串行", str(soft)),
            ("Full-slot strict 串行", str(strict)),
        ]
        cmd = [sys.executable, str(render_script),
               "--item", f"{lang}/{song}.mp3", "--audio", str(audio),
               "--out", str(out), "--page-seconds", str(args.page_seconds),
               "--no-global-windows"]
        for label, path in lanes:
            cmd += ["--baseline-align", f"{label}={path},selected"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        ft = out / "visuals/current_full_song/full_timeline.png"
        slug = song.replace(" ", "_")
        if ft.is_file():
            shutil.copyfile(ft, images / f"A_v2_{slug}.png")
        # KTV 4 panels (official = selected geometry, final legalized output)
        ktv = videos / f"A_v2_KTV_{slug}.mp4"
        try:
            render_alignment_comparison(
                alignment_paths=[b4, f60, soft, strict],
                labels=["B4 · pre-slot", "fix60 · 串行", "soft · 串行", "strict · 串行"],
                visual_source=None, audio_track=audio,
                output_path=ktv, ass_root=args.deliver / "_ktv_ass" / slug,
                font="Noto Sans CJK SC", layout="four", profile="final", force=True)
        except Exception as e:  # noqa: BLE001
            print(f"{song}: KTV FAIL {e}", flush=True)
        ok = ft.is_file() and ktv.is_file()
        print(f"{song}: {'OK' if ok else 'PARTIAL'} (exit={r.returncode})", flush=True)
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
