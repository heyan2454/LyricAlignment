"""Lightweight diagnostics for serial-window collapse and stable-segment experiments.

The helpers in this module are deliberately model-independent. They operate on
saved alignment rows and compact window traces so the same diagnostics can be
unit-tested and collected without loading Qwen.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable, Sequence


def _quantile(values: Sequence[float], q: float) -> float | None:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return None
    if len(finite) == 1:
        return finite[0]
    position = min(max(float(q), 0.0), 1.0) * (len(finite) - 1)
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return finite[lo]
    fraction = position - lo
    return finite[lo] * (1.0 - fraction) + finite[hi] * fraction


def _longest_true_run(values: Iterable[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _longest_equal_run(values: Sequence[float], *, tolerance_sec: float = 1e-9) -> int:
    if not values:
        return 0
    longest = 1
    current = 1
    previous = float(values[0])
    for value in values[1:]:
        current_value = float(value)
        if abs(current_value - previous) <= tolerance_sec:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
        previous = current_value
    return longest


def compact_probe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields needed to compare candidate-expansion attempts."""
    fields = (
        "global_character_index", "character", "fixed_global_start_sec",
        "fixed_global_end_sec", "raw_global_start_sec", "raw_global_end_sec",
        "official_fixed_global_start_sec", "official_fixed_global_end_sec",
        "raw_boundary_margin_mean", "raw_start_margin", "raw_end_margin",
        "core_start_sec", "core_end_sec", "input_start_sec", "input_end_sec",
    )
    return {field: row.get(field) for field in fields}


