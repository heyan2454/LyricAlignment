#!/usr/bin/env python3
"""Render all Demo items only after the alignment experiment is complete.

Outputs stay inside the existing ``items/<item_id>/render`` directory.  The
script never creates another ``<song>_qwen_fa*`` tree and never copies the same
video to a second filename.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.media_render import atomic_json, detect_font, render_media_video


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--experiment-root", type=Path, required=True)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--profile", choices=("review", "final"), default="review")
    p.add_argument("--render-incomplete", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    manifest = args.manifest.expanduser().resolve()
    root = args.experiment_root.expanduser().resolve()
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    if not (root / "experiment_summary.json").is_file():
        raise FileNotFoundError(
            f"alignment stage is not complete; missing {root / 'experiment_summary.json'}"
        )
    font = detect_font(args.font)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in read_jsonl(manifest):
        if str(item.get("dataset")) != "demo":
            continue
        item_id = str(item["item_id"])
        item_root = root / "items" / item_id
        alignment = item_root / "branches" / "B2_30_silence_official" / "alignment.json"
        if not alignment.is_file():
            failures.append({"item_id": item_id, "reason": "official_alignment_missing", "path": str(alignment)})
            continue
        visual = Path(item["visual_path"]).resolve() if item.get("visual_path") else None
        audio = Path(item.get("mix_audio_path") or item["audio_path"]).resolve()
        try:
            render_root = item_root / "render"
            output = render_media_video(
                alignment_path=alignment,
                visual_source=visual if visual and visual.is_file() else None,
                audio_track=audio,
                output_path=render_root / "official.mp4",
                ass_path=render_root / "work" / "official.ass",
                label="official · B2 · 30 s silence-aware",
                font=font,
                force=args.force,
                profile=args.profile,
            )
            item_result: dict[str, Any] = {
                "item_id": item_id,
                "official": output,
                "output_directory": str(render_root),
                "duplicate_output_directories_created": False,
            }
            incomplete = item_root / "incomplete_guard" / "alignment.json"
            if args.render_incomplete and incomplete.is_file():
                item_result["incomplete"] = render_media_video(
                    alignment_path=incomplete,
                    visual_source=visual if visual and visual.is_file() else None,
                    audio_track=audio,
                    output_path=render_root / "incomplete_guard.mp4",
                    ass_path=render_root / "work" / "incomplete_guard.ass",
                    label="constructed incomplete · fail closed",
                    font=font,
                    force=args.force,
                    profile=args.profile,
                )
            results.append(item_result)
        except Exception as exc:
            failures.append({"item_id": item_id, "reason": "render_failed", "error": f"{type(exc).__name__}: {exc}"})
    payload = {
        "schema_version": "inline_realign_demo_render_batch_v1",
        "alignment_stage_complete_before_render": True,
        "demo_item_count": len(results) + len(failures),
        "rendered_item_count": len(results),
        "failed_item_count": len(failures),
        "font": font,
        "profile": args.profile,
        "results": results,
        "failures": failures,
    }
    atomic_json(root / "demo_render_summary.json", payload)
    print(json.dumps({
        "status": "complete" if not failures else "partial_failure",
        "rendered_item_count": len(results),
        "failed_item_count": len(failures),
        "summary": str(root / "demo_render_summary.json"),
    }, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
