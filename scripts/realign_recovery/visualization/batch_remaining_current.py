#!/usr/bin/env python3
"""Render Current full-song for the remaining test songs that lack a windowed
alignment.  For each song: prepare a work copy under PREP, run
run_qwen_fa_batch --individual r2:vocal:windowed (reuses separated vocal from the
original *_qwen_fa), then render Current full-song timeline + MP4 to the flat
deliver images/ and videos/.  Strictly serial, one at a time (bounds CPU/GPU).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_remaining_current.py \
      --deliver <dir> [RESUME_INDEX]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TEST = "/home/hyan/Data/lyricalign/test"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
CKPT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
R2RUN = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724"

# song stem -> language
REMAINING = [
    ("Side by Side", "Chinese"), ("TH讠NK", "Chinese"), ("为何入眠", "Chinese"),
    ("何时何地", "Chinese"), ("权御天下", "Chinese"), ("梦良衣", "Chinese"),
    ("画下灯塔水母", "Chinese"), ("画下灯塔水母 - 副本", "Chinese"), ("若梦境来袭", "Chinese"),
    ("I See Fire", "English"), ("Immortals", "English"), ("Renegade", "English"),
    ("p.h", "Japanese"), ("初音未来的消失", "Japanese"), ("皱鳃鲨", "Japanese"),
    ("月半小夜曲", "Cantonese"), ("红日", "Cantonese"), ("难念的经", "Cantonese"),
]


def _run(c, t=1800):
    return subprocess.run(c, capture_output=True, text=True, timeout=t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--start", type=int, default=0, help="resume from this index")
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    songs = REMAINING[args.start: args.end if args.end else len(REMAINING)]
    images = args.deliver / "images"; videos = args.deliver / "videos"
    images.mkdir(parents=True, exist_ok=True); videos.mkdir(parents=True, exist_ok=True)
    script = REPO / "scripts" / "realign_recovery" / "visualization" / "render_full_song.py"
    tmp = args.deliver / "_tmp_current" / "work"; tmp.mkdir(parents=True, exist_ok=True)

    for name, lang in songs:
        d = f"{PREP}/{lang}"
        Path(d).mkdir(parents=True, exist_ok=True)
        src = f"{TEST}/{lang}/{name}"
        # ensure work copy has mp3+txt
        for ext in ("mp3", "txt"):
            sp = f"{src}.{ext}"; dp = f"{d}/{name}.{ext}"
            if os.path.exists(sp) and not os.path.exists(dp):
                shutil.copy(sp, dp)
        # ensure the _qwen_fa work copy exists with separated vocals
        dq = f"{d}/{name}_qwen_fa"
        sq = f"{src}_qwen_fa"
        if not os.path.isdir(os.path.join(dq, "work")):
            shutil.rmtree(dq, ignore_errors=True)
            shutil.copytree(sq, dq, dirs_exist_ok=True)
        align = f"{dq}/alignments/r2/vocal/windowed/alignment.json"
        ok = os.path.exists(align)
        if not ok:
            print(f"{name}: running Current(vocal) align", flush=True)
            r = _run([sys.executable, f"{REPO}/scripts/demo/run_qwen_fa_batch.py",
                      "--individual", "r2:vocal:windowed", "--stage", "align",
                      "--language", lang, "--r2-run", R2RUN, "--r2-checkpoint", CKPT,
                      d])
            ok = os.path.exists(align)
            print(f"  align exit={r.returncode} ok={ok}", flush=True)
        if not ok:
            print(f"{name}: SKIP (no alignment produced)", flush=True)
            continue
        audio = f"{dq}/work/audio/mix.wav"
        if not os.path.exists(audio):
            audio = f"{dq}/work/audio/vocals.wav"
        out = tmp / name.replace(" ", "_").replace("/", "_")
        _run([sys.executable, str(script),
              "--baseline-align", f"Current={align}",
              "--item", f"{lang}/{name}.mp3", "--audio", audio,
              "--out", str(out), "--page-seconds", str(args.page_seconds)])
        ft = out / "visuals/current_full_song/full_timeline.png"
        mp = out / "renders/current_full_song.mp4"
        key = name.replace(" ", "_").replace("/", "_")
        if ft.is_file():
            (images / f"Current_{key}.png").write_bytes(ft.read_bytes())
        if mp.is_file():
            (videos / f"Current_{key}.mp4").write_bytes(mp.read_bytes())
        print(f"{name}: {'OK' if ft.is_file() and mp.is_file() else 'FAIL'}", flush=True)
    print("BATCH_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
