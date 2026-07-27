#!/usr/bin/env python3
"""Render comparison-only videos for the controlled decoder/realign demo."""
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

from lyricalign.demo.media_render import atomic_json, detect_font, render_composite, render_media_video

BRANCH_SPECS = {
    "official_no_realign": "O0 · official decoder · no realign",
    "raw_no_realign": "R0 · raw argmax · no realign",
    "official_realign": "O1 · official decoder · local realign",
    "raw_realign": "R1 · raw argmax · local realign",
}


def require_file(path: Path) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--alignment-root", type=Path, required=True)
    p.add_argument("--mix-audio", type=Path, required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--visual-source", type=Path)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--subtitle-band-height", type=int)
    p.add_argument("--keep-render-panels", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    alignment_root = args.alignment_root.resolve()
    mix = require_file(args.mix_audio)
    visual = require_file(args.visual_source) if args.visual_source else None
    out = args.out_root.resolve()
    font = detect_font(args.font)
    panel_root = out / "work" / "render_panels"
    rendered: dict[str, dict[str, Any]] = {}

    for branch, label in BRANCH_SPECS.items():
        alignment = require_file(alignment_root / "branches" / branch / "alignment.json")
        result = render_media_video(
            alignment_path=alignment,
            visual_source=visual,
            audio_track=mix,
            output_path=panel_root / f"{branch}.mp4",
            ass_path=panel_root / "subtitles" / f"{branch}.ass",
            label=label,
            font=font,
            force=args.force,
            subtitle_band_height=args.subtitle_band_height,
        )
        rendered[branch] = result

    comparison_root = out / "videos" / "comparisons"
    outputs: list[dict[str, Any]] = []

    four_order = [
        "official_no_realign", "raw_no_realign",
        "official_realign", "raw_realign",
    ]
    four = render_composite(
        sources=[Path(rendered[name]["path"]) for name in four_order],
        source_hashes=[str(rendered[name]["request_hash"]) for name in four_order],
        output_path=comparison_root / "compare_official_raw_realign_2x2_mix.mp4",
        layout="four",
        force=args.force,
    )
    outputs.append({"kind": "four_way", "branches": four_order, **four})

    pairs = {
        "compare_official_realign_off_vs_on_mix.mp4": ("official_no_realign", "official_realign"),
        "compare_raw_realign_off_vs_on_mix.mp4": ("raw_no_realign", "raw_realign"),
        "compare_official_vs_raw_no_realign_mix.mp4": ("official_no_realign", "raw_no_realign"),
    }
    for filename, branch_pair in pairs.items():
        result = render_composite(
            sources=[Path(rendered[name]["path"]) for name in branch_pair],
            source_hashes=[str(rendered[name]["request_hash"]) for name in branch_pair],
            output_path=comparison_root / filename,
            layout="two",
            force=args.force,
        )
        outputs.append({"kind": "two_way", "branches": list(branch_pair), **result})

    primary = Path(four["path"])
    primary_copy = out / "decoder_realign_demo.mp4"
    if args.force or not primary_copy.is_file() or primary_copy.stat().st_mtime_ns < primary.stat().st_mtime_ns:
        temporary = primary_copy.with_suffix(".tmp.mp4")
        shutil.copy2(primary, temporary)
        temporary.replace(primary_copy)

    manifest = {
        "schema_version": "decoder_realign_comparison_render_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "alignment_root": str(alignment_root),
        "visual_source": None if visual is None else str(visual),
        "audio_track": str(mix),
        "inference_audio_role": "separated vocal (recorded in alignment manifest)",
        "font": font,
        "primary_video": str(primary_copy),
        "outputs": outputs,
        "individual_outputs_generated": False,
    }
    atomic_json(out / "render_manifest.json", manifest)
    if not args.keep_render_panels:
        shutil.rmtree(panel_root, ignore_errors=True)
    print(json.dumps({"status": "complete", **manifest}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
