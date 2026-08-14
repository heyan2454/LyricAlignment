#!/usr/bin/env python3
"""Final rerender of V1 (B4 vs Current) and V2 (Current + R-U + R-S) across songs
using the CORRECTED Current full-slot alignment (same language tokenizer + same
R2 checkpoint seed20260724/step-000750 as B4).  Caller must have run Current via
``run_qwen_fa_batch --individual r2:vocal:windowed --language <L> --r2-run ...``
so that B4/Current unit sequences are identical (per-unit comparable).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_final_v1v2.py \
     --v1-out <dir> --v2-out <dir>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
B4R = "/home/hyan/Data/lyricalign/runs/20260814_viz_B4"
TEST_DEMO = "/home/hyan/Data/lyricalign/runs/unit_realign_test_demo_formal_20260813/04_test_demo"

SONGS = [
    ("乙女解剖", "Japanese", "Japanese/乙女解剖.mp3"),
    ("浮夸", "Cantonese", "Cantonese/浮夸.mp3"),
    ("Past Lives", "English", "English/Past Lives.mp3"),
    ("此处通往天空", "Chinese", "Chinese/此处通往天空.mp3"),
    ("人造卫星", "Chinese", "Chinese/人造卫星.mp3"),
]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _lanes(out: Path):
    mf = out / "render_manifest.json"
    if mf.is_file():
        m = json.loads(mf.read_text(encoding="utf-8"))
        return [t["label"] for t in m["visual_groups"][0]["pages"][0]["track_geometry"]]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1-out", required=True, type=Path)
    ap.add_argument("--v2-out", required=True, type=Path)
    ap.add_argument("--clean-pages", action="store_true", default=True)
    args = ap.parse_args()

    script = REPO / "scripts" / "realign_recovery" / "visualization" / "render_full_song.py"
    for name, lang, item in SONGS:
        cur = f"{PREP}/{lang}/{name}_qwen_fa/alignments/r2/vocal/windowed/alignment.json"
        b4 = f"{B4R}/{name}/alignments/r2/vocal/windowed/alignment.json"
        audio = f"{PREP}/{lang}/{name}_qwen_fa/work/audio/vocals.wav"
        key = name.replace(" ", "_")
        # V1
        v1 = args.v1_out / key
        r = _run([
            sys.executable, str(script),
            "--baseline-align", f"B4 历史pre-slot串行={b4}",
            "--baseline-align", f"Current 当前(full-slot)={cur}",
            "--item", item, "--audio", audio, "--out", str(v1),
        ])
        # V2
        v2 = args.v2_out / key
        r2 = _run([
            sys.executable, str(script),
            "--baseline-align", f"Current 全曲={cur}",
            "--forward-root", f"{TEST_DEMO}/forward",
            "--plan", f"{TEST_DEMO}/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl",
            "--item", item, "--audio", audio, "--out", str(v2),
        ])
        if args.clean_pages:
            for base in (v1, v2):
                for p in base.glob("visuals/current_full_song/page_*.png"):
                    p.unlink()
        print(f"{name}: V1 lanes={_lanes(v1)} rc={r.returncode} | V2 lanes={_lanes(v2)} rc={r2.returncode}", flush=True)
    print("ALLDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
