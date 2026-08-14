#!/usr/bin/env python3
"""Batch-run render_full_song.py V2 (Current全曲 + R-U/R-S mechanism overlay) for 4 demo songs.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_v2_overlay.py \
      --out <run> [--page-seconds 15]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# repo root = LyricAlignment (this file: scripts/realign_recovery/visualization/batch_v2_overlay.py)
REPO = Path(__file__).resolve().parents[3]
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST_DEMO = "/home/hyan/Data/lyricalign/runs/unit_realign_test_demo_formal_20260813/04_test_demo"

SONGS = [
    ("乙女解剖", "Japanese", "Japanese/乙女解剖.mp3"),
    ("浮夸", "Cantonese", "Cantonese/浮夸.mp3"),
    ("Past Lives", "English", "English/Past Lives.mp3"),
    ("此处通往天空", "Chinese", "Chinese/此处通往天空.mp3"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    script = REPO / "scripts" / "realign_recovery" / "visualization" / "render_full_song.py"
    for name, lang, item in SONGS:
        cur = f"{PREP}/{lang}/{name}_qwen_fa/alignments/r2/vocal/windowed/alignment.json"
        audio = f"{PREP}/{lang}/{name}_qwen_fa/work/audio/vocals.wav"
        out = args.out / name.replace(" ", "_")
        cmd = [
            sys.executable, str(script),
            "--baseline-align", f"Current 全曲={cur}",
            "--forward-root", f"{TEST_DEMO}/forward",
            "--plan", f"{TEST_DEMO}/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl",
            "--item", item, "--audio", audio, "--out", str(out),
            "--page-seconds", str(args.page_seconds),
        ]
        print(f"===== {name} V2 overlay =====", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True)
        # parse final line json
        lanes = "?"
        if (out / "render_manifest.json").is_file():
            m = json.loads((out / "render_manifest.json").read_text(encoding="utf-8"))
            p0 = m["visual_groups"][0]["pages"][0]
            lanes = [t["label"] for t in p0["track_geometry"]]
        ft = out / "visuals" / "current_full_song" / "full_timeline.png"
        print(f"  {name}: exit={r.returncode} lanes={lanes} full_timeline={ft.is_file()}", flush=True)
        if r.returncode != 0:
            print("  stderr tail:", r.stderr[-600:], flush=True)
    print("ALLDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
