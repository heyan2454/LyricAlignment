"""Stage-separated alignment artifacts and structural quality diagnostics.

The final karaoke alignment intentionally remains ``alignment.json``.  This
module writes the accepted model timestamps at four stages beside it:

* ``alignment.raw.json``: timestamp-logit argmax values;
* ``alignment.processor_decoded.json``: processor ``decode_forced_alignment`` output;
* ``alignment.selected.json``: current-window ownership result before cross-window compression;
* ``alignment.json``: final committed/monotonic result;
* ``alignment.quality.json``: structural and diagnostic comparisons.

The quality report does not claim perceptual or ground-truth accuracy.  It only
states whether the output is structurally valid and surfaces suspicious changes
that require metric or listening review.
"""
from __future__ import annotations

import json
import os
import math
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ARTIFACT_SCHEMA_VERSION = "qwen_fa_alignment_artifacts_v1"
QUALITY_SCHEMA_VERSION = "qwen_fa_alignment_quality_v1"

_STAGE_FIELDS = {
    "raw": ("raw_global_start_sec", "raw_global_end_sec"),
    "processor_decoded": ("fixed_global_start_sec", "fixed_global_end_sec"),
    "selected": ("selected_start_sec", "selected_end_sec"),
    "final": ("start_sec", "end_sec"),
}


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _numeric_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return {
        "count": len(finite),
        "mean": statistics.fmean(finite) if finite else None,
        "median": _quantile(finite, 0.5),
        "p90": _quantile(finite, 0.9),
        "max": max(finite) if finite else None,
    }


def _ordered_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))


