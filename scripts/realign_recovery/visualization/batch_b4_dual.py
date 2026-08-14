#!/usr/bin/env python3
"""Add B4 vs Current dual contrast for the non-core test songs.

For each song (that has a Current full-song alignment but not yet a B4):
 1. run align_qwen_fa_serial_demo (B4 pre-slot serial, same R2 checkpoint).
 2. render B4 vs Current dual contrast into flat images/ and videos/.
Serial, one at a time.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_b4_dual.py \
      --deliver <dir> [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST = "/home/hyan/Data/lyricalign/test"
SNAP = "/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064"
CKPT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
R1 = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r1_pilot_seed20260724/checkpoints/step-000100"
B4WORK = "/home/hyan/Data/lyricalign/runs/20260814_viz_DELIVER/_b4work"

# non-core song stems already having Current full-song in prep, per language
NONCORE = [
    "Side by Side:Chinese", "TH讠NK:Chinese", "为何入眠:Chinese", "何时何地:Chinese",
    "权御天下:Chinese", "梦良衣:Chinese", "画下灯塔水母:Chinese",
    "画下灯塔水母 - 副本:Chinese", "若梦境来袭:Chinese", "伊卡洛斯奔向月亮:Chinese",
    "六重不忠:Chinese", "四季折之羽:Chinese", "安全词:Chinese", "本草纲目:Chinese",
    "祈愿花开:Chinese",
    "Camelia:English", "Take Me To Church:English", "I See Fire:English",
    "Immortals:English", "Renegade:English",
    "p.h:Japanese", "冬之花:Japanese", "炉心融解:Japanese",
    "初音未来的消失:Japanese", "皱鳃鲨:Japanese",
    "月半小夜曲:Cantonese", "电灯胆:Cantonese", "红日:Cantonese", "难念的经:Cantonese",
]


def _run(c, t=1800):
    return subprocess.run(c, capture_output=True, text=True, timeout=t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    songs = [tuple(s.split(":")) for s in NONCORE]
    songs = songs[args.start: args.end if args.end else len(songs)]
    images = args.deliver / "images"; videos = args.deliver / "videos"
    images.mkdir(parents=True, exist_ok=True); videos.mkdir(parents=True, exist_ok=True)
    script = REPO / "scripts" / "realign_recovery" / "visualization" / "render_full_song.py"
    tmp = args.deliver / "_tmp_b4" / "work"; tmp.mkdir(parents=True, exist_ok=True)

    for name, lang in songs:
        cur = f"{PREP}/{lang}/{name}_qwen_fa/alignments/r2/vocal/windowed/alignment.json"
        if not os.path.exists(cur):
            # some songs ship their alignment in the test *_qwen_fa directly
            cur = f"{TEST}/{lang}/{name}_qwen_fa/alignments/r2/vocal/windowed/alignment.json"
        if not os.path.exists(cur):
            print(f"skip {name}: no Current align", flush=True)
            continue
        # B4
        b4root = f"{B4WORK}/{name.replace('/','_')}"
        b4 = f"{b4root}/alignments/r2/vocal/windowed/alignment.json"
        if not os.path.exists(b4):
            print(f"{name}: B4 serial...", flush=True)
            t = f"{TEST}/{lang}/{name}"
            m = f"{t}_qwen_fa/work/audio/mix.wav"
            v = f"{t}_qwen_fa/work/audio/vocals.wav"
            r = _run([sys.executable, f"{REPO}/scripts/demo/align_qwen_fa_serial_demo.py",
                      "--lyrics", f"{t}.txt", "--mix-audio", m, "--vocal-audio", v,
                      "--out-root", b4root, "--model", SNAP, "--revision", "c07281df",
                      "--r1-checkpoint", R1, "--r2-checkpoint", CKPT,
                      "--decoder-kind", "official", "--core-sec", "60",
                      "--left-context-sec", "10", "--right-context-sec", "10",
                      "--silence-aware-window-plan", "--skip-silent-windows",
                      "--language", lang, "--force"])
            print(f"  B4 exit={r.returncode} ok={os.path.exists(b4)}", flush=True)
        if not os.path.exists(b4):
            print(f"{name}: SKIP (no B4)", flush=True)
            continue
        audio = f"{PREP}/{lang}/{name}_qwen_fa/work/audio/mix.wav"
        if not os.path.exists(audio):
            audio = f"{TEST}/{lang}/{name}_qwen_fa/work/audio/mix.wav"
        if not os.path.exists(audio):
            audio = f"{PREP}/{lang}/{name}_qwen_fa/work/audio/vocals.wav"
        if not os.path.exists(audio):
            audio = f"{TEST}/{lang}/{name}_qwen_fa/work/audio/vocals.wav"
        if not os.path.exists(audio):
            print(f"skip {name}: no audio", flush=True)
            continue
        out = tmp / name.replace(" ", "_")
        r = _run([sys.executable, str(script),
                  "--baseline-align", f"B4 历史pre-slot串行={b4}",
                  "--baseline-align", f"Current={cur}",
                  "--item", f"{lang}/{name}.mp3", "--audio", audio,
                  "--out", str(out), "--page-seconds", str(args.page_seconds)])
        ft = out / "visuals/current_full_song/full_timeline.png"
        mp = out / "renders/current_full_song.mp4"
        key = name.replace(" ", "_")
        if ft.is_file():
            (images / f"B4_vs_Current_{key}.png").write_bytes(ft.read_bytes())
        if mp.is_file():
            (videos / f"B4_vs_Current_{key}.mp4").write_bytes(mp.read_bytes())
        print(f"{name}: {'OK' if ft.is_file() and mp.is_file() else 'FAIL'}", flush=True)
    print("B4_DUAL_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
