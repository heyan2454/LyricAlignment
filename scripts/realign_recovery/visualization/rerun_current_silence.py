#!/usr/bin/env python3
"""Re-run Current (full-slot batch) with silence-aware + skip-silent config,
mirroring the B4 mechanism config (same core/ctx/checkpoint + silence flags),
for the test-demo songs.  Outputs go to a fresh dir per song (never overwrites
the existing default-Config Current in viz_fullsong_prep/test).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/rerun_current_silence.py \
      --out-root /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
      [--songs "song:lang" ...] [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SNAP = "/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064"
CKPT = "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
TEST = "/home/hyan/Data/lyricalign/test"
PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"

# All 33 test-demo songs (song:lang) with B4 available.
SONGS = [
    "乙女解剖:Japanese", "浮夸:Cantonese", "Past Lives:English", "此处通往天空:Chinese",
    "人造卫星:Chinese", "月半小夜曲:Cantonese", "祈愿花开:Chinese", "冬之花:Japanese",
    "Camelia:English", "I See Fire:English", "Immortals:English", "Renegade:English",
    "Take Me To Church:English", "p.h:Japanese", "初音未来的消失:Japanese",
    "炉心融解:Japanese", "皱鳃鲨:Japanese", "电灯胆:Cantonese", "红日:Cantonese",
    "难念的经:Cantonese", "TH讠NK:Chinese", "为何入眠:Chinese", "伊卡洛斯奔向月亮:Chinese",
    "何时何地:Chinese", "六重不忠:Chinese", "四季折之羽:Chinese", "安全词:Chinese",
    "本草纲目:Chinese", "权御天下:Chinese", "梦良衣:Chinese", "画下灯塔水母:Chinese",
    "画下灯塔水母 - 副本:Chinese", "若梦境来袭:Chinese",
]


def _run(c, t=3600):
    return subprocess.run(c, capture_output=True, text=True, timeout=t)


def resolve_txt(song: str, lang: str) -> Path | None:
    for base in (TEST, PREP):
        p = Path(base) / lang / f"{song}.txt"
        if p.is_file():
            return p
    return None


def reuse_separation(song: str, lang: str, out_dir: Path) -> None:
    """Pre-populate the new output's work/audio with the existing separation
    artifacts so batch skips demucs (it checks vocals+identity+quality)."""
    work = out_dir / "work" / "audio"
    work.mkdir(parents=True, exist_ok=True)
    for base in (TEST, PREP):
        src = Path(base) / lang / f"{song}_qwen_fa/work/audio"
        if src.is_dir():
            for name in ("vocals.wav", "accompaniment.wav", "vocals.identity.json",
                         "separation_quality.json"):
                f = src / name
                if f.is_file() and not (work / name).exists():
                    try:
                        import shutil
                        shutil.copy2(f, work / name)
                    except OSError:
                        pass
            return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--songs", action="append", default=[])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--no-reuse", action="store_true", help="do not pre-seed separation")
    args = ap.parse_args()

    songs = [tuple(s.split(":")) for s in (args.songs or SONGS)]
    songs = songs[args.start: args.end if args.end else len(songs)]
    batch = REPO / "scripts/demo/run_qwen_fa_batch.py"
    done, failed = [], []
    for song, lang in songs:
        txt = resolve_txt(song, lang)
        if txt is None:
            print(f"SKIP {song}: no txt", flush=True)
            continue
        out = args.out_root / song.replace(" ", "_")
        align = out / "alignments/r2/vocal/windowed/alignment.json"
        if align.is_file():
            print(f"{song}: already exists, skip", flush=True)
            done.append(song)
            continue
        if not args.no_reuse:
            reuse_separation(song, lang, out)
        print(f"{song}: silence-aware Current align...", flush=True)
        r = _run([sys.executable, str(batch), str(txt),
                  "--stage", "align", "--individual", "r2:vocal:windowed",
                  "--language", lang, "--output-dir", str(args.out_root),
                  "--silence-aware-window-plan", "--skip-silent-windows",
                  "--model", SNAP, "--revision", "c07281df",
                  "--r2-checkpoint", CKPT, "--force-align"])
        ok = align.is_file()
        print(f"  {song}: exit={r.returncode} ok={ok}", flush=True)
        if ok:
            done.append(song)
        else:
            failed.append(song)
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-4:]
            for line in tail:
                print(f"    [log] {line}", flush=True)
    print(json_summary(done, failed, len(songs)))
    return 0


def json_summary(done, failed, total):
    import json
    return json.dumps({"CURRENT_SILENCE_DONE": len(done), "failed": failed,
                       "total": total}, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
