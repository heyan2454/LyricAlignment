#!/usr/bin/env python3
"""Run two or more vocal-tail cases through R0/R1/R2 serial-window alignment.

This is intentionally separate from the full 夜苏打 matrix demo.  It processes
only the cases listed in one JSON config, only the separated-vocal audio, and
only serial-window inference.  R0, R1 and R2 are loaded one at a time; while a
model is resident, all configured cases are completed before it is released.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "qwen_fa_tail_windowed_v4_multilingual_units"


def load_serial_demo_module() -> ModuleType:
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("lyricalign_serial_demo_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import base alignment implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def resolve_path(value: str, *, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def read_config(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("config must contain a non-empty cases list")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in cases:
        if not isinstance(raw, dict):
            raise TypeError("every case must be an object")
        case_id = str(raw.get("case_id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"invalid or duplicate case_id: {case_id!r}")
        seen.add(case_id)
        source_start_sec = float(raw["source_start_sec"])
        if source_start_sec < 0:
            raise ValueError(f"source_start_sec must be non-negative: {case_id}")
        result.append(
            {
                "case_id": case_id,
                "display_label": str(raw.get("display_label") or case_id),
                "source_start_sec": source_start_sec,
                "lyrics_path": resolve_path(str(raw["lyrics_path"]), base=path.parent),
                "audio_path": resolve_path(str(raw["audio_path"]), base=path.parent),
                "case_root": resolve_path(str(raw["case_root"]), base=path.parent),
            }
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--r1-checkpoint", type=Path, required=True)
    parser.add_argument("--r2-checkpoint", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--core-sec", type=float, default=60.0)
    parser.add_argument("--left-context-sec", type=float, default=10.0)
    parser.add_argument("--right-context-sec", type=float, default=10.0)
    parser.add_argument("--future-line-padding", type=int, default=1)
    parser.add_argument("--minimum-forward-characters", type=int, default=64)
    parser.add_argument("--future-character-ratio", type=float, default=1.35)
    parser.add_argument("--max-candidate-expansions", type=int, default=4)
    parser.add_argument("--boundary-start-tolerance-sec", type=float, default=0.32)
    parser.add_argument("--seam-tolerance-sec", type=float, default=0.16)
    parser.add_argument("--line-padding", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--character-backtrack", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.config.is_file():
        raise FileNotFoundError(args.config)
    serial = load_serial_demo_module()
    args.language = serial.normalize_alignment_language(args.language)
    cases = read_config(args.config.resolve())

    prepared: list[dict[str, Any]] = []
    for case in cases:
        for key in ("lyrics_path", "audio_path"):
            if not case[key].is_file():
                raise FileNotFoundError(case[key])
        document = serial.parse_lyrics_text(case["lyrics_path"].read_text(encoding="utf-8-sig"), language=args.language)
        lyrics_identity = {
            "path": str(case["lyrics_path"].resolve()),
            "sha256": serial.sha256(case["lyrics_path"]),
            "line_count": len(document.lines),
            "character_count": len(document.characters),
            "alignment_unit_count": len(document.characters),
            "language": document.language,
            "alignment_unit_mode": document.unit_mode,
        }
        audio_identity = {
            "path": str(case["audio_path"].resolve()),
            "sha256": serial.sha256(case["audio_path"]),
            "source_start_sec": case["source_start_sec"],
        }
        case["case_root"].mkdir(parents=True, exist_ok=True)
        serial.atomic_json(
            case["case_root"] / "lyrics_structure.json",
            {
                "schema_version": SCHEMA_VERSION,
                "case_id": case["case_id"],
                "display_label": case["display_label"],
                "source_start_sec": case["source_start_sec"],
                "identity": lyrics_identity,
                "lines": [line.__dict__ for line in document.lines],
                "characters": [item.__dict__ for item in document.characters],
            },
        )
        prepared.append(
            {
                **case,
                "document": document,
                "lyrics_identity": lyrics_identity,
                "audio_identity": audio_identity,
            }
        )

    models = [
        ("r0", "raw", None),
        ("r1", "projector", args.r1_checkpoint),
        ("r2", "lora", args.r2_checkpoint),
    ]
    expected_outputs: list[Path] = []

    for model_name, kind, checkpoint in models:
        checkpoint_info = serial.checkpoint_identity(kind, checkpoint)
        requests: list[tuple[dict[str, Any], Path, dict[str, Any], str]] = []
        for case in prepared:
            request = {
                "schema_version": SCHEMA_VERSION,
                "case_id": case["case_id"],
                "display_label": case["display_label"],
                "source_start_sec": case["source_start_sec"],
                "model_name": model_name,
                "model_id": args.model,
                "revision": args.revision,
                "language": case["document"].language,
                "alignment_unit_mode": case["document"].unit_mode,
                "checkpoint": checkpoint_info,
                "lyrics": case["lyrics_identity"],
                "audio_name": "vocal_tail",
                "audio": case["audio_identity"],
                "mode": "windowed",
                "timestamp_segment_sec": args.timestamp_segment_sec,
                "window": {
                    "core_sec": args.core_sec,
                    "left_context_sec": args.left_context_sec,
                    "right_context_sec": args.right_context_sec,
                    "policy": serial.WINDOW_POLICY,
                    "future_line_padding": args.future_line_padding,
                    "minimum_forward_characters": args.minimum_forward_characters,
                    "future_character_ratio": args.future_character_ratio,
                    "max_candidate_expansions": args.max_candidate_expansions,
                    "boundary_start_tolerance_sec": args.boundary_start_tolerance_sec,
                    "seam_tolerance_sec": args.seam_tolerance_sec,
                },
            }
            request_hash = serial.canonical_hash(request)
            output = case["case_root"] / "alignments" / model_name / "windowed" / "alignment.json"
            expected_outputs.append(output)
            requests.append((case, output, request, request_hash))

        if not args.force and all(serial.output_is_current(path, request_hash) for _, path, _, request_hash in requests):
            print(json.dumps({"skip_model": model_name, "reason": "all tail outputs current"}), flush=True)
            continue

        print(json.dumps({"loading_model": model_name, "checkpoint_kind": kind}), flush=True)
        processor, model = serial.load_model(args, kind, checkpoint)
        try:
            for case, output, request, request_hash in requests:
                if not args.force and serial.output_is_current(output, request_hash):
                    print(json.dumps({"skip": str(output), "reason": "identity match"}), flush=True)
                    continue
                print(
                    json.dumps(
                        {
                            "model": model_name,
                            "case_id": case["case_id"],
                            "source_start_sec": case["source_start_sec"],
                            "mode": "windowed",
                            "status": "start",
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                audio = serial.decode_audio(case["audio_path"])
                progress_output = output.with_name("alignment.progress.json")
                failure_output = output.with_name("alignment.failure.json")
                output.unlink(missing_ok=True)
                failure_output.unlink(missing_ok=True)

                def write_progress(state: dict[str, Any]) -> None:
                    serial.atomic_json(
                        progress_output,
                        {
                            "schema_version": "qwen_fa_alignment_progress_v1",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "identity": {**request, "request_hash": request_hash},
                            "state": state,
                        },
                    )

                write_progress({"event": "alignment_started", "mode": "windowed"})
                try:
                    rows, trace = serial.windowed_alignment(
                        processor,
                        model,
                        audio,
                        case["document"],
                        args,
                        progress_callback=write_progress,
                    )
                except Exception as exc:
                    latest_progress = None
                    try:
                        latest_progress = json.loads(progress_output.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        pass
                    serial.atomic_json(
                        failure_output,
                        {
                            "schema_version": "qwen_fa_alignment_failure_v1",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "identity": {**request, "request_hash": request_hash},
                            "error": {
                                "type": type(exc).__name__,
                                "message": str(exc),
                                "diagnostic": getattr(exc, "diagnostic", None),
                            },
                            "latest_progress": latest_progress,
                        },
                    )
                    raise
                repaired_count = sum(bool(row.get("cross_window_repaired")) for row in rows)
                seam_repaired_count = sum(bool(row.get("seam_repaired")) for row in rows)
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "identity": {**request, "request_hash": request_hash},
                    "summary": {
                        "audio_duration_sec": float(len(audio) / 16000.0),
                        "source_start_sec": case["source_start_sec"],
                        "source_end_sec": case["source_start_sec"] + float(len(audio) / 16000.0),
                        "line_count": len(case["document"].lines),
                        "character_count": len(rows),
                        "alignment_unit_count": len(rows),
                        "language": case["document"].language,
                        "alignment_unit_mode": case["document"].unit_mode,
                        "cross_window_repaired_character_count": repaired_count,
                        "cross_window_repaired_character_rate": repaired_count / len(rows),
                        "seam_repaired_character_count": seam_repaired_count,
                        "seam_repaired_character_rate": seam_repaired_count / len(rows),
                        "window_policy": serial.WINDOW_POLICY,
                        "window_count": len(trace),
                        "mode": "windowed",
                        "audio_input": "separated_vocals_tail",
                        "diagnostic_only": True,
                        "uses_full_alignment_as_window_input": False,
                    },
                    "lines": [line.__dict__ for line in case["document"].lines],
                    "characters": rows,
                    "window_trace": trace,
                }
                artifact_result = serial.write_alignment_bundle(output, payload)
                progress_output.unlink(missing_ok=True)
                failure_output.unlink(missing_ok=True)
                print(
                    json.dumps(
                        {
                            "completed": str(output),
                            "quality_status": artifact_result["quality"]["status"],
                            "artifacts": artifact_result["paths"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                del audio
        finally:
            del model
            del processor
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    missing = [str(path) for path in expected_outputs if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing expected alignments: {missing}")
    root = args.config.resolve().parent
    serial.atomic_json(
        root / "alignment_matrix.complete.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_ids": [case["case_id"] for case in prepared],
            "models": [item[0] for item in models],
            "audio_input": "separated_vocals_tail",
            "modes": ["windowed"],
            "expected_alignment_count": len(expected_outputs),
            "outputs": [str(path) for path in expected_outputs],
        },
    )


if __name__ == "__main__":
    main()
