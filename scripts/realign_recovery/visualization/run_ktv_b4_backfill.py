#!/usr/bin/env python3
"""Backfill B4 pre-slot serial alignments for the other non-core test songs,
then render KTV B4-vs-Current dual-panel videos for all test-demo songs.

Only the 25 non-core songs that lack a B4 alignment on disk are re-alignmed
(serialised, one at a time, same R2 checkpoint as the existing B4 for fairness),
persisting to ``runs/20260814_ktv_B4/<song>/``.  Then the KTV renderer
(``batch_ktv_compare``) is run, which skips the 8 already-rendered and renders
the newly available songs.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_ktv_b4_backfill.py \
      --deliver /home/hyan/Data/lyricalign/runs/20260814_viz_DELIVER [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

SNAP = "/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064"
CKPT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
R1 = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r1_pilot_seed20260724/checkpoints/step-000100"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST = "/home/hyan/Data/lyricalign/test"
B4_ROOT = "/home/hyan/Data/lyricalign/runs/20260814_ktv_B4"

# songs lacking B4 (from earlier manifest)
MISSING = [
    "Camelia", "I See Fire", "Immortals", "Renegade", "TH讠NK", "Take Me To Church",
    "p.h", "为何入眠", "伊卡洛斯奔向月亮", "何时何地", "六重不忠", "初音未来的消失",
    "四季折之羽", "安全词", "本草纲目", "权御天下", "梦良衣", "炉心融解", "电灯胆",
    "画下灯塔水母", "画下灯塔水母 - 副本", "皱鳃鲨", "红日", "若梦境来袭", "难念的经",
]
LANG = {
    "Camelia": "English", "I See Fire": "English", "Immortals": "English",
    "Renegade": "English", "Take Me To Church": "English",
    "TH讠NK": "Chinese", "为何入眠": "Chinese", "伊卡洛斯奔向月亮": "Chinese",
    "何时何地": "Chinese", "六重不忠": "Chinese", "四季折之羽": "Chinese",
    "安全词": "Chinese", "本草纲目": "Chinese", "权御天下": "Chinese",
    "梦良衣": "Chinese", "画下灯塔水母": "Chinese", "画下灯塔水母 - 副本": "Chinese",
    "若梦境来袭": "Chinese", "祈愿花开": "Chinese",
    "p.h": "Japanese", "初音未来的消失": "Japanese", "炉心融解": "Japanese",
    "冬之花": "Japanese", "皱鳃鲨": "Japanese",
    "电灯胆": "Cantonese", "红日": "Cantonese", "难念的经": "Cantonese",
    "月半小夜曲": "Cantonese",
}


def _run(c, t=3600):
    return subprocess.run(c, capture_output=True, text=True, timeout=t)


def resolve_inputs(song: str, lang: str) -> tuple[str, str, str] | None:
    def first(cands):
        return next((p for p in cands if os.path.exists(p)), None)
    t = first([f"{PREP}/{lang}/{song}.txt", f"{TEST}/{lang}/{song}.txt"])
    m = first([f"{PREP}/{lang}/{song}_qwen_fa/work/audio/mix.wav",
               f"{TEST}/{lang}/{song}_qwen_fa/work/audio/mix.wav"])
    v = first([f"{PREP}/{lang}/{song}_qwen_fa/work/audio/vocals.wav",
               f"{TEST}/{lang}/{song}_qwen_fa/work/audio/vocals.wav"])
    if t and m and v:
        return (t, m, v)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--render", action="store_true", default=False,
                    help="after backfill, run batch_ktv_compare to render KTV videos")
    args = ap.parse_args()

    songs = MISSING[args.start:args.end if args.end else len(MISSING)]
    serial = Path(REPO) / "scripts/demo/align_qwen_fa_serial_demo.py"
    os.makedirs(B4_ROOT, exist_ok=True)

    backfill = []
    for song in songs:
        lang = LANG.get(song)
        if lang is None:
            print(f"SKIP {song}: no lang", flush=True); continue
        inp = resolve_inputs(song, lang)
        if inp is None:
            print(f"SKIP {song}: incomplete inputs", flush=True); continue
        t, m, v = inp
        b4 = f"{B4_ROOT}/{song}/alignments/r2/vocal/windowed/alignment.json"
        if os.path.exists(b4):
            print(f"{song}: B4 exists, skip", flush=True)
        else:
            print(f"{song}: B4 serial (lang={lang})...", flush=True)
            r = _run([sys.executable, str(serial),
                      "--lyrics", t, "--mix-audio", m, "--vocal-audio", v,
                      "--out-root", f"{B4_ROOT}/{song}", "--model", SNAP,
                      "--revision", "c07281df",
                      "--r1-checkpoint", R1, "--r2-checkpoint", CKPT,
                      "--decoder-kind", "official", "--core-sec", "60",
                      "--left-context-sec", "10", "--right-context-sec", "10",
                      "--silence-aware-window-plan", "--skip-silent-windows",
                      "--language", lang, "--force"])
            print(f"  {song}: exit={r.returncode} ok={os.path.exists(b4)}", flush=True)
            if r.stderr:
                tail = r.stderr.strip().splitlines()[-3:]
                for line in tail:
                    print(f"  [stderr] {line}", flush=True)
        if os.path.exists(b4):
            backfill.append(song)

    (Path(B4_ROOT) / "backfill_manifest.json").write_text(
        json.dumps({"ok": backfill, "attempted": len(songs)}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({"B4_BACKFILL_DONE": len(backfill), "of": len(songs)}, ensure_ascii=False))

    if args.render:
        ktv = Path(REPO) / "scripts/realign_recovery/visualization/batch_ktv_compare.py"
        r = _run([sys.executable, str(ktv), "--deliver", str(args.deliver), "--profile", "final"])
        print(r.stdout[-2000:], flush=True)
        if r.returncode != 0:
            print(r.stderr[-1000:], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
