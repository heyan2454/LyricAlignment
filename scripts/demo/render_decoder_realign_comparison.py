#!/usr/bin/env python3
"""Render official comparison directly in one encoding pass.

Default output is O0 vs O1 (official before/after realign) with the lightweight
review profile. Use --four-way only for stage closeout when raw diagnostics are
actually needed, and --profile final for the high-quality deliverable.
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
    link_or_copy,
    render_alignment_comparison,
)

BRANCH_SPECS = {
    "official_no_realign": "O0 · official · no realign",
    "raw_no_realign": "R0 · raw · no realign",
    "official_realign": "O1 · official · local realign",
    "raw_realign": "R1 · raw · local realign",
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
    p.add_argument("--profile", choices=("review", "final"), default="review")
    p.add_argument("--four-way", action="store_true", help="render O0/R0/O1/R1 instead of the default O0/O1 pair")
    # Compatibility flags: panel intermediates are no longer generated; pair extras are intentionally removed.
    p.add_argument("--keep-render-panels", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--render-pairs", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--subtitle-band-height", type=int, help=argparse.SUPPRESS)
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    alignment_root = args.alignment_root.resolve()
    mix = require_file(args.mix_audio)
    visual = require_file(args.visual_source) if args.visual_source else None
    out = args.out_root.resolve()
    font = detect_font(args.font)

    if args.four_way:
        branches = [
            "official_no_realign", "raw_no_realign",
            "official_realign", "raw_realign",
        ]
        layout = "four"
        filename = "compare_official_raw_realign_2x2_mix.mp4"
    else:
        branches = ["official_no_realign", "official_realign"]
        layout = "two"
        filename = "compare_official_realign_off_vs_on_mix.mp4"
    alignment_paths = [
        require_file(alignment_root / "branches" / branch / "alignment.json")
        for branch in branches
    ]
    result = render_alignment_comparison(
        alignment_paths=alignment_paths,
        labels=[BRANCH_SPECS[branch] for branch in branches],
        visual_source=visual,
        audio_track=mix,
        output_path=out / "videos" / "comparisons" / filename,
        ass_root=out / "work" / "direct_comparison_ass",
        font=font,
        layout=layout,
        profile=args.profile,
        force=args.force,
    )
    primary = Path(result["path"])
    primary_entry = out / "decoder_realign_demo.mp4"
    link_method = link_or_copy(primary, primary_entry)
    if not args.keep_render_panels:
        shutil.rmtree(out / "work" / "direct_comparison_ass", ignore_errors=True)

    manifest: dict[str, Any] = {
        "schema_version": "decoder_realign_comparison_render_v2_direct",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "alignment_root": str(alignment_root),
        "visual_source": None if visual is None else str(visual),
        "audio_track": str(mix),
        "font": font,
        "profile": args.profile,
        "branches": branches,
        "layout": layout,
        "primary_video": str(primary_entry),
        "primary_link_method": link_method,
        "encoding_passes": result.get("encoding_passes"),
        "output": result,
        "intermediate_panel_videos_generated": False,
        "raw_rendered": bool(args.four_way),
    }
    atomic_json(out / "render_manifest.json", manifest)
    print(json.dumps({"status": "complete", **manifest}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
