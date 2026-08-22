#!/usr/bin/env python3
"""Run the A-group v2 baselines: full-slot serial with three window plans
(soft / strict / fix60), all SELF-PROPAGATING (no B4 window reuse), on all 33
test-demo songs.  Also rerun the B4 lane source if needed.

Output:
  <out-root>/soft/<song>/alignments/...
  <out-root>/strict/<song>/alignments/...
  <out-root>/fix60/<song>/alignments/...

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/run_agroup_v2_batch.py \
      --out-root <dir> --model-dir <snap> --revision <rev> --checkpoint-path <ckpt> \
      [--plans soft,strict,fix60] [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

TEST = "/home/hyan/Data/lyricalign/test"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"

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


def resolve_vocals(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        p = Path(base) / lang / f"{song}_qwen_fa/work/audio/vocals.wav"
        if p.is_file():
            return p
    return None


def resolve_lyrics(song: str, lang: str) -> Path | None:
    for base in (PREP, TEST):
        p = Path(base) / lang / f"{song}.txt"
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--checkpoint-path", required=True)
    ap.add_argument("--plans", default="soft,strict,fix60")
    ap.add_argument("--propagate-raw", action="store_true",
                    help="pass --propagate-raw to the runner (serial commit uses "
                         "RAW timestamps; output stays official)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    args = ap.parse_args()

    plans = [p for p in args.plans.split(",") if p]
    songs = SONGS[args.start: args.end if args.end else len(SONGS)]
    runner = REPO / "scripts/realign_recovery/visualization/run_independent_60s.py"
    done, failed = [], []
    for song, lang in songs:
        voc = resolve_vocals(song, lang)
        lyr = resolve_lyrics(song, lang)
        if not (voc and lyr):
            print(f"SKIP {song}: voc={bool(voc)} lyr={bool(lyr)}", flush=True)
            failed.append(song)
            continue
        song_ok = True
        for plan in plans:
            out_align = args.out_root / plan / song / "alignments/r2/vocal/windowed/alignment.json"
            if out_align.is_file():
                print(f"{song} {plan}: exists, skip", flush=True)
                continue
            r = subprocess.run(
                [sys.executable, str(runner),
                 "--song", f"{song}={lang}={lyr}={voc}",
                 "--out-root", str(args.out_root / plan),
                 "--window-plan", plan,
                 *(["--propagate-raw"] if args.propagate_raw else []),
                 "--model-dir", args.model_dir, "--revision", args.revision,
                 "--checkpoint-path", args.checkpoint_path],
                capture_output=True, text=True, timeout=3600)
            ok = out_align.is_file()
            if not ok:
                song_ok = False
                tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
                for line in tail:
                    print(f"    [log] {line}", flush=True)
            print(f"{song} {plan}: {'OK' if ok else 'FAIL'}", flush=True)
        if song_ok:
            done.append(song)
        else:
            failed.append(song)
    print(json.dumps({"AGROUP_V2_DONE": len(done), "failed": failed,
                      "total": len(songs), "plans": plans}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
