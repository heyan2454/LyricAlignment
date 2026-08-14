#!/usr/bin/env python3
"""Render Current full-song timeline (+MP4) for songs that already have an
alignment.json in their *_qwen_fa (no new forward).  Reuses the alignment's own
audio (mix.wav) so nothing needs re-running.  Serial (one at a time) to bound CPU.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_current_fullsong.py \
     --deliver <dir> [--songs "song:lang"]  # default: the known 12 with alignment
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TEST = "/home/hyan/Data/lyricalign/test"

# song stem -> language dir  (tuples)
KNOWN = [
    ("伊卡洛斯奔向月亮", "Chinese"), ("六重不忠", "Chinese"), ("四季折之羽", "Chinese"),
    ("安全词", "Chinese"), ("本草纲目", "Chinese"), ("祈愿花开", "Chinese"),
    ("Camelia", "English"), ("Take Me To Church", "English"),
    ("冬之花", "Japanese"), ("炉心融解", "Japanese"),
    ("乙女解剖", "Cantonese"), ("电灯胆", "Cantonese"),
]


def _run(c):
    return subprocess.run(c, capture_output=True, text=True, timeout=1800)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--songs", default=None, help="comma song:lang (else KNOWN)")
    ap.add_argument("--page-seconds", type=float, default=15.0)
    ap.add_argument("--limit", type=int, default=0, help="max songs (0=all), for resume")
    args = ap.parse_args()

    songs = []
    if args.songs:
        for s in args.songs.split(","):
            nm, _, lg = s.rpartition(":")
            songs.append((nm, lg))
    else:
        songs = [(nm, lg) for nm, lg in KNOWN]
    if args.limit > 0:
        songs = songs[:args.limit]

    images = args.deliver / "images"
    videos = args.deliver / "videos"
    images.mkdir(parents=True, exist_ok=True)
    videos.mkdir(parents=True, exist_ok=True)
    script = REPO / "scripts" / "realign_recovery" / "visualization" / "render_full_song.py"
    tmp = args.deliver / "_tmp_current" / "work"
    tmp.mkdir(parents=True, exist_ok=True)

    done = 0
    for name, lang in songs:
        base = f"{TEST}/{lang}/{name}_qwen_fa"
        align = f"{base}/alignments/r2/vocal/windowed/alignment.json"
        import os
        if not os.path.exists(align):
            alt = f"{base}/alignments/r2/mix/windowed/alignment.json"
            if os.path.exists(alt):
                align = alt
            else:
                print(f"skip {name}: no windowed alignment", flush=True)
                continue
        audio = f"{base}/work/audio/mix.wav"
        if not os.path.exists(audio):
            audio = f"{base}/work/audio/vocals.wav"
        out = tmp / name.replace(" ", "_")
        r = _run([sys.executable, str(script),
                  "--baseline-align", f"Current={align}",
                  "--item", f"{lang}/{name}.mp3", "--audio", audio,
                  "--out", str(out), "--page-seconds", str(args.page_seconds)])
        ft = out / "visuals/current_full_song/full_timeline.png"
        mp = out / "renders/current_full_song.mp4"
        key = name.replace(" ", "_")
        if ft.is_file():
            (images / f"Current_{key}.png").write_bytes(ft.read_bytes())
        if mp.is_file():
            (videos / f"Current_{key}.mp4").write_bytes(mp.read_bytes())
        ok = ft.is_file() and mp.is_file()
        done += 1 if ok else 0
        print(f"{name}: {'OK' if ok else 'FAIL'} rc={r.returncode} ({done} done)", flush=True)
    print(f"ALLDONE done={done}/{len(songs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
