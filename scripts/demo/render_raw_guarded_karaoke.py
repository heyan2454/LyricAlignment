#!/usr/bin/env python3
"""Render raw-baseline and guarded-realign karaoke videos.

The alignment is always produced from the separated vocal track.  The primary
user-facing videos keep the original mix as audio and the original video as the
visual source when one is available.  Vocal-audio renders are retained only as
alignment diagnostics.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.media_render import (
    atomic_json,
    detect_font,
    render_composite,
    render_media_video,
)

SCHEMA_VERSION = "raw_guarded_karaoke_render_v1"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--alignment-root", type=Path, required=True)
    p.add_argument("--mix-audio", type=Path, required=True)
    p.add_argument("--vocal-audio", type=Path, required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--visual-source", type=Path)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--subtitle-band-height", type=int)
    p.add_argument("--force", action="store_true")
    return p


def require_file(path: Path) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def main() -> int:
    args = parser().parse_args()
    alignment_root = args.alignment_root.resolve()
    baseline = require_file(alignment_root / "baseline_raw" / "alignment.json")
    final = require_file(alignment_root / "alignment.json")
    mix = require_file(args.mix_audio)
    vocal = require_file(args.vocal_audio)
    visual = require_file(args.visual_source) if args.visual_source else None
    out = args.out_root.resolve()
    font = detect_font(args.font)

    specs: list[tuple[str, Path, Path, str]] = [
        ("raw_baseline_mix", baseline, mix, "R2 RAW · baseline · original mix"),
        ("guarded_final_mix", final, mix, "R2 RAW · guarded realign · original mix"),
        ("raw_baseline_vocal", baseline, vocal, "R2 RAW · baseline · separated vocal"),
        ("guarded_final_vocal", final, vocal, "R2 RAW · guarded realign · separated vocal"),
    ]
    rendered: dict[str, dict[str, Any]] = {}
    outputs: list[dict[str, Any]] = []
    for name, alignment, audio, label in specs:
        result = render_media_video(
            alignment_path=alignment,
            visual_source=visual,
            audio_track=audio,
            output_path=out / "videos" / "individual" / f"{name}.mp4",
            ass_path=out / "subtitles" / f"{name}.ass",
            label=label,
            font=font,
            force=args.force,
            subtitle_band_height=args.subtitle_band_height,
        )
        rendered[name] = result
        outputs.append({"kind": "individual", "name": name, **result})

    for audio_name in ("mix", "vocal"):
        left = rendered[f"raw_baseline_{audio_name}"]
        right = rendered[f"guarded_final_{audio_name}"]
        result = render_composite(
            sources=[Path(left["path"]), Path(right["path"])],
            source_hashes=[str(left["request_hash"]), str(right["request_hash"])],
            output_path=out / "videos" / "comparisons" / f"compare_raw_vs_guarded_{audio_name}.mp4",
            layout="two",
            force=args.force,
        )
        outputs.append({"kind": "two_way", "audio": audio_name, **result})

    primary = Path(rendered["guarded_final_mix"]["path"])
    primary_copy = out / "raw_guarded_demo.mp4"
    primary_copy.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not primary_copy.is_file() or primary_copy.stat().st_mtime_ns < primary.stat().st_mtime_ns:
        temporary = primary_copy.with_suffix(".tmp.mp4")
        shutil.copy2(primary, temporary)
        temporary.replace(primary_copy)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "alignment_root": str(alignment_root),
        "visual_source": None if visual is None else str(visual),
        "mix_audio": str(mix),
        "vocal_audio": str(vocal),
        "font": font,
        "primary_video": str(primary_copy),
        "outputs": outputs,
    }
    atomic_json(out / "render_manifest.json", manifest)
    print(json.dumps({"status": "complete", **manifest}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
