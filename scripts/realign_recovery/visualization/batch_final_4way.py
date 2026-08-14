#!/usr/bin/env python3
"""FINAL viz: V1 (B4 vs Current) and V2 (Current + R-U + R-S + R-CF), flat output.

- V1: B4 vs Current (vocal, same checkpoint seed20260724 step-000750).
- V2: Current + R-U + R-S (test-demo evidence) + R-CF (demo coarse_fine evidence).
- Flat: images/ and videos/ one folder each (no B4/Mech subfolders).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_final_4way.py \
     --deliver <dir> [--page-seconds 15]
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
RCF = "/home/hyan/Data/lyricalign/runs/20260814_rcf_demo/E4_demo_rcf/forward/evidence"

SONGS = [
    ("乙女解剖", "Japanese", "Japanese/乙女解剖.mp3"),
    ("浮夸", "Cantonese", "Cantonese/浮夸.mp3"),
    ("Past Lives", "English", "English/Past Lives.mp3"),
    ("此处通往天空", "Chinese", "Chinese/此处通往天空.mp3"),
    ("人造卫星", "Chinese", "Chinese/人造卫星.mp3"),
]


def _run(cmd, timeout=1200):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    images = args.deliver / "images"
    videos = args.deliver / "videos"
    images.mkdir(parents=True, exist_ok=True)
    videos.mkdir(parents=True, exist_ok=True)

    script = REPO / "scripts" / "realign_recovery" / "visualization" / "render_full_song.py"
    tmp = args.deliver / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    for name, lang, item in SONGS:
        cur = f"{PREP}/{lang}/{name}_qwen_fa/alignments/r2/vocal/windowed/alignment.json"
        b4 = f"{B4R}/{name}/alignments/r2/vocal/windowed/alignment.json"
        audio = f"{PREP}/{lang}/{name}_qwen_fa/work/audio/vocals.wav"
        key = name.replace(" ", "_")
        # V1
        v1 = tmp / key / "V1"
        _run([sys.executable, str(script),
              "--baseline-align", f"B4 历史pre-slot串行={b4}",
              "--baseline-align", f"Current={cur}",
              "--item", item, "--audio", audio, "--out", str(v1),
              "--page-seconds", str(args.page_seconds)])
        ft1 = v1 / "visuals/current_full_song/full_timeline.png"
        mp1 = v1 / "renders/current_full_song.mp4"
        if ft1.is_file():
            (images / f"B4_vs_Current_{key}.png").write_bytes(ft1.read_bytes())
        if mp1.is_file():
            (videos / f"B4_vs_Current_{key}.mp4").write_bytes(mp1.read_bytes())
        # V2 (4-way with R-CF)
        v2 = tmp / key / "V2"
        r = _run([sys.executable, str(script),
                  "--baseline-align", f"Current={cur}",
                  "--forward-root", f"{TEST_DEMO}/forward",
                  "--plan", f"{TEST_DEMO}/TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl",
                  "--rcf-evidence-root", RCF,
                  "--item", item, "--audio", audio, "--out", str(v2),
                  "--page-seconds", str(args.page_seconds)])
        ft2 = v2 / "visuals/current_full_song/full_timeline.png"
        mp2 = v2 / "renders/current_full_song.mp4"
        lanes = "?"
        mf = v2 / "render_manifest.json"
        if mf.is_file():
            m = json.loads(mf.read_text(encoding="utf-8"))
            lanes = [t["label"] for t in m["visual_groups"][0]["pages"][0]["track_geometry"]]
        if ft2.is_file():
            (images / f"Current_RU_RS_RCF_{key}.png").write_bytes(ft2.read_bytes())
        if mp2.is_file():
            (videos / f"Current_RU_RS_RCF_{key}.mp4").write_bytes(mp2.read_bytes())
        print(f"{name}: V1 ft={ft1.is_file()} mb={mp1.is_file()} | V2 lanes={lanes} rc={r.returncode} ft={ft2.is_file()}", flush=True)
    print("ALLDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