def stage_rows(rows: Iterable[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    """Return rows with ``start_sec``/``end_sec`` projected to one stage."""
    if stage not in _STAGE_FIELDS:
        raise ValueError(f"unknown alignment stage: {stage}")
    start_key, end_key = _STAGE_FIELDS[stage]
    result: list[dict[str, Any]] = []
    for source in _ordered_rows(rows):
        row = dict(source)
        # Full-mode and legacy rows may not have selected_* before decoration.
        if stage == "processor_decoded" and row.get("official_fixed_global_start_sec") is not None:
            # Multi-decoder runs keep the original Qwen processor output under
            # official_fixed_* while fixed_* is the decoder actually used for
            # serial ownership/commit decisions.
            start = row.get("official_fixed_global_start_sec")
            end = row.get("official_fixed_global_end_sec")
        elif stage == "selected":
            start = row.get(start_key, row.get("fixed_global_start_sec"))
            end = row.get(end_key, row.get("fixed_global_end_sec"))
        else:
            start = row.get(start_key)
            end = row.get(end_key)
        if start is None or end is None:
            raise KeyError(
                f"row {row.get('global_character_index')} lacks {start_key}/{end_key} for {stage}"
            )
        row["artifact_stage"] = stage
        row["start_sec"] = float(start)
        row["end_sec"] = float(end)
        result.append(row)
    return result


def _interval_diagnostics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = _ordered_rows(rows)
    negative_duration = 0
    zero_duration = 0
    start_regression = 0
    end_regression = 0
    inter_unit_overlap = 0
    overlap_amounts: list[float] = []
    previous_start: float | None = None
    previous_end: float | None = None
    for row in ordered:
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        if end < start - 1e-9:
            negative_duration += 1
        if end <= start + 1e-9:
            zero_duration += 1
        if previous_start is not None and start < previous_start - 1e-9:
            start_regression += 1
        if previous_end is not None:
            if end < previous_end - 1e-9:
                end_regression += 1
            overlap = max(0.0, previous_end - start)
            if overlap > 1e-9:
                inter_unit_overlap += 1
                overlap_amounts.append(overlap)
        previous_start = start
        previous_end = end
    count = len(ordered)
    return {
        "unit_count": count,
        "negative_duration_count": negative_duration,
        "negative_duration_rate": negative_duration / count if count else 0.0,
        "zero_duration_count": zero_duration,
        "zero_duration_rate": zero_duration / count if count else 0.0,
        "start_regression_count": start_regression,
        "end_regression_count": end_regression,
        "inter_unit_overlap_count": inter_unit_overlap,
        "inter_unit_overlap_rate": inter_unit_overlap / count if count else 0.0,
        "inter_unit_overlap_sec": _numeric_summary(overlap_amounts),
    }


def _stage_adjustment(
    earlier: Iterable[dict[str, Any]], later: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    left = {int(row["global_character_index"]): row for row in earlier}
    right = {int(row["global_character_index"]): row for row in later}
    common = sorted(set(left) & set(right))
    start_changes: list[float] = []
    end_changes: list[float] = []
    boundary_changes: list[float] = []
    changed_units = 0
    for index in common:
        start_delta = abs(float(right[index]["start_sec"]) - float(left[index]["start_sec"]))
        end_delta = abs(float(right[index]["end_sec"]) - float(left[index]["end_sec"]))
        start_changes.append(start_delta)
        end_changes.append(end_delta)
        boundary_changes.extend((start_delta, end_delta))
        if start_delta > 1e-9 or end_delta > 1e-9:
            changed_units += 1
    return {
        "common_unit_count": len(common),
        "changed_unit_count": changed_units,
        "changed_unit_rate": changed_units / len(common) if common else 0.0,
        "absolute_start_change_sec": _numeric_summary(start_changes),
        "absolute_end_change_sec": _numeric_summary(end_changes),
        "absolute_boundary_change_sec": _numeric_summary(boundary_changes),
    }


def _confidence_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = _ordered_rows(rows)
    return {
        "start_top1_probability": _numeric_summary(
            float(row["raw_start_top1_probability"])
            for row in ordered
            if row.get("raw_start_top1_probability") is not None
        ),
        "end_top1_probability": _numeric_summary(
            float(row["raw_end_top1_probability"])
            for row in ordered
            if row.get("raw_end_top1_probability") is not None
        ),
        "boundary_margin_mean": _numeric_summary(
            float(row["raw_boundary_margin_mean"])
            for row in ordered
            if row.get("raw_boundary_margin_mean") is not None
        ),
        "start_entropy": _numeric_summary(
            float(row["raw_start_entropy"])
            for row in ordered
            if row.get("raw_start_entropy") is not None
        ),
        "end_entropy": _numeric_summary(
            float(row["raw_end_entropy"])
            for row in ordered
            if row.get("raw_end_entropy") is not None
        ),
    }


def _attempt_summary(trace: Iterable[dict[str, Any]]) -> dict[str, Any]:
    traces = list(trace)
    attempts = [attempt for window in traces for attempt in window.get("attempts", [])]
    expanded = [attempt for attempt in attempts if attempt.get("status") == "expanded"]
    target_counts = [int(attempt["target_character_count"]) for attempt in attempts if attempt.get("target_character_count") is not None]
    committed_counts = [int(window.get("committed_character_count", 0)) for window in traces]
    return {
        "window_count": len(traces),
        "attempt_count": len(attempts),
        "expanded_attempt_count": len(expanded),
        "windows_with_expansion_count": sum(
            any(attempt.get("status") == "expanded" for attempt in window.get("attempts", []))
            for window in traces
        ),
        "max_expansion_index": max(
            (int(attempt.get("expansion_index", 0)) for attempt in attempts), default=0
        ),
        "target_character_count": _numeric_summary(target_counts),
        "committed_character_count": _numeric_summary(committed_counts),
    }


def build_quality_report(
    *,
    rows: Iterable[dict[str, Any]],
    trace: Iterable[dict[str, Any]],
    expected_unit_count: int,
    audio_duration_sec: float,
    mode: str,
) -> dict[str, Any]:
    """Build a structural report; no GT or perceptual accuracy is inferred."""
    final_rows = stage_rows(rows, "final")
    raw_rows = stage_rows(rows, "raw")
    processor_rows = stage_rows(rows, "processor_decoded")
    selected_rows = stage_rows(rows, "selected")

    final_indices = [int(row["global_character_index"]) for row in final_rows]
    expected_indices = list(range(expected_unit_count))
    structural_errors: list[str] = []
    if len(final_rows) != expected_unit_count:
        structural_errors.append(
            f"unit_count_mismatch:{len(final_rows)}!={expected_unit_count}"
        )
    if final_indices != expected_indices:
        structural_errors.append("non_contiguous_or_reordered_global_indices")
    for row in final_rows:
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        if not math.isfinite(start) or not math.isfinite(end):
            structural_errors.append("non_finite_final_timestamp")
            break
        if start < -1e-9 or end > audio_duration_sec + 1e-6:
            structural_errors.append("final_timestamp_outside_audio")
            break

    diagnostics = {
        "raw": _interval_diagnostics(raw_rows),
        "processor_decoded": _interval_diagnostics(processor_rows),
        "selected": _interval_diagnostics(selected_rows),
        "final": _interval_diagnostics(final_rows),
    }
    final_diag = diagnostics["final"]
    if final_diag["negative_duration_count"]:
        structural_errors.append("negative_final_duration")
    if final_diag["start_regression_count"] or final_diag["end_regression_count"]:
        structural_errors.append("non_monotonic_final_alignment")

    warnings: list[str] = []
    raw_diag = diagnostics["raw"]
    if raw_diag["negative_duration_count"]:
        warnings.append("raw_negative_duration")
    if raw_diag["start_regression_count"] or raw_diag["end_regression_count"]:
        warnings.append("raw_timestamp_regression")
    if raw_diag["inter_unit_overlap_count"]:
        warnings.append("raw_inter_unit_overlap")
    if diagnostics["processor_decoded"]["zero_duration_count"]:
        warnings.append("processor_zero_duration")
    if diagnostics["selected"]["inter_unit_overlap_count"]:
        warnings.append("selected_inter_unit_overlap")
    if final_diag["zero_duration_count"]:
        warnings.append("final_zero_duration")
    overlap_compressed = [row for row in final_rows if row.get("overlap_compressed")]
    if overlap_compressed:
        warnings.append("cross_window_overlap_compression")

    attempts = _attempt_summary(trace)
    if attempts["expanded_attempt_count"]:
        warnings.append("candidate_text_expansion_used")

    if structural_errors:
        status = "failed_structural"
    elif warnings:
        status = "warning"
    else:
        status = "passed_structural"

    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "interpretation": (
            "Structural/diagnostic report only; it is not a ground-truth accuracy score "
            "and must not be used for checkpoint selection."
        ),
        "mode": mode,
        "expected_unit_count": expected_unit_count,
        "audio_duration_sec": audio_duration_sec,
        "structural_errors": sorted(set(structural_errors)),
        "warnings": sorted(set(warnings)),
        "stage_interval_diagnostics": diagnostics,
        "stage_adjustments": {
            "raw_to_processor_decoded": _stage_adjustment(raw_rows, processor_rows),
            "processor_decoded_to_selected": _stage_adjustment(processor_rows, selected_rows),
            "selected_to_final": _stage_adjustment(selected_rows, final_rows),
        },
        "confidence": _confidence_summary(final_rows),
        "window_attempts": attempts,
        "commit_diagnostics": {
            "overlap_compressed_unit_count": len(overlap_compressed),
            "overlap_compressed_unit_rate": (
                len(overlap_compressed) / len(final_rows) if final_rows else 0.0
            ),
            "overlap_compression_sec": _numeric_summary(
                float(row.get("overlap_compression_sec", 0.0)) for row in overlap_compressed
            ),
            "collapsed_to_zero_count": sum(
                bool(row.get("overlap_compression_collapsed_to_zero"))
                for row in overlap_compressed
            ),
        },
    }


def write_alignment_bundle(output: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Write final and stage-separated artifacts next to ``output``."""
    rows = payload.get("characters")
    if not isinstance(rows, list):
        raise TypeError("alignment payload must contain a characters list")
    trace = payload.get("window_trace") or []
    summary = payload.get("summary") or {}
    expected = int(summary.get("alignment_unit_count", len(rows)))
    duration = float(summary.get("audio_duration_sec", 0.0))
    mode = str(payload.get("identity", {}).get("mode") or summary.get("mode") or "unknown")

    quality = build_quality_report(
        rows=rows,
        trace=trace,
        expected_unit_count=expected,
        audio_duration_sec=duration,
        mode=mode,
    )
    artifact_paths = {
        "raw": output.with_name("alignment.raw.json"),
        "processor_decoded": output.with_name("alignment.processor_decoded.json"),
        "selected": output.with_name("alignment.selected.json"),
        "final": output,
        "quality": output.with_name("alignment.quality.json"),
    }
    enriched = dict(payload)
    enriched["artifact_bundle"] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "quality_status": quality["status"],
        "files": {key: path.name for key, path in artifact_paths.items()},
    }

    compact = os.environ.get("LYRICALIGN_COMPACT_ARTIFACTS") == "1"
    for stage in (() if compact else ("raw", "processor_decoded", "selected")):
        stage_payload = {
            **enriched,
            "artifact_stage": stage,
            "characters": stage_rows(rows, stage),
        }
        _atomic_json(artifact_paths[stage], stage_payload)
    _atomic_json(artifact_paths["quality"], quality)
    _atomic_json(output, {**enriched, "artifact_stage": "final"})
    return {
        "quality": quality,
        "paths": {key: str(path) for key, path in artifact_paths.items()},
    }
