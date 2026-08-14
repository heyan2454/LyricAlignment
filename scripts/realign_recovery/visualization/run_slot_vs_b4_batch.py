#!/usr/bin/env python3
"""Batch: build full-slot (silence-aware Base, official) manifests for the
non-Japanese test-demo songs and run them with the real executor.

Skips Japanese songs (nagisa tokenisation is unstable under the RealAligner
join-parse; same limitation as the past realign_gate test-demo runs).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_slot_vs_b4_batch.py \
      --out-root /home/hyan/Data/lyricalign/runs/20260815_slot_vs_b4 \
      --model-dir <snap> --revision <rev> --checkpoint-path <ckpt> [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

TEST = "/home/hyan/Data/lyricalign/test"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
B4_CORE = "/home/hyan/Data/lyricalign/runs/20260814_viz_B4"
B4_NONCORE = "/home/hyan/Data/lyricalign/runs/20260814_b4review"
B4_KTV = "/home/hyan/Data/lyricalign/runs/20260814_ktv_B4"

# all 33 test-demo songs (incl. Japanese — Plan A direct-infer_slice is
# tokenization-stable for word-level nagisa units).
SONGS = [
    ("本草纲目", "Chinese"), ("安全词", "Chinese"), ("六重不忠", "Chinese"),
    ("四季折之羽", "Chinese"), ("若梦境来袭", "Chinese"), ("TH讠NK", "Chinese"),
    ("祈愿花开", "Chinese"), ("为何入眠", "Chinese"), ("伊卡洛斯奔向月亮", "Chinese"),
    ("何时何地", "Chinese"), ("权御天下", "Chinese"), ("梦良衣", "Chinese"),
    ("画下灯塔水母", "Chinese"), ("画下灯塔水母 - 副本", "Chinese"),
    ("此处通往天空", "Chinese"), ("人造卫星", "Chinese"),
    ("Past Lives", "English"), ("Camelia", "English"), ("I See Fire", "English"),
    ("Immortals", "English"), ("Renegade", "English"), ("Take Me To Church", "English"),
    ("月半小夜曲", "Cantonese"), ("浮夸", "Cantonese"), ("电灯胆", "Cantonese"),
    ("红日", "Cantonese"), ("难念的经", "Cantonese"),
    ("乙女解剖", "Japanese"), ("冬之花", "Japanese"), ("p.h", "Japanese"),
    ("炉心融解", "Japanese"), ("初音未来的消失", "Japanese"), ("皱鳃鲨", "Japanese"),
]


def resolve_b4(song: str) -> Path | None:
    for root in (B4_NONCORE, B4_CORE, B4_KTV):
        for cand in (Path(root) / song / "alignments/r2/vocal/windowed/alignment.json",
                     Path(root) / song.replace(" ", "_") / "alignments/r2/vocal/windowed/alignment.json"):
            if cand.is_file():
                return cand
    return None


def resolve_vocals(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        p = Path(base) / lang / f"{song}_qwen_fa/work/audio/vocals.wav"
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--checkpoint-path", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    songs = SONGS[args.start: args.end if args.end else len(SONGS)]
    build = REPO / "scripts/realign_recovery/visualization/build_testdemo_slot_manifest.py"
    run = REPO / "scripts/realign_recovery/visualization/run_testdemo_slot_infer.py"
    done, failed = [], []
    for song, lang in songs:
        b4 = resolve_b4(song)
        voc = resolve_vocals(song, lang)
        if not (b4 and voc):
            print(f"SKIP {song}: b4={bool(b4)} voc={bool(voc)}", flush=True)
            failed.append(song)
            continue
        out_align = args.out_root / "align" / song / "alignments/r2/vocal/windowed/alignment.json"
        if out_align.is_file():
            print(f"{song}: exists, skip", flush=True)
            done.append(song)
            continue
        manifest = args.out_root / f"manifest_{song.replace(' ','_')}.jsonl"
        rb = subprocess.run(
            [sys.executable, str(build), "--songs", f"{song}={lang}={b4}={voc}",
             "--out", str(manifest)],
            capture_output=True, text=True, timeout=600)
        n_ok = sum(1 for line in rb.stdout.splitlines() if "ok)" in line or "ok]" in line)
        rr = subprocess.run(
            [sys.executable, str(run), "--manifest", str(manifest),
             "--out-root", str(args.out_root / "align"),
             "--model-dir", args.model_dir, "--revision", args.revision,
             "--checkpoint-path", args.checkpoint_path,
             *(["--limit", str(args.limit)] if args.limit else [])],
            capture_output=True, text=True, timeout=3600)
        ok = out_align.is_file()
        print(f"{song}: {'OK' if ok else 'FAIL'} (manifest_exit={rb.returncode} run_exit={rr.returncode})", flush=True)
        if ok:
            done.append(song)
        else:
            failed.append(song)
            tail = (rr.stderr or rr.stdout or "").strip().splitlines()[-3:]
            for line in tail:
                print(f"    [log] {line}", flush=True)
    print(json.dumps({"SLOT_BATCH_DONE": len(done), "failed": failed, "total": len(songs)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
