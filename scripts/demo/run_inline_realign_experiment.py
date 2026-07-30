#!/usr/bin/env python3
"""Run official-window baselines and inline-realign shadow diagnostics.

The experiment loads the Qwen forced aligner once, then processes a canonical
JSONL manifest containing Demo, M4Singer and MIR-1K items.  It never writes a
shadow repair into the serial result.  The purpose is to establish whether a
repair would have been detected before commit, whether stable segments exist
within one or two adjacent windows, and whether exact/+2 local reruns agree.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import statistics
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "demo"))

import align_qwen_fa_serial_demo as SERIAL
import run_demo_realign_quick as QUICK

from lyricalign.demo.alignment_artifacts import stage_rows, write_alignment_bundle
from lyricalign.demo.inline_realign import (
    anomaly_spans_from_trace,
    attempt_probe_rows,
    compare_attempt_probes,
    nearest_segment_pair,
    reproduce_segment,
    segment_anchor_rows,
    stable_segment_candidate_diagnostics,
    stable_segments,
)
from lyricalign.demo.karaoke import normalize_alignment_language, parse_lyrics_text
from lyricalign.demo.raw_guarded import agreement_between_trials
from lyricalign.demo.realign_diagnostics import (
    accepted_shadow_rows,
    atomic_json,
    bounded_splice,
    evaluate_rows,
    structural_summary,
)
from lyricalign.training.qwen_fa_runtime import decode_audio
from lyricalign.metrics.character import evaluate_tolerant
from lyricalign.demo.run_state import RunState

VARIANTS: dict[str, dict[str, Any]] = {
    "B0_60_fixed_official": {
        "core_sec": 60.0, "silence_mode": "fixed", "serial_control": "same",
        "meaning": "60 秒固定窗口；official 控制歌词推进",
    },
    "B1_30_fixed_official": {
        "core_sec": 30.0, "silence_mode": "fixed", "serial_control": "same",
        "meaning": "30 秒固定窗口；official 控制歌词推进",
    },
    "B2_30_silence_official": {
        "core_sec": 30.0, "silence_mode": "snap", "serial_control": "same",
        "meaning": "30 秒静音吸附窗口；音频上下文仍连续",
    },
    "B3_30_silence_raw_control": {
        "core_sec": 30.0, "silence_mode": "snap", "serial_control": "raw",
        "meaning": "30 秒静音吸附窗口；raw 控制歌词推进",
    },
    "B4_60_silence_official": {
        "core_sec": 60.0, "silence_mode": "snap", "serial_control": "same",
        "meaning": "60 秒静音吸附窗口",
    },
    "B5_30_strict_silence_official": {
        "core_sec": 30.0, "silence_mode": "strict", "serial_control": "same",
        "meaning": "30 秒严格静音边界；模型输入不跨越强静音",
    },
    "B6_60_strict_silence_official": {
        "core_sec": 60.0, "silence_mode": "strict", "serial_control": "same",
        "meaning": "60 秒严格静音边界；模型输入不跨越强静音",
    },
    "C0_30_silence_compressed_diagnostic": {
        "core_sec": 30.0, "silence_mode": "compressed", "serial_control": "same",
        "meaning": "30 秒先按原时间轴静音吸附分窗；模型输入删除长静音后映射回原时间轴",
        "diagnostic_only": True,
    },
    "C1_60_silence_compressed_diagnostic": {
        "core_sec": 60.0, "silence_mode": "compressed", "serial_control": "same",
        "meaning": "60 秒先按原时间轴静音吸附分窗；模型输入删除长静音后映射回原时间轴",
        "diagnostic_only": True,
    },
}



def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_gt(path: Path | None) -> list[dict[str, Any]]:
    return [] if path is None else read_jsonl(path)


def canonical_final_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project infer_slice or serial rows to the common final start/end schema."""
    values = [dict(row) for row in rows]
    result: list[dict[str, Any]] = []
    for row in values:
        start = row.get("start_sec", row.get("fixed_global_start_sec"))
        end = row.get("end_sec", row.get("fixed_global_end_sec"))
        if start is None or end is None:
            raise KeyError(
                f"row {row.get('global_character_index')} lacks start/end and fixed_global_start/end"
            )
        row["start_sec"] = float(start)
        row["end_sec"] = float(end)
        if row.get("global_character_index") is None and row.get("character_index") is not None:
            row["global_character_index"] = int(row["character_index"])
        row["artifact_stage"] = row.get("artifact_stage", "final")
        result.append(row)
    return sorted(result, key=lambda row: int(row["global_character_index"]))


