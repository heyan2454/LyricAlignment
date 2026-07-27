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

VARIANTS: dict[str, dict[str, Any]] = {
    "B0_60_fixed_official": {
        "core_sec": 60.0, "silence_aware": False, "serial_control": "same",
        "meaning": "old-style 60 s fixed window; official controls its own lyric progress",
    },
    "B1_30_fixed_official": {
        "core_sec": 30.0, "silence_aware": False, "serial_control": "same",
        "meaning": "30 s fixed window; official controls its own lyric progress",
    },
    "B2_30_silence_official": {
        "core_sec": 30.0, "silence_aware": True, "serial_control": "same",
        "meaning": "30 s silence-aware window; official controls its own lyric progress",
    },
    "B3_30_silence_raw_control": {
        "core_sec": 30.0, "silence_aware": True, "serial_control": "raw",
        "meaning": "30 s silence-aware window; raw controls ownership/cursor, official supplies output time",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def metrics_without_details(rows: list[dict[str, Any]], gt: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not gt:
        return None
    result = evaluate_rows(rows, gt)
    result.pop("details", None)
    return result


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
    return SimpleNamespace(
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
        core_sec=float(variant["core_sec"]),
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
        future_line_padding=args.future_line_padding,
        minimum_forward_characters=args.minimum_forward_characters,
        future_character_ratio=args.future_character_ratio,
        max_candidate_expansions=args.max_candidate_expansions,
        boundary_start_tolerance_sec=args.boundary_start_tolerance_sec,
        seam_tolerance_sec=args.seam_tolerance_sec,
        capture_shadow_rows=True,
        capture_attempt_probes=True,
        attempt_probe_max_rows=args.attempt_probe_max_rows,
        stable_segment_min_units=args.stable_segment_min_units,
        stable_segment_confidence_quantile=args.stable_segment_confidence_quantile,
        stable_raw_official_tolerance_sec=args.stable_raw_official_tolerance_sec,
        stable_context_tolerance_sec=args.stable_context_tolerance_sec,
        stable_prefix_reproduction_tolerance_sec=args.stable_prefix_reproduction_tolerance_sec,
        stable_prefix_minimum_observed_units=args.stable_prefix_minimum_observed_units,
        stable_prefix_minimum_observed_ratio=args.stable_prefix_minimum_observed_ratio,
        decoder_kind="official",
        serial_control_decoder_kind=str(variant["serial_control"]),
        skip_silent_windows=True,
        silent_active_ratio_max=args.silent_active_ratio_max,
        silent_peak_margin_db=args.silent_peak_margin_db,
        silent_min_sustained_sec=args.silent_min_sustained_sec,
        startup_vocal_preroll_sec=args.startup_vocal_preroll_sec,
        startup_minimum_forward_characters=args.startup_minimum_forward_characters,
        silence_aware_window_plan=bool(variant["silence_aware"]),
        silence_boundary_min_sec=args.silence_boundary_min_sec,
        strong_silence_anchor_sec=args.strong_silence_anchor_sec,
        silence_boundary_search_sec=args.silence_boundary_search_sec,
        leading_silence_min_sec=args.leading_silence_min_sec,
        tail_min_core_sec=args.tail_min_core_sec,
        minimum_core_sec=args.minimum_core_sec,
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
    return {
        "schema_version": "inline_realign_baseline_request_v3_localized_diagnostics",
        "item_id": item["item_id"],
        "dataset": item["dataset"],
        "profile": item.get("profile"),
        "lyrics_path": item["lyrics_path"],
        "lyrics_sha256": SERIAL.sha256(Path(item["lyrics_path"])),
        "audio_path": item["audio_path"],
        "audio_sha256": SERIAL.sha256(Path(item["audio_path"])),
        "model": str(args.model),
        "revision": args.revision,
        "checkpoint": checkpoint,
        "variant": variant_name,
        "variant_spec": variant,
        "parameters": {
            "left_context_sec": args.left_context_sec,
            "right_context_sec": args.right_context_sec,
            "future_character_ratio": args.future_character_ratio,
            "max_candidate_expansions": args.max_candidate_expansions,
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
    write_alignment_bundle(alignment_path, payload)
    atomic_json(branch_root / "summary.json", payload["summary"])
    return rows, trace, payload


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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    input_start = float(trace_row.get("effective_input_start_sec", trace_row.get("input_start_sec", 0.0)))
    input_end = float(trace_row.get("input_end_sec", trace_row.get("effective_input_end_sec", 0.0)))
    sample_start = max(0, int(round(input_start * 16000)))
    sample_end = min(len(audio), int(round(input_end * 16000)))
    return SERIAL.infer_slice(
        processor=processor, model=model, audio=audio[sample_start:sample_end], document=document,
        character_start=character_start, character_end=character_end,
        global_audio_offset_sec=input_start, args=local_serial_args(args),
    )


def run_stable_window_assistance_trials(
    *, args: argparse.Namespace, processor: Any, model: Any, audio: Any, document: Any,
    gt: list[dict[str, Any]], rows: list[dict[str, Any]], trace: list[dict[str, Any]],
    assistance: dict[str, Any],
) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    by_window = {int(row.get("window_index", -1)): row for row in trace}
    for transition in assistance.get("transitions", []):
        if len(trials) >= args.max_stable_window_trials_per_item:
            break
        if not transition.get("informative_cursor_change"):
            continue
        target_window = int(transition["to_window_index"]); trace_row = by_window.get(target_window)
        prefix_info = transition.get("prefix_segment")
        if trace_row is None or prefix_info is None:
            continue
        character_start = int(transition["stable_prefix_input_cursor"])
        character_end = int(trace_row.get("candidate_character_end", len(document.characters)))
        try:
            rerun_rows, audit = _attempt_rows_for_rerun(
                processor=processor, model=model, audio=audio, document=document, args=args,
                trace_row=trace_row, character_start=character_start, character_end=character_end,
            )
        except Exception as exc:
            trials.append({**transition, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            continue
        source_segment = {
            **prefix_info,
            "rows": [
                row for row in rows
                if int(prefix_info["character_start"]) <= int(row["global_character_index"]) <= int(prefix_info["character_end"])
            ],
        }
        reproduction = reproduce_segment(
            source_segment, rerun_rows, tolerance_sec=args.stable_prefix_reproduction_tolerance_sec,
            minimum_observed_units=args.stable_prefix_minimum_observed_units,
            minimum_observed_ratio=args.stable_prefix_minimum_observed_ratio,
        ) if source_segment else {"supported": False, "reason": "selected_segment_rows_not_in_trace"}
        trials.append({
            **transition, "status": "complete", "rerun_character_start": character_start,
            "rerun_character_end": character_end, "rerun_prefix_reproduction": reproduction,
            "rerun_gt": metrics_without_details(rerun_rows, gt),
            "rerun_structural": structural_summary(rerun_rows),
            "audit": audit,
        })
    return {
        "schema_version": "stable_window_assistance_trials_v1",
        "trial_count": len(trials),
        "successful_trial_count": sum(row.get("status") == "complete" for row in trials),
        "trials": trials,
    }


def run_forced_expansion_trials(
    *, args: argparse.Namespace, processor: Any, model: Any, audio: Any, document: Any,
    gt: list[dict[str, Any]], trace: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    total = len(document.characters)
    candidates = [row for row in trace if not row.get("silent_core_skipped") and row.get("attempts")]
    candidates.sort(key=lambda row: (
        -int((row.get("precommit_diagnostic") or {}).get("triggered", False)),
        -int(row.get("committed_character_count", 0)), int(row.get("window_index", 0)),
    ))
    for trace_row in candidates[: args.max_expansion_trials_per_item]:
        start = int(trace_row.get("candidate_character_start", trace_row.get("input_character_start_before", 0)))
        baseline_end = int(trace_row.get("candidate_character_end", start))
        span = max(1, baseline_end - start)
        variants: list[dict[str, Any]] = []
        for ratio in (1.25, 1.50):
            end = min(total, max(baseline_end + 1, start + int(math.ceil(span * ratio))))
            if end <= baseline_end:
                continue
            try:
                rerun_rows, audit = _attempt_rows_for_rerun(
                    processor=processor, model=model, audio=audio, document=document, args=args,
                    trace_row=trace_row, character_start=start, character_end=end,
                )
            except Exception as exc:
                variants.append({"ratio": ratio, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                continue
            baseline_probe = (trace_row.get("attempts") or [])[-1].get("probe_rows", [])
            movement = compare_attempt_probes([
                {"attempt_index": 0, "probe_rows": baseline_probe},
                {"attempt_index": 1, "probe_rows": attempt_probe_rows(
                    rerun_rows, core_end_sec=float(trace_row.get("core_end_sec", 0.0)),
                    next_input_boundary_sec=trace_row.get("next_input_boundary_sec"),
                    max_rows=args.attempt_probe_max_rows,
                )},
            ])
            variants.append({
                "ratio": ratio, "status": "complete", "character_end": end,
                "movement": movement, "structural": structural_summary(rerun_rows),
                "gt": metrics_without_details(rerun_rows, gt), "audit": audit,
            })
        results.append({
            "window_index": trace_row.get("window_index"),
            "baseline_character_start": start, "baseline_character_end": baseline_end,
            "variants": variants,
        })
    return {
        "schema_version": "forced_candidate_expansion_trials_v1",
        "window_count": len(results),
        "variant_run_count": sum(len(row["variants"]) for row in results),
        "windows": results,
    }


def construct_incomplete_guard(
    *, item: dict[str, Any], baseline_payload: dict[str, Any], candidates: list[dict[str, Any]],
    out_path: Path, gt: list[dict[str, Any]],
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
            "incomplete_kind": "constructed_fail_closed_validation",
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
        "constructed_for_validation": True,
    }
    write_alignment_bundle(out_path, payload)
    return payload["summary"]


def run_inline_shadow(
    *, args: argparse.Namespace, item: dict[str, Any], processor: Any, model: Any,
    audio: Any, document: Any, gt: list[dict[str, Any]], rows: list[dict[str, Any]],
    trace: list[dict[str, Any]], out_path: Path, request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    automatic_candidates = [
        {**row, "candidate_source": row.get("candidate_source", "automatic_precommit")}
        for row in anomaly_spans_from_trace(trace)
    ]
    oracle_candidates = gt_error_spans(
        rows, gt, threshold_sec=args.gt_oracle_error_threshold_sec,
    )[: args.max_gt_oracle_cases_per_item]
    candidates = (
        automatic_candidates[: args.max_shadow_cases_per_item]
        + oracle_candidates
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
            "would_write": False,
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
        try:
            exact = QUICK.local_infer(
                processor=processor, model=model, audio=audio, document=document,
                serial_args=local_serial_args(args), left=left_anchor, right=right_anchor,
                audio_duration_sec=duration, crop_mode="exact_anchor", padding_sec=0.0,
                context_units=0, context_rows=stage_rows(rows, "selected"),
            )
            plus2 = QUICK.local_infer(
                processor=processor, model=model, audio=audio, document=document,
                serial_args=local_serial_args(args), left=left_anchor, right=right_anchor,
                audio_duration_sec=duration, crop_mode="matched_context", padding_sec=0.0,
                context_units=2, context_rows=stage_rows(rows, "selected"),
            )
        except Exception as exc:  # keep formal run progressing; preserve exact failure
            decision["reason"] = "local_inference_failed"
            decision["error"] = f"{type(exc).__name__}: {exc}"
            decisions.append(decision)
            continue
        replace_start = int(exact["replace_start"])
        replace_end = int(exact["replace_end"])
        replacement_indices = list(range(replace_start, replace_end + 1))
        agreement = agreement_between_trials(
            exact["decoded_rows"], plus2["decoded_rows"], replacement_indices,
            tolerance_sec=args.context_agreement_tolerance_sec,
        )
        replaced, splice = bounded_splice(
            rows, exact["decoded_rows"],
            replace_start=replace_start, replace_end=replace_end,
            remerge=True, projection="isotonic", minimum_duration_sec=0.0,
        )
        before = _target_structural(rows, replacement_indices)
        after = _target_structural(replaced, replacement_indices)
        before_score = _anomaly_score(before)
        after_score = _anomaly_score(after)
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
        improvement_supported = gt_improved if source == "gt_oracle" else after_score < before_score
        would_write = bool(agreement.get("supported")) and bool(splice.get("valid")) and improvement_supported
        decision.update({
            "reason": (
                "shadow_would_write" if would_write
                else "exact_plus2_disagreement" if not agreement.get("supported")
                else "invalid_splice" if not splice.get("valid")
                else "gt_not_improved" if source == "gt_oracle"
                else "trigger_not_reduced"
            ),
            "would_write": would_write,
            "replace_start": replace_start,
            "replace_end": replace_end,
            "context_agreement": agreement,
            "splice": splice,
            "structural_before": before,
            "structural_after": after,
            "anomaly_score_before": before_score,
            "anomaly_score_after": after_score,
            "gt_before": gt_before,
            "gt_after": gt_after,
            "gt_improved": gt_improved,
            "replacement_preview": _replacement_preview(
                rows, replaced, gt, replacement_indices, limit=args.max_case_preview_rows,
            ),
            "exact_wall_sec": exact.get("wall_sec"),
            "plus2_wall_sec": plus2.get("wall_sec"),
        })
        decisions.append(decision)
    payload = {
        "schema_version": "inline_realign_shadow_v1",
        "created_at": utc_now(),
        "item_id": item["item_id"],
        "dataset": item["dataset"],
        "candidate_count": len(candidates),
        "automatic_candidate_count": len(automatic_candidates),
        "gt_oracle_candidate_count": len(oracle_candidates),
        "decision_count": len(decisions),
        "local_inference_attempted_count": sum(row.get("replace_start") is not None or row.get("reason") == "local_inference_failed" for row in decisions),
        "would_write_count": sum(bool(row.get("would_write")) for row in decisions),
        "decisions": decisions,
    }
    if request is not None:
        payload = with_auxiliary_identity(payload, request)
    atomic_json(out_path, payload)
    return payload


def selected_variants(item: dict[str, Any]) -> list[str]:
    variant_set = str(item.get("variant_set", "official_primary"))
    if variant_set == "baseline_matrix":
        return list(VARIANTS)
    if variant_set == "official_primary":
        return ["B2_30_silence_official"]
    raise ValueError(f"unknown variant_set for {item.get('item_id')}: {variant_set}")


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
    p.add_argument("--context-agreement-tolerance-sec", type=float, default=0.24)
    p.add_argument("--gt-oracle-error-threshold-sec", type=float, default=0.24)
    p.add_argument("--max-gt-oracle-cases-per-item", type=int, default=3)
    p.add_argument("--max-shadow-cases-per-item", type=int, default=8)
    p.add_argument("--max-stable-window-trials-per-item", type=int, default=2)
    p.add_argument("--max-expansion-trials-per-item", type=int, default=1)
    p.add_argument("--disable-stable-window-assistance", action="store_true")
    p.add_argument("--disable-forced-expansion-trials", action="store_true")
    p.add_argument("--construct-incomplete-cases", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--max-case-preview-rows", type=int, default=64)
    p.add_argument("--disable-inline-shadow", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    args.manifest = args.manifest.expanduser().resolve()
    args.out_root = args.out_root.expanduser().resolve()
    args.r2_checkpoint = args.r2_checkpoint.expanduser().resolve()
    for path in (args.manifest, args.r2_checkpoint):
        if not path.exists():
            raise FileNotFoundError(path)
    items = read_jsonl(args.manifest)
    if not items:
        raise ValueError("empty experiment manifest")
    args.out_root.mkdir(parents=True, exist_ok=True)
    status_path = args.out_root / "run_status.jsonl"
    checkpoint = SERIAL.checkpoint_identity("lora", args.r2_checkpoint)
    load_args = SimpleNamespace(
        model=str(args.model), revision=args.revision,
        local_files_only=args.local_files_only, cache_dir=args.cache_dir,
        device=args.device,
    )
    processor, model = SERIAL.load_model(load_args, "lora", args.r2_checkpoint)
    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        for item in items:
            item_id = str(item["item_id"])
            item_root = args.out_root / "items" / item_id
            append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "running"})
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
                document = parse_lyrics_text(lyrics_path.read_text(encoding="utf-8-sig"), language=args.language)
                gt = load_gt(gt_path)
                if gt and len(gt) != len(document.characters):
                    raise ValueError(
                        f"{item_id}: lyrics/GT count mismatch {len(document.characters)} != {len(gt)}"
                    )
                audio = decode_audio(audio_path)
                branch_summaries: dict[str, Any] = {}
                b2_rows: list[dict[str, Any]] | None = None
                b2_trace: list[dict[str, Any]] | None = None
                b2_payload: dict[str, Any] | None = None
                for variant_name in selected_variants(item):
                    rows, trace, payload = run_variant(
                        args=args, item=item, variant_name=variant_name,
                        variant=VARIANTS[variant_name], processor=processor, model=model,
                        audio=audio, document=document, gt=gt, checkpoint=checkpoint,
                        item_root=item_root,
                    )
                    branch_summaries[variant_name] = payload["summary"]
                    if variant_name == "B2_30_silence_official":
                        b2_rows, b2_trace, b2_payload = rows, trace, payload
                if (
                    item.get("variant_set") == "official_primary"
                    and b2_payload is not None
                    and int((b2_payload.get("planner_divergence") or {}).get("diverged_window_count", 0)) > 0
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
                incomplete_summary = None
                baseline_hash = None if b2_payload is None else b2_payload.get("identity", {}).get("request_hash")
                if not args.disable_inline_shadow and b2_rows is not None and b2_trace is not None:
                    shadow_request = {
                        "schema_version": "inline_realign_shadow_request_v2_gt_oracle_localized",
                        "baseline_request_hash": baseline_hash,
                        "max_shadow_cases_per_item": args.max_shadow_cases_per_item,
                        "max_gt_oracle_cases_per_item": args.max_gt_oracle_cases_per_item,
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
                            audio=audio, document=document, gt=gt, rows=b2_rows,
                            trace=b2_trace, out_path=shadow_path, request=shadow_request,
                        )
                if b2_rows is not None and b2_trace is not None and not args.disable_stable_window_assistance:
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
                                args=args, rows=b2_rows, trace=b2_trace, gt=gt,
                                total_characters=len(document.characters),
                            ),
                            assistance_request,
                        )
                        atomic_json(assistance_path, assistance_payload)

                    trial_request = {
                        "schema_version": "stable_window_assistance_trials_request_v1",
                        "assistance_request_hash": assistance_payload.get("identity", {}).get("request_hash"),
                        "max_trials_per_item": args.max_stable_window_trials_per_item,
                    }
                    trial_path = item_root / "stable_window_assistance_trials.json"
                    assistance_trials = current_auxiliary_payload(
                        trial_path, canonical_hash(trial_request), force=args.force,
                    )
                    if assistance_trials is None:
                        assistance_trials = with_auxiliary_identity(
                            run_stable_window_assistance_trials(
                                args=args, processor=processor, model=model, audio=audio,
                                document=document, gt=gt, rows=b2_rows, trace=b2_trace,
                                assistance=assistance_payload,
                            ),
                            trial_request,
                        )
                        atomic_json(trial_path, assistance_trials)
                if b2_trace is not None and not args.disable_forced_expansion_trials:
                    expansion_request = {
                        "schema_version": "forced_candidate_expansion_request_v1",
                        "baseline_request_hash": baseline_hash,
                        "max_trials_per_item": args.max_expansion_trials_per_item,
                        "ratios": [1.25, 1.50],
                        "attempt_probe_max_rows": args.attempt_probe_max_rows,
                    }
                    expansion_path = item_root / "forced_expansion_trials.json"
                    expansion_payload = current_auxiliary_payload(
                        expansion_path, canonical_hash(expansion_request), force=args.force,
                    )
                    if expansion_payload is None:
                        expansion_payload = with_auxiliary_identity(
                            run_forced_expansion_trials(
                                args=args, processor=processor, model=model, audio=audio,
                                document=document, gt=gt, trace=b2_trace,
                            ),
                            expansion_request,
                        )
                        atomic_json(expansion_path, expansion_payload)
                if args.construct_incomplete_cases and b2_payload is not None:
                    incomplete_candidates = []
                    if shadow_payload is not None:
                        incomplete_candidates = [
                            decision["trigger"] for decision in shadow_payload.get("decisions", [])
                            if decision.get("trigger")
                        ]
                    if not incomplete_candidates and item.get("incomplete_exercise") and b2_rows:
                        tail_units = min(8, len(b2_rows))
                        incomplete_candidates = [{
                            "window_index": int(b2_rows[-1].get("owner_window_index", -1)),
                            "character_start": len(b2_rows) - tail_units,
                            "character_end": len(b2_rows) - 1,
                            "reasons": ["constructed_incomplete_tail_exercise"],
                            "severity": tail_units,
                            "candidate_source": "constructed_incomplete_exercise",
                            "range_source": "deterministic_tail_exercise",
                        }]
                    incomplete_summary = construct_incomplete_guard(
                        item=item, baseline_payload=b2_payload, candidates=incomplete_candidates,
                        out_path=item_root / "incomplete_guard" / "alignment.json", gt=gt,
                    )
                item_summary = {
                    "item_id": item_id,
                    "dataset": item["dataset"],
                    "profile": item.get("profile"),
                    "selection_role": item.get("selection_role"),
                    "variant_set": item.get("variant_set"),
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
                    "forced_expansion_trials": None if expansion_payload is None else {
                        key: value for key, value in expansion_payload.items() if key != "windows"
                    },
                    "incomplete_guard": incomplete_summary,
                }
                atomic_json(item_root / "item_summary.json", item_summary)
                summaries.append(item_summary)
                append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "complete"})
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
                append_jsonl(status_path, {"time": utc_now(), "item_id": item_id, "status": "failed", "error": str(exc)})
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
        "schema_version": "inline_realign_experiment_summary_v1",
        "created_at": utc_now(),
        "manifest": str(args.manifest),
        "item_count": len(items),
        "completed_item_count": len(summaries),
        "failed_item_count": len(failures),
        "variants": VARIANTS,
        "items": summaries,
        "failures": failures,
        "interpretation_limits": [
            "Inline realign is shadow-only in this implementation; no serial result is modified.",
            "Demo items without GT support structural and listening review, not accuracy claims.",
            "M4Singer synthetic-long seams must be reported separately from natural MIR-1K songs.",
            "GT-oracle targets test local-realign capability and must not be reported as an automatic detector result.",
            "Constructed incomplete outputs are fail-closed validation artifacts, not claims that every source item is incomplete.",
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
