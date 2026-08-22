#!/usr/bin/env python3
"""Re-render the B4-vs-Current static full-song timeline images (and the
timeline MP4s) using the *fixed* Current alignment (silence-aware + skip-silent,
B4-consistent config) instead of the legacy default-config Current.

The fixed Current lives in ``runs/20260814_ktv_current_silence/<song>/``;
``batch_ktv_compare.resolve_current`` already prefers it.  This script reuses
that resolver, runs ``render_full_song.py`` per song, and flat-delivers
``B4_vs_Current_<song>.png`` / ``B4_vs_Current_<song>.mp4`` into the existing
deliver ``images/`` and ``videos/`` (overwriting the legacy-Current renders).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/rerender_static_b4_current.py \
      --deliver /home/hyan/Data/lyricalign/runs/20260814_viz_DELIVER [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_ktv_module():
    spec = importlib.util.spec_from_file_location(
        "bkc", Path(__file__).resolve().parent / "batch_ktv_compare.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--page-seconds", type=float, default=15.0)
    args = ap.parse_args()

    M = _load_ktv_module()
    videos = args.deliver / "videos"
    images = args.deliver / "images"
    videos.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)

    slugs = sorted(
        p.stem[len("B4_vs_Current_"):]
        for p in videos.glob("B4_vs_Current_*.mp4")
        if not p.stem.startswith("B4_vs_Current_KTV_")
    )
    if args.end:
        slugs = slugs[args.start:args.end]
    else:
        slugs = slugs[args.start:]

    script = REPO / "scripts/realign_recovery/visualization/render_full_song.py"
    tmp = args.deliver / "_tmp_static_silence" / "work"
    tmp.mkdir(parents=True, exist_ok=True)

    done, failed = [], []
    for slug in slugs:
        song = M.slug_to_song(slug)
        lang = M.LANG_LOOKUP.get(song)
        if lang is None:
            print(f"SKIP {song}: no lang", flush=True); continue
        cur = M.resolve_current(song, lang)
        b4 = M.resolve_b4(song)
        audio = M.resolve_audio(song, lang)
        if not (cur and b4 and audio):
            print(f"SKIP {song}: cur={bool(cur)} b4={bool(b4)} audio={bool(audio)}", flush=True)
            failed.append(song); continue
        out = tmp / slug
        r = subprocess.run(
            [sys.executable, str(script),
             "--baseline-align", f"B4 历史pre-slot串行={b4}",
             "--baseline-align", f"Current={cur}",
             "--item", f"{lang}/{song}.mp3", "--audio", str(audio),
             "--out", str(out), "--page-seconds", str(args.page_seconds)],
            capture_output=True, text=True, timeout=3600)
        ft = out / "visuals/current_full_song/full_timeline.png"
        mp = out / "renders/current_full_song.mp4"
        if ft.is_file():
            (images / f"B4_vs_Current_{slug}.png").write_bytes(ft.read_bytes())
        if mp.is_file():
            (videos / f"B4_vs_Current_{slug}.mp4").write_bytes(mp.read_bytes())
        ok = ft.is_file() and mp.is_file()
        print(f"{song}: {'OK' if ok else 'FAIL'} (exit={r.returncode})", flush=True)
        if ok:
            done.append(song)
        else:
            failed.append(song)
    print(json.dumps({"STATIC_RERENDER_DONE": len(done), "failed": failed, "total": len(slugs)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
