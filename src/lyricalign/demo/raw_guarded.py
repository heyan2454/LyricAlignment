"""Runtime-safe helpers for a raw-timestamp baseline plus guarded local realignment.

This module deliberately separates broad anomaly detection from the much stricter
intervention gate. A detector false positive that is not modified is recorded as
compute overhead, not as an alignment error.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Sequence

from lyricalign.demo.realign_diagnostics import (
    build_overlap_features,
    compare_two_candidates,
    select_anchor_pair,
)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    f = pos - lo
    return ordered[lo] * (1.0 - f) + ordered[hi] * f


def build_runtime_anchor_rows(
    rows: Sequence[dict[str, Any]], shadow_rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build automatic anchor features without using ground truth."""
    overlap = build_overlap_features(shadow_rows)
    result: list[dict[str, Any]] = []
    for source in sorted(rows, key=lambda row: int(row["global_character_index"])):
        row = dict(source)
        index = int(row["global_character_index"])
        selected_start = float(row.get("selected_start_sec", row.get("fixed_global_start_sec", row["start_sec"])))
        selected_end = float(row.get("selected_end_sec", row.get("fixed_global_end_sec", row["end_sec"])))
        raw_start = float(row.get("raw_global_start_sec", selected_start))
        raw_end = float(row.get("raw_global_end_sec", selected_end))
        fixed_start = float(row.get("fixed_global_start_sec", selected_start))
        fixed_end = float(row.get("fixed_global_end_sec", selected_end))
        margins = [row.get("raw_start_margin"), row.get("raw_end_margin")]
        probabilities = [row.get("raw_start_top1_probability"), row.get("raw_end_top1_probability")]
        result.append({
            "global_character_index": index,
            "character": row.get("character"),
            "selected_start_sec": selected_start,
            "selected_end_sec": selected_end,
            "confidence_margin_min": (
                min(float(v) for v in margins if v is not None)
                if any(v is not None for v in margins) else None
            ),
            "confidence_probability_min": (
                min(float(v) for v in probabilities if v is not None)
                if any(v is not None for v in probabilities) else None
            ),
            "raw_decoded_movement_max_sec": max(abs(raw_start - fixed_start), abs(raw_end - fixed_end)),
            "compressed": bool(row.get("overlap_compressed")) or float(row.get("start_sec", selected_start)) > selected_start + 1e-9,
            "collapsed": float(row.get("end_sec", selected_end)) <= float(row.get("start_sec", selected_start)) + 1e-9,
            **overlap.get(index, {}),
        })
    return result


def choose_runtime_anchor_policy(
    anchor_rows: Sequence[dict[str, Any]], *,
    margin_quantile: float = 0.75,
    overlap_tolerance_sec: float = 0.16,
    stability_tolerance_sec: float = 0.08,
) -> dict[str, Any]:
    """Choose a conservative A4-style policy from the current song only."""
    margins = [float(row["confidence_margin_min"]) for row in anchor_rows if row.get("confidence_margin_min") is not None]
    threshold = _quantile(margins, margin_quantile)
    return {
        "family": "A4",
        "policy_id": f"runtime_A4_q{margin_quantile:g}",
        "confidence_margin_min": threshold if threshold is not None else 0.0,
        "overlap_tolerance_sec": float(overlap_tolerance_sec),
        "stability_tolerance_sec": float(stability_tolerance_sec),
        "margin_quantile": float(margin_quantile),
        "anchor_row_count": len(anchor_rows),
    }


def choose_anchor_pair(
    anchor_rows: Sequence[dict[str, Any]], policy: dict[str, Any],
    target_start: int, target_end: int, *,
    max_distance_units: int = 16,
    max_pair_span_units: int = 16,
    max_pair_span_sec: float = 12.0,
    guard_units: int = 1,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    return select_anchor_pair(
        anchor_rows, policy, target_start, target_end,
        max_distance_units=max_distance_units,
        max_pair_span_units=max_pair_span_units,
        max_pair_span_sec=max_pair_span_sec,
        guard_units=guard_units,
    )


def agreement_between_trials(
    exact_rows: Sequence[dict[str, Any]], plus2_rows: Sequence[dict[str, Any]],
    indices: Iterable[int], *, tolerance_sec: float = 0.16,
) -> dict[str, Any]:
    comparison = compare_two_candidates(exact_rows, plus2_rows, indices)
    maximum = comparison.get("max_boundary_difference_sec")
    supported = (
        maximum is not None
        and not comparison.get("missing_indices")
        and float(maximum) <= float(tolerance_sec) + 1e-9
    )
    return {
        "supported": supported,
        "tolerance_sec": float(tolerance_sec),
        "comparison": comparison,
        "reason": "exact_and_plus2_agree" if supported else "exact_and_plus2_disagree",
    }


def nonoverlapping_candidates(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a severity-first, non-overlapping set for deterministic intervention."""
    selected: list[dict[str, Any]] = []
    occupied: set[int] = set()
    ordered = sorted(
        candidates,
        key=lambda row: (-float(row.get("severity_score", 0.0)), int(row["dependency_character_start"])),
    )
    for row in ordered:
        indices = set(range(int(row["dependency_character_start"]), int(row["dependency_character_end"]) + 1))
        if indices & occupied:
            continue
        selected.append(dict(row))
        occupied.update(indices)
    return sorted(selected, key=lambda row: int(row["dependency_character_start"]))


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def summarize_interventions(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    changes = [float(row.get("boundary_change_sec", 0.0)) for row in rows]
    return {
        "count": len(rows),
        "changed_count": sum(value > 1e-9 for value in changes),
        "mean_boundary_change_sec": statistics.fmean(changes) if changes else None,
        "max_boundary_change_sec": max(changes, default=None),
    }


def attach_silence_anchor_evidence(
    anchor_rows: Sequence[dict[str, Any]],
    silence_intervals: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Promote characters adjacent to sustained silence as stable anchors.

    The silence interval remains explicit evidence; this helper does not invent
    timestamps or create virtual lyric units.  It only marks the nearest
    non-collapsed character on each side of a detected silence interval.
    """
    result = [dict(row) for row in anchor_rows]
    for interval in silence_intervals:
        start = float(interval["start_sec"])
        end = float(interval["end_sec"])
        left_candidates = [
            row for row in result
            if not bool(row.get("collapsed")) and float(row["selected_end_sec"]) <= start + 1e-9
        ]
        right_candidates = [
            row for row in result
            if not bool(row.get("collapsed")) and float(row["selected_start_sec"]) >= end - 1e-9
        ]
        evidence = {
            "silence_id": interval.get("silence_id"),
            "silence_start_sec": start,
            "silence_end_sec": end,
            "silence_duration_sec": float(interval.get("duration_sec", end - start)),
            "silence_strength": interval.get("strength", "normal"),
        }
        if left_candidates:
            row = max(left_candidates, key=lambda item: float(item["selected_end_sec"]))
            row["silence_anchor_after"] = evidence
            row["silence_anchor_strength"] = evidence["silence_strength"]
        if right_candidates:
            row = min(right_candidates, key=lambda item: float(item["selected_start_sec"]))
            row["silence_anchor_before"] = evidence
            row["silence_anchor_strength"] = evidence["silence_strength"]
    return result
