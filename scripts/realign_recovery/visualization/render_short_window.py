#!/usr/bin/env python3
"""Render the short-window experiment on the 3 Chinese songs:
4 lanes = B4 历史串行 | C1 60s独立 | Short 短窗(时间聚类) | Short 串行.

timeline:  images/short_<song>.png (full song) + videos/short_<song>.mp4
KTV:       videos/KTV_short_<song>.mp4

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_short_window.py \
      --deliver <dir>
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))
sys.path.insert(0, str(REPO / "scripts" / "realign_recovery" / "visualization"))

SONGS = {
    "祈愿花开": "Chinese",
    "人造卫星": "Chinese",
    "本草纲目": "Chinese",
}
B4_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4/align"
C1_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/serial3"
SHORT_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/shortcluster_p05_v3"
SHORT_SER_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/shortcluster_serial"
TEST = "/home/hyan/Data/lyricalign/test"


def resolve_vocal(song: str, lang: str) -> Path | None:
    for base in ("/home/hyan/Data/lyricalign/viz_fullsong_prep", TEST):
        p = Path(base) / lang / f"{song}_qwen_fa/work/audio/vocals.wav"
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--page-seconds", type=float, default=12.0)
    ap.add_argument("--skip-video", action="store_true")
    args = ap.parse_args()

    videos = args.deliver / "videos"
    images = args.deliver / "images"
    videos.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    render_script = REPO / "scripts/realign_recovery/visualization/render_full_song.py"

    for song, lang in SONGS.items():
        b4 = Path(B4_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        c1 = Path(C1_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        short = Path(SHORT_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        short_ser = Path(SHORT_SER_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        audio = resolve_vocal(song, lang)
        if not all(p.is_file() for p in (b4, c1, short, short_ser)) or audio is None:
            print(f"{song}: missing lanes/audio", flush=True)
            continue
        out = args.deliver / "_tmp" / song
        if out.exists():
            shutil.rmtree(out)
        cmd = [
            sys.executable, str(render_script),
            "--baseline-align", f"B4 历史串行={b4}",
            "--baseline-align", f"C1 60s独立={c1}",
            "--baseline-align", f"Short 短窗独立={short}",
            "--baseline-align", f"Short 串行={short_ser}",
            "--item", f"{lang}/{song}.mp3",
            "--audio", str(audio),
            "--out", str(out),
            "--page-seconds", str(args.page_seconds),
            "--no-global-windows",
        ]
        print(f"render {song}...", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            print(f"  FAIL {song}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}", flush=True)
            continue
        # collect artifacts: rename to song-level names
        full_tl = out / "visuals/current_full_song/full_timeline.png"
        if full_tl.is_file():
            dst = images / f"short_{song}.png"
            shutil.copy(full_tl, dst)
            print(f"  -> {dst}", flush=True)
        vid = out / "renders/current_full_song.mp4"
        if vid.is_file():
            dst = videos / f"short_{song}.mp4"
            shutil.copy(vid, dst)
            print(f"  -> {dst}", flush=True)
        # per-page timeline pngs (higher resolution)
        pages = sorted((out / "visuals/current_full_song").glob("page_*.png"))
        if pages:
            pd = images / f"short_{song}_pages"
            pd.mkdir(parents=True, exist_ok=True)
            for p in pages:
                shutil.copy(p, pd / p.name)
            print(f"  -> {pd}/ ({len(pages)} pages)", flush=True)
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
