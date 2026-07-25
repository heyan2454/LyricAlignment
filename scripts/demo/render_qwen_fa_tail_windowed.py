#!/usr/bin/env python3
"""Render the dedicated 夜苏打 vocal-tail serial-window alignments."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "qwen_fa_tail_windowed_render_v1"


def load_render_module() -> ModuleType:
    path = ROOT / "scripts" / "demo" / "render_qwen_fa_karaoke.py"
    spec = importlib.util.spec_from_file_location("lyricalign_karaoke_render_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import base renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def resolve_path(value: str, *, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def read_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("config must contain a non-empty cases list")
    return [
        {
            "case_id": str(row["case_id"]),
            "display_label": str(row.get("display_label") or row["case_id"]),
            "source_start_sec": float(row["source_start_sec"]),
            "audio_path": resolve_path(str(row["audio_path"]), base=path.parent),
            "case_root": resolve_path(str(row["case_root"]), base=path.parent),
        }
        for row in cases
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--font", default="Noto Sans CJK SC")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.config.is_file():
        raise FileNotFoundError(args.config)
    base = load_render_module()
    cases = read_cases(args.config.resolve())
    font = base.detect_font(args.font)
    all_outputs: list[dict[str, Any]] = []

    for case in cases:
        if not case["audio_path"].is_file():
            raise FileNotFoundError(case["audio_path"])
        individual: dict[str, dict[str, Any]] = {}
        case_outputs: list[dict[str, Any]] = []
        for model in ("r0", "r1", "r2"):
            alignment = case["case_root"] / "alignments" / model / "windowed" / "alignment.json"
            if not alignment.is_file():
                raise FileNotFoundError(alignment)
            rendered = base.render_individual(
                alignment_path=alignment,
                audio_path=case["audio_path"],
                output_path=case["case_root"] / "videos" / "individual" / f"{model}_vocal_tail_windowed.mp4",
                ass_path=case["case_root"] / "subtitles" / f"{model}_vocal_tail_windowed.ass",
                label=f"{model.upper()} · 分离人声 · {case['display_label']} · 串行分窗",
                font=font,
                width=args.width,
                height=args.height,
                fps=args.fps,
                force=args.force,
            )
            individual[model] = rendered
            row = {
                "kind": "individual",
                "case_id": case["case_id"],
                "model": model,
                "audio": "vocal_tail",
                "mode": "windowed",
                **rendered,
            }
            case_outputs.append(row)
            all_outputs.append(row)

        comparison = base.render_composite(
            sources=[Path(individual[model]["path"]) for model in ("r0", "r1", "r2")],
            source_hashes=[str(individual[model]["request_hash"]) for model in ("r0", "r1", "r2")],
            output_path=case["case_root"] / "videos" / "comparisons" / "compare_models_vocal_tail_windowed.mp4",
            layout="three",
            force=args.force,
        )
        comparison_row = {
            "kind": "three_way",
            "case_id": case["case_id"],
            "models": ["r0", "r1", "r2"],
            "audio": "vocal_tail",
            "mode": "windowed",
            **comparison,
        }
        case_outputs.append(comparison_row)
        all_outputs.append(comparison_row)
        base.atomic_json(
            case["case_root"] / "render_manifest.json",
            {
                "schema_version": SCHEMA_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "case_id": case["case_id"],
                "display_label": case["display_label"],
                "source_start_sec": case["source_start_sec"],
                "font": font,
                "individual_video_count": 3,
                "three_way_video_count": 1,
                "outputs": case_outputs,
            },
        )

    base.atomic_json(
        args.config.resolve().parent / "render_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "font": font,
            "case_count": len(cases),
            "individual_video_count": 3 * len(cases),
            "three_way_video_count": len(cases),
            "total_video_count": 4 * len(cases),
            "outputs": all_outputs,
        },
    )


if __name__ == "__main__":
    main()