def metrics_without_details(rows: list[dict[str, Any]], gt: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return canonical tolerant metrics plus signed-error diagnostics.

    The previous implementation only evaluated the common/matched character set.
    That can make an alignment look better after dropping or invalidating difficult
    units.  The primary fields now follow
    ``character_interval_metrics_v3_tolerant`` and penalize invalid/missing units.
    Signed-error diagnostics are retained under ``matched_only_diagnostic`` for
    mechanism analysis, but they are not the primary score.
    """
    if not gt:
        return None
    prediction_rows = canonical_final_rows(rows)
    gt_by_index = {
        int(row.get("character_index", row.get("global_character_index"))): dict(row)
        for row in gt
    }
    reference: list[dict[str, Any]] = []
    for index, row in sorted(gt_by_index.items()):
        reference.append({
            "item_id": "item",
            "song_id": "item",
            "character_index": index,
            "normalized_character": row.get("normalized_character") or row.get("character") or str(index),
            "start_sec": float(row["start_sec"]),
            "end_sec": float(row["end_sec"]),
        })
    prediction: list[dict[str, Any]] = []
    for row in prediction_rows:
        index = int(row.get("global_character_index", row.get("character_index")))
        prediction.append({
            "item_id": "item",
            "song_id": "item",
            "character_index": index,
            "normalized_character": (
                gt_by_index.get(index, {}).get("normalized_character")
                or gt_by_index.get(index, {}).get("character")
                or row.get("normalized_character")
                or row.get("character")
                or str(index)
            ),
            "start_sec": float(row["start_sec"]),
            "end_sec": float(row["end_sec"]),
        })
    canonical = evaluate_tolerant(reference, prediction)
    diagnostic = evaluate_rows(prediction_rows, gt)
    diagnostic.pop("details", None)
    return {
        **canonical,
        # Compatibility aliases now point to the all-reference canonical score.
        "boundary_mae_sec": canonical["all_item_penalized_boundary_mae_sec"],
        "requested_unit_count": canonical["character_count"],
        "matched_unit_count": canonical["valid_prediction_count"],
        "missing_unit_count": canonical["missing_prediction_count"],
        "matched_only_diagnostic": diagnostic,
        "primary_metric_note": (
            "Primary MAE penalizes invalid/missing predictions. "
            "matched_only_diagnostic is auxiliary and must not be used as the main score."
        ),
    }


def stable_segment_gt_summary(
    segments: list[dict[str, Any]], rows: list[dict[str, Any]], gt: list[dict[str, Any]],
) -> dict[str, Any]:
    if not gt:
        return {"gt_available": False, "segment_count": len(segments), "segments": segments}
    by_index = {int(row["global_character_index"]): row for row in rows}
    compact_segments: list[dict[str, Any]] = []
    correct_units = 0
    total_units = 0
    all_errors: list[float] = []
    for segment in segments:
        indices = list(range(int(segment["character_start"]), int(segment["character_end"]) + 1))
        evaluation = evaluate_rows([by_index[index] for index in indices if index in by_index], gt, indices)
        details = evaluation.pop("details", [])
        errors = [
            value for row in details
            for value in (float(row["onset_abs_error_sec"]), float(row["offset_abs_error_sec"]))
        ]
        all_errors.extend(errors)
        unit_correct = sum(
            float(row["onset_abs_error_sec"]) <= 0.16
            and float(row["offset_abs_error_sec"]) <= 0.16
            for row in details
        )
        correct_units += unit_correct
        total_units += len(details)
        compact = {key: value for key, value in segment.items() if key != "rows"}
        compact["gt"] = {
            **evaluation,
            "joint_within_0p16_unit_count": unit_correct,
            "max_boundary_error_sec": max(errors, default=None),
        }
        compact_segments.append(compact)
    return {
        "gt_available": True,
        "segment_count": len(compact_segments),
        "stable_unit_count": total_units,
        "joint_within_0p16_unit_count": correct_units,
        "joint_within_0p16_rate": correct_units / total_units if total_units else None,
        "boundary_mae_sec": sum(all_errors) / len(all_errors) if all_errors else None,
        "segments": compact_segments,
    }


def serial_args(args: argparse.Namespace, variant: dict[str, Any]) -> SimpleNamespace:
    # Defaults mirror parser() so request-identity helpers remain independently testable.
    value = lambda name, default: getattr(args, name, default)
    return SimpleNamespace(
        device=value("device", "cuda"),
        timestamp_segment_sec=value("timestamp_segment_sec", 0.08),
        core_sec=float(variant["core_sec"]),
        left_context_sec=value("left_context_sec", 10.0),
        right_context_sec=value("right_context_sec", 10.0),
        future_line_padding=value("future_line_padding", 1),
        minimum_forward_characters=value("minimum_forward_characters", 64),
        future_character_ratio=value("future_character_ratio", 1.35),
        max_candidate_expansions=value("max_candidate_expansions", 4),
        boundary_start_tolerance_sec=value("boundary_start_tolerance_sec", 0.32),
        seam_tolerance_sec=value("seam_tolerance_sec", 0.16),
        capture_shadow_rows=True,
        capture_attempt_probes=True,
        attempt_probe_max_rows=value("attempt_probe_max_rows", 48),
        stable_segment_min_units=value("stable_segment_min_units", 2),
        stable_segment_confidence_quantile=value("stable_segment_confidence_quantile", 0.50),
        stable_raw_official_tolerance_sec=value("stable_raw_official_tolerance_sec", 0.16),
        stable_context_tolerance_sec=value("stable_context_tolerance_sec", 0.24),
        stable_prefix_reproduction_tolerance_sec=value("stable_prefix_reproduction_tolerance_sec", 0.24),
        stable_prefix_minimum_observed_units=value("stable_prefix_minimum_observed_units", 2),
        stable_prefix_minimum_observed_ratio=value("stable_prefix_minimum_observed_ratio", 0.50),
        decoder_kind="official",
        serial_control_decoder_kind=str(variant["serial_control"]),
        skip_silent_windows=True,
        silent_active_ratio_max=value("silent_active_ratio_max", 0.01),
        silent_peak_margin_db=value("silent_peak_margin_db", 3.0),
        silent_min_sustained_sec=value("silent_min_sustained_sec", 0.40),
        startup_vocal_preroll_sec=value("startup_vocal_preroll_sec", 2.0),
        startup_minimum_forward_characters=value("startup_minimum_forward_characters", 24),
        silence_aware_window_plan=str(variant.get("silence_mode", "fixed")) == "snap",
        strict_silence_boundary_plan=str(variant.get("silence_mode", "fixed")) == "strict",
        strict_silence_boundary_sec=value("strict_silence_boundary_sec", 1.5),
        compress_silence_audio=str(variant.get("silence_mode", "fixed")) == "compressed",
        silence_compression_min_sec=value("silence_compression_min_sec", 1.5),
        silence_compression_padding_sec=value("silence_compression_padding_sec", 0.20),
        silence_boundary_min_sec=value("silence_boundary_min_sec", 0.8),
        strong_silence_anchor_sec=value("strong_silence_anchor_sec", 1.5),
        silence_boundary_search_sec=value("silence_boundary_search_sec", 6.0),
        leading_silence_min_sec=value("leading_silence_min_sec", 2.0),
        tail_min_core_sec=value("tail_min_core_sec", 18.0),
        minimum_core_sec=value("minimum_core_sec", 12.0),
        gpu_decoder_runtime=None,
    )


def local_serial_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
        decoder_kind="official",
        gpu_decoder_runtime=None,
    )


def planner_divergence_summary(trace: list[dict[str, Any]], *, total_characters: int) -> dict[str, Any]:
    """Check whether raw and official would make different serial split decisions."""
    windows: list[dict[str, Any]] = []
    for window in trace:
        shadow = list(window.get("shadow_rows") or [])
        if not shadow or window.get("silent_core_skipped"):
            continue
        committed_before = int(window.get("committed_cursor_before", 0))
        input_before = int(window.get("input_character_start_before", 0))
        core_start = float(window.get("core_start_sec", 0.0))
        core_end = float(window.get("core_end_sec", 0.0))
        final_core = bool(window.get("is_final_core", False))
        decisions: dict[str, dict[str, Any]] = {}
        for decoder in ("official", "raw"):
            projected = SERIAL.project_rows_for_decoder(shadow, decoder)
            _, committed, _ = SERIAL.split_core_commit_prefix(
                projected, expected_input_character_start=input_before,
                committed_character_start=committed_before, core_start_sec=core_start,
                core_end_sec=core_end, final_core=final_core,
                start_tolerance_sec=0.32,
            )
            next_cursor = total_characters if final_core else None
            if not final_core and window.get("next_input_boundary_sec") is not None:
                next_cursor, _ = SERIAL.next_window_transcript_start(
                    projected, input_boundary_sec=float(window["next_input_boundary_sec"]),
                    total_characters=total_characters,
                )
            decisions[decoder] = {
                "committed_cursor_after": committed_before + len(committed),
                "next_input_cursor": next_cursor,
            }
        diverged = decisions["official"] != decisions["raw"]
        windows.append({
            "window_index": window.get("window_index"),
            "diverged": diverged,
            "official": decisions["official"],
            "raw": decisions["raw"],
            "committed_cursor_delta": decisions["raw"]["committed_cursor_after"] - decisions["official"]["committed_cursor_after"],
            "next_input_cursor_delta": (
                None if decisions["raw"]["next_input_cursor"] is None or decisions["official"]["next_input_cursor"] is None
                else int(decisions["raw"]["next_input_cursor"]) - int(decisions["official"]["next_input_cursor"])
            ),
        })
    return {
        "evaluated_window_count": len(windows),
        "diverged_window_count": sum(bool(row["diverged"]) for row in windows),
        "first_divergence_window": next((row["window_index"] for row in windows if row["diverged"]), None),
        "windows": windows,
    }


def branch_request(
    args: argparse.Namespace, item: dict[str, Any], variant_name: str,
    variant: dict[str, Any], checkpoint: dict[str, Any],
) -> dict[str, Any]:
    serial_parameters = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(serial_args(args, variant)).items()
    }
    return {
        "schema_version": "inline_realign_baseline_request_v4_complete_behavior_identity",
        "behavior_schema_version": "serial_window_behavior_20260728_v4",
        "item_id": item["item_id"],
        "dataset": item["dataset"],
        "profile": item.get("profile"),
        "language": item.get("language", "Chinese"),
        "alignment_unit_mode_hint": item.get("alignment_unit_mode"),
        "lyrics_path": item["lyrics_path"],
        "lyrics_sha256": SERIAL.sha256(Path(item["lyrics_path"])),
        "audio_path": item["audio_path"],
        "audio_sha256": SERIAL.sha256(Path(item["audio_path"])),
        "model": str(args.model),
        "revision": args.revision,
        "checkpoint": checkpoint,
        "variant": variant_name,
        "variant_spec": variant,
        "serial_parameters": serial_parameters,
        "diagnostic_parameters": {
            "capture_attempt_probes": True,
            "max_case_preview_rows": args.max_case_preview_rows,
            "precommit_diagnostic_version": "localized_core_committed_v2",
            "stable_prefix_minimum_observed_units": args.stable_prefix_minimum_observed_units,
            "stable_prefix_minimum_observed_ratio": args.stable_prefix_minimum_observed_ratio,
            "stable_segment_min_units": args.stable_segment_min_units,
            "stable_segment_confidence_quantile": args.stable_segment_confidence_quantile,
            "stable_raw_official_tolerance_sec": args.stable_raw_official_tolerance_sec,
            "stable_context_tolerance_sec": args.stable_context_tolerance_sec,
        },
    }


def evaluation_request(item: dict[str, Any], inference_request_hash: str) -> dict[str, Any]:
    """Build the evaluation-only cache identity.

    GT and metric changes invalidate only evaluation artifacts. They are
    deliberately excluded from :func:`branch_request`, so cached model
    inference remains reusable.
    """
    gt_path = Path(str(item["gt_path"])) if item.get("gt_path") else None
    return {
        "schema_version": "inline_realign_evaluation_request_v1",
        "inference_request_hash": inference_request_hash,
        "gt_available": bool(gt_path and gt_path.is_file()),
        "gt_sha256": None if gt_path is None or not gt_path.is_file() else SERIAL.sha256(gt_path),
        "metric_schema_version": "character_interval_metrics_v3_tolerant",
        "matched_only_diagnostic_schema_version": "character_boundary_metrics_v2_onset_offset_signed_absolute",
        "stable_segment_metric_schema_version": "stable_segment_joint_0p16_v1",
    }


def refresh_cached_evaluation(
    *, payload: dict[str, Any], item: dict[str, Any], gt: list[dict[str, Any]],
    alignment_path: Path, summary_path: Path,
) -> bool:
    """Refresh GT-derived fields without rerunning model inference."""
    inference_hash = str(payload.get("identity", {}).get("request_hash") or "")
    request = evaluation_request(item, inference_hash)
    request_hash = canonical_hash(request)
    if payload.get("evaluation_identity", {}).get("request_hash") == request_hash:
        return False

    rows = canonical_final_rows(payload.get("characters", []))
    stable_payload = payload.get("stable_segments") or {}
    stored_segments = stable_payload.get("segments", []) if isinstance(stable_payload, dict) else []
    stable_summary = stable_segment_gt_summary(list(stored_segments), rows, gt)
    payload.setdefault("summary", {})["gt"] = metrics_without_details(rows, gt)
    payload["summary"]["stable_segment_gt"] = {
        key: value for key, value in stable_summary.items() if key != "segments"
    }
    payload["stable_segments"] = stable_summary
    gt_path = str(item.get("gt_path")) if item.get("gt_path") else None
    payload["evaluation_identity"] = {
        "request_hash": request_hash,
        "request": request,
        "gt_path": gt_path,
        "refreshed_at": utc_now(),
    }
    write_alignment_bundle(alignment_path, payload)
    atomic_json(summary_path, payload["summary"])
    return True


def alignment_is_current(path: Path, request_hash: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("identity", {}).get("request_hash") == request_hash


def current_auxiliary_payload(path: Path, request_hash: str, *, force: bool) -> dict[str, Any] | None:
    if force or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if payload.get("identity", {}).get("request_hash") == request_hash else None


def with_auxiliary_identity(payload: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "identity": {"request_hash": canonical_hash(request), "request": request},
    }


def compact_shadow_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "global_character_index", "character", "fixed_global_start_sec",
        "fixed_global_end_sec", "raw_global_start_sec", "raw_global_end_sec",
        "official_fixed_global_start_sec", "official_fixed_global_end_sec",
        "raw_boundary_margin_mean", "core_start_sec", "core_end_sec",
        "input_start_sec", "input_end_sec", "serial_control_decoder_kind",
    )
    return {field: row.get(field) for field in fields}


def compact_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in trace:
        row = dict(source)
        if "shadow_rows" in row:
            row["shadow_rows"] = [compact_shadow_row(value) for value in row.get("shadow_rows", [])]
        suffix = row.get("stable_suffix_candidate")
        if isinstance(suffix, dict):
            row["stable_suffix_candidate"] = {key: value for key, value in suffix.items() if key != "rows"}
        result.append(row)
    return result


def run_variant(
    *, args: argparse.Namespace, item: dict[str, Any], variant_name: str,
    variant: dict[str, Any], processor: Any, model: Any, audio: Any,
    document: Any, gt: list[dict[str, Any]], checkpoint: dict[str, Any],
    item_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    request = branch_request(args, item, variant_name, variant, checkpoint)
    request_hash = canonical_hash(request)
    branch_root = item_root / "branches" / variant_name
    alignment_path = branch_root / "alignment.json"
    if not args.force and alignment_is_current(alignment_path, request_hash):
        payload = json.loads(alignment_path.read_text(encoding="utf-8"))
        refresh_cached_evaluation(
            payload=payload, item=item, gt=gt, alignment_path=alignment_path,
            summary_path=branch_root / "summary.json",
        )
        return list(payload["characters"]), list(payload.get("window_trace", [])), payload

    started = time.perf_counter()
    sargs = serial_args(args, variant)
    rows, trace = SERIAL.windowed_alignment(processor, model, audio, document, sargs)
    stable = stable_segments(
        rows,
        accepted_shadow_rows(trace),
        min_units=args.stable_segment_min_units,
        confidence_quantile=args.stable_segment_confidence_quantile,
        raw_official_tolerance_sec=args.stable_raw_official_tolerance_sec,
        repeated_context_tolerance_sec=args.stable_context_tolerance_sec,
    )
    stable_summary = stable_segment_gt_summary(stable, rows, gt)
    planner_divergence = planner_divergence_summary(trace, total_characters=len(rows))
    trace = compact_trace(trace)
    precommit_count = sum(bool((window.get("precommit_diagnostic") or {}).get("triggered")) for window in trace)
    prefix_failures = sum(
        not bool((window.get("stable_prefix_reproduction") or {}).get("supported"))
        and (window.get("stable_prefix_reproduction") or {}).get("reason")
        not in {"no_previous_stable_segment", "segment_not_observed_in_current_window"}
        for window in trace
    )
    payload = {
        "schema_version": "inline_realign_baseline_v1",
        "created_at": utc_now(),
        "identity": {
            "request_hash": request_hash,
            "request": request,
            "model": str(args.model),
            "revision": args.revision,
            "checkpoint": checkpoint,
        },
        "summary": {
            "item_id": item["item_id"],
            "dataset": item["dataset"],
            "profile": item.get("profile"),
            "language": document.language,
            "alignment_unit_mode": document.unit_mode,
            "variant": variant_name,
            "variant_meaning": variant["meaning"],
            "audio_duration_sec": len(audio) / 16000.0,
            "character_count": len(rows),
            "window_count": len(trace),
            "wall_sec": time.perf_counter() - started,
            "structural": structural_summary(rows),
            "gt": metrics_without_details(rows, gt),
            "precommit_triggered_window_count": precommit_count,
            "stable_prefix_reproduction_failure_count": prefix_failures,
            "stable_segment_count": len(stable),
            "stable_segment_gt": {
                key: value for key, value in stable_summary.items() if key != "segments"
            },
            "planner_divergence": {
                key: value for key, value in planner_divergence.items() if key != "windows"
            },
        },
        "lines": [line.__dict__ for line in document.lines],
        "characters": rows,
        "window_trace": trace,
        "stable_segments": stable_summary,
        "planner_divergence": planner_divergence,
    }
    evaluation = evaluation_request(item, request_hash)
    payload["evaluation_identity"] = {
        "request_hash": canonical_hash(evaluation),
        "request": evaluation,
        "gt_path": str(item.get("gt_path")) if item.get("gt_path") else None,
        "refreshed_at": utc_now(),
    }
    write_alignment_bundle(alignment_path, payload)
    atomic_json(branch_root / "summary.json", payload["summary"])
    return rows, trace, payload


def write_experimental_alignment(
    *, output_path: Path, baseline_payload: dict[str, Any], rows: list[dict[str, Any]],
    experiment_name: str, experiment_family: str, gt: list[dict[str, Any]],
    request: dict[str, Any], metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a full-song shadow alignment for visual/metric comparison.

    Experimental artifacts never replace the B2 branch.  They are full-length
    projections so every Demo can be rendered in a fair multi-way comparison.
    """
    summary = {
        **baseline_payload.get("summary", {}),
        "variant": experiment_name,
        "variant_meaning": experiment_family,
        "structural": structural_summary(rows),
        "gt": metrics_without_details(rows, gt),
        "experimental_shadow_only": True,
    }
    payload = {
        "schema_version": "inline_realign_experimental_alignment_v1",
        "created_at": utc_now(),
        "identity": {
            "request_hash": canonical_hash(request), "request": request,
            "baseline_request_hash": baseline_payload.get("identity", {}).get("request_hash"),
        },
        "summary": summary,
        "lines": baseline_payload.get("lines", []),
        "characters": canonical_final_rows(rows),
        "window_trace": baseline_payload.get("window_trace", []),
        "experimental_metadata": metadata or {},
    }
    write_alignment_bundle(output_path, payload)
    return payload


def _target_structural(rows: list[dict[str, Any]], indices: Iterable[int]) -> dict[str, Any]:
    wanted = set(int(index) for index in indices)
    return structural_summary(
        row for row in rows if int(row["global_character_index"]) in wanted
    )


def _anomaly_score(summary: dict[str, Any]) -> int:
    return (
        4 * int(summary.get("negative_duration_count", 0))
        + 3 * int(summary.get("inter_unit_overlap_count", 0))
        + 2 * int(summary.get("zero_duration_count", 0))
        + int(summary.get("start_regression_count", 0))
    )


def _bounded_preview_indices(indices: list[int], limit: int) -> list[int]:
    """Keep endpoints and evenly spaced interior indices under a hard row cap."""
    if limit <= 0 or not indices:
        return []
    ordered = sorted(set(int(index) for index in indices))
    if len(ordered) <= limit:
        return ordered
    if limit == 1:
        return [ordered[len(ordered) // 2]]
    positions = {round(step * (len(ordered) - 1) / (limit - 1)) for step in range(limit)}
    return [ordered[position] for position in sorted(positions)]


def _replacement_preview(
    baseline: list[dict[str, Any]], proposed: list[dict[str, Any]], gt: list[dict[str, Any]],
    indices: list[int], *, limit: int,
) -> dict[str, Any]:
    baseline_by_index = {int(row["global_character_index"]): row for row in baseline}
    proposed_by_index = {int(row["global_character_index"]): row for row in proposed}
    gt_by_index = {
        int(row.get("character_index", row.get("global_character_index", -1))): row
        for row in gt
    }
    sampled = _bounded_preview_indices(indices, limit)
    rows: list[dict[str, Any]] = []
    for index in sampled:
        before = baseline_by_index.get(index, {})
        after = proposed_by_index.get(index, {})
        truth = gt_by_index.get(index, {})
        rows.append({
            "global_character_index": index,
            "character": before.get("character", after.get("character", truth.get("character"))),
            "baseline_start_sec": before.get("start_sec"),
            "baseline_end_sec": before.get("end_sec"),
            "proposed_start_sec": after.get("start_sec"),
            "proposed_end_sec": after.get("end_sec"),
            "gt_start_sec": truth.get("start_sec"),
            "gt_end_sec": truth.get("end_sec"),
        })
    return {
        "total_row_count": len(sorted(set(indices))),
        "included_row_count": len(rows),
        "truncated": len(rows) < len(sorted(set(indices))),
        "rows": rows,
    }


def _gt_row_index(row: dict[str, Any]) -> int:
    return int(row.get("character_index", row.get("global_character_index", -1)))


def gt_error_spans(
    rows: list[dict[str, Any]], gt: list[dict[str, Any]], *,
    threshold_sec: float, minimum_run: int = 1,
) -> list[dict[str, Any]]:
    """Create GT-defined local targets so local realign is tested independently of detection."""
    if not gt:
        return []
    by_gt = {_gt_row_index(row): row for row in gt}
    ordered = sorted(rows, key=lambda row: int(row["global_character_index"]))
    flagged: list[tuple[dict[str, Any], float]] = []
    for row in ordered:
        index = int(row["global_character_index"])
        truth = by_gt.get(index)
        if truth is None:
            flagged.append((row, 0.0))
            continue
        onset = abs(float(row["start_sec"]) - float(truth["start_sec"]))
        offset = abs(float(row["end_sec"]) - float(truth["end_sec"]))
        duration = float(row["end_sec"]) - float(row["start_sec"])
        error = max(onset, offset)
        flagged.append((row, error if error > threshold_sec + 1e-9 or duration <= 1e-9 else 0.0))
    spans: list[dict[str, Any]] = []
    current: list[tuple[dict[str, Any], float]] = []
    for row, error in flagged:
        if error > 0:
            if current and int(row["global_character_index"]) != int(current[-1][0]["global_character_index"]) + 1:
                if len(current) >= minimum_run:
                    spans.append(_gt_span(current, threshold_sec))
                current = []
            current.append((row, error))
        elif current:
            if len(current) >= minimum_run:
                spans.append(_gt_span(current, threshold_sec))
            current = []
    if current and len(current) >= minimum_run:
        spans.append(_gt_span(current, threshold_sec))
    return sorted(spans, key=lambda value: (-float(value["max_gt_boundary_error_sec"]), int(value["character_start"])))


def _gt_span(values: list[tuple[dict[str, Any], float]], threshold_sec: float) -> dict[str, Any]:
    first = values[0][0]
    last = values[-1][0]
    owners = [int(row.get("owner_window_index", -1)) for row, _ in values]
    return {
        "window_index": next((value for value in owners if value >= 0), -1),
        "character_start": int(first["global_character_index"]),
        "character_end": int(last["global_character_index"]),
        "reasons": ["gt_boundary_error"],
        "severity": max(1, int(round(max(error for _, error in values) * 1000))),
        "max_gt_boundary_error_sec": max(error for _, error in values),
        "gt_threshold_sec": threshold_sec,
        "candidate_source": "gt_oracle",
        "range_source": "gt_error_contiguous_span",
    }


def _gt_cursor_at_boundary(gt: list[dict[str, Any]], boundary_sec: float, total_characters: int) -> int | None:
    if not gt:
        return None
    ordered = sorted(gt, key=_gt_row_index)
    for row in ordered:
        index = _gt_row_index(row)
        start = float(row["start_sec"]); end = float(row["end_sec"])
        if start < boundary_sec - 1e-9 and end > boundary_sec + 1e-9:
            return min(index + 1, total_characters)
        if start >= boundary_sec - 1e-9:
            return index
    return total_characters


def _gt_commit_cursor(gt: list[dict[str, Any]], core_end_sec: float, total_characters: int) -> int | None:
    if not gt:
        return None
    for row in sorted(gt, key=_gt_row_index):
        if float(row["start_sec"]) >= core_end_sec - 1e-9:
            return _gt_row_index(row)
    return total_characters


def _segment_from_rows(source: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda row: int(row["global_character_index"]))
    return {
        **{key: value for key, value in source.items() if key != "rows"},
        "character_start": int(ordered[0]["global_character_index"]),
        "character_end": int(ordered[-1]["global_character_index"]),
        "character_count": len(ordered),
        "text": "".join(str(row.get("character", "")) for row in ordered),
        "start_sec": float(ordered[0]["start_sec"]),
        "end_sec": float(ordered[-1]["end_sec"]),
        "rows": ordered,
    }


def _local_segment_parts(
    segment: dict[str, Any], *, minimum_units: int, predicate: Any,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for row in segment.get("rows", []):
        if not predicate(row):
            continue
        if not groups or int(row["global_character_index"]) != int(groups[-1][-1]["global_character_index"]) + 1:
            groups.append([row])
        else:
            groups[-1].append(row)
    return [
        clipped for group in groups if len(group) >= minimum_units
        if (clipped := _segment_from_rows(segment, group)) is not None
    ]


def stable_window_assistance_summary(
    *, args: argparse.Namespace, rows: list[dict[str, Any]], trace: list[dict[str, Any]],
    gt: list[dict[str, Any]], total_characters: int,
) -> dict[str, Any]:
    """Evaluate stable segments as local transcript/commit boundaries without changing output."""
    shadow = accepted_shadow_rows(trace)
    segments = stable_segments(
        rows, shadow, min_units=args.stable_segment_min_units,
        confidence_quantile=args.stable_segment_confidence_quantile,
        raw_official_tolerance_sec=args.stable_raw_official_tolerance_sec,
        repeated_context_tolerance_sec=args.stable_context_tolerance_sec,
    )
    transitions: list[dict[str, Any]] = []
    for position in range(max(0, len(trace) - 1)):
        current = trace[position]; following = trace[position + 1]
        if current.get("silent_core_skipped") or following.get("silent_core_skipped"):
            continue
        boundary = current.get("next_input_boundary_sec")
        if boundary is None:
            continue
        next_input_start = float(following.get("effective_input_start_sec", following.get("input_start_sec", 0.0)))
        next_core_start = float(following.get("core_start_sec", 0.0))
        audible_parts: list[dict[str, Any]] = []
        for segment in segments:
            audible_parts.extend(_local_segment_parts(
                segment, minimum_units=args.stable_segment_min_units,
                predicate=lambda row: (
                    float(row["end_sec"]) >= next_input_start - 1e-9
                    and float(row["start_sec"]) < next_core_start + 1e-9
                    and int(row["global_character_index"]) < int(following.get("committed_character_end", total_characters))
                ),
            ))
        prefix = max(
            audible_parts,
            key=lambda value: (float(value["end_sec"]), int(value["character_end"])),
            default=None,
        )

        safe_parts: list[dict[str, Any]] = []
        committed_start = int(current.get("committed_character_start", 0))
        committed_end = int(current.get("committed_character_end", 0))
        core_end = float(current.get("core_end_sec", 0.0))
        for segment in segments:
            safe_parts.extend(_local_segment_parts(
                segment, minimum_units=args.stable_segment_min_units,
                predicate=lambda row: (
                    committed_start <= int(row["global_character_index"]) < committed_end
                    and float(row["end_sec"]) <= core_end + 1e-9
                ),
            ))
        safe = max(safe_parts, key=lambda value: int(value["character_end"]), default=None)

        baseline_input = int(following.get("input_character_start_before", following.get("next_window_input_character_start", 0)))
        baseline_commit = int(current.get("committed_cursor_after", current.get("committed_character_end", 0)))
        ideal_input = _gt_cursor_at_boundary(gt, float(boundary), total_characters)
        ideal_commit = _gt_commit_cursor(gt, core_end, total_characters)
        suggested_input = None if prefix is None else int(prefix["character_start"])
        safe_commit = None if safe is None else int(safe["character_end"]) + 1
        reproduction = reproduce_segment(
            prefix, following.get("shadow_rows", []),
            tolerance_sec=args.stable_prefix_reproduction_tolerance_sec,
            minimum_observed_units=args.stable_prefix_minimum_observed_units,
            minimum_observed_ratio=args.stable_prefix_minimum_observed_ratio,
        )
        transitions.append({
            "from_window_index": current.get("window_index"),
            "to_window_index": following.get("window_index"),
            "next_input_boundary_sec": boundary,
            "next_input_audio_start_sec": next_input_start,
            "next_core_start_sec": next_core_start,
            "baseline_input_cursor": baseline_input,
            "stable_prefix_input_cursor": suggested_input,
            "gt_ideal_input_cursor": ideal_input,
            "baseline_input_skipped_gt_characters": None if ideal_input is None else max(0, baseline_input - ideal_input),
            "stable_input_skipped_gt_characters": None if ideal_input is None or suggested_input is None else max(0, suggested_input - ideal_input),
            "stable_input_extra_context_characters": None if ideal_input is None or suggested_input is None else max(0, ideal_input - suggested_input),
            "baseline_commit_cursor": baseline_commit,
            "stable_safe_commit_cursor": safe_commit,
            "gt_ideal_commit_cursor": ideal_commit,
            "baseline_overcommit_gt_characters": None if ideal_commit is None else max(0, baseline_commit - ideal_commit),
            "stable_overcommit_gt_characters": None if ideal_commit is None or safe_commit is None else max(0, safe_commit - ideal_commit),
            "stable_deferred_character_count": None if safe_commit is None else max(0, baseline_commit - safe_commit),
            "prefix_segment": None if prefix is None else {key: value for key, value in prefix.items() if key != "rows"},
            "safe_commit_segment": None if safe is None else {key: value for key, value in safe.items() if key != "rows"},
            "prefix_reproduction": reproduction,
            "informative_cursor_change": suggested_input is not None and suggested_input != baseline_input,
        })
    return {
        "schema_version": "stable_window_assistance_v2_local_subsegment",
        "transition_count": len(transitions),
        "prefix_available_count": sum(row["stable_prefix_input_cursor"] is not None for row in transitions),
        "informative_cursor_change_count": sum(bool(row["informative_cursor_change"]) for row in transitions),
        "reproduced_count": sum(bool((row.get("prefix_reproduction") or {}).get("supported")) for row in transitions),
        "transitions": transitions,
    }


def _attempt_rows_for_rerun(
    *, processor: Any, model: Any, audio: Any, document: Any, args: argparse.Namespace,
    trace_row: dict[str, Any], character_start: int, character_end: int,
    audio_start_sec: float | None = None, audio_end_sec: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one local window with an explicitly matched audio/text crop."""
    input_start = (
        float(audio_start_sec) if audio_start_sec is not None
        else float(trace_row.get("effective_input_start_sec", trace_row.get("input_start_sec", 0.0)))
    )
    input_end = (
        float(audio_end_sec) if audio_end_sec is not None
        else float(trace_row.get("input_end_sec", trace_row.get("effective_input_end_sec", 0.0)))
    )
    if character_end <= character_start:
        raise ValueError(f"empty transcript crop {character_start}:{character_end}")
    if input_end <= input_start + 1e-6:
        raise ValueError(f"empty audio crop {input_start:.6f}:{input_end:.6f}")
    sample_start = max(0, int(round(input_start * 16000)))
    sample_end = min(len(audio), int(round(input_end * 16000)))
    if sample_end <= sample_start:
        raise ValueError("matched audio crop has no samples")
    inferred_rows, audit = SERIAL.infer_slice(
        processor=processor, model=model, audio=audio[sample_start:sample_end], document=document,
        character_start=character_start, character_end=character_end,
        global_audio_offset_sec=input_start, args=local_serial_args(args),
    )
    return canonical_final_rows(inferred_rows), {
        **audit,
        "matched_input": {
            "audio_start_sec": input_start,
            "audio_end_sec": input_end,
            "character_start": int(character_start),
            "character_end": int(character_end),
            "audio_text_synchronized": True,
        },
    }


def _matched_crop_from_baseline(
    rows: list[dict[str, Any]], *, character_start: int, character_end: int,
    duration_sec: float,
) -> tuple[float, float]:
    by_index = {int(row["global_character_index"]): row for row in rows}
    first = by_index.get(character_start)
    last = by_index.get(character_end - 1)
    if first is None or last is None:
        raise KeyError(f"baseline lacks matched crop boundary {character_start}:{character_end}")
    audio_start = max(0.0, float(first["start_sec"]))
    audio_end = min(float(duration_sec), float(last["end_sec"]))
    if audio_end <= audio_start + 1e-6:
        raise ValueError(
            f"baseline timestamps do not define a positive matched crop for {character_start}:{character_end}: "
            f"{audio_start:.6f}:{audio_end:.6f}"
        )
    return audio_start, audio_end


def build_stable_trial_request(
    *, args: argparse.Namespace, assistance_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build cache identity for synchronized stable-window trials."""
    return {
        "schema_version": "stable_window_assistance_trials_request_v4_audio_text_synchronized",
        "assistance_request_hash": assistance_payload.get("identity", {}).get("request_hash"),
        "max_trials_per_item": int(args.max_stable_window_trials_per_item),
        "stable_context_units": [0, 2, 4],
        "audio_text_synchronized": True,
        # Retained only so an old CLI invocation changes identity rather than
        # silently reusing the invalid fixed-eight-character implementation.
        "legacy_stable_left_overlap_units": int(getattr(args, "stable_left_overlap_units", 8)),
        "stable_left_overlap_units": int(getattr(args, "stable_left_overlap_units", 8)),
    }


def run_stable_window_assistance_trials(
    *, args: argparse.Namespace, processor: Any, model: Any, audio: Any, document: Any,
    gt: list[dict[str, Any]], rows: list[dict[str, Any]], trace: list[dict[str, Any]],
    assistance: dict[str, Any], item: dict[str, Any] | None = None,
    baseline_payload: dict[str, Any] | None = None, item_root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate stable anchors with strictly synchronized audio/text crops.

    The previous S1--S3 implementation kept the original early audio start but
    removed the corresponding early transcript.  Those trials were invalid.
    Here each transcript start (stable, stable-2, stable-4) determines the audio
    start from the same baseline unit, and the transcript end determines the
    audio end.  The stable segment itself is frozen during the shadow splice.
    """
    trials: list[dict[str, Any]] = []
    by_window = {int(row.get("window_index", -1)): row for row in trace}
    baseline_rows = canonical_final_rows(rows)
    variant_rows: dict[str, list[dict[str, Any]]] = {
        "S0_stable_anchor_only": canonical_final_rows(rows),
        "S1_stable_sync_exact": canonical_final_rows(rows),
        "S2_stable_sync_minus2": canonical_final_rows(rows),
        "S3_stable_sync_minus4": canonical_final_rows(rows),
    }
    applied_counts = {key: 0 for key in variant_rows}
    duration_sec = float(len(audio) / 16000.0)
    for transition in assistance.get("transitions", []):
        if len(trials) >= args.max_stable_window_trials_per_item:
            break
        if transition.get("stable_prefix_input_cursor") is None:
            continue
        target_window = int(transition["to_window_index"])
        trace_row = by_window.get(target_window)
        prefix_info = transition.get("prefix_segment")
        if trace_row is None or prefix_info is None:
            continue
        stable_start = int(transition["stable_prefix_input_cursor"])
        character_end_exclusive = int(trace_row.get("candidate_character_end", len(document.characters)))
        character_end_exclusive = max(stable_start + 1, min(len(document.characters), character_end_exclusive))
        committed_end_exclusive = int(trace_row.get("committed_character_end", character_end_exclusive))
        replace_end = min(len(document.characters) - 1, max(stable_start, committed_end_exclusive - 1))
        source_segment_rows = [
            row for row in baseline_rows
            if int(prefix_info["character_start"])
            <= int(row["global_character_index"])
            <= int(prefix_info["character_end"])
        ]
        source_segment = {**prefix_info, "rows": source_segment_rows}
        starts = {
            "baseline_matched_rerun": int(transition["baseline_input_cursor"]),
            "S1_stable_sync_exact": stable_start,
            "S2_stable_sync_minus2": max(0, stable_start - 2),
            "S3_stable_sync_minus4": max(0, stable_start - 4),
        }
        candidates: dict[str, dict[str, Any]] = {}
        for candidate_name, character_start in starts.items():
            try:
                audio_start, audio_end = _matched_crop_from_baseline(
                    baseline_rows,
                    character_start=character_start,
                    character_end=character_end_exclusive,
                    duration_sec=duration_sec,
                )
                rerun_rows, audit = _attempt_rows_for_rerun(
                    processor=processor, model=model, audio=audio, document=document, args=args,
                    trace_row=trace_row, character_start=character_start,
                    character_end=character_end_exclusive,
                    audio_start_sec=audio_start, audio_end_sec=audio_end,
                )
                # Stable evidence is a frozen anchor, not a suggestion that a
                # later rerun may rewrite the same interval.
                frozen = {int(row["global_character_index"]): row for row in source_segment_rows}
                rerun_rows = [frozen.get(int(row["global_character_index"]), row) for row in rerun_rows]
                replacement = [
                    row for row in rerun_rows
                    if character_start <= int(row["global_character_index"]) <= replace_end
                ]
                reproduction = reproduce_segment(
                    source_segment, rerun_rows,
                    tolerance_sec=args.stable_prefix_reproduction_tolerance_sec,
                    minimum_observed_units=args.stable_prefix_minimum_observed_units,
                    minimum_observed_ratio=args.stable_prefix_minimum_observed_ratio,
                )
                candidate_payload: dict[str, Any] = {
                    "status": "complete",
                    "character_start": character_start,
                    "character_end": character_end_exclusive,
                    "audio_start_sec": audio_start,
                    "audio_end_sec": audio_end,
                    "audio_text_synchronized": True,
                    "replace_end": replace_end,
                    "prefix_reproduction": reproduction,
                    "gt": metrics_without_details(rerun_rows, gt),
                    "structural": structural_summary(rerun_rows),
                    "audit": audit,
                    "decoded_rows": rerun_rows,
                }
                output_variant = (
                    "S0_stable_anchor_only"
                    if candidate_name == "baseline_matched_rerun" else candidate_name
                )
                candidate_payload["output_variant"] = output_variant
                if output_variant in variant_rows and replacement:
                    updated, splice = bounded_splice(
                        variant_rows[output_variant], replacement,
                        replace_start=min(int(row["global_character_index"]) for row in replacement),
                        replace_end=max(int(row["global_character_index"]) for row in replacement),
                        remerge=True, projection="isotonic", minimum_duration_sec=0.0,
                    )
                    candidate_payload["splice"] = splice
                    if splice.get("valid"):
                        variant_rows[output_variant] = updated
                        applied_counts[output_variant] += 1
                candidates[candidate_name] = candidate_payload
            except Exception as exc:
                candidates[candidate_name] = {
                    "status": "failed",
                    "character_start": character_start,
                    "character_end": character_end_exclusive,
                    "audio_text_synchronized": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        baseline_gt = (candidates.get("baseline_matched_rerun") or {}).get("gt") or {}
        candidate_deltas: dict[str, float | None] = {}
        for name in variant_rows:
            if name == "S0_stable_anchor_only":
                candidate_deltas[name] = 0.0
                continue
            value = (candidates.get(name) or {}).get("gt") or {}
            baseline_mae = baseline_gt.get("boundary_mae_sec")
            candidate_mae = value.get("boundary_mae_sec")
            candidate_deltas[name] = (
                None if baseline_mae is None or candidate_mae is None
                else float(candidate_mae) - float(baseline_mae)
            )
        trials.append({
            **transition,
            "status": "complete" if any(value.get("status") == "complete" for value in candidates.values()) else "failed",
            "experiment_role": "baseline_matched_rerun_anchor_freeze_vs_audio_text_synchronized_stable_crop",
            "stable_context_units": [0, 2, 4],
            "candidates": candidates,
            "candidate_minus_baseline_boundary_mae_sec": candidate_deltas,
        })
    alignment_paths: dict[str, str] = {}
    baseline_payload = baseline_payload or {}
    for name, final_rows in variant_rows.items():
        if item_root is None:
            continue
        request = {
            "schema_version": "stable_anchor_full_alignment_request_v2_audio_text_synchronized",
            "baseline_request_hash": baseline_payload.get("identity", {}).get("request_hash"),
            "variant": name,
            "stable_context_units": [0, 2, 4],
            "audio_text_synchronized": True,
            "trial_count": len(trials),
            "applied_count": applied_counts[name],
        }
        path = item_root / "experimental_alignments" / name / "alignment.json"
        write_experimental_alignment(
            output_path=path, baseline_payload=baseline_payload, rows=final_rows,
            experiment_name=name,
            experiment_family="stable anchor synchronized audio/text crop ablation",
            gt=gt, request=request,
            metadata={
                "trial_count": len(trials),
                "applied_count": applied_counts[name],
                "audio_text_synchronized": True,
            },
        )
        alignment_paths[name] = str(path)
    return {
        "schema_version": "stable_window_assistance_trials_v4_audio_text_synchronized",
        "trial_count": len(trials),
        "successful_trial_count": sum(row.get("status") == "complete" for row in trials),
        "paired_complete_count": sum(
            all(value.get("status") == "complete" for value in row.get("candidates", {}).values())
            for row in trials
        ),
        "stable_context_units": [0, 2, 4],
        "audio_text_synchronized": True,
        "invalid_legacy_s1_s3_reused": False,
        "applied_counts": applied_counts,
        "alignment_paths": alignment_paths,
        "trials": trials,
    }


def run_forced_expansion_trials(
    *, args: argparse.Namespace, processor: Any, model: Any, audio: Any, document: Any,
    gt: list[dict[str, Any]], rows: list[dict[str, Any]], trace: list[dict[str, Any]],
    assistance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure model response to under-, exact-, and over-supplied lyrics.

    The historical experiment only enlarged future text.  This version keeps
    the acoustic window fixed and independently changes transcript end and
    transcript start, matching actual serial-production failure modes.
    """
    results: list[dict[str, Any]] = []
    total = len(document.characters)
    transition_by_window = {
        int(row["to_window_index"]): row
        for row in (assistance or {}).get("transitions", [])
        if row.get("to_window_index") is not None
    }
    candidates = [row for row in trace if not row.get("silent_core_skipped") and row.get("attempts")]
    candidates.sort(key=lambda row: (
        -int((row.get("precommit_diagnostic") or {}).get("triggered", False)),
        -int(row.get("committed_character_count", 0)), int(row.get("window_index", 0)),
    ))
    legacy_expansion_only = not hasattr(args, "text_dosage_end_deltas") and not hasattr(args, "text_dosage_start_deltas")
    end_deltas = tuple() if legacy_expansion_only else tuple(int(value) for value in getattr(args, "text_dosage_end_deltas", (-8, -4, -2, 0, 2, 4, 8, 16)))
    start_deltas = tuple() if legacy_expansion_only else tuple(int(value) for value in getattr(args, "text_dosage_start_deltas", (-4, -2, 0, 2, 4)))
    for trace_row in candidates[: args.max_expansion_trials_per_item]:
        window_index = int(trace_row.get("window_index", -1))
        transition = transition_by_window.get(window_index)
        prefix_info = None if transition is None else transition.get("prefix_segment")
        start = int(trace_row.get("candidate_character_start", trace_row.get("input_character_start_before", 0)))
        baseline_end = int(trace_row.get("candidate_character_end", start))
        baseline_probe = (trace_row.get("attempts") or [])[-1].get("probe_rows", [])
        variants: list[dict[str, Any]] = []

        def run_variant(*, kind: str, delta: int, candidate_start: int, candidate_end: int) -> dict[str, Any]:
            if candidate_end <= candidate_start:
                return {
                    "kind": kind, "delta_units": delta, "status": "invalid_empty_text",
                    "character_start": candidate_start, "character_end": candidate_end,
                }
            try:
                rerun_rows, audit = _attempt_rows_for_rerun(
                    processor=processor, model=model, audio=audio, document=document, args=args,
                    trace_row=trace_row, character_start=candidate_start, character_end=candidate_end,
                )
            except Exception as exc:
                return {
                    "kind": kind, "delta_units": delta, "status": "failed",
                    "character_start": candidate_start, "character_end": candidate_end,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            probe = attempt_probe_rows(
                rerun_rows,
                core_end_sec=float(trace_row.get("core_end_sec", 0.0)),
                next_input_boundary_sec=trace_row.get("next_input_boundary_sec"),
                max_rows=args.attempt_probe_max_rows,
            )
            movement = compare_attempt_probes([
                {"attempt_index": 0, "probe_rows": baseline_probe},
                {"attempt_index": 1, "probe_rows": probe},
            ])
            durations = [float(row["end_sec"]) - float(row["start_sec"]) for row in rerun_rows]
            tail = rerun_rows[-min(8, len(rerun_rows)):] if rerun_rows else []
            return {
                "kind": kind,
                "delta_units": delta,
                "status": "complete",
                "character_start": candidate_start,
                "character_end": candidate_end,
                "input_audio_start_sec": float(trace_row.get("effective_input_start_sec", trace_row.get("input_start_sec", 0.0))),
                "input_audio_end_sec": float(trace_row.get("input_end_sec", 0.0)),
                "movement": movement,
                "structural": structural_summary(rerun_rows),
                "gt": metrics_without_details(rerun_rows, gt),
                "tail_duration_sec": [
                    float(row["end_sec"]) - float(row["start_sec"]) for row in tail
                ],
                "negative_duration_count": sum(value < -1e-9 for value in durations),
                "zero_duration_count": sum(value <= 1e-9 for value in durations),
                "decoded_rows": rerun_rows,
                "probe_rows": probe,
                "audit": audit,
            }

        for delta in end_deltas:
            candidate_end = min(total, max(start + 1, baseline_end + delta))
            variants.append(run_variant(
                kind="text_end_delta", delta=delta,
                candidate_start=start, candidate_end=candidate_end,
            ))
        for delta in start_deltas:
            candidate_start = min(max(0, start + delta), max(0, baseline_end - 1))
            variants.append(run_variant(
                kind="text_start_delta", delta=delta,
                candidate_start=candidate_start, candidate_end=baseline_end,
            ))
        span = max(1, baseline_end - start)
        for ratio in (1.25, 1.50):
            candidate_end = min(total, max(baseline_end + 1, start + int(math.ceil(span * ratio))))
            variants.append(run_variant(
                kind="text_end_ratio", delta=int(round((ratio - 1.0) * 100)),
                candidate_start=start, candidate_end=candidate_end,
            ) | {"ratio": ratio})
        results.append({
            "window_index": window_index,
            "baseline_character_start": start,
            "baseline_character_end": baseline_end,
            "baseline_input_audio_start_sec": float(trace_row.get("effective_input_start_sec", trace_row.get("input_start_sec", 0.0))),
            "baseline_input_audio_end_sec": float(trace_row.get("input_end_sec", 0.0)),
            "stable_prefix_available": prefix_info is not None,
            "stable_prefix_segment": prefix_info,
            "variants": variants,
        })
    return {
        "schema_version": "text_dosage_trials_v3_under_exact_over_start_end",
        "window_count": len(results),
        "variant_run_count": sum(len(row["variants"]) for row in results),
        "end_deltas": list(end_deltas),
        "start_deltas": list(start_deltas),
        "ratios": [1.25, 1.50],
        "interpretation": (
            "The acoustic window is fixed. Negative end deltas may remove lyrics actually sung in the window; "
            "positive deltas add future lyrics. Start deltas simulate early/late serial cursors."
        ),
        "windows": results,
    }


def construct_incomplete_guard(
    *, item: dict[str, Any], baseline_payload: dict[str, Any], candidates: list[dict[str, Any]],
    out_path: Path, gt: list[dict[str, Any]], constructed_for_validation: bool = True,
    automatic_shadow_only: bool = False,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    target = min(candidates, key=lambda row: int(row["character_start"]))
    cutoff = max(0, int(target["character_start"]))
    all_rows = list(baseline_payload.get("characters", []))
    prefix = [row for row in all_rows if int(row["global_character_index"]) < cutoff]
    remaining = max(0, len(all_rows) - len(prefix))
    request = {
        "schema_version": "inline_realign_incomplete_guard_request_v1",
        "baseline_request_hash": baseline_payload.get("identity", {}).get("request_hash"),
        "cutoff_character_index": cutoff, "trigger": target,
    }
    payload = {
        "schema_version": "inline_realign_incomplete_guard_v1",
        "created_at": utc_now(),
        "identity": {"request_hash": canonical_hash(request), "request": request},
        "summary": {
            **baseline_payload.get("summary", {}),
            "completion_status": "incomplete",
            "incomplete_kind": (
                "constructed_fail_closed_validation" if constructed_for_validation
                else "automatic_unresolved_shadow"
            ),
            "aligned_character_count": len(prefix),
            "remaining_character_count": remaining,
            "first_unresolved_character_index": cutoff,
            "reason": "stop_before_unresolved_span_instead_of_forcing_tail",
            "gt_prefix": metrics_without_details(prefix, gt),
        },
        "lines": baseline_payload.get("lines", []),
        "characters": prefix,
        "unresolved": {
            "character_start": cutoff,
            "character_end": len(all_rows) - 1,
            "first_trigger": target,
        },
        "constructed_for_validation": constructed_for_validation,
        "automatic_shadow_only": automatic_shadow_only,
    }
    write_alignment_bundle(out_path, payload)
    return payload["summary"]


def run_inline_shadow(
    *, args: argparse.Namespace, item: dict[str, Any], processor: Any, model: Any,
    audio: Any, document: Any, gt: list[dict[str, Any]], rows: list[dict[str, Any]],
    trace: list[dict[str, Any]], out_path: Path, baseline_payload: dict[str, Any],
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    automatic_candidates = [
        {**row, "candidate_source": row.get("candidate_source", "automatic_precommit")}
        for row in anomaly_spans_from_trace(trace)
    ]
    oracle_candidates_all = gt_error_spans(
        rows, gt, threshold_sec=args.gt_oracle_error_threshold_sec,
    )
    oracle_candidates = oracle_candidates_all[: args.max_gt_oracle_cases_per_item]
    clean_candidates = clean_control_spans(
        rows, gt, threshold_sec=min(0.08, args.gt_oracle_error_threshold_sec / 2.0),
        minimum_units=args.stable_segment_min_units,
        limit=args.max_clean_control_cases_per_item,
    )
    candidates = (
        automatic_candidates[: args.max_shadow_cases_per_item]
        + oracle_candidates
        + clean_candidates
    )
    # Preserve source diversity while removing exact duplicate spans.
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for candidate in candidates:
        key = (
            int(candidate["character_start"]), int(candidate["character_end"]),
            str(candidate.get("candidate_source", "automatic_precommit")),
        )
        if key not in seen:
            seen.add(key); deduplicated.append(candidate)
    candidates = deduplicated
    shadow = accepted_shadow_rows(trace)
    duration = len(audio) / 16000.0
    decisions: list[dict[str, Any]] = []
    immediate_rows = canonical_final_rows(rows)
    fused_rows = canonical_final_rows(rows)
    immediate_applied_cases: list[str] = []
    fused_applied_cases: list[str] = []
    for ordinal, candidate in enumerate(candidates):
        target_start = max(0, int(candidate["character_start"]))
        target_end = min(len(document.characters) - 1, int(candidate["character_end"]))
        window_index = int(candidate["window_index"])
        decision: dict[str, Any] = {
            "case_id": f"{item['item_id']}_inline_{ordinal:03d}",
            "target_start": target_start,
            "target_end": target_end,
            "source_window_index": window_index,
            "trigger": candidate,
            "candidate_source": candidate.get("candidate_source", "automatic_precommit"),
            "gt_oracle_improved_shadow": False,
            "automatic_gate_accepted_shadow": False,
            "manual_gate_accepted_shadow": False,
            "actual_writeback": False,
        }
        pair = None
        searched_scopes: list[list[int]] = []
        scope_diagnostics: list[dict[str, Any]] = []
        for scope in (
            {window_index},
            {value for value in (window_index - 1, window_index) if value >= 0},
            {window_index, window_index + 1},
            {value for value in (window_index - 1, window_index, window_index + 1) if value >= 0},
        ):
            searched_scopes.append(sorted(scope))
            scope_diagnostics.append(stable_segment_candidate_diagnostics(
                rows, shadow,
                target_start=target_start, target_end=target_end, window_indices=scope,
                confidence_quantile=args.stable_segment_confidence_quantile,
                raw_official_tolerance_sec=args.stable_raw_official_tolerance_sec,
                repeated_context_tolerance_sec=args.stable_context_tolerance_sec,
            ))
            segments = stable_segments(
                rows, shadow,
                window_indices=scope,
                min_units=args.stable_segment_min_units,
                confidence_quantile=args.stable_segment_confidence_quantile,
                raw_official_tolerance_sec=args.stable_raw_official_tolerance_sec,
                repeated_context_tolerance_sec=args.stable_context_tolerance_sec,
                excluded_character_range=(target_start, target_end),
            )
            left, right, reason = nearest_segment_pair(
                segments, target_start=target_start, target_end=target_end
            )
            if left is not None and right is not None:
                pair = (scope, left, right)
                break
            decision["last_segment_search_reason"] = reason
        decision["searched_window_scopes"] = searched_scopes
        decision["anchor_scope_diagnostics"] = scope_diagnostics
        if pair is None:
            decision["reason"] = decision.get("last_segment_search_reason", "no_stable_segment_pair")
            decisions.append(decision)
            continue
        scope, left_segment, right_segment = pair
        left_anchor, right_anchor = segment_anchor_rows(left_segment, right_segment)
        decision["selected_window_scope"] = sorted(scope)
        decision["left_segment"] = {key: value for key, value in left_segment.items() if key != "rows"}
        decision["right_segment"] = {key: value for key, value in right_segment.items() if key != "rows"}
        trials: dict[str, dict[str, Any]] = {}
        try:
            for trial_name, context_units in (("exact", 0), ("plus2", 2), ("plus4", 4)):
                trials[trial_name] = QUICK.local_infer(
                    processor=processor, model=model, audio=audio, document=document,
                    serial_args=local_serial_args(args), left=left_anchor, right=right_anchor,
                    audio_duration_sec=duration,
                    crop_mode="exact_anchor" if context_units == 0 else "matched_context",
                    padding_sec=0.0, context_units=context_units,
                    context_rows=stage_rows(rows, "selected"),
                )
        except Exception as exc:  # keep formal run progressing; preserve exact failure
            decision["reason"] = "local_inference_failed"
            decision["error"] = f"{type(exc).__name__}: {exc}"
            decisions.append(decision)
            continue
        replace_start = int(trials["exact"]["replace_start"])
        replace_end = int(trials["exact"]["replace_end"])
        replacement_indices = list(range(replace_start, replace_end + 1))
        consensus = three_context_consensus(
            trials, replacement_indices, tolerance_sec=args.context_agreement_tolerance_sec,
        )
        before = _target_structural(rows, replacement_indices)
        before_score = _anomaly_score(before)
        trial_evaluations: dict[str, dict[str, Any]] = {}
        for trial_name, trial_payload in trials.items():
            trial_rows, trial_splice = bounded_splice(
                rows, trial_payload["decoded_rows"],
                replace_start=replace_start, replace_end=replace_end,
                remerge=True, projection="isotonic", minimum_duration_sec=0.0,
            )
            trial_structural = _target_structural(trial_rows, replacement_indices)
            trial_score = _anomaly_score(trial_structural)
            trial_safe = (
                bool(trial_splice.get("valid"))
                and int(trial_structural.get("negative_duration_count", 0)) <= int(before.get("negative_duration_count", 0))
                and int(trial_structural.get("start_regression_count", 0)) <= int(before.get("start_regression_count", 0))
                and int(trial_structural.get("end_regression_count", 0)) <= int(before.get("end_regression_count", 0))
                and int(trial_structural.get("inter_unit_overlap_count", 0)) <= int(before.get("inter_unit_overlap_count", 0))
            )
            trial_evaluations[trial_name] = {
                "rows": trial_rows, "splice": trial_splice,
                "structural": trial_structural, "score": trial_score,
                "hard_safety_passed": trial_safe,
            }
        selected_trial = consensus.get("selected_trial")
        selected_trial_by = "three_context_consensus"
        if not selected_trial:
            relaxed_candidates = [
                (name, value) for name, value in trial_evaluations.items()
                if value["hard_safety_passed"]
                and int(before.get("zero_duration_count", 0)) > 0
                and int(value["structural"].get("zero_duration_count", 0))
                    < int(before.get("zero_duration_count", 0))
                and int(value["score"]) <= int(before_score)
            ]
            if relaxed_candidates:
                selected_trial, _ = min(
                    relaxed_candidates,
                    key=lambda pair: (
                        int(pair[1]["score"]),
                        int(pair[1]["structural"].get("zero_duration_count", 0)),
                        str(pair[0]),
                    ),
                )
                selected_trial_by = "zero_duration_relaxed_best_trial"
            else:
                selected_trial = "exact"
                selected_trial_by = "diagnostic_exact_fallback"
        selected_evaluation = trial_evaluations[str(selected_trial)]
        replaced = selected_evaluation["rows"]
        splice = selected_evaluation["splice"]
        after = selected_evaluation["structural"]
        after_score = int(selected_evaluation["score"])
        hard_safety_passed = bool(selected_evaluation["hard_safety_passed"])
        fused_replacement = median_fused_context_rows(trials, replacement_indices)
        fused_candidate, fused_splice = bounded_splice(
            rows, fused_replacement,
            replace_start=replace_start, replace_end=replace_end,
            remerge=True, projection="isotonic", minimum_duration_sec=0.0,
        ) if fused_replacement else (canonical_final_rows(rows), {"valid": False, "reason": "no_fused_rows"})
        fused_after = _target_structural(fused_candidate, replacement_indices)
        fused_after_score = _anomaly_score(fused_after)
        gt_before = metrics_without_details(
            [row for row in rows if int(row["global_character_index"]) in replacement_indices],
            [row for row in gt if int(row.get("character_index", row.get("global_character_index", -1))) in replacement_indices],
        )
        gt_after = metrics_without_details(
            [row for row in replaced if int(row["global_character_index"]) in replacement_indices],
            [row for row in gt if int(row.get("character_index", row.get("global_character_index", -1))) in replacement_indices],
        )
        gt_improved = False
        if gt_before and gt_after:
            before_mae = gt_before.get("boundary_mae_sec")
            after_mae = gt_after.get("boundary_mae_sec")
            gt_improved = (
                before_mae is not None and after_mae is not None
                and float(after_mae) + 1e-9 < float(before_mae)
            )
        source = str(candidate.get("candidate_source", "automatic_precommit"))
        gt_worsened = False
        if gt_before and gt_after:
            before_mae = gt_before.get("boundary_mae_sec")
            after_mae = gt_after.get("boundary_mae_sec")
            gt_worsened = (
                before_mae is not None and after_mae is not None
                and float(after_mae) > float(before_mae) + 1e-9
            )
        strict_decrease_gate = (
            bool(consensus.get("supported"))
            and hard_safety_passed
            and after_score < before_score
        )
        would_pass_non_gt_gate = (
            bool(consensus.get("supported"))
            and hard_safety_passed
            and after_score <= before_score
        )
        zero_duration_relaxed_gate = (
            int(before.get("zero_duration_count", 0)) > 0
            and int(after.get("zero_duration_count", 0)) < int(before.get("zero_duration_count", 0))
            and hard_safety_passed
            and after_score <= before_score
        )
        fused_hard_safety_passed = (
            bool(fused_splice.get("valid"))
            and int(fused_after.get("negative_duration_count", 0)) <= int(before.get("negative_duration_count", 0))
            and int(fused_after.get("start_regression_count", 0)) <= int(before.get("start_regression_count", 0))
            and int(fused_after.get("end_regression_count", 0)) <= int(before.get("end_regression_count", 0))
            and int(fused_after.get("inter_unit_overlap_count", 0)) <= int(before.get("inter_unit_overlap_count", 0))
        )
        fused_gate_accepted = fused_hard_safety_passed and fused_after_score <= before_score
        gt_oracle_improved_shadow = bool(
            source == "gt_oracle" and consensus.get("supported") and hard_safety_passed and gt_improved
        )
        automatic_gate_accepted_shadow = bool(
            source == "automatic_precommit" and (would_pass_non_gt_gate or zero_duration_relaxed_gate)
        )
        manual_gate_accepted_shadow = bool(
            source == "manual_demo" and (would_pass_non_gt_gate or zero_duration_relaxed_gate)
        )
        false_accept = bool((would_pass_non_gt_gate or zero_duration_relaxed_gate) and gt_worsened)
        accepted_gate_kind = (
            "gt_oracle_improved" if gt_oracle_improved_shadow
            else "zero_duration_relaxed" if zero_duration_relaxed_gate and (automatic_gate_accepted_shadow or manual_gate_accepted_shadow)
            else "structure_nonincrease_consensus" if (automatic_gate_accepted_shadow or manual_gate_accepted_shadow)
            else "clean_control_counterfactual" if source == "clean_control" and (would_pass_non_gt_gate or zero_duration_relaxed_gate)
            else "none"
        )
        decision.update({
            "reason": (
                "gt_oracle_improved_shadow" if gt_oracle_improved_shadow
                else "automatic_zero_duration_relaxed_gate_accepted" if source == "automatic_precommit" and zero_duration_relaxed_gate
                else "automatic_structure_nonincrease_gate_accepted" if automatic_gate_accepted_shadow
                else "clean_control_counterfactual_pass" if source == "clean_control" and (would_pass_non_gt_gate or zero_duration_relaxed_gate)
                else "three_context_disagreement" if not consensus.get("supported") and not zero_duration_relaxed_gate
                else "invalid_or_unsafe_splice" if not hard_safety_passed
                else "gt_not_improved" if source == "gt_oracle"
                else "structure_not_improved_or_zero_not_reduced"
            ),
            "gt_oracle_improved_shadow": gt_oracle_improved_shadow,
            "automatic_gate_accepted_shadow": automatic_gate_accepted_shadow,
            "manual_gate_accepted_shadow": manual_gate_accepted_shadow,
            "actual_writeback": False,
            "strict_decrease_gate": strict_decrease_gate,
            "would_pass_non_gt_gate": would_pass_non_gt_gate,
            "zero_duration_relaxed_gate": zero_duration_relaxed_gate,
            "accepted_gate_kind": accepted_gate_kind,
            "hard_safety_passed": hard_safety_passed,
            "eligible_for_actual_writeback": False,
            "counterfactual_false_accept": false_accept,
            "replace_start": replace_start,
            "replace_end": replace_end,
            "context_agreement": consensus,
            "three_context_consensus": consensus,
            "selected_context_trial": selected_trial,
            "selected_context_trial_by": selected_trial_by,
            "trial_structural_diagnostics": {
                name: {key: value for key, value in trial.items() if key != "rows"}
                for name, trial in trial_evaluations.items()
            },
            "splice": splice,
            "structural_before": before,
            "structural_after": after,
            "fused_structural_after": fused_after,
            "fused_splice": fused_splice,
            "fused_gate_accepted_shadow": fused_gate_accepted,
            "fused_replacement_rows": fused_replacement,
            "anomaly_score_before": before_score,
            "anomaly_score_after": after_score,
            "fused_anomaly_score_after": fused_after_score,
            "gt_before": gt_before,
            "gt_after": gt_after,
            "gt_improved": gt_improved,
            "gt_worsened": gt_worsened,
            "replacement_preview": _replacement_preview(
                rows, replaced, gt, replacement_indices, limit=args.max_case_preview_rows,
            ),
            "exact_wall_sec": trials["exact"].get("wall_sec"),
            "plus2_wall_sec": trials["plus2"].get("wall_sec"),
            "plus4_wall_sec": trials["plus4"].get("wall_sec"),
            "context_trials": {
                name: {
                    "input": value.get("input"),
                    "replace_start": value.get("replace_start"),
                    "replace_end": value.get("replace_end"),
                    "decoded_rows": value.get("decoded_rows", []),
                    "wall_sec": value.get("wall_sec"),
                }
                for name, value in trials.items()
            },
        })
        if source == "automatic_precommit" and automatic_gate_accepted_shadow:
            try:
                updated_rows, immediate_splice = bounded_splice(
                    immediate_rows, trials[selected_trial]["decoded_rows"],
                    replace_start=replace_start, replace_end=replace_end,
                    remerge=True, projection="isotonic", minimum_duration_sec=0.0,
                )
                decision["immediate_alignment_splice"] = immediate_splice
                if immediate_splice.get("valid"):
                    immediate_rows = updated_rows
                    immediate_applied_cases.append(str(decision["case_id"]))
            except Exception as exc:
                decision["immediate_alignment_error"] = f"{type(exc).__name__}: {exc}"
        if source == "automatic_precommit" and fused_gate_accepted:
            try:
                updated_rows, fused_full_splice = bounded_splice(
                    fused_rows, fused_replacement,
                    replace_start=replace_start, replace_end=replace_end,
                    remerge=True, projection="isotonic", minimum_duration_sec=0.0,
                )
                decision["fused_alignment_splice"] = fused_full_splice
                if fused_full_splice.get("valid"):
                    fused_rows = updated_rows
                    fused_applied_cases.append(str(decision["case_id"]))
            except Exception as exc:
                decision["fused_alignment_error"] = f"{type(exc).__name__}: {exc}"
        decisions.append(decision)
    immediate_request = {
        "schema_version": "immediate_inline_full_alignment_request_v1",
        "baseline_request_hash": baseline_payload.get("identity", {}).get("request_hash"),
        "shadow_request_hash": None if request is None else canonical_hash(request),
        "applied_case_ids": immediate_applied_cases,
        "gate": "three_context_consensus_or_zero_duration_relaxed + safe_splice + anomaly_score_nonincrease",
    }
    immediate_path = out_path.parent / "experimental_alignments" / "R1_immediate_inline" / "alignment.json"
    write_experimental_alignment(
        output_path=immediate_path, baseline_payload=baseline_payload, rows=immediate_rows,
        experiment_name="R1_immediate_inline",
        experiment_family="automatic precommit inline-realign shadow",
        gt=gt, request=immediate_request,
        metadata={"applied_case_ids": immediate_applied_cases, "applied_count": len(immediate_applied_cases)},
    )
    fused_request = {
        "schema_version": "context_median_fused_full_alignment_request_v1",
        "baseline_request_hash": baseline_payload.get("identity", {}).get("request_hash"),
        "shadow_request_hash": None if request is None else canonical_hash(request),
        "applied_case_ids": fused_applied_cases,
        "gate": "median_boundary_fusion + safe_splice + anomaly_score_nonincrease",
    }
    fused_path = out_path.parent / "experimental_alignments" / "R4_context_median_fused" / "alignment.json"
    write_experimental_alignment(
        output_path=fused_path, baseline_payload=baseline_payload, rows=fused_rows,
        experiment_name="R4_context_median_fused",
        experiment_family="automatic three-context boundary-median fusion shadow",
        gt=gt, request=fused_request,
        metadata={"applied_case_ids": fused_applied_cases, "applied_count": len(fused_applied_cases)},
    )
    payload = {
        "schema_version": "inline_realign_shadow_v2_split_decisions_and_fusion",
        "created_at": utc_now(),
        "item_id": item["item_id"],
        "dataset": item["dataset"],
        "candidate_count": len(candidates),
        "automatic_candidate_count": len(automatic_candidates),
        "gt_oracle_candidate_count": len(oracle_candidates),
        "gt_oracle_all_candidate_count": len(oracle_candidates_all),
        "clean_control_candidate_count": len(clean_candidates),
        "detector_gt_overlap": detector_gt_overlap_summary(
            automatic_candidates, oracle_candidates_all, total_units=len(document.characters),
            gt_available=bool(gt),
        ),
        "decision_count": len(decisions),
        "local_inference_attempted_count": sum(row.get("replace_start") is not None or row.get("reason") == "local_inference_failed" for row in decisions),
        "gt_oracle_improved_shadow_count": sum(bool(row.get("gt_oracle_improved_shadow")) for row in decisions),
        "automatic_gate_accepted_shadow_count": sum(bool(row.get("automatic_gate_accepted_shadow")) for row in decisions),
        "manual_gate_accepted_shadow_count": sum(bool(row.get("manual_gate_accepted_shadow")) for row in decisions),
        "actual_writeback_count": sum(bool(row.get("actual_writeback")) for row in decisions),
        "would_pass_non_gt_gate_count": sum(bool(row.get("would_pass_non_gt_gate")) for row in decisions),
        "zero_duration_relaxed_gate_count": sum(bool(row.get("zero_duration_relaxed_gate")) for row in decisions),
        "clean_control_counterfactual_false_accept_count": sum(
            bool(row.get("counterfactual_false_accept"))
            for row in decisions if row.get("candidate_source") == "clean_control"
        ),
        "immediate_alignment_path": str(immediate_path),
        "immediate_applied_case_count": len(immediate_applied_cases),
        "context_median_fused_alignment_path": str(fused_path),
        "context_median_fused_applied_case_count": len(fused_applied_cases),
        "decisions": decisions,
    }
    if request is not None:
        payload = with_auxiliary_identity(payload, request)
    atomic_json(out_path, payload)
    return payload



def _span_indices(span: dict[str, Any]) -> set[int]:
    return set(range(int(span["character_start"]), int(span["character_end"]) + 1))


def detector_gt_overlap_summary(
    automatic: list[dict[str, Any]], oracle_all: list[dict[str, Any]], *, total_units: int,
    gt_available: bool | None = None,
) -> dict[str, Any]:
    """Evaluate automatic localization against GT error spans without mixing it with repair quality."""
    automatic_sets = [_span_indices(span) for span in automatic]
    oracle_sets = [_span_indices(span) for span in oracle_all]
    automatic_hit = [any(values & target for target in oracle_sets) for values in automatic_sets]
    oracle_hit = [any(values & target for target in automatic_sets) for values in oracle_sets]
    automatic_units = set().union(*automatic_sets) if automatic_sets else set()
    oracle_units = set().union(*oracle_sets) if oracle_sets else set()
    overlap_units = automatic_units & oracle_units
    precision = sum(automatic_hit) / len(automatic_hit) if automatic_hit else None
    recall = sum(oracle_hit) / len(oracle_hit) if oracle_hit else None
    unit_precision = len(overlap_units) / len(automatic_units) if automatic_units else None
    unit_recall = len(overlap_units) / len(oracle_units) if oracle_units else None
    return {
        "schema_version": "inline_detector_gt_overlap_v1",
        "gt_available": bool(oracle_all) if gt_available is None else bool(gt_available),
        "automatic_case_count": len(automatic),
        "gt_error_case_count": len(oracle_all),
        "automatic_case_hit_count": sum(automatic_hit),
        "gt_error_case_detected_count": sum(oracle_hit),
        "case_precision": precision,
        "case_recall": recall,
        "automatic_unit_count": len(automatic_units),
        "gt_error_unit_count": len(oracle_units),
        "overlap_unit_count": len(overlap_units),
        "unit_precision": unit_precision,
        "unit_recall": unit_recall,
        "total_unit_count": total_units,
    }


def clean_control_spans(
    rows: list[dict[str, Any]], gt: list[dict[str, Any]], *, threshold_sec: float,
    minimum_units: int, limit: int,
) -> list[dict[str, Any]]:
    """Choose deterministic GT-clean interior spans for realign harm measurement."""
    if not gt or limit <= 0:
        return []
    details = evaluate_rows(canonical_final_rows(rows), gt).get("details", [])
    clean_indices = sorted(
        int(detail["character_index"])
        for detail in details
        if float(detail["onset_abs_error_sec"]) <= threshold_sec
        and float(detail["offset_abs_error_sec"]) <= threshold_sec
    )
    groups: list[list[int]] = []
    for index in clean_indices:
        if not groups or index != groups[-1][-1] + 1:
            groups.append([index])
        else:
            groups[-1].append(index)
    spans: list[dict[str, Any]] = []
    required = max(3 * minimum_units, 6)
    by_index = {int(row["global_character_index"]): row for row in rows}
    for group in sorted(groups, key=lambda values: (-len(values), values[0])):
        if len(group) < required:
            continue
        width = max(minimum_units, min(4, len(group) // 3))
        center = len(group) // 2
        start = group[max(minimum_units, center - width // 2)]
        end = min(group[-minimum_units - 1], start + width - 1)
        if end < start:
            continue
        owner = by_index.get(start, {}).get("owner_window_index", 0)
        spans.append({
            "window_index": int(owner or 0),
            "character_start": int(start),
            "character_end": int(end),
            "reasons": ["gt_clean_control"],
            "severity": 0,
            "candidate_source": "clean_control",
            "range_source": "deterministic_gt_clean_interior",
        })
        if len(spans) >= limit:
            break
    return spans


def three_context_consensus(
    trials: dict[str, dict[str, Any]], replacement_indices: list[int], *, tolerance_sec: float,
) -> dict[str, Any]:
    """Accept a local path when any two of exact/+2/+4 agree."""
    pairs = [("exact", "plus2"), ("exact", "plus4"), ("plus2", "plus4")]
    pair_results: list[dict[str, Any]] = []
    supported_pairs: list[tuple[str, str]] = []
    for left_name, right_name in pairs:
        left = trials.get(left_name); right = trials.get(right_name)
        if not left or not right:
            continue
        agreement = agreement_between_trials(
            left["decoded_rows"], right["decoded_rows"], replacement_indices,
            tolerance_sec=tolerance_sec,
        )
        pair_results.append({"left": left_name, "right": right_name, **agreement})
        if agreement.get("supported"):
            supported_pairs.append((left_name, right_name))
    selected = None
    for preferred in ("exact", "plus2", "plus4"):
        if any(preferred in pair for pair in supported_pairs):
            selected = preferred
            break
    return {
        "supported": bool(supported_pairs),
        "selected_trial": selected,
        "supported_pair_count": len(supported_pairs),
        "supported_pairs": [list(pair) for pair in supported_pairs],
        "pair_results": pair_results,
        "rule": "at_least_one_of_three_pairwise_agreements",
    }



def median_fused_context_rows(
    trials: dict[str, dict[str, Any]], replacement_indices: list[int],
) -> list[dict[str, Any]]:
    """Fuse exact/+2/+4 by per-boundary median before monotonic projection."""
    names = [name for name in ("exact", "plus2", "plus4") if trials.get(name)]
    by_name = {
        name: {int(row["global_character_index"]): row for row in trials[name].get("decoded_rows", [])}
        for name in names
    }
    fused: list[dict[str, Any]] = []
    for index in replacement_indices:
        available = [mapping[index] for mapping in by_name.values() if index in mapping]
        if not available:
            continue
        template = dict(available[0])
        starts = sorted(float(row["start_sec"]) for row in available)
        ends = sorted(float(row["end_sec"]) for row in available)
        template["start_sec"] = statistics.median(starts)
        template["end_sec"] = statistics.median(ends)
        template["context_fusion"] = "median_exact_plus2_plus4"
        fused.append(template)
    return fused

def _simple_stable_segments_from_rows(
    rows: list[dict[str, Any]], *, minimum_units: int, after_index: int | None = None,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for row in sorted(canonical_final_rows(rows), key=lambda value: int(value["global_character_index"])):
        index = int(row["global_character_index"])
        if after_index is not None and index <= after_index:
            continue
        if float(row["end_sec"]) <= float(row["start_sec"]) + 1e-9:
            continue
        raw_start = row.get("raw_global_start_sec")
        raw_end = row.get("raw_global_end_sec")
        if raw_start is not None and abs(float(raw_start) - float(row["start_sec"])) > 0.24:
            continue
        if raw_end is not None and abs(float(raw_end) - float(row["end_sec"])) > 0.24:
            continue
        if not groups or index != int(groups[-1][-1]["global_character_index"]) + 1:
            groups.append([row])
        else:
            groups[-1].append(row)
    return [
        value for group in groups if len(group) >= minimum_units
        if (value := _segment_from_rows({"evidence_kind": "counterfactual_rerun"}, group)) is not None
    ]


def run_pending_confirmation_shadow(
    *, args: argparse.Namespace, item: dict[str, Any], processor: Any, model: Any,
    audio: Any, document: Any, gt: list[dict[str, Any]], rows: list[dict[str, Any]],
    trace: list[dict[str, Any]], shadow_payload: dict[str, Any] | None,
    baseline_payload: dict[str, Any], item_root: Path,
    immediate_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bounded post-serial simulation of anchor-recovered deferred realign.

    The intended production design is delayed inline execution as soon as a
    future right stable anchor appears.  The current experiment runs after the
    serial branch has completed so it can evaluate the same bounded intervals
    without changing the canonical serial state.  It writes R2 (deferred only)
    and R3 (immediate + deferred) full-song shadow alignments.
    """
    deferred_rows = canonical_final_rows(rows)
    combined_rows = canonical_final_rows(immediate_rows or rows)
    cases: list[dict[str, Any]] = []
    applied_case_ids: list[str] = []
    by_window = {int(value.get("window_index", -1)): value for value in trace}
    all_shadow = accepted_shadow_rows(trace)
    decisions = list((shadow_payload or {}).get("decisions", []))
    for decision in decisions:
        if len(cases) >= args.max_pending_shadow_cases_per_item:
            break
        if decision.get("candidate_source") != "automatic_precommit":
            continue
        if decision.get("would_pass_non_gt_gate"):
            continue
        reason = str(decision.get("reason", ""))
        if reason not in {
            "no_right_stable_segment", "no_stable_segment_pair", "no_left_stable_segment",
            "three_context_disagreement", "trigger_not_reduced",
        }:
            continue
        window_index = int(decision.get("source_window_index", -1))
        target_start = int(decision["target_start"]); target_end = int(decision["target_end"])
        case: dict[str, Any] = {
            "case_id": f"{item['item_id']}_deferred_{len(cases):03d}",
            "source_window_index": window_index, "target_start": target_start,
            "target_end": target_end, "pending_unit_count": target_end - target_start + 1,
            "status": "unresolved", "searched_future_windows": [],
        }
        left_candidates = stable_segments(
            rows, all_shadow, window_indices={value for value in (window_index - 1, window_index) if value >= 0},
            min_units=args.stable_segment_min_units,
            confidence_quantile=args.stable_segment_confidence_quantile,
            raw_official_tolerance_sec=args.stable_raw_official_tolerance_sec,
            repeated_context_tolerance_sec=args.stable_context_tolerance_sec,
            excluded_character_range=(target_start, target_end),
        )
        left = max(
            (segment for segment in left_candidates if int(segment["character_end"]) < target_start),
            key=lambda segment: int(segment["character_end"]), default=None,
        )
        if left is None:
            case["reason"] = "no_left_stable_segment_for_deferred_realign"
            cases.append(case); continue
        right = None; replay_rows: list[dict[str, Any]] = []; replay_audit: dict[str, Any] | None = None
        selected_future_window = None
        for offset in range(1, max(1, int(args.deferred_max_windows)) + 1):
            future_index = window_index + offset
            future_trace = by_window.get(future_index)
            if future_trace is None:
                break
            case["searched_future_windows"].append(future_index)
            replay_start = int(left["character_start"])
            replay_end = min(
                len(document.characters),
                max(int(future_trace.get("candidate_character_end", target_end + 1)), target_end + args.minimum_forward_characters),
            )
            try:
                candidate_rows, candidate_audit = _attempt_rows_for_rerun(
                    processor=processor, model=model, audio=audio, document=document, args=args,
                    trace_row=future_trace, character_start=replay_start, character_end=replay_end,
                )
            except Exception as exc:
                case.setdefault("replay_failures", []).append({"window_index": future_index, "error": f"{type(exc).__name__}: {exc}"})
                continue
            right_segments = _simple_stable_segments_from_rows(
                candidate_rows, minimum_units=args.stable_segment_min_units, after_index=target_end,
            )
            candidate_right = min(right_segments, key=lambda segment: int(segment["character_start"]), default=None)
            if candidate_right is None:
                continue
            interval_units = int(candidate_right["character_start"]) - int(left["character_end"]) - 1
            interval_seconds = float(candidate_right["start_sec"]) - float(left["end_sec"])
            if interval_units > args.deferred_max_units or interval_seconds > args.deferred_max_seconds:
                case["reason"] = "deferred_interval_exceeds_bound"
                case["interval_units"] = interval_units; case["interval_seconds"] = interval_seconds
                break
            right = candidate_right; replay_rows = candidate_rows; replay_audit = candidate_audit
            selected_future_window = future_index
            break
        case["left_segment"] = {key: value for key, value in left.items() if key != "rows"}
        if right is None:
            case.setdefault("reason", "future_windows_did_not_recover_right_stable_segment")
            cases.append(case); continue
        case["right_segment"] = {key: value for key, value in right.items() if key != "rows"}
        case["recovered_right_anchor_window"] = selected_future_window
        case["replay_audit"] = replay_audit
        left_anchor, right_anchor = segment_anchor_rows(left, right)
        duration = len(audio) / 16000.0
        trials: dict[str, dict[str, Any]] = {}
        try:
            for name, units in (("exact", 0), ("plus2", 2), ("plus4", 4)):
                trials[name] = QUICK.local_infer(
                    processor=processor, model=model, audio=audio, document=document,
                    serial_args=local_serial_args(args), left=left_anchor, right=right_anchor,
                    audio_duration_sec=duration,
                    crop_mode="exact_anchor" if units == 0 else "matched_context",
                    padding_sec=0.0, context_units=units, context_rows=stage_rows(rows, "selected"),
                )
            replace_start = int(trials["exact"]["replace_start"]); replace_end = int(trials["exact"]["replace_end"])
            indices = list(range(replace_start, replace_end + 1))
            consensus = three_context_consensus(trials, indices, tolerance_sec=args.context_agreement_tolerance_sec)
            before_structural = _target_structural(deferred_rows, indices)
            before_score = _anomaly_score(before_structural)
            trial_evaluations: dict[str, dict[str, Any]] = {}
            for trial_name, trial_payload in trials.items():
                trial_rows, trial_splice = bounded_splice(
                    deferred_rows, trial_payload["decoded_rows"],
                    replace_start=replace_start, replace_end=replace_end,
                    remerge=True, projection="isotonic", minimum_duration_sec=0.0,
                )
                trial_structural = _target_structural(trial_rows, indices)
                trial_score = _anomaly_score(trial_structural)
                trial_safe = (
                    bool(trial_splice.get("valid"))
                    and int(trial_structural.get("negative_duration_count", 0)) <= int(before_structural.get("negative_duration_count", 0))
                    and int(trial_structural.get("start_regression_count", 0)) <= int(before_structural.get("start_regression_count", 0))
                    and int(trial_structural.get("end_regression_count", 0)) <= int(before_structural.get("end_regression_count", 0))
                    and int(trial_structural.get("inter_unit_overlap_count", 0)) <= int(before_structural.get("inter_unit_overlap_count", 0))
                )
                trial_evaluations[trial_name] = {
                    "rows": trial_rows, "splice": trial_splice,
                    "structural": trial_structural, "score": trial_score,
                    "hard_safety_passed": trial_safe,
                }
            selected_name = consensus.get("selected_trial")
            selected_by = "three_context_consensus"
            if not selected_name:
                # Deferred is allowed to use the zero-duration-specific relaxed
                # path even when complete paths disagree.  Choose the safest
                # structural candidate rather than rejecting before the gate.
                relaxed_candidates = [
                    (name, value) for name, value in trial_evaluations.items()
                    if value["hard_safety_passed"]
                    and int(before_structural.get("zero_duration_count", 0)) > 0
                    and int(value["structural"].get("zero_duration_count", 0))
                        < int(before_structural.get("zero_duration_count", 0))
                    and int(value["score"]) <= int(before_score)
                ]
                if not relaxed_candidates:
                    case.update({
                        "reason": "deferred_three_context_disagreement",
                        "context_consensus": consensus,
                        "trial_structural_diagnostics": {
                            name: {key: value for key, value in trial.items() if key != "rows"}
                            for name, trial in trial_evaluations.items()
                        },
                    })
                    cases.append(case); continue
                selected_name, _ = min(
                    relaxed_candidates,
                    key=lambda pair: (
                        int(pair[1]["score"]),
                        int(pair[1]["structural"].get("zero_duration_count", 0)),
                        str(pair[0]),
                    ),
                )
                selected_by = "zero_duration_relaxed_best_trial"
            selected_evaluation = trial_evaluations[str(selected_name)]
            candidate_deferred = selected_evaluation["rows"]
            splice = selected_evaluation["splice"]
            after_structural = selected_evaluation["structural"]
            after_score = int(selected_evaluation["score"])
            hard_safety_passed = bool(selected_evaluation["hard_safety_passed"])
            strict_decrease_gate = (
                bool(consensus.get("supported")) and hard_safety_passed and after_score < before_score
            )
            zero_duration_relaxed_gate = (
                int(before_structural.get("zero_duration_count", 0)) > 0
                and int(after_structural.get("zero_duration_count", 0)) < int(before_structural.get("zero_duration_count", 0))
                and hard_safety_passed
                and after_score <= before_score
            )
            structure_nonincrease_gate = (
                bool(consensus.get("supported")) and hard_safety_passed and after_score <= before_score
            )
            would_pass_non_gt_gate = structure_nonincrease_gate or zero_duration_relaxed_gate
            before_gt = metrics_without_details(
                [value for value in deferred_rows if int(value["global_character_index"]) in indices],
                [value for value in gt if _gt_row_index(value) in indices],
            )
            after_gt = metrics_without_details(
                [value for value in candidate_deferred if int(value["global_character_index"]) in indices],
                [value for value in gt if _gt_row_index(value) in indices],
            )
            case.update({
                "status": "resolved_shadow" if would_pass_non_gt_gate else "candidate_rejected",
                "reason": "deferred_shadow_gate_passed" if would_pass_non_gt_gate else "deferred_trigger_not_reduced",
                "replace_start": replace_start, "replace_end": replace_end,
                "context_consensus": consensus, "selected_context_trial": selected_name,
                "selected_context_trial_by": selected_by,
                "strict_decrease_gate": strict_decrease_gate,
                "structure_nonincrease_gate": structure_nonincrease_gate,
                "accepted_gate_kind": (
                    "zero_duration_relaxed" if zero_duration_relaxed_gate and not structure_nonincrease_gate
                    else "structure_nonincrease_consensus" if structure_nonincrease_gate
                    else "none"
                ),
                "splice": splice, "structural_before": before_structural,
                "structural_after": after_structural,
                "anomaly_score_before": before_score, "anomaly_score_after": after_score,
                "would_pass_non_gt_gate": would_pass_non_gt_gate,
                "zero_duration_relaxed_gate": zero_duration_relaxed_gate,
                "hard_safety_passed": hard_safety_passed,
                "actual_writeback": False,
                "eligible_for_actual_writeback": False,
                "context_trials": {
                    name: {
                        "input": value.get("input"),
                        "replace_start": value.get("replace_start"),
                        "replace_end": value.get("replace_end"),
                        "decoded_rows": value.get("decoded_rows", []),
                        "wall_sec": value.get("wall_sec"),
                    }
                    for name, value in trials.items()
                },
                "gt_before": before_gt, "gt_after": after_gt,
            })
            if would_pass_non_gt_gate:
                deferred_rows = candidate_deferred
                candidate_combined, combined_splice = bounded_splice(
                    combined_rows, trials[selected_name]["decoded_rows"],
                    replace_start=replace_start, replace_end=replace_end,
                    remerge=True, projection="isotonic", minimum_duration_sec=0.0,
                )
                case["combined_splice"] = combined_splice
                if combined_splice.get("valid"):
                    combined_rows = candidate_combined
                applied_case_ids.append(str(case["case_id"]))
        except Exception as exc:
            case.update({"reason": "deferred_local_realign_failed", "error": f"{type(exc).__name__}: {exc}"})
        cases.append(case)
    base_hash = baseline_payload.get("identity", {}).get("request_hash")
    outputs = {
        "R2_deferred": deferred_rows,
        "R3_inline_deferred": combined_rows,
    }
    alignment_paths: dict[str, str] = {}
    for name, final_rows in outputs.items():
        output_path = item_root / "experimental_alignments" / name / "alignment.json"
        write_experimental_alignment(
            output_path=output_path, baseline_payload=baseline_payload, rows=final_rows,
            experiment_name=name,
            experiment_family="bounded anchor-recovered deferred realign shadow",
            gt=gt,
            request={
                "schema_version": "deferred_full_alignment_request_v1",
                "baseline_request_hash": base_hash, "variant": name,
                "max_windows": args.deferred_max_windows,
                "max_seconds": args.deferred_max_seconds,
                "max_units": args.deferred_max_units,
                "applied_case_ids": applied_case_ids,
            },
            metadata={"applied_case_ids": applied_case_ids, "applied_count": len(applied_case_ids)},
        )
        alignment_paths[name] = str(output_path)
    return {
        "schema_version": "deferred_realign_shadow_v2_anchor_recovered_bounded",
        "case_count": len(cases),
        "resolved_shadow_count": sum(case.get("status") == "resolved_shadow" for case in cases),
        "applied_case_count": len(applied_case_ids), "applied_case_ids": applied_case_ids,
        "alignment_paths": alignment_paths, "cases": cases,
        "interpretation": (
            "post-serial simulation of delayed-inline behavior; bounded local intervals only; "
            "canonical B2 output is unchanged"
        ),
    }

def run_tail_rollback_shadow(
    *, args: argparse.Namespace, audio: Any, document: Any, gt: list[dict[str, Any]],
    rows: list[dict[str, Any]], trace: list[dict[str, Any]], processor: Any, model: Any,
) -> dict[str, Any]:
    """Rerun the final two acoustic windows with a conservative lyric split."""
    usable = [value for value in trace if not value.get("silent_core_skipped")]
    if len(usable) < 2 or args.max_tail_rollback_cases_per_item <= 0:
        return {"schema_version": "tail_two_window_rollback_shadow_v1", "case_count": 0, "cases": []}
    last_two = usable[-2:]
    last_window_indices = {int(value.get("window_index", -1)) for value in last_two}
    diagnostic_triggered = any(
        bool((value.get("precommit_diagnostic") or {}).get("triggered")) for value in last_two
    )
    tail_rows = [
        value for value in rows
        if int(value.get("owner_window_index", -1)) in last_window_indices
    ]
    tail_zero_count = sum(
        float(value.get("end_sec", 0.0)) <= float(value.get("start_sec", 0.0)) + 1e-9
        for value in tail_rows
    )
    if not diagnostic_triggered and tail_zero_count < 4:
        return {
            "schema_version": "tail_two_window_rollback_shadow_v1",
            "case_count": 0, "cases": [],
            "skip_reason": "no_severe_tail_trigger",
        }
    total = len(document.characters)
    start = int(last_two[0].get("input_character_start_before", last_two[0].get("candidate_character_start", 0)))
    baseline_penultimate_commit = int(last_two[0].get("committed_cursor_after", last_two[0].get("committed_character_end", start)))
    remaining = max(0, total - start)
    durations = [max(1e-6, float(value.get("core_end_sec", 0.0)) - float(value.get("core_start_sec", 0.0))) for value in last_two]
    split = start + int(round(remaining * durations[0] / sum(durations)))
    split = min(total, max(start + 1, split))
    specs = [(last_two[0], start, min(total, split + args.minimum_forward_characters)),
             (last_two[1], max(start, split - args.minimum_forward_characters // 2), total)]
    reruns: list[dict[str, Any]] = []
    combined_by_index: dict[int, dict[str, Any]] = {}
    for trace_row, char_start, char_end in specs:
        try:
            rerun_rows, audit = _attempt_rows_for_rerun(
                processor=processor, model=model, audio=audio, document=document, args=args,
                trace_row=trace_row, character_start=char_start, character_end=char_end,
            )
            reruns.append({
                "window_index": trace_row.get("window_index"), "status": "complete",
                "character_start": char_start, "character_end": char_end,
                "structural": structural_summary(rerun_rows), "audit": audit,
            })
            for value in rerun_rows:
                index = int(value["global_character_index"])
                # Prefer the penultimate result before the proposed split and the final result after it.
                if index not in combined_by_index or index >= split:
                    combined_by_index[index] = value
        except Exception as exc:
            reruns.append({
                "window_index": trace_row.get("window_index"), "status": "failed",
                "character_start": char_start, "character_end": char_end,
                "error": f"{type(exc).__name__}: {exc}",
            })
    combined = [combined_by_index[index] for index in sorted(combined_by_index)]
    case = {
        "baseline_penultimate_commit_cursor": baseline_penultimate_commit,
        "proposed_split_cursor": split,
        "split_delta_units": split - baseline_penultimate_commit,
        "reruns": reruns,
        "combined_structural": structural_summary(combined) if combined else None,
        "combined_gt": metrics_without_details(combined, gt) if combined else None,
        "status": "complete" if all(value["status"] == "complete" for value in reruns) else "partial_failure",
    }
    return {
        "schema_version": "tail_two_window_rollback_shadow_v1",
        "case_count": 1,
        "cases": [case],
        "interpretation": "independent two-window counterfactual; not a production serial merge",
    }


def legacy_r2_comparison(item: dict[str, Any], baseline_payload: dict[str, Any], gt: list[dict[str, Any]]) -> dict[str, Any] | None:
    source = item.get("legacy_r2_alignment_path")
    if not source:
        return None
    path = Path(str(source))
    if not path.is_file():
        return {"status": "missing", "path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    legacy_rows = canonical_final_rows(payload.get("characters", []))
    current_rows = canonical_final_rows(baseline_payload.get("characters", []))
    return {
        "schema_version": "legacy_r2_vs_current_b2_v1",
        "status": "complete",
        "path": str(path.resolve()),
        "legacy_structural": structural_summary(legacy_rows),
        "current_structural": structural_summary(current_rows),
        "legacy_gt": metrics_without_details(legacy_rows, gt),
        "current_gt": metrics_without_details(current_rows, gt),
        "timing_comparison": {
            "common_unit_count": len(set(int(v["global_character_index"]) for v in legacy_rows) & set(int(v["global_character_index"]) for v in current_rows)),
            "legacy_final_end_sec": max((float(v["end_sec"]) for v in legacy_rows), default=None),
            "current_final_end_sec": max((float(v["end_sec"]) for v in current_rows), default=None),
        },
        "interpretation": "legacy R2 is a behavioral reference unless external GT is present",
    }



def raw_minimal_repair_rows(rows: list[dict[str, Any]], *, monotonic: bool) -> list[dict[str, Any]]:
    """Project B2 raw argmax to a lightweight repair without official decoding."""
    raw = stage_rows(rows, "raw")
    result: list[dict[str, Any]] = []
    previous_end = 0.0
    for source in raw:
        row = dict(source)
        start = float(row["start_sec"])
        end = max(start, float(row["end_sec"]))
        if monotonic:
            start = max(start, previous_end)
            end = max(end, start)
        row["start_sec"] = start
        row["end_sec"] = end
        row["raw_minimal_repair"] = "monotonic" if monotonic else "nonnegative_only"
        result.append(row)
        previous_end = end
    return result


def write_raw_decoder_ablations(
    *, item_root: Path, baseline_payload: dict[str, Any], rows: list[dict[str, Any]],
    gt: list[dict[str, Any]],
) -> dict[str, Any]:
    paths: dict[str, str] = {}
    summaries: dict[str, Any] = {}
    for name, monotonic in (
        ("D5_raw_nonnegative_only", False),
        ("D6_raw_minimal_monotonic", True),
    ):
        repaired = raw_minimal_repair_rows(rows, monotonic=monotonic)
        request = {
            "schema_version": "raw_decoder_ablation_request_v1",
            "baseline_request_hash": baseline_payload.get("identity", {}).get("request_hash"),
            "variant": name,
            "monotonic": monotonic,
        }
        path = item_root / "experimental_alignments" / name / "alignment.json"
        payload = write_experimental_alignment(
            output_path=path, baseline_payload=baseline_payload, rows=repaired,
            experiment_name=name,
            experiment_family="raw argmax lightweight repair ablation",
            gt=gt, request=request,
            metadata={"monotonic": monotonic},
        )
        paths[name] = str(path)
        summaries[name] = payload.get("summary", {})
    return {
        "schema_version": "raw_decoder_ablations_v1",
        "alignment_paths": paths,
        "summaries": summaries,
    }

def synthetic_seam_gt_summary(item: dict[str, Any], rows: list[dict[str, Any]], gt: list[dict[str, Any]], *, radius_sec: float = 1.0) -> dict[str, Any] | None:
    seams = [float(value) for value in item.get("synthetic_seams_sec", [])]
    if not seams or not gt:
        return None
    gt_by_index = {_gt_row_index(value): value for value in gt}
    near: list[int] = []
    far: list[int] = []
    for row in rows:
        index = int(row["global_character_index"])
        reference = gt_by_index.get(index)
        if reference is None:
            continue
        midpoint = (float(reference["start_sec"]) + float(reference["end_sec"])) / 2.0
        (near if any(abs(midpoint - seam) <= radius_sec for seam in seams) else far).append(index)
    return {
        "schema_version": "synthetic_seam_gt_summary_v1",
        "seam_count": len(seams), "radius_sec": radius_sec,
        "near_seam_unit_count": len(near), "far_from_seam_unit_count": len(far),
        "near_seam_gt": evaluate_rows(rows, gt, near) if near else None,
        "far_from_seam_gt": evaluate_rows(rows, gt, far) if far else None,
    }

def selected_variants(args: argparse.Namespace, item: dict[str, Any]) -> list[str]:
    """Resolve the actual variant list from the frozen effective config."""
    variant_set = str(item.get("variant_set", "official_primary"))
    if variant_set == "baseline_matrix":
        names = list(args.baseline_matrix_variants)
        if str(args.primary_variant) not in names:
            names.insert(0, str(args.primary_variant))
    elif variant_set == "official_primary":
        names = [str(args.primary_variant)]
    else:
        raise ValueError(f"unknown variant_set for {item.get('item_id')}: {variant_set}")
    unknown = [name for name in names if name not in VARIANTS]
    if unknown:
        raise ValueError(f"unknown configured variants for {item.get('item_id')}: {unknown}")
    # Preserve order but never execute duplicate branches.
    return list(dict.fromkeys(names))



def experiment_item_request(
    args: argparse.Namespace, item: dict[str, Any], checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Frozen identity for deciding whether an entire item can be skipped."""
    resolved = dict(item)
    for key in ("lyrics_path", "audio_path", "gt_path"):
        if resolved.get(key):
            resolved[key] = str(Path(str(resolved[key])).expanduser().resolve())
    branch_hashes = {
        name: canonical_hash(branch_request(args, resolved, name, VARIANTS[name], checkpoint))
        for name in selected_variants(args, resolved)
    }
    gt_path = Path(str(resolved["gt_path"])) if resolved.get("gt_path") else None
    return {
        "schema_version": "inline_realign_item_request_v2_full_suite",
        "item_id": resolved["item_id"],
        "dataset": resolved.get("dataset"),
        "profile": resolved.get("profile"),
        "language": resolved.get("language"),
        "configured_primary_variant": args.primary_variant,
        "configured_baseline_matrix_variants": list(args.baseline_matrix_variants),
        "branch_request_hashes": branch_hashes,
        "gt_sha256": None if gt_path is None or not gt_path.is_file() else SERIAL.sha256(gt_path),
        "shadow": {
            "disabled": bool(args.disable_inline_shadow),
            "max_automatic": int(args.max_shadow_cases_per_item),
            "max_gt_oracle": int(args.max_gt_oracle_cases_per_item),
            "max_clean": int(args.max_clean_control_cases_per_item),
            "context_units": [0, 2, 4],
            "agreement_tolerance_sec": float(args.context_agreement_tolerance_sec),
            "gate": "safe_splice + anomaly_nonincrease; zero-duration relaxed; median fusion",
        },
        "stable": {
            "disabled": bool(args.disable_stable_window_assistance),
            "max_trials": int(args.max_stable_window_trials_per_item),
            "context_units": [0, 2, 4],
            "audio_text_synchronized": True,
        },
        "text_dosage": {
            "disabled": bool(args.disable_forced_expansion_trials),
            "max_trials": int(args.max_expansion_trials_per_item),
            "end_deltas": list(args.text_dosage_end_deltas),
            "start_deltas": list(args.text_dosage_start_deltas),
            "ratios": [1.25, 1.50],
        },
        "deferred": {
            "disabled": bool(args.disable_pending_confirmation_shadow),
            "max_cases": int(args.max_pending_shadow_cases_per_item),
            "max_windows": int(args.deferred_max_windows),
            "max_seconds": float(args.deferred_max_seconds),
            "max_units": int(args.deferred_max_units),
        },
        "raw_decoder_ablations": ["nonnegative_only", "minimal_monotonic"],
        "checkpoint": checkpoint,
    }


def can_resume_skip_item(
    *, resume: bool, force: bool, item_id: str, restart_items: set[str], complete_and_valid: bool,
) -> bool:
    """Return whether an item may be reused without entering model execution."""
    return bool(resume and not force and item_id not in restart_items and complete_and_valid)


def expected_item_outputs(args: argparse.Namespace, item: dict[str, Any], item_root: Path) -> list[Path]:
    outputs = [item_root / "item_summary.json"]
    variants = selected_variants(args, item)
    outputs.extend(item_root / "branches" / name / "alignment.json" for name in variants)
    if str(args.primary_variant) in variants:
        outputs.extend([
            item_root / "experimental_alignments" / "D5_raw_nonnegative_only" / "alignment.json",
            item_root / "experimental_alignments" / "D6_raw_minimal_monotonic" / "alignment.json",
        ])
        if not args.disable_inline_shadow:
            outputs.extend([
                item_root / "inline_realign_shadow.json",
                item_root / "experimental_alignments" / "R1_immediate_inline" / "alignment.json",
                item_root / "experimental_alignments" / "R4_context_median_fused" / "alignment.json",
            ])
        if item.get("profile") != "local_segment" and not args.disable_stable_window_assistance:
            outputs.extend([
                item_root / "stable_window_assistance.json",
                item_root / "stable_window_assistance_trials.json",
                item_root / "experimental_alignments" / "S0_stable_anchor_only" / "alignment.json",
                item_root / "experimental_alignments" / "S1_stable_sync_exact" / "alignment.json",
                item_root / "experimental_alignments" / "S2_stable_sync_minus2" / "alignment.json",
                item_root / "experimental_alignments" / "S3_stable_sync_minus4" / "alignment.json",
            ])
        if item.get("profile") != "local_segment" and not args.disable_forced_expansion_trials:
            outputs.append(item_root / "text_dosage_trials.json")
        if not args.disable_pending_confirmation_shadow and not args.disable_inline_shadow:
            outputs.extend([
                item_root / "pending_confirmation_shadow.json",
                item_root / "experimental_alignments" / "R2_deferred" / "alignment.json",
                item_root / "experimental_alignments" / "R3_inline_deferred" / "alignment.json",
            ])
    return outputs

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--r2-checkpoint", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--language", type=normalize_alignment_language, default="Chinese")
    p.add_argument("--primary-variant", default="B4_60_silence_official")
    p.add_argument(
        "--baseline-matrix-variants",
        default=",".join(VARIANTS),
        help="comma-separated ordered branch IDs for long-serial items",
    )
    p.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    p.add_argument("--left-context-sec", type=float, default=10.0)
    p.add_argument("--right-context-sec", type=float, default=10.0)
    p.add_argument("--future-line-padding", type=int, default=1)
    p.add_argument("--minimum-forward-characters", type=int, default=64)
    p.add_argument("--future-character-ratio", type=float, default=1.35)
    p.add_argument("--max-candidate-expansions", type=int, default=4)
    p.add_argument("--boundary-start-tolerance-sec", type=float, default=0.32)
    p.add_argument("--seam-tolerance-sec", type=float, default=0.16)
    p.add_argument("--silent-active-ratio-max", type=float, default=0.01)
    p.add_argument("--silent-peak-margin-db", type=float, default=3.0)
    p.add_argument("--silent-min-sustained-sec", type=float, default=0.40)
    p.add_argument("--startup-vocal-preroll-sec", type=float, default=2.0)
    p.add_argument("--startup-minimum-forward-characters", type=int, default=24)
    p.add_argument("--silence-boundary-min-sec", type=float, default=0.8)
    p.add_argument("--strong-silence-anchor-sec", type=float, default=1.5)
    p.add_argument("--strict-silence-boundary-sec", type=float, default=1.5)
    p.add_argument("--silence-compression-min-sec", type=float, default=1.5)
    p.add_argument("--silence-compression-padding-sec", type=float, default=0.20)
    p.add_argument("--silence-boundary-search-sec", type=float, default=6.0)
    p.add_argument("--leading-silence-min-sec", type=float, default=2.0)
    p.add_argument("--tail-min-core-sec", type=float, default=18.0)
    p.add_argument("--minimum-core-sec", type=float, default=12.0)
    p.add_argument("--attempt-probe-max-rows", type=int, default=48)
    p.add_argument("--stable-segment-min-units", type=int, default=2)
    p.add_argument("--stable-segment-confidence-quantile", type=float, default=0.50)
    p.add_argument("--stable-raw-official-tolerance-sec", type=float, default=0.16)
    p.add_argument("--stable-context-tolerance-sec", type=float, default=0.24)
    p.add_argument("--stable-prefix-reproduction-tolerance-sec", type=float, default=0.24)
    p.add_argument("--stable-prefix-minimum-observed-units", type=int, default=2)
    p.add_argument("--stable-prefix-minimum-observed-ratio", type=float, default=0.50)
    p.add_argument("--stable-left-overlap-units", type=int, default=8)
    p.add_argument("--deferred-max-windows", type=int, default=3)
    p.add_argument("--deferred-max-seconds", type=float, default=120.0)
    p.add_argument("--deferred-max-units", type=int, default=320)
    p.add_argument("--context-agreement-tolerance-sec", type=float, default=0.24)
    p.add_argument("--gt-oracle-error-threshold-sec", type=float, default=0.24)
    p.add_argument("--max-gt-oracle-cases-per-item", type=int, default=3)
    p.add_argument("--max-shadow-cases-per-item", type=int, default=8)
    p.add_argument("--max-stable-window-trials-per-item", type=int, default=2)
    p.add_argument("--max-expansion-trials-per-item", "--max-text-dosage-trials-per-item", dest="max_expansion_trials_per_item", type=int, default=1)
    p.add_argument("--text-dosage-end-deltas", default="-8,-4,-2,0,2,4,8,16")
    p.add_argument("--text-dosage-start-deltas", default="-4,-2,0,2,4")
    p.add_argument("--max-clean-control-cases-per-item", type=int, default=2)
    p.add_argument("--max-pending-shadow-cases-per-item", type=int, default=3)
    p.add_argument("--max-tail-rollback-cases-per-item", type=int, default=2)
    p.add_argument("--disable-stable-window-assistance", action="store_true")
    p.add_argument("--disable-forced-expansion-trials", "--disable-text-dosage-trials", dest="disable_forced_expansion_trials", action="store_true")
    p.add_argument("--disable-pending-confirmation-shadow", action="store_true")
    p.add_argument("--disable-tail-rollback-shadow", action="store_true")
    p.add_argument("--construct-incomplete-cases", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--max-case-preview-rows", type=int, default=64)
    p.add_argument("--disable-inline-shadow", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--resume", action="store_true", help="skip complete items whose frozen request identity and outputs still match")
    p.add_argument("--retry-failed-only", action="store_true")
    p.add_argument("--restart-item", action="append", default=[])
    return p


def main() -> int:
    args = parser().parse_args()
    args.primary_variant = str(args.primary_variant).strip()
    args.baseline_matrix_variants = tuple(
        value.strip() for value in str(args.baseline_matrix_variants).split(",") if value.strip()
    )
    if args.primary_variant not in VARIANTS:
        raise ValueError(f"unknown --primary-variant: {args.primary_variant}")
    unknown_variants = [name for name in args.baseline_matrix_variants if name not in VARIANTS]
    if unknown_variants:
        raise ValueError(f"unknown --baseline-matrix-variants: {unknown_variants}")
    args.text_dosage_end_deltas = tuple(int(value.strip()) for value in str(args.text_dosage_end_deltas).split(",") if value.strip())
    args.text_dosage_start_deltas = tuple(int(value.strip()) for value in str(args.text_dosage_start_deltas).split(",") if value.strip())
    args.manifest = args.manifest.expanduser().resolve()
    args.out_root = args.out_root.expanduser().resolve()
    args.r2_checkpoint = args.r2_checkpoint.expanduser().resolve()
    for path in (args.manifest, args.r2_checkpoint):
        if not path.exists():
            raise FileNotFoundError(path)
    items = read_jsonl(args.manifest)
    if not items:
        raise ValueError("empty experiment manifest")
    selected_languages = {
        normalize_alignment_language(str(item.get("language") or args.language))
        for item in items
    }
    if "Japanese" in selected_languages and importlib.util.find_spec("nagisa") is None:
        raise RuntimeError(
            "Japanese Demo items are selected but the required Nagisa tokenizer is unavailable; "
            "install it in the experiment environment with: pip install nagisa"
        )
    args.out_root.mkdir(parents=True, exist_ok=True)
    status_path = args.out_root / "run_status.jsonl"
    checkpoint = SERIAL.checkpoint_identity("lora", args.r2_checkpoint)
    run_state = RunState(args.out_root)
    restart_items = {str(value) for value in args.restart_item}
    prepared: list[tuple[dict[str, Any], dict[str, Any], str, list[Path]]] = []
    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skipped_item_count = 0
    for source in items:
        resolved = dict(source)
        for key in ("lyrics_path", "audio_path", "gt_path"):
            if resolved.get(key):
                resolved[key] = str(Path(str(resolved[key])).expanduser().resolve())
        item_id = str(resolved["item_id"])
        item_root = args.out_root / "items" / item_id
        request = experiment_item_request(args, resolved, checkpoint)
        request_hash = canonical_hash(request)
        outputs = expected_item_outputs(args, resolved, item_root)
        state_payload = read_json_if_exists(run_state.item_path(item_id))
        complete_and_valid = run_state.item_is_complete(
            item_id, request_hash=request_hash, outputs=outputs
        )
        if args.retry_failed_only and item_id not in restart_items:
            if state_payload.get("status") == "failed":
                prepared.append((resolved, request, request_hash, outputs))
                continue
            if not complete_and_valid:
                raise RuntimeError(
                    "--retry-failed-only encountered an item that is neither a valid complete item "
                    f"nor a recorded failure: {item_id} status={state_payload.get('status')!r}. "
                    "Use ordinary --resume so incomplete/pending items can be repaired."
                )
        can_skip = can_resume_skip_item(
            resume=args.resume, force=args.force, item_id=item_id,
            restart_items=restart_items, complete_and_valid=complete_and_valid,
        )
        if can_skip:
            summary = read_json_if_exists(item_root / "item_summary.json")
            if not summary:
                raise RuntimeError(f"valid item state lacks item_summary.json: {item_id}")
            summaries.append(summary)
            skipped_item_count += 1
            append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "resume_skipped_complete"})
        else:
            prepared.append((resolved, request, request_hash, outputs))

    if not prepared:
        aggregate = {
            "schema_version": "inline_realign_experiment_summary_v2_resumable",
            "created_at": utc_now(), "manifest": str(args.manifest),
            "item_count": len(items), "completed_item_count": len(summaries),
            "failed_item_count": 0, "resume_skipped_item_count": skipped_item_count,
            "executed_item_count": 0, "variants": VARIANTS, "items": summaries, "failures": [],
        }
        atomic_json(args.out_root / "experiment_summary.json", aggregate)
        atomic_json(args.out_root / "complete.json", {"status": "complete", **aggregate})
        print(json.dumps({"stage": "experiment", "status": "resume_all_items_complete", "skipped": skipped_item_count}, ensure_ascii=False), flush=True)
        return 0

    load_args = SimpleNamespace(
        model=str(args.model), revision=args.revision,
        local_files_only=args.local_files_only, cache_dir=args.cache_dir,
        device=args.device,
    )
    processor, model = SERIAL.load_model(load_args, "lora", args.r2_checkpoint)
    try:
        for item_ordinal, prepared_item in enumerate(prepared, 1):
            item, item_request_payload, item_request_hash, item_expected_outputs = prepared_item
            item_id = str(item["item_id"])
            item_root = args.out_root / "items" / item_id
            run_state.begin_item(item_id, request=item_request_payload, outputs=item_expected_outputs)
            (item_root / "failure.json").unlink(missing_ok=True)
            append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "running", "item_ordinal": item_ordinal, "item_total": len(prepared)})
            atomic_json(args.out_root / "experiment_live_status.json", {
                "schema_version": "inline_realign_experiment_live_status_v1",
                "time": utc_now(), "status": "running", "item_id": item_id,
                "item_ordinal": item_ordinal, "item_total": len(prepared),
            })
            print(json.dumps({"stage": "experiment", "status": "item_start", "item": f"{item_ordinal}/{len(prepared)}", "item_id": item_id}, ensure_ascii=False), flush=True)
            try:
                lyrics_path = Path(item["lyrics_path"]).resolve()
                audio_path = Path(item["audio_path"]).resolve()
                gt_path = Path(item["gt_path"]).resolve() if item.get("gt_path") else None
                for path in (lyrics_path, audio_path):
                    if not path.is_file():
                        raise FileNotFoundError(path)
                if gt_path is not None and not gt_path.is_file():
                    raise FileNotFoundError(gt_path)
                item = {
                    **item,
                    "lyrics_path": str(lyrics_path),
                    "audio_path": str(audio_path),
                    "gt_path": None if gt_path is None else str(gt_path),
                }
                item_language = normalize_alignment_language(str(item.get("language") or args.language))
                item = {**item, "language": item_language}
                document = parse_lyrics_text(
                    lyrics_path.read_text(encoding="utf-8-sig"), language=item_language
                )
                gt = load_gt(gt_path)
                if gt and len(gt) != len(document.characters):
                    raise ValueError(
                        f"{item_id}: lyrics/GT count mismatch {len(document.characters)} != {len(gt)}"
                    )
                audio = decode_audio(audio_path)
                branch_summaries: dict[str, Any] = {}
                primary_rows: list[dict[str, Any]] | None = None
                primary_trace: list[dict[str, Any]] | None = None
                primary_payload: dict[str, Any] | None = None
                for variant_name in selected_variants(args, item):
                    print(json.dumps({"stage": "experiment", "status": "branch_start", "item": f"{item_ordinal}/{len(prepared)}", "item_id": item_id, "branch": variant_name}, ensure_ascii=False), flush=True)
                    atomic_json(args.out_root / "experiment_live_status.json", {
                        "schema_version": "inline_realign_experiment_live_status_v1",
                        "time": utc_now(), "status": "branch_running", "item_id": item_id,
                        "item_ordinal": item_ordinal, "item_total": len(prepared), "branch": variant_name,
                    })
                    rows, trace, payload = run_variant(
                        args=args, item=item, variant_name=variant_name,
                        variant=VARIANTS[variant_name], processor=processor, model=model,
                        audio=audio, document=document, gt=gt, checkpoint=checkpoint,
                        item_root=item_root,
                    )
                    branch_summaries[variant_name] = payload["summary"]
                    print(json.dumps({"stage": "experiment", "status": "branch_complete", "item_id": item_id, "branch": variant_name, "window_count": payload.get("summary", {}).get("window_count")}, ensure_ascii=False), flush=True)
                    if variant_name == str(args.primary_variant):
                        primary_rows, primary_trace, primary_payload = rows, trace, payload
                if (
                    item.get("variant_set") == "official_primary"
                    and str(args.primary_variant) == "B2_30_silence_official"
                    and primary_payload is not None
                    and int((primary_payload.get("planner_divergence") or {}).get("diverged_window_count", 0)) > 0
                ):
                    rows, trace, payload = run_variant(
                        args=args, item=item, variant_name="B3_30_silence_raw_control",
                        variant=VARIANTS["B3_30_silence_raw_control"], processor=processor, model=model,
                        audio=audio, document=document, gt=gt, checkpoint=checkpoint,
                        item_root=item_root,
                    )
                    branch_summaries["B3_30_silence_raw_control"] = payload["summary"]
                shadow_payload = None
                assistance_payload = None
                assistance_trials = None
                expansion_payload = None
                pending_payload = None
                tail_rollback_payload = None
                legacy_comparison_payload = None
                seam_gt_payload = None
                incomplete_summary = None
                automatic_incomplete_summary = None
                raw_decoder_ablations = None
                baseline_hash = None if primary_payload is None else primary_payload.get("identity", {}).get("request_hash")
                if primary_payload is not None and primary_rows is not None:
                    raw_decoder_ablations = write_raw_decoder_ablations(
                        item_root=item_root, baseline_payload=primary_payload, rows=primary_rows, gt=gt,
                    )
                    atomic_json(item_root / "raw_decoder_ablations.json", raw_decoder_ablations)
                    legacy_comparison_payload = legacy_r2_comparison(item, primary_payload, gt)
                    if legacy_comparison_payload is not None:
                        atomic_json(item_root / "legacy_r2_comparison.json", legacy_comparison_payload)
                    seam_gt_payload = synthetic_seam_gt_summary(item, primary_rows, gt)
                    if seam_gt_payload is not None:
                        # Remove verbose per-unit details before storing the compact seam audit.
                        for key in ("near_seam_gt", "far_from_seam_gt"):
                            if isinstance(seam_gt_payload.get(key), dict):
                                seam_gt_payload[key].pop("details", None)
                        atomic_json(item_root / "synthetic_seam_gt_summary.json", seam_gt_payload)
                if not args.disable_inline_shadow and primary_rows is not None and primary_trace is not None:
                    shadow_request = {
                        "schema_version": "inline_realign_shadow_request_v4_counterfactual_gate_and_full_alignment",
                        "baseline_request_hash": baseline_hash,
                        "max_shadow_cases_per_item": args.max_shadow_cases_per_item,
                        "max_gt_oracle_cases_per_item": args.max_gt_oracle_cases_per_item,
                        "max_clean_control_cases_per_item": args.max_clean_control_cases_per_item,
                        "context_units": [0, 2, 4],
                        "gt_oracle_error_threshold_sec": args.gt_oracle_error_threshold_sec,
                        "stable_segment_min_units": args.stable_segment_min_units,
                        "stable_segment_confidence_quantile": args.stable_segment_confidence_quantile,
                        "stable_raw_official_tolerance_sec": args.stable_raw_official_tolerance_sec,
                        "stable_context_tolerance_sec": args.stable_context_tolerance_sec,
                        "context_agreement_tolerance_sec": args.context_agreement_tolerance_sec,
                    }
                    shadow_path = item_root / "inline_realign_shadow.json"
                    shadow_payload = current_auxiliary_payload(
                        shadow_path, canonical_hash(shadow_request), force=args.force,
                    )
                    if shadow_payload is None:
                        shadow_payload = run_inline_shadow(
                            args=args, item=item, processor=processor, model=model,
                            audio=audio, document=document, gt=gt, rows=primary_rows,
                            trace=primary_trace, out_path=shadow_path, baseline_payload=primary_payload,
                            request=shadow_request,
                        )
                if primary_rows is not None and primary_trace is not None and not args.disable_stable_window_assistance:
                    assistance_request = {
                        "schema_version": "stable_window_assistance_request_v3_local_subsegment",
                        "baseline_request_hash": baseline_hash,
                        "stable_segment_min_units": args.stable_segment_min_units,
                        "stable_segment_confidence_quantile": args.stable_segment_confidence_quantile,
                        "stable_raw_official_tolerance_sec": args.stable_raw_official_tolerance_sec,
                        "stable_context_tolerance_sec": args.stable_context_tolerance_sec,
                        "stable_prefix_reproduction_tolerance_sec": args.stable_prefix_reproduction_tolerance_sec,
                        "stable_prefix_minimum_observed_units": args.stable_prefix_minimum_observed_units,
                        "stable_prefix_minimum_observed_ratio": args.stable_prefix_minimum_observed_ratio,
                    }
                    assistance_path = item_root / "stable_window_assistance.json"
                    assistance_payload = current_auxiliary_payload(
                        assistance_path, canonical_hash(assistance_request), force=args.force,
                    )
                    if assistance_payload is None:
                        assistance_payload = with_auxiliary_identity(
                            stable_window_assistance_summary(
                                args=args, rows=primary_rows, trace=primary_trace, gt=gt,
                                total_characters=len(document.characters),
                            ),
                            assistance_request,
                        )
                        atomic_json(assistance_path, assistance_payload)

                    trial_request = build_stable_trial_request(
                        args=args, assistance_payload=assistance_payload,
                    )
                    trial_path = item_root / "stable_window_assistance_trials.json"
                    assistance_trials = current_auxiliary_payload(
                        trial_path, canonical_hash(trial_request), force=args.force,
                    )
                    if assistance_trials is None:
                        try:
                            trial_result = run_stable_window_assistance_trials(
                                args=args, processor=processor, model=model, audio=audio,
                                document=document, gt=gt, rows=primary_rows, trace=primary_trace,
                                assistance=assistance_payload, item=item,
                                baseline_payload=primary_payload, item_root=item_root,
                            )
                        except Exception as exc:
                            trial_result = {
                                "schema_version": "stable_window_assistance_trials_v3_isolated_failure",
                                "status": "failed",
                                "trial_count": 0,
                                "successful_trial_count": 0,
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(limit=12),
                                "trials": [],
                            }
                        assistance_trials = with_auxiliary_identity(trial_result, trial_request)
                        atomic_json(trial_path, assistance_trials)
                if (
                    primary_trace is not None
                    and item.get("profile") != "local_segment"
                    and not args.disable_forced_expansion_trials
                ):
                    expansion_request = {
                        "schema_version": "text_dosage_request_v3_under_exact_over_start_end",
                        "baseline_request_hash": baseline_hash,
                        "max_trials_per_item": args.max_expansion_trials_per_item,
                        "end_deltas": list(args.text_dosage_end_deltas),
                        "start_deltas": list(args.text_dosage_start_deltas),
                        "ratios": [1.25, 1.50],
                        "attempt_probe_max_rows": args.attempt_probe_max_rows,
                    }
                    expansion_path = item_root / "text_dosage_trials.json"
                    expansion_payload = current_auxiliary_payload(
                        expansion_path, canonical_hash(expansion_request), force=args.force,
                    )
                    if expansion_payload is None:
                        try:
                            expansion_result = run_forced_expansion_trials(
                                args=args, processor=processor, model=model, audio=audio,
                                document=document, gt=gt, rows=primary_rows or [], trace=primary_trace,
                                assistance=assistance_payload,
                            )
                        except Exception as exc:
                            expansion_result = {
                                "schema_version": "text_dosage_trials_v3_isolated_failure",
                                "status": "failed",
                                "window_count": 0,
                                "variant_run_count": 0,
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(limit=12),
                                "windows": [],
                            }
                        expansion_payload = with_auxiliary_identity(expansion_result, expansion_request)
                        atomic_json(expansion_path, expansion_payload)
                if (
                    primary_rows is not None and primary_trace is not None and shadow_payload is not None
                    and not args.disable_pending_confirmation_shadow
                ):
                    pending_request = {
                        "schema_version": "deferred_realign_shadow_request_v2_anchor_recovered_bounded",
                        "baseline_request_hash": baseline_hash,
                        "shadow_request_hash": shadow_payload.get("identity", {}).get("request_hash"),
                        "max_cases_per_item": args.max_pending_shadow_cases_per_item,
                        "three_context_units": [0, 2, 4],
                        "max_windows": args.deferred_max_windows,
                        "max_seconds": args.deferred_max_seconds,
                        "max_units": args.deferred_max_units,
                    }
                    pending_path = item_root / "pending_confirmation_shadow.json"
                    pending_payload = current_auxiliary_payload(
                        pending_path, canonical_hash(pending_request), force=args.force,
                    )
                    if pending_payload is None:
                        try:
                            immediate_alignment = read_json_if_exists(
                                item_root / "experimental_alignments" / "R1_immediate_inline" / "alignment.json"
                            )
                            pending_result = run_pending_confirmation_shadow(
                                args=args, item=item, processor=processor, model=model, audio=audio,
                                document=document, gt=gt, rows=primary_rows, trace=primary_trace,
                                shadow_payload=shadow_payload, baseline_payload=primary_payload,
                                item_root=item_root,
                                immediate_rows=list(immediate_alignment.get("characters", [])) or primary_rows,
                            )
                        except Exception as exc:
                            pending_result = {
                                "schema_version": "deferred_realign_shadow_v2_isolated_failure",
                                "status": "failed", "case_count": 0,
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(limit=12), "cases": [],
                            }
                        pending_payload = with_auxiliary_identity(pending_result, pending_request)
                        atomic_json(pending_path, pending_payload)
                if (
                    primary_rows is not None and primary_trace is not None
                    and item.get("profile") != "local_segment"
                    and not args.disable_tail_rollback_shadow
                ):
                    tail_request = {
                        "schema_version": "tail_two_window_rollback_shadow_request_v1",
                        "baseline_request_hash": baseline_hash,
                        "max_cases_per_item": args.max_tail_rollback_cases_per_item,
                    }
                    tail_path = item_root / "tail_two_window_rollback_shadow.json"
                    tail_rollback_payload = current_auxiliary_payload(
                        tail_path, canonical_hash(tail_request), force=args.force,
                    )
                    if tail_rollback_payload is None:
                        try:
                            tail_result = run_tail_rollback_shadow(
                                args=args, audio=audio, document=document, gt=gt, rows=primary_rows,
                                trace=primary_trace, processor=processor, model=model,
                            )
                        except Exception as exc:
                            tail_result = {
                                "schema_version": "tail_two_window_rollback_shadow_v1_isolated_failure",
                                "status": "failed", "case_count": 0,
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(limit=12), "cases": [],
                            }
                        tail_rollback_payload = with_auxiliary_identity(tail_result, tail_request)
                        atomic_json(tail_path, tail_rollback_payload)
                if args.construct_incomplete_cases and primary_payload is not None:
                    constructed_candidates: list[dict[str, Any]] = []
                    if item.get("incomplete_exercise") and primary_rows:
                        tail_units = min(8, len(primary_rows))
                        constructed_candidates = [{
                            "window_index": int(primary_rows[-1].get("owner_window_index", -1)),
                            "character_start": len(primary_rows) - tail_units,
                            "character_end": len(primary_rows) - 1,
                            "reasons": ["constructed_incomplete_tail_exercise"],
                            "severity": tail_units,
                            "candidate_source": "constructed_incomplete_exercise",
                            "range_source": "deterministic_tail_exercise",
                        }]
                    incomplete_summary = construct_incomplete_guard(
                        item=item, baseline_payload=primary_payload, candidates=constructed_candidates,
                        out_path=item_root / "incomplete_guard" / "alignment.json", gt=gt,
                        constructed_for_validation=True, automatic_shadow_only=False,
                    )
                    automatic_candidates = []
                    if shadow_payload is not None:
                        automatic_candidates = [
                            decision["trigger"] for decision in shadow_payload.get("decisions", [])
                            if decision.get("trigger")
                            and decision.get("candidate_source") == "automatic_precommit"
                            and not decision.get("automatic_gate_accepted_shadow")
                            and int((decision.get("trigger") or {}).get("severity", 0)) >= 4
                        ]
                    automatic_incomplete_summary = construct_incomplete_guard(
                        item=item, baseline_payload=primary_payload, candidates=automatic_candidates,
                        out_path=item_root / "automatic_incomplete_shadow" / "alignment.json", gt=gt,
                        constructed_for_validation=False, automatic_shadow_only=True,
                    )
                item_summary = {
                    "item_id": item_id,
                    "dataset": item["dataset"],
                    "profile": item.get("profile"),
                    "language": item.get("language"),
                    "alignment_unit_mode": document.unit_mode,
                    "selection_role": item.get("selection_role"),
                    "variant_set": item.get("variant_set"),
                    "duration_bucket": item.get("duration_bucket"),
                    "synthetic_target_duration_sec": item.get("synthetic_target_duration_sec"),
                    "synthetic_seams_sec": item.get("synthetic_seams_sec"),
                    "legacy_r2_alignment_path": item.get("legacy_r2_alignment_path"),
                    "branches": branch_summaries,
                    "inline_shadow": None if shadow_payload is None else {
                        key: value for key, value in shadow_payload.items() if key != "decisions"
                    },
                    "stable_window_assistance": None if assistance_payload is None else {
                        key: value for key, value in assistance_payload.items() if key != "transitions"
                    },
                    "stable_window_assistance_trials": None if assistance_trials is None else {
                        key: value for key, value in assistance_trials.items() if key != "trials"
                    },
                    "text_dosage_trials": None if expansion_payload is None else {
                        key: value for key, value in expansion_payload.items() if key not in {"windows", "results"}
                    },
                    "forced_expansion_trials_legacy_alias": None,
                    "deferred_realign_shadow": None if pending_payload is None else {
                        key: value for key, value in pending_payload.items() if key != "cases"
                    },
                    "pending_confirmation_shadow": None if pending_payload is None else {
                        key: value for key, value in pending_payload.items() if key != "cases"
                    },
                    "tail_two_window_rollback_shadow": None if tail_rollback_payload is None else {
                        key: value for key, value in tail_rollback_payload.items() if key != "cases"
                    },
                    "raw_decoder_ablations": raw_decoder_ablations,
                    "legacy_r2_comparison": legacy_comparison_payload,
                    "synthetic_seam_gt_summary": seam_gt_payload,
                    "incomplete_guard": incomplete_summary,
                    "automatic_incomplete_shadow": automatic_incomplete_summary,
                }
                item_summary["item_identity"] = {
                    "request_hash": item_request_hash,
                    "request": item_request_payload,
                    "resume_safe": True,
                }
                atomic_json(item_root / "item_summary.json", item_summary)
                run_state.finish_item(
                    item_id, status="complete", request_hash=item_request_hash,
                    outputs=item_expected_outputs,
                )
                summaries.append(item_summary)
                append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "complete", "item_ordinal": item_ordinal, "item_total": len(prepared)})
                print(json.dumps({"stage": "experiment", "status": "item_complete", "item": f"{item_ordinal}/{len(prepared)}", "item_id": item_id}, ensure_ascii=False), flush=True)
            except Exception as exc:
                failure = {
                    "item_id": item_id,
                    "dataset": item.get("dataset"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                failures.append(failure)
                atomic_json(item_root / "failure.json", failure)
                run_state.finish_item(
                    item_id, status="failed", request_hash=item_request_hash,
                    outputs=item_expected_outputs, error=f"{type(exc).__name__}: {exc}",
                )
                append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "failed", "error": str(exc), "item_ordinal": item_ordinal, "item_total": len(prepared)})
                print(json.dumps({"stage": "experiment", "status": "item_failed", "item": f"{item_ordinal}/{len(prepared)}", "item_id": item_id, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
                if args.fail_fast:
                    raise
    finally:
        del model, processor
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    aggregate = {
        "schema_version": "inline_realign_experiment_summary_v2_resumable_full_suite",
        "created_at": utc_now(),
        "manifest": str(args.manifest),
        "item_count": len(items),
        "completed_item_count": len(summaries),
        "failed_item_count": len(failures),
        "resume_skipped_item_count": skipped_item_count,
        "executed_item_count": len(prepared),
        "variants": VARIANTS,
        "items": summaries,
        "failures": failures,
        "interpretation_limits": [
            "Inline realign is shadow-only in this implementation; no serial result is modified.",
            "Demo items without GT support structural and listening review, not accuracy claims.",
            "M4Singer synthetic-long seams must be reported separately from natural MIR-1K songs.",
            "GT-oracle targets test local-realign capability and must not be reported as an automatic detector result.",
            "Constructed incomplete outputs are fail-closed validation artifacts, not claims that every source item is incomplete.",
            "Automatic incomplete, pending confirmation, and two-window tail rollback remain shadow-only counterfactuals.",
            "Clean-control local reruns measure harm and are never eligible for writeback in this experiment.",
        ],
    }
    atomic_json(args.out_root / "experiment_summary.json", aggregate)
    atomic_json(args.out_root / "complete.json", {
        "status": "complete" if not failures else "partial_failure",
        "created_at": utc_now(),
        "completed_item_count": len(summaries),
        "failed_item_count": len(failures),
    })
    print(json.dumps({
        "status": "complete" if not failures else "partial_failure",
        "out_root": str(args.out_root),
        "completed_item_count": len(summaries),
        "failed_item_count": len(failures),
    }, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
