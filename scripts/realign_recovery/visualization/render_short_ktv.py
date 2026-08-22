#!/usr/bin/env python3
"""4-panel KTV-subtitle comparison for the short-window experiment.

Panels: B4 历史串行 | C1 60s独立 | Short 短窗独立 | Short 串行
One encode, black background + rolling karaoke subtitle per panel, shared
mix audio (vocal fallback), layout="four".

Output: <deliver>/videos/KTV_short_<song>.mp4

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/render_short_ktv.py \
      --deliver <dir> [--profile final]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "demo"))

from lyricalign.demo.media_render import render_alignment_comparison  # noqa: E402

SONGS = ["祈愿花开", "人造卫星", "本草纲目"]
B4_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4/align"
C1_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/serial3"
SHORT_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/shortcluster_p05_v3"
SHORT_SER_ROOT = "/home/hyan/Data/lyricalign/runs/20260815_slot_v2/shortcluster_serial"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST = "/home/hyan/Data/lyricalign/test"


def resolve_audio(song: str) -> Path | None:
    for base in (PREP, TEST):
        for sub in ("mix.wav", "vocals.wav"):
            p = Path(base) / "Chinese" / f"{song}_qwen_fa/work/audio/{sub}"
            if p.is_file():
                return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--profile", choices=("review", "final"), default="final")
    args = ap.parse_args()

    videos = args.deliver / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    ass_root = args.deliver / "_ktv_ass"
    for song in SONGS:
        b4 = Path(B4_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        c1 = Path(C1_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        short = Path(SHORT_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        short_ser = Path(SHORT_SER_ROOT) / song / "alignments/r2/vocal/windowed/alignment.json"
        audio = resolve_audio(song)
        if not all(p.is_file() for p in (b4, c1, short, short_ser)) or audio is None:
            print(f"{song}: missing inputs", flush=True)
            continue
        out = videos / f"KTV_short_{song}.mp4"
        try:
            meta = render_alignment_comparison(
                alignment_paths=[b4, c1, short, short_ser],
                labels=["B4 · pre-slot", "C1 · 60s独立", "Short · 短窗独立", "Short · 串行"],
                visual_source=None,
                audio_track=audio,
                output_path=out,
                ass_root=ass_root / song,
                font="Noto Sans CJK SC",
                layout="four",
                profile=args.profile,
            )
            print(f"ok {song} -> {out}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {song}: {e}", flush=True)
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
