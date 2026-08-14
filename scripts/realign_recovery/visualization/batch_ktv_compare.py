#!/usr/bin/env python3
"""Batch KTV-subtitle B4 vs Current comparison videos.

For every test-demo song that already has a B4_vs_Current deliverable, render a
**karaoke-subtitle** comparison using the mature ``render_alignment_comparison``:
one encode, left/right panels (B4 | Current), each panel = black background +
two-row KTV rolling subtitle (``build_bottom_ass``) sharing the same mix audio &
global timeline.  ``layout='two'``, black background (no original video).

Output: <deliver>/videos/B4_vs_Current_KTV_<song>.mp4  (joined into existing deliver).

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/batch_ktv_compare.py \
      --deliver /home/hyan/Data/lyricalign/runs/20260814_viz_DELIVER \
      [--profile final] [--start N] [--end N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from lyricalign.demo.media_render import render_alignment_comparison  # noqa: E402

PREP = "/home/hyan/Data/lyricalign/viz_fullsong_prep"
TEST = "/home/hyan/Data/lyricalign/test"
B4_CORE = "/home/hyan/Data/lyricalign/runs/20260814_viz_B4"       # core 5 songs (乙女/浮夸/PastLives/此处/人造)
B4_NONCORE = "/home/hyan/Data/lyricalign/runs/20260814_b4review"   # 月半/祈愿/冬之花 (and any other b4 there)

# slug (deliver filename stem) -> (song original name, language).  slug came from
# name.replace(" ","_"), so inverted by "_"->" " except the known multi-part/odd ones.
SLUG_SONG_OVERRIDES = {
    "I_See_Fire": "I See Fire", "Past_Lives": "Past Lives",
    "Take_Me_To_Church": "Take Me To Church", "TH讠NK": "TH讠NK",
    "画下灯塔水母_-_副本": "画下灯塔水母 - 副本",
    "p.h": "p.h", "Camelia": "Camelia", "Immortals": "Immortals",
    "Renegade": "Renegade",
}
LANG_LOOKUP = {
    "乙女解剖": "Japanese", "浮夸": "Cantonese", "Past Lives": "English",
    "此处通往天空": "Chinese", "人造卫星": "Chinese",
    "Camelia": "English", "Take Me To Church": "English", "I See Fire": "English",
    "Immortals": "English", "Renegade": "English",
    "p.h": "Japanese", "冬之花": "Japanese", "炉心融解": "Japanese",
    "初音未来的消失": "Japanese", "皱鳃鲨": "Japanese",
    "Side by Side": "Chinese", "TH讠NK": "Chinese", "为何入眠": "Chinese",
    "何时何地": "Chinese", "权御天下": "Chinese", "梦良衣": "Chinese",
    "画下灯塔水母": "Chinese", "画下灯塔水母 - 副本": "Chinese",
    "若梦境来袭": "Chinese", "伊卡洛斯奔向月亮": "Chinese", "六重不忠": "Chinese",
    "四季折之羽": "Chinese", "安全词": "Chinese", "本草纲目": "Chinese",
    "祈愿花开": "Chinese",
    "月半小夜曲": "Cantonese", "电灯胆": "Cantonese", "红日": "Cantonese",
    "难念的经": "Cantonese",
}


def slug_to_song(slug: str) -> str:
    if slug in SLUG_SONG_OVERRIDES:
        return SLUG_SONG_OVERRIDES[slug]
    return slug.replace("_", " ")


def resolve_current(song: str, lang: str) -> Path | None:
    cand = [
        Path(PREP) / lang / f"{song}_qwen_fa/alignments/r2/vocal/windowed/alignment.json",
        Path(TEST) / lang / f"{song}_qwen_fa/alignments/r2/vocal/windowed/alignment.json",
    ]
    for p in cand:
        if p.is_file():
            return p
    return None


def resolve_b4(song: str) -> Path | None:
    for root in (B4_NONCORE, B4_CORE):
        cand = Path(root) / song / "alignments/r2/vocal/windowed/alignment.json"
        if cand.is_file():
            return cand
        # try underscored dirname too
        cand2 = Path(root) / song.replace(" ", "_") / "alignments/r2/vocal/windowed/alignment.json"
        if cand2.is_file():
            return cand2
    return None


def resolve_audio(song: str, lang: str) -> Path | None:
    cand = [
        Path(PREP) / lang / f"{song}_qwen_fa/work/audio/mix.wav",
        Path(TEST) / lang / f"{song}_qwen_fa/work/audio/mix.wav",
        Path(PREP) / lang / f"{song}_qwen_fa/work/audio/vocals.wav",
        Path(TEST) / lang / f"{song}_qwen_fa/work/audio/vocals.wav",
    ]
    for p in cand:
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", required=True, type=Path)
    ap.add_argument("--profile", choices=("review", "final"), default="final")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    videos = args.deliver / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    ass_root = args.deliver / "_ktv_ass"
    # Only the original B4_vs_Current_<song>.mp4 set is an input; the *_KTV_*
    # outputs of this renderer must not be fed back in as inputs.
    existing = sorted(
        p.stem[len("B4_vs_Current_"):]
        for p in videos.glob("B4_vs_Current_*.mp4")
        if not p.stem.startswith("B4_vs_Current_KTV_")
    )
    if args.end:
        existing = existing[args.start:args.end]
    else:
        existing = existing[args.start:]

    results = []
    for slug in existing:
        song = slug_to_song(slug)
        lang = LANG_LOOKUP.get(song)
        if lang is None:
            results.append({"song": song, "ok": False, "reason": "no_lang"})
            continue
        cur = resolve_current(song, lang)
        b4 = resolve_b4(song)
        audio = resolve_audio(song, lang)
        if not (cur and b4 and audio):
            results.append({
                "song": song, "ok": False,
                "reason": "missing_inputs",
                "has_current": bool(cur), "has_b4": bool(b4), "has_audio": bool(audio),
            })
            continue
        out = videos / f"B4_vs_Current_KTV_{slug}.mp4"
        try:
            meta = render_alignment_comparison(
                alignment_paths=[b4, cur],
                labels=["B4 · pre-slot", "Current · full-slot"],
                visual_source=None,  # black background karaoke
                audio_track=audio,
                output_path=out,
                ass_root=ass_root / slug,
                font="Noto Sans CJK SC",
                layout="two",
                profile=args.profile,
                force=args.force,
            )
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {song}: {e}", flush=True)
            results.append({"song": song, "ok": False, "error": str(e)})
            continue
        print(f"OK {song}: {out.name} skipped={meta.get('skipped')}", flush=True)
        results.append({"song": song, **{k: meta.get(k) for k in ("path", "skipped", "request_hash", "encoding_passes")}, "ok": True})

    summary = {"ok": sum(1 for r in results if r.get("ok")), "total": len(existing),
               "skipped": [r["song"] for r in results if not r.get("ok")],
               "results": results}
    (args.deliver / "ktv_compare_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"KTV_DONE": summary["ok"], "of": summary["total"]}, ensure_ascii=False))
    print("MANIFEST:", args.deliver / "ktv_compare_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