def attempt_probe_rows(
    rows: Sequence[dict[str, Any]], *, core_end_sec: float,
    next_input_boundary_sec: float | None, max_rows: int = 48,
    radius_units: int = 6, tail_sec: float = 2.0,
) -> list[dict[str, Any]]:
    """Select a compact, deterministic set around ownership boundaries and pileups."""
    ordered = sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))
    if not ordered or max_rows <= 0:
        return []
    selected_positions: set[int] = set()

    def add_around(position: int) -> None:
        for offset in range(-radius_units, radius_units + 1):
            candidate = position + offset
            if 0 <= candidate < len(ordered):
                selected_positions.add(candidate)

    boundaries = [float(core_end_sec)]
    if next_input_boundary_sec is not None:
        boundaries.append(float(next_input_boundary_sec))
    for boundary in boundaries:
        crossing = next(
            (
                position for position, row in enumerate(ordered)
                if float(row.get("fixed_global_start_sec", 0.0)) >= boundary
            ),
            len(ordered) - 1,
        )
        add_around(crossing)

    input_end = max(float(row.get("input_end_sec", core_end_sec)) for row in ordered)
    tail_start = input_end - max(0.0, float(tail_sec))
    for position, row in enumerate(ordered):
        if float(row.get("fixed_global_start_sec", 0.0)) >= tail_start:
            selected_positions.add(position)

    for position in range(min(3, len(ordered))):
        selected_positions.add(position)
    for position in range(max(0, len(ordered) - 3), len(ordered)):
        selected_positions.add(position)

    ranked = sorted(selected_positions)
    if len(ranked) > max_rows:
        # Preserve both ends and sample the middle deterministically.
        if max_rows == 1:
            ranked = [ranked[len(ranked) // 2]]
        else:
            step = (len(ranked) - 1) / (max_rows - 1)
            ranked = sorted({ranked[int(round(index * step))] for index in range(max_rows)})
    return [compact_probe_row(ordered[position]) for position in ranked]


def compare_attempt_probes(attempts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compare the accepted expansion with earlier candidate-text expansions."""
    attempts_with_rows = [row for row in attempts if row.get("probe_rows")]
    if len(attempts_with_rows) < 2:
        return {
            "supported": False,
            "reason": "fewer_than_two_captured_attempts",
            "comparison_count": 0,
        }
    accepted = attempts_with_rows[-1]
    accepted_by_index = {
        int(row["global_character_index"]): row for row in accepted["probe_rows"]
    }
    comparisons: list[dict[str, Any]] = []
    for earlier in attempts_with_rows[:-1]:
        earlier_by_index = {
            int(row["global_character_index"]): row for row in earlier["probe_rows"]
        }
        common = sorted(set(accepted_by_index) & set(earlier_by_index))
        movements: list[float] = []
        for index in common:
            left = earlier_by_index[index]
            right = accepted_by_index[index]
            movements.extend((
                abs(float(left["fixed_global_start_sec"]) - float(right["fixed_global_start_sec"])),
                abs(float(left["fixed_global_end_sec"]) - float(right["fixed_global_end_sec"])),
            ))
        comparisons.append({
            "earlier_attempt_index": earlier.get("attempt_index"),
            "accepted_attempt_index": accepted.get("attempt_index"),
            "common_character_count": len(common),
            "max_boundary_movement_sec": max(movements, default=None),
            "median_boundary_movement_sec": statistics.median(movements) if movements else None,
        })
    finite = [
        float(row["max_boundary_movement_sec"])
        for row in comparisons if row["max_boundary_movement_sec"] is not None
    ]
    return {
        "supported": bool(finite),
        "reason": "captured_expansion_comparison" if finite else "no_common_probe_characters",
        "comparison_count": len(comparisons),
        "max_boundary_movement_sec": max(finite, default=None),
        "comparisons": comparisons,
    }


def _span_from_rows(rows: Sequence[dict[str, Any]], *, reason: str, severity: int) -> dict[str, Any] | None:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda row: int(row["global_character_index"]))
    return {
        "character_start": int(ordered[0]["global_character_index"]),
        "character_end": int(ordered[-1]["global_character_index"]),
        "reason": reason,
        "severity": int(severity),
        "character_count": len(ordered),
    }


def _contiguous_flag_spans(
    rows: Sequence[dict[str, Any]], flags: Sequence[bool], *, reason: str, minimum_run: int, weight: int,
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for row, flag in zip(rows, flags):
        if flag:
            current.append(row)
        else:
            if len(current) >= minimum_run:
                span = _span_from_rows(current, reason=reason, severity=len(current) * weight)
                if span is not None:
                    spans.append(span)
            current = []
    if len(current) >= minimum_run:
        span = _span_from_rows(current, reason=reason, severity=len(current) * weight)
        if span is not None:
            spans.append(span)
    return spans


def _equal_boundary_flags(rows: Sequence[dict[str, Any]], *, tolerance_sec: float = 1e-9) -> list[bool]:
    flags = [False] * len(rows)
    run_start = 0
    while run_start < len(rows):
        run_end = run_start + 1
        start_value = float(rows[run_start]["start_sec"])
        end_value = float(rows[run_start]["end_sec"])
        while run_end < len(rows):
            same_start = abs(float(rows[run_end]["start_sec"]) - start_value) <= tolerance_sec
            same_end = abs(float(rows[run_end]["end_sec"]) - end_value) <= tolerance_sec
            if not (same_start or same_end):
                break
            run_end += 1
        if run_end - run_start >= 2:
            for index in range(run_start, run_end):
                flags[index] = True
        run_start = run_end
    return flags


def analyze_precommit_trial(
    *, existing_rows: Sequence[dict[str, Any]], candidate_rows: Sequence[dict[str, Any]],
    trial_rows: Sequence[dict[str, Any]], window: dict[str, Any],
    all_candidate_rows: Sequence[dict[str, Any]] | None = None,
    vocal_activity: dict[str, Any] | None, tail_sec: float = 2.0,
    zero_run_trigger: int = 4, stacking_run_trigger: int = 6,
    tail_count_trigger: int = 8, tail_ratio_trigger: float = 0.25,
    active_sec_trigger: float = 3.0, uncommitted_character_index: int | None = None,
) -> dict[str, Any]:
    """Diagnose the rows that would actually be committed.

    Future lookahead is deliberately excluded from the tail-pileup trigger.  A
    forced aligner naturally places text whose audio has not arrived at the end
    of the input; counting that text previously made almost every long window a
    false positive and expanded the target to the entire committed prefix.
    """
    existing_count = len(existing_rows)
    new_rows = [dict(row) for row in trial_rows[existing_count:]]
    new_rows.sort(key=lambda row: int(row["global_character_index"]))
    durations = [max(0.0, float(row["end_sec"]) - float(row["start_sec"])) for row in new_rows]
    zero_flags = [duration <= 1e-9 for duration in durations]
    zero_count = sum(zero_flags)
    zero_run = _longest_true_run(zero_flags)
    equal_flags = _equal_boundary_flags(new_rows)
    stacking_run = _longest_true_run(equal_flags)

    core_end = float(window.get("core_end_sec", window.get("input_end_sec", 0.0)))
    tail_start = core_end - max(0.0, float(tail_sec))
    tail_rows = [
        row for row in new_rows
        if float(row.get("start_sec", row.get("fixed_global_start_sec", 0.0))) >= tail_start - 1e-9
    ]
    tail_count = len(tail_rows)
    tail_ratio = tail_count / max(len(new_rows), 1)
    active_duration = (
        None if vocal_activity is None
        else float(vocal_activity.get("sustained_active_duration_sec", 0.0))
    )

    reasons: list[str] = []
    spans: list[dict[str, Any]] = []
    zero_spans = _contiguous_flag_spans(
        new_rows, zero_flags, reason="zero_duration_run", minimum_run=zero_run_trigger, weight=3,
    )
    stack_spans = _contiguous_flag_spans(
        new_rows, equal_flags, reason="equal_boundary_run", minimum_run=stacking_run_trigger, weight=2,
    )
    if zero_spans or stack_spans:
        reasons.append("collapse_or_boundary_stacking")
        spans.extend(zero_spans)
        spans.extend(stack_spans)
    if tail_count >= tail_count_trigger and tail_ratio >= tail_ratio_trigger:
        reasons.append("large_core_tail_pileup")
        span = _span_from_rows(tail_rows, reason="core_tail_pileup", severity=tail_count)
        if span is not None:
            spans.append(span)
    if not candidate_rows and active_duration is not None and active_duration >= active_sec_trigger:
        reasons.append("active_core_without_lyric_progress")
        if uncommitted_character_index is not None:
            spans.append({
                "character_start": int(uncommitted_character_index),
                "character_end": int(uncommitted_character_index),
                "reason": "active_core_without_lyric_progress",
                "severity": max(1, int(round(active_duration))),
                "character_count": 1,
            })

    # Merge duplicate/overlapping spans only when they refer to the same local area.
    merged: list[dict[str, Any]] = []
    for span in sorted(spans, key=lambda value: (int(value["character_start"]), int(value["character_end"]))):
        if merged and int(span["character_start"]) <= int(merged[-1]["character_end"]) + 1:
            merged[-1]["character_end"] = max(int(merged[-1]["character_end"]), int(span["character_end"]))
            merged[-1]["character_count"] = int(merged[-1]["character_end"]) - int(merged[-1]["character_start"]) + 1
            merged[-1]["severity"] = int(merged[-1]["severity"]) + int(span["severity"])
            merged[-1]["reason"] = "+".join(sorted(set(str(merged[-1]["reason"]).split("+")) | {str(span["reason"])}))
        else:
            merged.append(dict(span))

    compression_values = [float(row.get("overlap_compression_sec", 0.0)) for row in new_rows]
    return {
        "triggered": bool(reasons),
        "reasons": reasons,
        "anomaly_spans": merged,
        "candidate_character_count": len(candidate_rows),
        "all_candidate_character_count": len(all_candidate_rows or candidate_rows),
        "trial_committed_character_count": len(new_rows),
        "zero_duration_count": zero_count,
        "longest_zero_duration_run": zero_run,
        "longest_equal_boundary_run": stacking_run,
        "tail_reference": "committed_rows_near_core_end",
        "tail_window_sec": tail_sec,
        "tail_pileup_count": tail_count,
        "tail_pileup_ratio": tail_ratio,
        "core_end_sec": core_end,
        "core_sustained_active_sec": active_duration,
        "overlap_compression_count": sum(value > 1e-9 for value in compression_values),
        "overlap_compression_max_sec": max(compression_values, default=0.0),
    }


def _observation_role(row: dict[str, Any]) -> str:
    start = float(row.get("fixed_global_start_sec", 0.0))
    core_start = float(row.get("core_start_sec", -math.inf))
    core_end = float(row.get("core_end_sec", math.inf))
    if start < core_start:
        return "left_context"
    if start >= core_end:
        return "future_lookahead"
    return "core"


def build_observation_features(shadow_rows: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for source in shadow_rows:
        row = dict(source)
        grouped[int(row["global_character_index"])].append(row)
    result: dict[int, dict[str, Any]] = {}
    for index, rows in grouped.items():
        supported = [row for row in rows if _observation_role(row) != "future_lookahead"]
        starts = [float(row["fixed_global_start_sec"]) for row in supported]
        ends = [float(row["fixed_global_end_sec"]) for row in supported]
        roles: dict[str, int] = defaultdict(int)
        for row in rows:
            roles[_observation_role(row)] += 1
        result[index] = {
            "observation_count": len(rows),
            "supported_observation_count": len(supported),
            "observation_roles": dict(sorted(roles.items())),
            "supported_start_range_sec": max(starts) - min(starts) if len(starts) >= 2 else None,
            "supported_end_range_sec": max(ends) - min(ends) if len(ends) >= 2 else None,
        }
    return result


def _stable_row_assessments(
    rows: Sequence[dict[str, Any]], shadow_rows: Iterable[dict[str, Any]], *,
    window_indices: set[int] | None, confidence_quantile: float,
    raw_official_tolerance_sec: float, repeated_context_tolerance_sec: float,
) -> tuple[list[dict[str, Any]], float]:
    observations = build_observation_features(shadow_rows)
    ordered = sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))
    if window_indices is not None:
        ordered = [row for row in ordered if int(row.get("owner_window_index", -1)) in window_indices]
    margins = [
        float(row.get("raw_boundary_margin_mean", 0.0))
        for row in ordered if row.get("raw_boundary_margin_mean") is not None
    ]
    threshold = _quantile(margins, confidence_quantile)
    threshold = 0.0 if threshold is None else threshold
    assessments: list[dict[str, Any]] = []
    for row in ordered:
        index = int(row["global_character_index"])
        duration = max(0.0, float(row["end_sec"]) - float(row["start_sec"]))
        margin = float(row.get("raw_boundary_margin_mean", 0.0))
        raw_start = float(row.get("raw_global_start_sec", row.get("selected_start_sec", row["start_sec"])))
        raw_end = float(row.get("raw_global_end_sec", row.get("selected_end_sec", row["end_sec"])))
        official_start = float(row.get("official_fixed_global_start_sec", row.get("selected_start_sec", row["start_sec"])))
        official_end = float(row.get("official_fixed_global_end_sec", row.get("selected_end_sec", row["end_sec"])))
        movement = max(abs(raw_start - official_start), abs(raw_end - official_end))
        observed = observations.get(index, {})
        ranges = [observed.get("supported_start_range_sec"), observed.get("supported_end_range_sec")]
        repeated_ok = all(
            value is None or float(value) <= repeated_context_tolerance_sec + 1e-9
            for value in ranges
        )
        reasons: list[str] = []
        if duration <= 1e-9:
            reasons.append("non_positive_duration")
        if bool(row.get("overlap_compression_collapsed_to_zero")):
            reasons.append("overlap_collapsed_to_zero")
        if margin < threshold - 1e-12:
            reasons.append("confidence_below_window_quantile")
        if movement > raw_official_tolerance_sec + 1e-9:
            reasons.append("raw_official_movement_exceeded")
        if not repeated_ok:
            reasons.append("supported_context_disagreement")
        assessments.append({
            "row": row, "passed": not reasons, "reasons": reasons,
            "confidence_threshold": threshold, "raw_official_movement_max_sec": movement,
            "observation": observed,
        })
    return assessments, threshold


def stable_segment_candidate_diagnostics(
    rows: Sequence[dict[str, Any]], shadow_rows: Iterable[dict[str, Any]], *,
    target_start: int, target_end: int, window_indices: set[int] | None = None,
    confidence_quantile: float = 0.50, raw_official_tolerance_sec: float = 0.16,
    repeated_context_tolerance_sec: float = 0.24, nearest_limit: int = 3,
) -> dict[str, Any]:
    """Explain why stable rows are or are not available around one target span."""
    assessments, threshold = _stable_row_assessments(
        rows, shadow_rows, window_indices=window_indices,
        confidence_quantile=confidence_quantile,
        raw_official_tolerance_sec=raw_official_tolerance_sec,
        repeated_context_tolerance_sec=repeated_context_tolerance_sec,
    )
    reason_counts: dict[str, int] = defaultdict(int)
    for assessment in assessments:
        if assessment["passed"]:
            reason_counts["passed"] += 1
        else:
            for reason in assessment["reasons"]:
                reason_counts[reason] += 1

    def compact(assessment: dict[str, Any]) -> dict[str, Any]:
        row = assessment["row"]
        return {
            "global_character_index": int(row["global_character_index"]),
            "character": row.get("character"),
            "start_sec": float(row["start_sec"]),
            "end_sec": float(row["end_sec"]),
            "raw_boundary_margin_mean": row.get("raw_boundary_margin_mean"),
            "raw_official_movement_max_sec": assessment["raw_official_movement_max_sec"],
            "observation": assessment["observation"],
            "passed": assessment["passed"],
            "reasons": assessment["reasons"],
        }

    left = sorted(
        (value for value in assessments if int(value["row"]["global_character_index"]) < target_start),
        key=lambda value: int(value["row"]["global_character_index"]), reverse=True,
    )[:nearest_limit]
    right = sorted(
        (value for value in assessments if int(value["row"]["global_character_index"]) > target_end),
        key=lambda value: int(value["row"]["global_character_index"]),
    )[:nearest_limit]
    return {
        "window_indices": None if window_indices is None else sorted(window_indices),
        "target_start": target_start, "target_end": target_end,
        "confidence_quantile": confidence_quantile, "confidence_threshold": threshold,
        "raw_official_tolerance_sec": raw_official_tolerance_sec,
        "repeated_context_tolerance_sec": repeated_context_tolerance_sec,
        "row_count": len(assessments), "reason_counts": dict(sorted(reason_counts.items())),
        "nearest_left_rows": [compact(value) for value in left],
        "nearest_right_rows": [compact(value) for value in right],
    }


def stable_segments(
    rows: Sequence[dict[str, Any]], shadow_rows: Iterable[dict[str, Any]], *,
    window_indices: set[int] | None = None, min_units: int = 2,
    confidence_quantile: float = 0.50, raw_official_tolerance_sec: float = 0.16,
    repeated_context_tolerance_sec: float = 0.24,
    excluded_character_range: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Find contiguous stable *segments* without requiring two observations.

    Confidence and raw/official convergence are hard conditions. Repeated
    supported observations are checked when available, but a good single-window
    segment is retained and explicitly labelled as single-context evidence.
    """
    assessments, threshold = _stable_row_assessments(
        rows, shadow_rows, window_indices=window_indices,
        confidence_quantile=confidence_quantile,
        raw_official_tolerance_sec=raw_official_tolerance_sec,
        repeated_context_tolerance_sec=repeated_context_tolerance_sec,
    )
    stable_rows: list[dict[str, Any]] = []
    excluded_start, excluded_end = excluded_character_range or (-1, -2)
    for assessment in assessments:
        if not assessment["passed"]:
            continue
        row = assessment["row"]
        index = int(row["global_character_index"])
        if excluded_start <= index <= excluded_end:
            continue
        stable_rows.append({
            **row,
            "stable_confidence_threshold": threshold,
            "raw_official_movement_max_sec": assessment["raw_official_movement_max_sec"],
            "observation": assessment["observation"],
        })

    groups: list[list[dict[str, Any]]] = []
    for row in stable_rows:
        if not groups or int(row["global_character_index"]) != int(groups[-1][-1]["global_character_index"]) + 1:
            groups.append([row])
        else:
            groups[-1].append(row)
    result: list[dict[str, Any]] = []
    for group in groups:
        if len(group) < min_units:
            continue
        repeated_count = sum(
            int(row.get("observation", {}).get("supported_observation_count", 0)) >= 2
            for row in group
        )
        result.append({
            "character_start": int(group[0]["global_character_index"]),
            "character_end": int(group[-1]["global_character_index"]),
            "character_count": len(group),
            "text": "".join(str(row.get("character", "")) for row in group),
            "start_sec": float(group[0]["start_sec"]),
            "end_sec": float(group[-1]["end_sec"]),
            "owner_window_indices": sorted({int(row.get("owner_window_index", -1)) for row in group}),
            "minimum_margin": min(float(row.get("raw_boundary_margin_mean", 0.0)) for row in group),
            "maximum_raw_official_movement_sec": max(float(row["raw_official_movement_max_sec"]) for row in group),
            "repeated_supported_character_count": repeated_count,
            "evidence_kind": (
                "mixed_or_repeated_context" if repeated_count else "single_window_high_confidence"
            ),
            "rows": group,
        })
    return result


def nearest_segment_pair(
    segments: Sequence[dict[str, Any]], *, target_start: int, target_end: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    left_candidates = [row for row in segments if int(row["character_end"]) < target_start]
    right_candidates = [row for row in segments if int(row["character_start"]) > target_end]
    left = max(left_candidates, key=lambda row: int(row["character_end"]), default=None)
    right = min(right_candidates, key=lambda row: int(row["character_start"]), default=None)
    if left is None and right is None:
        return None, None, "no_left_or_right_stable_segment"
    if left is None:
        return None, right, "no_left_stable_segment"
    if right is None:
        return left, None, "no_right_stable_segment"
    return left, right, None


def segment_anchor_rows(
    left_segment: dict[str, Any], right_segment: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use the segment edges for cropping while retaining full segment evidence."""
    left_row = dict(left_segment["rows"][-1])
    right_row = dict(right_segment["rows"][0])
    left_row["selected_start_sec"] = float(left_row.get("selected_start_sec", left_row["start_sec"]))
    left_row["selected_end_sec"] = float(left_row.get("selected_end_sec", left_row["end_sec"]))
    right_row["selected_start_sec"] = float(right_row.get("selected_start_sec", right_row["start_sec"]))
    right_row["selected_end_sec"] = float(right_row.get("selected_end_sec", right_row["end_sec"]))
    return left_row, right_row


def reproduce_segment(
    segment: dict[str, Any] | None, current_shadow_rows: Sequence[dict[str, Any]], *,
    tolerance_sec: float = 0.24, minimum_observed_units: int = 2,
    minimum_observed_ratio: float = 0.50,
) -> dict[str, Any]:
    if segment is None:
        return {"supported": False, "reason": "no_previous_stable_segment"}
    current = {int(row["global_character_index"]): row for row in current_shadow_rows}
    differences: list[float] = []
    observed: list[int] = []
    source_rows = list(segment.get("rows", []))
    for source in source_rows:
        index = int(source["global_character_index"])
        if index not in current:
            continue
        row = current[index]
        differences.extend((
            abs(float(source.get("selected_start_sec", source["start_sec"])) - float(row["fixed_global_start_sec"])),
            abs(float(source.get("selected_end_sec", source["end_sec"])) - float(row["fixed_global_end_sec"])),
        ))
        observed.append(index)
    if not differences:
        return {
            "supported": False,
            "reason": "segment_not_observed_in_current_window",
            "expected_character_start": segment.get("character_start"),
            "expected_character_end": segment.get("character_end"),
        }
    expected_count = max(1, len(source_rows))
    observed_ratio = len(observed) / expected_count
    if len(observed) < minimum_observed_units or observed_ratio < minimum_observed_ratio - 1e-9:
        return {
            "supported": False,
            "reason": "insufficient_segment_coverage",
            "observed_character_indices": observed,
            "observed_character_count": len(observed),
            "expected_character_count": expected_count,
            "observed_ratio": observed_ratio,
            "minimum_observed_units": minimum_observed_units,
            "minimum_observed_ratio": minimum_observed_ratio,
            "max_boundary_difference_sec": max(differences),
            "median_boundary_difference_sec": statistics.median(differences),
            "tolerance_sec": tolerance_sec,
        }
    maximum = max(differences)
    return {
        "supported": maximum <= tolerance_sec + 1e-9,
        "reason": "reproduced" if maximum <= tolerance_sec + 1e-9 else "boundary_difference_exceeds_tolerance",
        "observed_character_indices": observed,
        "observed_character_count": len(observed),
        "expected_character_count": expected_count,
        "observed_ratio": observed_ratio,
        "max_boundary_difference_sec": maximum,
        "median_boundary_difference_sec": statistics.median(differences),
        "tolerance_sec": tolerance_sec,
    }


def anomaly_spans_from_trace(trace: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return precisely located non-overlapping anomaly spans.

    New traces contain local spans from the precommit trial.  The old whole-
    window fallback is retained only for compatibility with earlier evidence.
    """
    spans: list[dict[str, Any]] = []
    for window in trace:
        diagnostic = window.get("precommit_diagnostic") or {}
        if not diagnostic.get("triggered"):
            continue
        local_spans = list(diagnostic.get("anomaly_spans") or [])
        if local_spans:
            for local in local_spans:
                spans.append({
                    "window_index": int(window.get("window_index", -1)),
                    "character_start": int(local["character_start"]),
                    "character_end": int(local["character_end"]),
                    "reasons": [str(local.get("reason", "precommit_anomaly"))],
                    "severity": int(local.get("severity", local.get("character_count", 1))),
                    "diagnostic": diagnostic,
                    "range_source": "localized_precommit_span",
                })
            continue
        start = int(window.get("committed_character_start", window.get("committed_cursor_before", 0)))
        end_exclusive = int(window.get("committed_character_end", window.get("committed_cursor_after", start)))
        if end_exclusive <= start:
            end_exclusive = start + 1
        spans.append({
            "window_index": int(window.get("window_index", -1)),
            "character_start": start,
            "character_end": end_exclusive - 1,
            "reasons": list(diagnostic.get("reasons", [])),
            "severity": (
                int(diagnostic.get("longest_zero_duration_run", 0))
                + int(diagnostic.get("longest_equal_boundary_run", 0))
                + int(diagnostic.get("tail_pileup_count", 0))
            ),
            "diagnostic": diagnostic,
            "range_source": "legacy_whole_commit_fallback",
        })
    # Merge only overlapping spans from the same source window.
    merged: list[dict[str, Any]] = []
    for span in sorted(spans, key=lambda row: (int(row["window_index"]), int(row["character_start"]), int(row["character_end"]))):
        if (
            merged
            and int(span["window_index"]) == int(merged[-1]["window_index"])
            and int(span["character_start"]) <= int(merged[-1]["character_end"]) + 1
        ):
            merged[-1]["character_end"] = max(int(merged[-1]["character_end"]), int(span["character_end"]))
            merged[-1]["severity"] = int(merged[-1]["severity"]) + int(span["severity"])
            merged[-1]["reasons"] = sorted(set(merged[-1]["reasons"]) | set(span["reasons"]))
        else:
            merged.append(dict(span))
    return sorted(merged, key=lambda row: (-int(row["severity"]), int(row["window_index"])))

