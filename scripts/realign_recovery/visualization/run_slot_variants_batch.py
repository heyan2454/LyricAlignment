#!/usr/bin/env python3
"""Batch: build + run the strict/compress 2x2 variant group (C2 strict-only,
C3 compress-only, C4 strict+compress) for all 33 test-demo songs, Plan A
(direct infer_slice) style.

Each variant: build_testdemo_slot_variant_manifest.py -> run_testdemo_slot_infer.py.
Compressed variants write compressed audio + mapping into <out-root>/audio and
the runner remaps outputs back to the original clock.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_slot_variants_batch.py \
      --out-root /home/hyan/Data/lyricalign/runs/20260815_slot_v2 \
      --model-dir <snap> --revision <rev> --checkpoint-path <ckpt> [--variants strict,compress,strict_compress]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

TEST = "/home/hyan/Data/lyricalign/test"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
B4_CORE = "/home/hyan/Data/lyricalign/runs/20260814_viz_B4"
B4_NONCORE = "/home/hyan/Data/lyricalign/runs/20260814_b4review"
B4_KTV = "/home/hyan/Data/lyricalign/runs/20260814_ktv_B4"

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
    ap.add_argument("--variants", default="strict,compress,strict_compress")
    ap.add_argument("--max-units", type=int, default=150)
    ap.add_argument("--skip-built", action="store_true",
                    help="skip songs whose alignment.json already exists")
    args = ap.parse_args()

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    build = REPO / "scripts/realign_recovery/visualization/build_testdemo_slot_variant_manifest.py"
    run = REPO / "scripts/realign_recovery/visualization/run_testdemo_slot_infer.py"
    (args.out_root / "audio").mkdir(parents=True, exist_ok=True)

    for variant in variants:
        specs = []
        missing = []
        for song, lang in SONGS:
            b4 = resolve_b4(song)
            voc = resolve_vocals(song, lang)
            if b4 is None or voc is None:
                missing.append(f"{song}(b4={b4 is not None},voc={voc is not None})")
                continue
            specs.append(f"{song}={lang}={b4}={voc}")
        if missing:
            print(f"[{variant}] WARN missing: {missing}", flush=True)
        manifest = args.out_root / f"manifest_{variant}.jsonl"
        # strict-family windows are large (whole active regions) so the model
        # input cap is relaxed; compress keeps the conservative cap (60s soft
        # windows are small enough)
        cap = 250 if variant in ("strict", "strict_compress") else args.max_units
        cmd = [sys.executable, str(build), "--variant", variant,
               "--audio-out", str(args.out_root / "audio"),
               "--out", str(manifest), "--max-units", str(cap)]
        for s in specs:
            cmd += ["--songs", s]
        subprocess.run(cmd, check=True)
        n_ok = sum(1 for l in manifest.read_text(encoding="utf-8").splitlines()
                   if l.strip() and json.loads(l).get("status", "").startswith("ok"))
        print(f"[{variant}] manifest rows ok-ish: {n_ok}", flush=True)
        if not n_ok:
            print(f"[{variant}] nothing to run, skip", flush=True)
            continue
        subprocess.run([
            sys.executable, str(run), "--manifest", str(manifest),
            "--out-root", str(args.out_root / "align" / variant),
            "--model-dir", args.model_dir, "--revision", args.revision,
            "--checkpoint-path", args.checkpoint_path,
        ], check=True)
        print(f"[{variant}] done", flush=True)
    print("ALL VARIANTS DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
