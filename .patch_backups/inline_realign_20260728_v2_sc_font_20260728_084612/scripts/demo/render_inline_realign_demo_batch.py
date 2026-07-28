#!/usr/bin/env python3
"""Render multi-way K-song comparison and behavior videos for every Demo item.

No unpaired individual model video is produced.  The canonical outputs are:

* ``comparison_main_2x2.mp4``: raw, baseline and two current improvements;
* ``comparison_stable_2x2.mp4`` when S1/S2/S3 artifacts exist;
* ``comparison_realign_2x2.mp4`` when R1/R2/R3 artifacts exist;
* ``behavior_current.mp4``: B2 karaoke plus per-window raw/official/detector state.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.media_render import atomic_json, detect_font, render_alignment_comparison

spec = importlib.util.spec_from_file_location(
    "inline_behavior_renderer", ROOT / "scripts" / "demo" / "render_inline_realign_behavior_video.py"
)
assert spec and spec.loader
BEHAVIOR = importlib.util.module_from_spec(spec); spec.loader.exec_module(BEHAVIOR)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def require_files(paths: list[Path], *, purpose: str) -> None:
    missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise FileNotFoundError(f"{purpose} missing or empty: {missing}")


def resolve_token(item_root: Path, token: str) -> tuple[Path, str]:
    mapping = {
        "RAW_B2": (item_root / "branches" / "B2_30_silence_official" / "alignment.raw.json", "Raw · B2 window inference"),
        "B0_60_fixed_official": (item_root / "branches" / token / "alignment.json", "B0 · 60 s fixed baseline"),
        "B1_30_fixed_official": (item_root / "branches" / token / "alignment.json", "B1 · 30 s fixed"),
        "B2_30_silence_official": (item_root / "branches" / token / "alignment.json", "B2 · 30 s silence-aware"),
        "B3_30_silence_raw_control": (item_root / "branches" / token / "alignment.json", "B3 · raw cursor control"),
    }
    if token not in mapping:
        return item_root / "branches" / token / "alignment.json", token
    return mapping[token]


def render_set(
    *, paths: list[Path], labels: list[str], visual: Path | None, audio: Path,
    output: Path, ass_root: Path, font: str, profile: str, force: bool,
) -> dict[str, Any]:
    if len(paths) != 4 or len(labels) != 4:
        raise ValueError("four-way comparison requires exactly four paths and labels")
    require_files(paths, purpose=f"comparison inputs for {output.name}")
    result = render_alignment_comparison(
        alignment_paths=paths, labels=labels, visual_source=visual, audio_track=audio,
        output_path=output, ass_root=ass_root, font=font, layout="four",
        profile=profile, force=force,
    )
    require_files([output], purpose=f"rendered comparison {output.name}")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--experiment-root", type=Path, required=True)
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.add_argument("--profile", choices=("review", "final"), default="review")
    p.add_argument("--comparison-branches", default="RAW_B2,B0_60_fixed_official,B1_30_fixed_official,B2_30_silence_official")
    p.add_argument("--render-incomplete", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args(); manifest = args.manifest.expanduser().resolve(); root = args.experiment_root.expanduser().resolve()
    if not manifest.is_file(): raise FileNotFoundError(manifest)
    if not (root / "experiment_summary.json").is_file(): raise FileNotFoundError(root / "experiment_summary.json")
    font = detect_font(args.font)
    resolved = read_json(root / "resolved_config.json")
    source = resolved.get("source_config") if isinstance(resolved.get("source_config"), dict) else {}
    stable_enabled = bool(nested(source, "shadow", "stable_anchor", "enabled", default=True))
    deferred_enabled = bool(nested(source, "shadow", "deferred_realign", "enabled", default=True))
    immediate_enabled = bool(nested(source, "shadow", "deferred_realign", "immediate_inline", default=True))
    requested = [value.strip() for value in args.comparison_branches.split(",") if value.strip()]
    if len(requested) != 4:
        raise ValueError("--comparison-branches must contain exactly four comma-separated tokens")
    results: list[dict[str, Any]] = []; failures: list[dict[str, Any]] = []
    demo_items = [row for row in read_jsonl(manifest) if str(row.get("dataset")) == "demo"]
    for ordinal, item in enumerate(demo_items, 1):
        item_id = str(item["item_id"]); item_root = root / "items" / item_id; render_root = item_root / "render"
        try:
            visual = Path(str(item["visual_path"])).resolve() if item.get("visual_path") else None
            if visual is not None and not visual.is_file(): visual = None
            audio = Path(str(item.get("mix_audio_path") or item["audio_path"])).resolve()
            main_pairs = [resolve_token(item_root, token) for token in requested]
            main = render_set(
                paths=[value[0] for value in main_pairs], labels=[value[1] for value in main_pairs],
                visual=visual, audio=audio, output=render_root / "comparison_main_2x2.mp4",
                ass_root=render_root / "work" / "main", font=font, profile=args.profile, force=args.force,
            )
            stable_pairs = [
                (item_root / "branches" / "B2_30_silence_official" / "alignment.json", "B2 current"),
                (item_root / "experimental_alignments" / "S1_stable_inclusive" / "alignment.json", "S1 stable-inclusive"),
                (item_root / "experimental_alignments" / "S2_stable_left_overlap" / "alignment.json", "S2 stable + left overlap"),
                (item_root / "experimental_alignments" / "S3_stable_frozen_overlap" / "alignment.json", "S3 stable frozen overlap"),
            ]
            stable = None
            if stable_enabled:
                stable = render_set(
                    paths=[value[0] for value in stable_pairs], labels=[value[1] for value in stable_pairs],
                    visual=visual, audio=audio, output=render_root / "comparison_stable_2x2.mp4",
                    ass_root=render_root / "work" / "stable", font=font, profile=args.profile, force=args.force,
                )
            realign_pairs = [
                (item_root / "branches" / "B2_30_silence_official" / "alignment.json", "R0 no realign"),
                (item_root / "experimental_alignments" / "R1_immediate_inline" / "alignment.json", "R1 inline realign"),
                (item_root / "experimental_alignments" / "R2_deferred" / "alignment.json", "R2 deferred realign"),
                (item_root / "experimental_alignments" / "R3_inline_deferred" / "alignment.json", "R3 inline + deferred"),
            ]
            realign = None
            if immediate_enabled and deferred_enabled:
                realign = render_set(
                    paths=[value[0] for value in realign_pairs], labels=[value[1] for value in realign_pairs],
                    visual=visual, audio=audio, output=render_root / "comparison_realign_2x2.mp4",
                    ass_root=render_root / "work" / "realign", font=font, profile=args.profile, force=args.force,
                )
            elif immediate_enabled or deferred_enabled:
                raise RuntimeError("partial realign configuration cannot produce the canonical R0/R1/R2/R3 comparison")
            behavior_path = render_root / "behavior_current.mp4"
            behavior = BEHAVIOR.render_behavior_video(
                alignment_path=item_root / "branches" / "B2_30_silence_official" / "alignment.json",
                visual_source=visual, audio_track=audio, output_path=behavior_path,
                ass_path=render_root / "work" / "behavior" / "behavior.ass", font=font,
                profile=args.profile, force=args.force,
            )
            require_files([behavior_path], purpose="behavior video")
            # ASS intermediates can be regenerated and are not canonical results.
            if args.profile == "review":
                for name in ("main", "stable", "realign"):
                    shutil.rmtree(render_root / "work" / name, ignore_errors=True)
            item_result = {
                "item_id": item_id, "comparison_main": main,
                "comparison_stable": stable, "comparison_realign": realign,
                "behavior_current": behavior, "output_directory": str(render_root),
                "unpaired_individual_videos_generated": False,
            }
            results.append(item_result)
            print(json.dumps({"stage": "render", "item": f"{ordinal}/{len(demo_items)}", "item_id": item_id, "status": "complete", "stable_video": stable is not None, "realign_video": realign is not None}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failure = {"item_id": item_id, "reason": "render_failed", "error": f"{type(exc).__name__}: {exc}"}; failures.append(failure)
            print(json.dumps({"stage": "render", **failure, "status": "failed"}, ensure_ascii=False), flush=True)
    payload = {
        "schema_version": "inline_realign_demo_render_batch_v3_strict_expected_artifacts",
        "alignment_stage_complete_before_render": True, "demo_item_count": len(demo_items),
        "rendered_item_count": len(results), "failed_item_count": len(failures),
        "font": font, "profile": args.profile, "comparison_tokens": requested,
        "expected_videos_per_item": 2 + int(stable_enabled) + int(immediate_enabled and deferred_enabled),
        "results": results, "failures": failures,
    }
    atomic_json(root / "demo_render_summary.json", payload)
    print(json.dumps({"status": "complete" if not failures else "partial_failure", "rendered_item_count": len(results), "failed_item_count": len(failures), "summary": str(root / "demo_render_summary.json")}, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
