"""Pure diagnostics and artifact helpers for demo local-realignment experiments.

The functions in this module deliberately separate four layers:

* structural anomaly detection, which never needs ground truth;
* anchor feature/rule evaluation, where GT is used only for analysis;
* bounded replacement/remerge candidates;
* per-case identity, status, and result collection.

Model inference remains in ``scripts/demo/run_demo_realign_quick.py`` so the
same loaded Qwen model can be reused across many cases.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from lyricalign.demo.alignment_artifacts import stage_rows

TIMESTAMP_STEP_SEC = 0.08
TOLERANCES_SEC = (0.08, 0.16, 0.24, 0.50, 1.00)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False, suffix=".tmp") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    temporary.replace(path)


def quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, probability)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def numeric_summary(values: Iterable[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return {
        "count": len(finite),
        "mean": statistics.fmean(finite) if finite else None,
        "median": quantile(finite, 0.5),
        "p90": quantile(finite, 0.9),
        "max": max(finite, default=None),
    }


def ordered_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))


def by_index(rows: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row["global_character_index"]): dict(row) for row in rows}


def project_inference_rows(rows: Iterable[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    """Project raw infer_slice rows or serial rows to start/end fields."""
    if stage in {"raw", "processor_decoded", "selected", "final"}:
        return stage_rows(rows, stage)
    raise ValueError(stage)


def stage_transition_provenance(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe where each character boundary first changed across saved stages."""
    result: list[dict[str, Any]] = []
    for source in ordered_rows(rows):
        index = int(source["global_character_index"])
        stage_values: dict[str, dict[str, float]] = {}
        for stage in ("raw", "processor_decoded", "selected", "final"):
            projected = project_inference_rows([source], stage)[0]
            stage_values[stage] = {"start_sec": float(projected["start_sec"]), "end_sec": float(projected["end_sec"])}
        transitions = []
        previous_name = "raw"
        previous = stage_values[previous_name]
        for stage in ("processor_decoded", "selected", "final"):
            current = stage_values[stage]
            movement = max(abs(current["start_sec"] - previous["start_sec"]), abs(current["end_sec"] - previous["end_sec"]))
            transitions.append({
                "from_stage": previous_name, "to_stage": stage,
                "max_boundary_movement_sec": movement,
                "changed": movement > 1e-9,
                "collapsed_after_transition": current["end_sec"] <= current["start_sec"] + 1e-9,
            })
            previous_name, previous = stage, current
        first_changed = next((row["to_stage"] for row in transitions if row["changed"]), None)
        first_collapsed = next((row["to_stage"] for row in transitions if row["collapsed_after_transition"]), None)
        result.append({
            "global_character_index": index,
            "character": source.get("character"),
            "stages": stage_values,
            "transitions": transitions,
            "first_changed_stage": first_changed,
            "first_collapsed_stage": first_collapsed,
            "selection_source": source.get("selection_source") or source.get("selected_source"),
            "overlap_compressed": bool(source.get("overlap_compressed")),
            "overlap_compression_floor_sec": source.get("overlap_compression_floor_sec"),
        })
    return result


def evaluate_rows(
    predictions: Iterable[dict[str, Any]],
    gt_rows: Iterable[dict[str, Any]],
    indices: Iterable[int] | None = None,
) -> dict[str, Any]:
    pred = by_index(predictions)
    gt = {int(row.get("character_index", row.get("global_character_index"))): dict(row) for row in gt_rows}
    requested = sorted(gt) if indices is None else sorted(set(int(index) for index in indices))
    details: list[dict[str, Any]] = []
    missing: list[int] = []
    for index in requested:
        if index not in gt or index not in pred:
            missing.append(index)
            continue
        p = pred[index]
        g = gt[index]
        p_start = float(p["start_sec"])
        p_end = float(p["end_sec"])
        g_start = float(g["start_sec"])
        g_end = float(g["end_sec"])
        details.append({
            "character_index": index,
            "character": g.get("normalized_character") or g.get("character") or p.get("character"),
            "gt_start_sec": g_start,
            "gt_end_sec": g_end,
            "pred_start_sec": p_start,
            "pred_end_sec": p_end,
            "onset_signed_error_sec": p_start - g_start,
            "offset_signed_error_sec": p_end - g_end,
            "onset_abs_error_sec": abs(p_start - g_start),
            "offset_abs_error_sec": abs(p_end - g_end),
        })
    boundary_errors = [value for row in details for value in (row["onset_abs_error_sec"], row["offset_abs_error_sec"])]
    result: dict[str, Any] = {
        "requested_unit_count": len(requested),
        "matched_unit_count": len(details),
        "missing_unit_count": len(missing),
        "missing_indices": missing,
        "onset_mae_sec": statistics.fmean([row["onset_abs_error_sec"] for row in details]) if details else None,
        "offset_mae_sec": statistics.fmean([row["offset_abs_error_sec"] for row in details]) if details else None,
        "boundary_mae_sec": statistics.fmean(boundary_errors) if boundary_errors else None,
        "boundary_median_sec": quantile(boundary_errors, 0.5),
        "boundary_p90_sec": quantile(boundary_errors, 0.9),
        "boundary_max_sec": max(boundary_errors, default=None),
        "details": details,
    }
    for tolerance in TOLERANCES_SEC:
        key = str(tolerance).replace(".", "p")
        result[f"onset_within_{key}_rate"] = (
            sum(row["onset_abs_error_sec"] <= tolerance for row in details) / len(details) if details else None
        )
        result[f"joint_within_{key}_rate"] = (
            sum(row["onset_abs_error_sec"] <= tolerance and row["offset_abs_error_sec"] <= tolerance for row in details) / len(details)
            if details else None
        )
    return result


def structural_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = ordered_rows(rows)
    zero = 0
    negative = 0
    overlaps = 0
    regressions = 0
    previous_end: float | None = None
    previous_start: float | None = None
    durations: list[float] = []
    for row in ordered:
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        duration = end - start
        durations.append(duration)
        if duration < -1e-9:
            negative += 1
        if duration <= 1e-9:
            zero += 1
        if previous_end is not None and start < previous_end - 1e-9:
            overlaps += 1
        if previous_start is not None and start < previous_start - 1e-9:
            regressions += 1
        previous_start = start
        previous_end = end
    return {
        "unit_count": len(ordered),
        "zero_duration_count": zero,
        "negative_duration_count": negative,
        "inter_unit_overlap_count": overlaps,
        "start_regression_count": regressions,
        "duration_sec": numeric_summary(durations),
    }


def accepted_shadow_rows(window_trace: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for window in window_trace:
        window_index = int(window["window_index"])
        for source in window.get("shadow_rows", []):
            row = dict(source)
            row["shadow_window_index"] = window_index
            result.append(row)
    return result


def build_overlap_features(shadow_rows: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Aggregate independent accepted-window predictions for each lyric unit."""
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in shadow_rows:
        grouped[int(row["global_character_index"])].append(dict(row))
    result: dict[int, dict[str, Any]] = {}
    for index, rows in grouped.items():
        unique: dict[int, dict[str, Any]] = {}
        for row in rows:
            unique[int(row.get("shadow_window_index", row.get("window_index", -1)))] = row
        observations = list(unique.values())
        fixed_starts = [float(row["fixed_global_start_sec"]) for row in observations]
        fixed_ends = [float(row["fixed_global_end_sec"]) for row in observations]
        raw_starts = [float(row["raw_global_start_sec"]) for row in observations if row.get("raw_global_start_sec") is not None]
        raw_ends = [float(row["raw_global_end_sec"]) for row in observations if row.get("raw_global_end_sec") is not None]
        result[index] = {
            "overlap_observation_count": len(observations),
            "overlap_window_indices": sorted(unique),
            "overlap_fixed_start_range_sec": max(fixed_starts) - min(fixed_starts) if len(fixed_starts) >= 2 else None,
            "overlap_fixed_end_range_sec": max(fixed_ends) - min(fixed_ends) if len(fixed_ends) >= 2 else None,
            "overlap_fixed_midpoint_range_sec": (
                max((a + b) / 2 for a, b in zip(fixed_starts, fixed_ends, strict=True))
                - min((a + b) / 2 for a, b in zip(fixed_starts, fixed_ends, strict=True))
                if len(fixed_starts) >= 2 else None
            ),
            "overlap_raw_start_range_sec": max(raw_starts) - min(raw_starts) if len(raw_starts) >= 2 else None,
            "overlap_raw_end_range_sec": max(raw_ends) - min(raw_ends) if len(raw_ends) >= 2 else None,
            "overlap_fixed_start_median_sec": quantile(fixed_starts, 0.5),
            "overlap_fixed_end_median_sec": quantile(fixed_ends, 0.5),
            "overlap_observations": [
                {
                    "window_index": int(row.get("shadow_window_index", row.get("window_index", -1))),
                    "raw_start_sec": row.get("raw_global_start_sec"),
                    "raw_end_sec": row.get("raw_global_end_sec"),
                    "decoded_start_sec": row.get("fixed_global_start_sec"),
                    "decoded_end_sec": row.get("fixed_global_end_sec"),
                }
                for row in observations
            ],
        }
    return result


def commit_dependency_span(rows: Sequence[dict[str, Any]], target_start: int, target_end: int) -> tuple[int, int, list[dict[str, Any]]]:
    """Trace observable forward-compression dependencies without GT.

    ``target_end`` is inclusive.  The returned span includes the earliest unit
    whose final end supplied the compression floor of a target unit.  This is a
    commit-dependency explanation, not a claim that the predecessor is wrong.
    """
    indexed = by_index(rows)
    start = target_start
    trace: list[dict[str, Any]] = []
    cursor = target_start
    visited: set[int] = set()
    while cursor in indexed and cursor not in visited:
        visited.add(cursor)
        row = indexed[cursor]
        compressed = bool(row.get("overlap_compressed")) or (
            row.get("selected_start_sec") is not None
            and float(row.get("start_sec", 0.0)) > float(row["selected_start_sec"]) + 1e-9
        )
        if not compressed or cursor <= 0 or cursor - 1 not in indexed:
            break
        predecessor = indexed[cursor - 1]
        floor = float(row.get("overlap_compression_floor_sec", row.get("start_sec", 0.0)))
        pred_end = float(predecessor["end_sec"])
        trace.append({
            "affected_index": cursor,
            "dependency_index": cursor - 1,
            "compression_floor_sec": floor,
            "dependency_final_end_sec": pred_end,
            "reason": "previous_final_end_supplied_forward_compression_floor",
        })
        start = cursor - 1
        cursor -= 1
        # Continue only when the predecessor itself was structurally changed.
        pred_selected_end = predecessor.get("selected_end_sec")
        if not predecessor.get("overlap_compressed") and (
            pred_selected_end is None or abs(float(pred_selected_end) - pred_end) <= 1e-9
        ):
            break
    return start, target_end, trace


def _candidate_flags(
    rows: Sequence[dict[str, Any]], overlap: dict[int, dict[str, Any]], *,
    timestamp_step_sec: float,
) -> dict[int, set[str]]:
    flags: dict[int, set[str]] = defaultdict(set)
    ordered = ordered_rows(rows)
    durations = [max(0.0, float(row["end_sec"]) - float(row["start_sec"])) for row in ordered]
    local_median = quantile([value for value in durations if value > 1e-9], 0.5) or timestamp_step_sec
    previous: dict[str, Any] | None = None
    for row in ordered:
        index = int(row["global_character_index"])
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        duration = max(0.0, end - start)
        selected_start = float(row.get("selected_start_sec", row.get("fixed_global_start_sec", start)))
        selected_end = float(row.get("selected_end_sec", row.get("fixed_global_end_sec", end)))
        selected_duration = max(0.0, selected_end - selected_start)
        compression = max(0.0, start - selected_start)
        if duration <= 1e-9:
            flags[index].add("zero_duration")
        if duration <= timestamp_step_sec + 1e-9:
            flags[index].add("one_step_or_shorter")
        if selected_duration > 2 * timestamp_step_sec and duration / selected_duration <= 0.25:
            flags[index].add("severe_duration_compression")
        if compression >= 2 * timestamp_step_sec - 1e-9 or bool(row.get("overlap_compressed")):
            flags[index].add("selected_to_final_compression")
        if previous is not None and selected_start < float(previous["end_sec"]) - 1e-9:
            flags[index].add("selected_conflicts_with_frozen_prefix")
        if previous is not None and (
            abs(start - float(previous["start_sec"])) <= 1e-9
            or abs(end - float(previous["end_sec"])) <= 1e-9
        ):
            flags[index].add("boundary_stacking")
        raw_start = row.get("raw_global_start_sec")
        raw_end = row.get("raw_global_end_sec")
        fixed_start = row.get("fixed_global_start_sec")
        fixed_end = row.get("fixed_global_end_sec")
        if None not in (raw_start, raw_end, fixed_start, fixed_end):
            movement = max(abs(float(raw_start) - float(fixed_start)), abs(float(raw_end) - float(fixed_end)))
            if movement >= 3 * timestamp_step_sec - 1e-9:
                flags[index].add("large_raw_decoded_movement")
        overlap_row = overlap.get(index, {})
        ranges = [
            overlap_row.get("overlap_fixed_start_range_sec"),
            overlap_row.get("overlap_fixed_end_range_sec"),
        ]
        if any(value is not None and float(value) >= 3 * timestamp_step_sec - 1e-9 for value in ranges):
            flags[index].add("cross_window_disagreement")
        if duration <= max(timestamp_step_sec, 0.20 * local_median):
            flags[index].add("local_rate_short_unit")
        previous = row
    return flags


def mine_natural_candidates(
    rows: Sequence[dict[str, Any]],
    shadow_rows: Iterable[dict[str, Any]],
    *,
    item_id: str,
    audio_variant: str,
    max_gap_units: int = 1,
    max_target_units: int = 8,
    disagreement_peak_threshold_sec: float = 0.24,
    timestamp_step_sec: float = TIMESTAMP_STEP_SEC,
) -> list[dict[str, Any]]:
    """Mine short natural candidates without using GT.

    Structural failures and cross-window disagreement are handled separately.
    Continuous disagreement is split around local peaks instead of becoming one
    very long repair interval.
    """
    overlap = build_overlap_features(shadow_rows)
    flags = _candidate_flags(rows, overlap, timestamp_step_sec=timestamp_step_sec)
    indexed = by_index(rows)
    structural_names = {
        "zero_duration", "severe_duration_compression", "selected_to_final_compression",
        "selected_conflicts_with_frozen_prefix", "boundary_stacking",
        "large_raw_decoded_movement",
    }
    structural_indices = sorted(index for index, names in flags.items() if names & structural_names)

    def grouped(indices: list[int]) -> list[list[int]]:
        groups: list[list[int]] = []
        for index in indices:
            if not groups or index - groups[-1][-1] > max_gap_units + 1 or len(groups[-1]) >= max_target_units:
                groups.append([index])
            else:
                groups[-1].append(index)
        return groups

    groups_with_type: list[tuple[str, list[int]]] = [("structural", group) for group in grouped(structural_indices)]

    disagreement_scores: dict[int, float] = {}
    for index, feature in overlap.items():
        values = [feature.get("overlap_fixed_start_range_sec"), feature.get("overlap_fixed_end_range_sec")]
        finite = [float(value) for value in values if value is not None]
        if finite:
            disagreement_scores[index] = max(finite)
    peak_indices: list[int] = []
    for index, score in sorted(disagreement_scores.items()):
        if score < disagreement_peak_threshold_sec - 1e-9:
            continue
        left = disagreement_scores.get(index - 1, -math.inf)
        right = disagreement_scores.get(index + 1, -math.inf)
        if score >= left and score >= right:
            peak_indices.append(index)

    # Quick v2 produced many sliding, heavily overlapping windows around nearby
    # disagreement peaks. Keep the strongest peak first and suppress any later
    # proposal whose target interval overlaps an already accepted interval.
    accepted_disagreement_windows: list[dict[str, Any]] = []
    for peak in sorted(peak_indices, key=lambda idx: (-disagreement_scores[idx], idx)):
        half = max_target_units // 2
        start_idx = max(min(indexed), peak - half)
        end_idx = min(max(indexed), start_idx + max_target_units - 1)
        start_idx = max(min(indexed), end_idx - max_target_units + 1)
        overlapping = next((
            row for row in accepted_disagreement_windows
            if not (end_idx < int(row["start"]) or start_idx > int(row["end"]))
        ), None)
        if overlapping is not None:
            overlapping["merged_peak_indices"].append(peak)
            overlapping["merged_peak_scores_sec"].append(disagreement_scores[peak])
            continue
        accepted_disagreement_windows.append({
            "start": start_idx,
            "end": end_idx,
            "primary_peak_index": peak,
            "primary_peak_score_sec": disagreement_scores[peak],
            "merged_peak_indices": [peak],
            "merged_peak_scores_sec": [disagreement_scores[peak]],
        })
    disagreement_metadata: dict[tuple[int, int], dict[str, Any]] = {}
    for window in sorted(accepted_disagreement_windows, key=lambda row: (int(row["start"]), int(row["end"]))):
        start_idx = int(window["start"])
        end_idx = int(window["end"])
        groups_with_type.append(("cross_window_disagreement_peak", list(range(start_idx, end_idx + 1))))
        disagreement_metadata[(start_idx, end_idx)] = window

    # Deduplicate exact groups while preserving short spans.
    seen: set[tuple[str, int, int]] = set()
    candidates: list[dict[str, Any]] = []
    ordinal = 0
    for candidate_type, indices in groups_with_type:
        indices = sorted(index for index in set(indices) if index in indexed)
        if not indices:
            continue
        observed_start, observed_end = min(indices), max(indices)
        if candidate_type == "structural":
            dependency_start, dependency_end, dependency_trace = commit_dependency_span(rows, observed_start, observed_end)
            if dependency_end - dependency_start + 1 > max_target_units:
                dependency_start = max(observed_start - 1, dependency_end - max_target_units + 1)
                dependency_trace = [row for row in dependency_trace if int(row["dependency_index"]) >= dependency_start]
        else:
            dependency_start, dependency_end, dependency_trace = observed_start, observed_end, []
        key = (candidate_type, dependency_start, dependency_end)
        if key in seen:
            continue
        seen.add(key)
        all_indices = list(range(dependency_start, dependency_end + 1))
        trigger_counts = Counter(name for index in all_indices for name in flags.get(index, set()))
        start_sec = min(float(indexed[index]["start_sec"]) for index in all_indices)
        end_sec = max(float(indexed[index]["end_sec"]) for index in all_indices)
        selected_start = min(float(indexed[index].get("selected_start_sec", indexed[index]["start_sec"])) for index in all_indices)
        selected_end = max(float(indexed[index].get("selected_end_sec", indexed[index]["end_sec"])) for index in all_indices)
        peak_score = max((disagreement_scores.get(index, 0.0) for index in all_indices), default=0.0)
        severity_score = (
            8 * trigger_counts["zero_duration"] + 5 * trigger_counts["severe_duration_compression"]
            + 3 * trigger_counts["selected_to_final_compression"]
            + 2 * trigger_counts["large_raw_decoded_movement"]
            + trigger_counts["boundary_stacking"] + 4 * peak_score
        )
        candidate_id = f"{item_id}_{audio_variant}_{candidate_type}_{ordinal:03d}_{dependency_start:05d}_{dependency_end:05d}"
        ordinal += 1
        candidates.append({
            "case_id": candidate_id, "item_id": item_id, "audio_variant": audio_variant,
            "family": "natural", "candidate_type": candidate_type,
            "observed_character_start": observed_start, "observed_character_end": observed_end,
            "dependency_character_start": dependency_start, "dependency_character_end": dependency_end,
            "character_indices": all_indices, "target_unit_count": len(all_indices),
            "trigger_counts": dict(sorted(trigger_counts.items())),
            "trigger_flags_by_index": {str(index): sorted(flags[index]) for index in all_indices if flags.get(index)},
            "constraint_dependency_trace": dependency_trace,
            "cross_window_disagreement_peak_sec": peak_score,
            "cross_window_disagreement_metadata": (
                disagreement_metadata.get((observed_start, observed_end))
                if candidate_type == "cross_window_disagreement_peak" else None
            ),
            "final_interval_sec": [start_sec, end_sec], "selected_interval_sec": [selected_start, selected_end],
            "severity_score": severity_score,
        })
    return sorted(candidates, key=lambda row: (-float(row["severity_score"]), int(row["dependency_character_start"])))


def build_anchor_rows(
    rows: Sequence[dict[str, Any]],
    shadow_rows: Iterable[dict[str, Any]],
    gt_rows: Sequence[dict[str, Any]],
    *,
    item_id: str,
    audio_variant: str,
) -> list[dict[str, Any]]:
    overlap = build_overlap_features(shadow_rows)
    gt = {int(row["character_index"]): row for row in gt_rows}
    result: list[dict[str, Any]] = []
    for row in ordered_rows(rows):
        index = int(row["global_character_index"])
        if index not in gt:
            continue
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        selected_start = float(row.get("selected_start_sec", row.get("fixed_global_start_sec", start)))
        selected_end = float(row.get("selected_end_sec", row.get("fixed_global_end_sec", end)))
        raw_start = float(row.get("raw_global_start_sec", selected_start))
        raw_end = float(row.get("raw_global_end_sec", selected_end))
        fixed_start = float(row.get("fixed_global_start_sec", selected_start))
        fixed_end = float(row.get("fixed_global_end_sec", selected_end))
        gt_start = float(gt[index]["start_sec"])
        gt_end = float(gt[index]["end_sec"])
        feature = overlap.get(index, {})
        start_probability = row.get("raw_start_top1_probability")
        end_probability = row.get("raw_end_top1_probability")
        start_margin = row.get("raw_start_margin")
        end_margin = row.get("raw_end_margin")
        entropy_values = [value for value in (row.get("raw_start_entropy"), row.get("raw_end_entropy")) if value is not None]
        result.append({
            "item_id": item_id,
            "audio_variant": audio_variant,
            "global_character_index": index,
            "character": row.get("character"),
            "final_start_sec": start,
            "final_end_sec": end,
            "selected_start_sec": selected_start,
            "selected_end_sec": selected_end,
            "gt_start_sec": gt_start,
            "gt_end_sec": gt_end,
            "onset_abs_error_sec": abs(selected_start - gt_start),
            "offset_abs_error_sec": abs(selected_end - gt_end),
            "joint_error_max_sec": max(abs(selected_start - gt_start), abs(selected_end - gt_end)),
            "confidence_probability_min": min(float(start_probability), float(end_probability)) if None not in (start_probability, end_probability) else None,
            "confidence_margin_min": min(float(start_margin), float(end_margin)) if None not in (start_margin, end_margin) else None,
            "entropy_mean": statistics.fmean(float(value) for value in entropy_values) if entropy_values else None,
            "raw_decoded_movement_max_sec": max(abs(raw_start - fixed_start), abs(raw_end - fixed_end)),
            "selected_final_movement_max_sec": max(abs(selected_start - start), abs(selected_end - end)),
            "compressed": bool(row.get("overlap_compressed")) or start > selected_start + 1e-9,
            "collapsed": end <= start + 1e-9,
            "duration_sec": max(0.0, selected_end - selected_start),
            **{key: value for key, value in feature.items() if key != "overlap_observations"},
        })
    return result


def _policy_pass(row: dict[str, Any], policy: dict[str, Any]) -> bool:
    family = str(policy["family"])
    margin_threshold = policy.get("confidence_margin_min")
    overlap_tolerance = policy.get("overlap_tolerance_sec")
    stability_tolerance = policy.get("stability_tolerance_sec")
    if family in {"A0", "A2", "A3", "A4"}:
        margin = row.get("confidence_margin_min")
        if margin is None or margin_threshold is None or float(margin) < float(margin_threshold):
            return False
    if family in {"A1", "A2", "A3", "A4"}:
        if int(row.get("overlap_observation_count") or 0) < 2:
            return False
        disagreement = max(
            float(row.get("overlap_fixed_start_range_sec") or 0.0),
            float(row.get("overlap_fixed_end_range_sec") or 0.0),
        )
        if overlap_tolerance is None or disagreement > float(overlap_tolerance) + 1e-9:
            return False
    if family in {"A3", "A4"}:
        if stability_tolerance is None or float(row.get("raw_decoded_movement_max_sec") or math.inf) > float(stability_tolerance) + 1e-9:
            return False
    if family == "A4" and (bool(row.get("compressed")) or bool(row.get("collapsed"))):
        return False
    return True


def anchor_policy_grid(anchor_rows: Sequence[dict[str, Any]], timestamp_step_sec: float = TIMESTAMP_STEP_SEC) -> list[dict[str, Any]]:
    margins = [float(row["confidence_margin_min"]) for row in anchor_rows if row.get("confidence_margin_min") is not None]
    margin_thresholds = sorted(set(round(float(quantile(margins, q) or 0.0), 8) for q in (0.50, 0.60, 0.70, 0.80, 0.90)))
    overlap_tolerances = [step * timestamp_step_sec for step in (1, 2, 3, 4, 6)]
    policies: list[dict[str, Any]] = []
    for family in ("A0", "A1", "A2", "A3", "A4"):
        margins_for_family: Sequence[float | None] = margin_thresholds if family != "A1" else [None]
        overlaps_for_family: Sequence[float | None] = overlap_tolerances if family != "A0" else [None]
        for margin in margins_for_family:
            for overlap in overlaps_for_family:
                policy = {
                    "family": family,
                    "confidence_margin_min": margin,
                    "overlap_tolerance_sec": overlap,
                    "stability_tolerance_sec": overlap if family in {"A3", "A4"} else None,
                }
                policy["policy_id"] = f"{family}_m{margin if margin is not None else 'na'}_o{overlap if overlap is not None else 'na'}"
                policies.append(policy)
    return policies


def select_anchor_pair(
    anchor_rows: Sequence[dict[str, Any]],
    policy: dict[str, Any],
    target_start: int,
    target_end: int,
    *,
    max_distance_units: int = 16,
    max_pair_span_units: int = 16,
    max_pair_span_sec: float = 12.0,
    guard_units: int = 1,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Choose nearby anchors outside the suspicious interval and guard band."""
    by_idx = {int(row["global_character_index"]): row for row in anchor_rows}
    rejected: list[dict[str, Any]] = []
    left = None
    left_limit = target_start - guard_units - 1
    for index in range(left_limit, max(-1, left_limit - max_distance_units - 1), -1):
        row = by_idx.get(index)
        if row is None:
            continue
        if _policy_pass(row, policy):
            left = row
            break
        rejected.append({"side": "left", "index": index, "reason": "policy_failed"})
    right = None
    right_begin = target_end + guard_units + 1
    for index in range(right_begin, right_begin + max_distance_units + 1):
        row = by_idx.get(index)
        if row is None:
            break
        if _policy_pass(row, policy):
            right = row
            break
        rejected.append({"side": "right", "index": index, "reason": "policy_failed"})
    if left is None or right is None:
        return left, right, rejected
    span_units = int(right["global_character_index"]) - int(left["global_character_index"]) + 1
    span_sec = float(right["selected_end_sec"]) - float(left["selected_start_sec"])
    if span_units > max_pair_span_units:
        rejected.append({"side": "pair", "reason": "pair_span_units_exceeded", "value": span_units, "limit": max_pair_span_units})
        return None, None, rejected
    if span_sec > max_pair_span_sec + 1e-9:
        rejected.append({"side": "pair", "reason": "pair_span_sec_exceeded", "value": span_sec, "limit": max_pair_span_sec})
        return None, None, rejected
    return left, right, rejected


def scan_anchor_policies(
    anchor_rows: Sequence[dict[str, Any]],
    candidates: Sequence[dict[str, Any]],
    *,
    timestamp_step_sec: float = TIMESTAMP_STEP_SEC,
    max_distance_units: int = 16,
    max_pair_span_units: int = 16,
    max_pair_span_sec: float = 12.0,
    guard_units: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    policies = anchor_policy_grid(anchor_rows, timestamp_step_sec=timestamp_step_sec)
    results: list[dict[str, Any]] = []
    for policy in policies:
        accepted = [row for row in anchor_rows if _policy_pass(row, policy)]
        result: dict[str, Any] = {
            **policy,
            "anchor_count": len(accepted),
            "anchor_coverage": len(accepted) / len(anchor_rows) if anchor_rows else 0.0,
        }
        for tolerance in (0.08, 0.16, 0.24):
            key = str(tolerance).replace(".", "p")
            result[f"anchor_joint_within_{key}_rate"] = (
                sum(float(row["joint_error_max_sec"]) <= tolerance for row in accepted) / len(accepted) if accepted else None
            )
        pair_count = 0
        pair_correct = {0.08: 0, 0.16: 0, 0.24: 0}
        pair_distances: list[int] = []
        audio_lengths: list[float] = []
        grouped_anchor_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for anchor_row in anchor_rows:
            grouped_anchor_rows[(
                str(anchor_row.get("item_id")), str(anchor_row.get("audio_variant")), str(anchor_row.get("core_sec")),
            )].append(anchor_row)
        for candidate in candidates:
            candidate_anchor_rows = grouped_anchor_rows.get(
                (
                    str(candidate.get("item_id")), str(candidate.get("audio_variant")), str(candidate.get("core_sec")),
                ), []
            )
            left, right, _ = select_anchor_pair(
                candidate_anchor_rows, policy,
                int(candidate["dependency_character_start"]),
                int(candidate["dependency_character_end"]),
                max_distance_units=max_distance_units,
                max_pair_span_units=max_pair_span_units,
                max_pair_span_sec=max_pair_span_sec,
                guard_units=guard_units,
            )
            if left is None or right is None:
                continue
            pair_count += 1
            pair_distances.append(
                int(candidate["dependency_character_start"]) - int(left["global_character_index"])
                + int(right["global_character_index"]) - int(candidate["dependency_character_end"])
            )
            audio_lengths.append(float(right["selected_end_sec"]) - float(left["selected_start_sec"]))
            for tolerance in pair_correct:
                if float(left["joint_error_max_sec"]) <= tolerance and float(right["joint_error_max_sec"]) <= tolerance:
                    pair_correct[tolerance] += 1
        result["pair_count"] = pair_count
        result["pair_coverage"] = pair_count / len(candidates) if candidates else 0.0
        for tolerance, correct in pair_correct.items():
            key = str(tolerance).replace(".", "p")
            result[f"pair_both_within_{key}_rate"] = correct / pair_count if pair_count else None
        result["pair_distance_units"] = numeric_summary(pair_distances)
        result["pair_audio_length_sec"] = numeric_summary(audio_lengths)
        accuracy = result.get("pair_both_within_0p16_rate")
        result["selection_score"] = (
            (float(accuracy) if accuracy is not None else 0.0) * math.sqrt(max(float(result["pair_coverage"]), 0.0))
        )
        results.append(result)
    ordered = sorted(
        results,
        key=lambda row: (
            -float(row["selection_score"]),
            -float(row.get("pair_both_within_0p16_rate") or 0.0),
            -float(row["pair_coverage"]),
            row["policy_id"],
        ),
    )
    shortlist: list[dict[str, Any]] = []
    if ordered:
        shortlist.append({**ordered[0], "shortlist_role": "best_utility"})
        strict = max(
            ordered,
            key=lambda row: (
                float(row.get("pair_both_within_0p16_rate") or 0.0),
                float(row.get("pair_both_within_0p08_rate") or 0.0),
                float(row["pair_coverage"]),
            ),
        )
        if strict["policy_id"] != shortlist[0]["policy_id"]:
            shortlist.append({**strict, "shortlist_role": "strict_accuracy"})
        family_best: dict[str, dict[str, Any]] = {}
        for row in ordered:
            family_best.setdefault(str(row["family"]), row)
        for family in ("A1", "A4"):
            row = family_best.get(family)
            if row and all(item["policy_id"] != row["policy_id"] for item in shortlist):
                shortlist.append({**row, "shortlist_role": f"family_{family}"})
            if len(shortlist) >= 4:
                break
    return results, shortlist[:4]


def oracle_anchor_pair(
    gt_rows: Sequence[dict[str, Any]], target_start: int, target_end: int, *, guard_units: int = 0
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    gt = {int(row["character_index"]): row for row in gt_rows}
    left_index = target_start - guard_units - 1
    right_index = target_end + guard_units + 1
    if left_index not in gt or right_index not in gt:
        return None, None
    left = {
        "global_character_index": left_index,
        "character": gt[left_index].get("normalized_character") or gt[left_index].get("character"),
        "selected_start_sec": float(gt[left_index]["start_sec"]),
        "selected_end_sec": float(gt[left_index]["end_sec"]),
        "anchor_source": "ground_truth_oracle",
    }
    right = {
        "global_character_index": right_index,
        "character": gt[right_index].get("normalized_character") or gt[right_index].get("character"),
        "selected_start_sec": float(gt[right_index]["start_sec"]),
        "selected_end_sec": float(gt[right_index]["end_sec"]),
        "anchor_source": "ground_truth_oracle",
    }
    return left, right


def crop_from_anchors(
    left: dict[str, Any], right: dict[str, Any], *, padding_sec: float, audio_duration_sec: float
) -> tuple[float, float]:
    start = max(0.0, float(left["selected_start_sec"]) - padding_sec)
    end = min(audio_duration_sec, float(right["selected_end_sec"]) + padding_sec)
    if end <= start:
        raise ValueError(f"invalid anchor crop: {start} >= {end}")
    return start, end


def stage_from_local_inference(rows: Iterable[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    if stage == "local_raw":
        keys = ("raw_global_start_sec", "raw_global_end_sec")
    elif stage == "local_decoded":
        keys = ("fixed_global_start_sec", "fixed_global_end_sec")
    else:
        raise ValueError(stage)
    result: list[dict[str, Any]] = []
    for source in ordered_rows(rows):
        row = dict(source)
        row["start_sec"] = float(row[keys[0]])
        row["end_sec"] = float(row[keys[1]])
        row["artifact_stage"] = stage
        result.append(row)
    return result


def bounded_splice(
    baseline_rows: Sequence[dict[str, Any]],
    replacement_rows: Sequence[dict[str, Any]],
    *,
    replace_start: int,
    replace_end: int,
    remerge: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace inclusive indices while preserving all non-target rows exactly.

    When ``remerge`` is true, replacement rows are forward-compressed against
    the unchanged prefix, and the last replacement is capped at the unchanged
    right neighbor's start.  No later row is shifted.
    """
    baseline = by_index(baseline_rows)
    replacement = by_index(replacement_rows)
    missing = [index for index in range(replace_start, replace_end + 1) if index not in replacement]
    if missing:
        return ordered_rows(baseline_rows), {
            "valid": False,
            "reason": "replacement_missing_indices",
            "missing_indices": missing,
            "changed_indices": [],
        }
    output = {index: dict(row) for index, row in baseline.items()}
    previous_end = float(baseline[replace_start - 1]["end_sec"]) if replace_start - 1 in baseline else 0.0
    right_start = float(baseline[replace_end + 1]["start_sec"]) if replace_end + 1 in baseline else math.inf
    changed: list[int] = []
    clipped = 0
    for index in range(replace_start, replace_end + 1):
        row = dict(replacement[index])
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        source_start, source_end = start, end
        if remerge:
            start = max(start, previous_end)
            end = max(end, start)
            if index == replace_end and end > right_start:
                end = right_start
                start = min(start, end)
                clipped += 1
        row["start_sec"] = start
        row["end_sec"] = end
        row["quick_realign_source_start_sec"] = source_start
        row["quick_realign_source_end_sec"] = source_end
        row["quick_realign_remerged"] = remerge
        output[index] = row
        previous_end = end
        changed.append(index)
    ordered = [output[index] for index in sorted(output)]
    structural = structural_summary(ordered)
    valid = structural["negative_duration_count"] == 0 and structural["inter_unit_overlap_count"] == 0
    return ordered, {
        "valid": valid,
        "reason": None if valid else "structural_conflict_after_splice",
        "changed_indices": changed,
        "right_boundary_clip_count": clipped,
        "structural": structural,
    }


def stage_rollback_candidate(
    baseline_rows: Sequence[dict[str, Any]], stage: str, replace_start: int, replace_end: int,
    *, max_predecessor_units: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Restore one saved stage and include earlier units that would clamp it again.

    Quick v2 restored the target unit but still used the previous unit's final
    end as the lower bound. A correct raw interval could therefore be compressed
    back to the old final result. This function expands the replacement to the
    left while that final-prefix boundary would block the requested stage.
    """
    replacement = project_inference_rows(baseline_rows, stage)
    final = project_inference_rows(baseline_rows, "final")
    stage_by_index = by_index(replacement)
    final_by_index = by_index(final)
    effective_start = replace_start
    expansion_trace: list[dict[str, Any]] = []
    minimum_index = min(final_by_index, default=replace_start)
    while effective_start > minimum_index and len(expansion_trace) < max_predecessor_units:
        predecessor_index = effective_start - 1
        if effective_start not in stage_by_index or predecessor_index not in final_by_index:
            break
        requested_stage_start = float(stage_by_index[effective_start]["start_sec"])
        predecessor_final_end = float(final_by_index[predecessor_index]["end_sec"])
        if requested_stage_start >= predecessor_final_end - 1e-9:
            break
        expansion_trace.append({
            "blocked_index": effective_start,
            "included_predecessor_index": predecessor_index,
            "requested_stage_start_sec": requested_stage_start,
            "predecessor_final_end_sec": predecessor_final_end,
            "reason": "previous_final_end_would_recompress_restored_stage",
        })
        effective_start = predecessor_index
    merged, diagnostic = bounded_splice(
        final, replacement, replace_start=effective_start, replace_end=replace_end, remerge=True,
    )
    diagnostic.update({
        "requested_replace_start": replace_start,
        "requested_replace_end": replace_end,
        "effective_replace_start": effective_start,
        "effective_replace_end": replace_end,
        "predecessor_expansion_count": len(expansion_trace),
        "predecessor_expansion_trace": expansion_trace,
        "stage": stage,
    })
    return merged, diagnostic


def repair_context_agreement(
    candidates: Sequence[dict[str, Any]], ordinal: int, *, tolerance_sec: float = 0.16,
) -> dict[str, Any]:
    """Check whether another reasonable input construction supports a result."""
    candidate = candidates[ordinal]
    mode = str(candidate.get("mode", ""))
    crop_mode = str(candidate.get("crop_mode", ""))
    if "rollback" in mode:
        return {
            "required": False, "supported": True, "reason": "saved_stage_recovery_does_not_use_multiple_input_crops",
            "tolerance_sec": tolerance_sec, "supporting_candidate_ordinals": [],
        }
    if crop_mode not in {"exact_anchor", "matched_context"} or "bounded_remerge" not in mode:
        return {
            "required": True, "supported": False, "reason": "candidate_is_not_a_supported_local_input_mode",
            "tolerance_sec": tolerance_sec, "supporting_candidate_ordinals": [],
        }
    rows = candidate.get("changed_rows") or []
    indices = candidate.get("target_indices") or candidate.get("replacement_indices") or []
    support: list[dict[str, Any]] = []
    for other_ordinal, other in enumerate(candidates):
        if other_ordinal == ordinal:
            continue
        if str(other.get("anchor_mode")) != str(candidate.get("anchor_mode")):
            continue
        if str(other.get("mode")) != mode:
            continue
        other_crop = str(other.get("crop_mode", ""))
        if other_crop not in {"exact_anchor", "matched_context"} or other_crop == crop_mode and int(other.get("context_units") or 0) == int(candidate.get("context_units") or 0):
            continue
        if other.get("target_indices") != candidate.get("target_indices"):
            continue
        comparison = compare_two_candidates(rows, other.get("changed_rows") or [], indices)
        maximum = comparison.get("max_boundary_difference_sec")
        if maximum is not None and not comparison.get("missing_indices") and float(maximum) <= tolerance_sec + 1e-9:
            support.append({
                "candidate_ordinal": other_ordinal,
                "crop_mode": other_crop,
                "context_units": other.get("context_units"),
                "max_boundary_difference_sec": maximum,
            })
    return {
        "required": True,
        "supported": bool(support),
        "reason": "supported_by_another_reasonable_input" if support else "no_second_reasonable_input_agreed",
        "tolerance_sec": tolerance_sec,
        "supporting_candidate_ordinals": [row["candidate_ordinal"] for row in support],
        "support": support,
    }


def select_single_repair_candidate(
    candidates: Sequence[dict[str, Any]], *, require_context_agreement: bool = False,
    context_agreement_tolerance_sec: float = 0.16,
    excluded_anchor_modes: Sequence[str] = ("gt_oracle",),
) -> dict[str, Any]:
    """Select one candidate without GT, or keep the baseline when uncertain."""
    eligible = []
    rejected_counts: Counter[str] = Counter()
    excluded = set(excluded_anchor_modes)
    for ordinal, candidate in enumerate(candidates):
        if "direct_trust" in str(candidate.get("mode", "")):
            rejected_counts["direct_trust_diagnostic"] += 1
            continue
        if str(candidate.get("anchor_mode")) in excluded:
            rejected_counts["ground_truth_anchor_excluded"] += 1
            continue
        splice = candidate.get("splice") or {}
        acceptance = candidate.get("acceptance") or {}
        if not splice.get("valid"):
            rejected_counts["invalid_splice"] += 1
            continue
        before = (acceptance.get("before_anomaly") or {}).get("score")
        after = (acceptance.get("after_anomaly") or {}).get("score")
        if before is None or after is None or float(after) >= float(before):
            rejected_counts["no_anomaly_reduction"] += 1
            continue
        anchor_error = (candidate.get("anchor_reproduction") or {}).get("max_error_sec")
        if anchor_error is not None and float(anchor_error) > 0.16:
            rejected_counts["anchor_reproduction_too_far"] += 1
            continue
        agreement = repair_context_agreement(
            candidates, ordinal, tolerance_sec=context_agreement_tolerance_sec,
        )
        if require_context_agreement and agreement.get("required") and not agreement.get("supported"):
            rejected_counts["no_second_input_agreement"] += 1
            continue
        mode = str(candidate.get("mode", ""))
        crop_mode = str(candidate.get("crop_mode", "stage_rollback"))
        mode_priority = 0 if "rollback" in mode else 1
        crop_priority = {"exact_anchor": 0, "matched_context": 1, "audio_only_padding": 2, "stage_rollback": 0}.get(crop_mode, 3)
        modification = (candidate.get("modification_summary") or {}).get("boundary_change_abs_sec", {}).get("mean")
        eligible.append(((float(after), mode_priority, crop_priority, float(modification or 0.0), ordinal), candidate, agreement))
    if not eligible:
        return {
            "selected": False, "decision": "keep_baseline",
            "reason": "no_candidate_passed_non_gt_safety_rules",
            "excluded_anchor_modes": sorted(excluded),
            "require_context_agreement": require_context_agreement,
            "context_agreement_tolerance_sec": context_agreement_tolerance_sec,
            "rejected_candidate_counts": dict(sorted(rejected_counts.items())),
        }
    _, selected, agreement = min(eligible, key=lambda item: item[0])
    return {
        "selected": True, "decision": "replace",
        "mode": selected.get("mode"), "anchor_mode": selected.get("anchor_mode"),
        "crop_mode": selected.get("crop_mode"), "padding_sec": selected.get("padding_sec"),
        "context_units": selected.get("context_units"),
        "candidate_ordinal": candidates.index(selected),
        "reason": "lowest_remaining_anomaly_then_smallest_supported_change",
        "excluded_anchor_modes": sorted(excluded),
        "require_context_agreement": require_context_agreement,
        "context_agreement_tolerance_sec": context_agreement_tolerance_sec,
        "context_agreement": agreement,
        "rejected_candidate_counts": dict(sorted(rejected_counts.items())),
    }


def selected_rollback_candidate(
    baseline_rows: Sequence[dict[str, Any]], replace_start: int, replace_end: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return stage_rollback_candidate(baseline_rows, "selected", replace_start, replace_end)


def anomaly_score(rows: Sequence[dict[str, Any]], indices: Iterable[int]) -> dict[str, Any]:
    indexed = by_index(rows)
    index_list = [index for index in indices if index in indexed]
    zero = sum(float(indexed[index]["end_sec"]) <= float(indexed[index]["start_sec"]) + 1e-9 for index in index_list)
    short = sum(float(indexed[index]["end_sec"]) - float(indexed[index]["start_sec"]) <= TIMESTAMP_STEP_SEC + 1e-9 for index in index_list)
    overlaps = 0
    for index in index_list:
        if index - 1 in indexed and float(indexed[index]["start_sec"]) < float(indexed[index - 1]["end_sec"]) - 1e-9:
            overlaps += 1
    score = 8 * zero + 2 * short + 5 * overlaps
    return {"score": score, "zero_duration_count": zero, "short_count": short, "overlap_count": overlaps}


def non_gt_acceptance(
    baseline_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
    target_indices: Iterable[int],
    *,
    anchor_reproduction_max_sec: float | None = None,
    tolerance_sec: float = 0.16,
) -> dict[str, Any]:
    target = list(target_indices)
    before = anomaly_score(baseline_rows, target)
    after = anomaly_score(candidate_rows, target)
    structural = structural_summary(candidate_rows)
    accepted = (
        structural["negative_duration_count"] == 0
        and structural["inter_unit_overlap_count"] == 0
        and after["score"] < before["score"]
        and (anchor_reproduction_max_sec is None or anchor_reproduction_max_sec <= tolerance_sec)
    )
    return {
        "accepted": accepted,
        "before_anomaly": before,
        "after_anomaly": after,
        "anchor_reproduction_max_sec": anchor_reproduction_max_sec,
        "anchor_tolerance_sec": tolerance_sec,
        "structural": structural,
    }


def local_anchor_reproduction(
    local_rows: Sequence[dict[str, Any]], left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    indexed = by_index(local_rows)
    errors: list[float] = []
    details: list[dict[str, Any]] = []
    for anchor in (left, right):
        index = int(anchor["global_character_index"])
        if index not in indexed:
            details.append({"index": index, "missing": True})
            continue
        row = indexed[index]
        onset = abs(float(row["start_sec"]) - float(anchor["selected_start_sec"]))
        offset = abs(float(row["end_sec"]) - float(anchor["selected_end_sec"]))
        errors.extend((onset, offset))
        details.append({"index": index, "onset_abs_sec": onset, "offset_abs_sec": offset})
    return {
        "complete": len(details) == 2 and all(not item.get("missing") for item in details),
        "max_error_sec": max(errors, default=None),
        "details": details,
    }


def compare_two_candidates(left: Sequence[dict[str, Any]], right: Sequence[dict[str, Any]], indices: Iterable[int]) -> dict[str, Any]:
    a = by_index(left)
    b = by_index(right)
    differences: list[float] = []
    missing: list[int] = []
    for index in indices:
        if index not in a or index not in b:
            missing.append(index)
            continue
        differences.extend((
            abs(float(a[index]["start_sec"]) - float(b[index]["start_sec"])),
            abs(float(a[index]["end_sec"]) - float(b[index]["end_sec"])),
        ))
    return {
        "missing_indices": missing,
        "boundary_difference_sec": numeric_summary(differences),
        "max_boundary_difference_sec": max(differences, default=None),
    }


def replay_commit_shift(
    baseline_rows: Sequence[dict[str, Any]], seam_index: int, shift_sec: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay a shifted previous committed end on following selected rows."""
    final = project_inference_rows(baseline_rows, "final")
    selected = by_index(project_inference_rows(baseline_rows, "selected"))
    output = by_index(final)
    if seam_index not in output:
        raise KeyError(seam_index)
    previous_end = float(output[seam_index]["end_sec"]) + shift_sec
    affected: list[int] = []
    for index in range(seam_index + 1, max(output) + 1):
        if index not in selected:
            break
        row = dict(selected[index])
        original_start = float(row["start_sec"])
        original_end = float(row["end_sec"])
        start = max(original_start, previous_end)
        end = max(original_end, start)
        changed_current = start > original_start + 1e-9 or end > original_end + 1e-9
        # Stop before replacing the first unit no longer affected by the injected floor.
        if not changed_current:
            break
        row.update({
            "start_sec": start,
            "end_sec": end,
            "injection_type": "commit_shift",
            "injected_previous_end_shift_sec": shift_sec,
            "injected_compression_sec": max(0.0, previous_end - original_start),
        })
        output[index] = row
        affected.append(index)
        previous_end = end
    return [output[index] for index in sorted(output)], {
        "seam_index": seam_index,
        "shift_sec": shift_sec,
        "affected_indices": affected,
    }


def status_is_complete(path: Path, request_hash: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("request_hash") == request_hash and payload.get("status") == "complete"


def collect_quick_results(out_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    case_statuses = read_jsonl(out_root / "run_status.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    for row in case_statuses:
        key = str(row.get("case_id") or row.get("phase") or canonical_hash(row))
        latest[key] = row
    counts = Counter(str(row.get("status", "unknown")) for row in latest.values())
    failures = [row for row in latest.values() if row.get("status") == "failed"]
    q2_cases = [
        path for path in sorted((out_root / "q2_natural_realign" / "cases").glob("*.json"))
        if not path.name.endswith((".status.json", ".failure.json"))
    ] if (out_root / "q2_natural_realign" / "cases").exists() else []
    q3_cases = [
        path for path in sorted((out_root / "q3_injection_matrix" / "cases").glob("*.json"))
        if not path.name.endswith((".status.json", ".failure.json"))
    ] if (out_root / "q3_injection_matrix" / "cases").exists() else []
    repair_rows: list[dict[str, Any]] = []
    for path in [*q2_cases, *q3_cases]:
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            failures.append({"status": "failed", "path": str(path), "error": "invalid_json"})
            continue
        for candidate in payload.get("repair_candidates", []):
            before = (candidate.get("metrics") or {}).get("before") or {}
            after = (candidate.get("metrics") or {}).get("after") or {}
            before_mae = before.get("boundary_mae_sec")
            after_mae = after.get("boundary_mae_sec")
            repair_rows.append({
                "case_id": payload.get("case_id"),
                "family": payload.get("family"),
                "mode": candidate.get("mode"),
                "anchor_mode": candidate.get("anchor_mode"),
                "padding_sec": candidate.get("padding_sec"),
                "crop_mode": candidate.get("crop_mode"),
                "context_units": candidate.get("context_units"),
                "accepted_non_gt": (candidate.get("acceptance") or {}).get("accepted"),
                "before_boundary_mae_sec": before_mae,
                "after_boundary_mae_sec": after_mae,
                "delta_boundary_mae_sec": (
                    float(after_mae) - float(before_mae) if before_mae is not None and after_mae is not None else None
                ),
                "structurally_valid": (candidate.get("splice") or {}).get("valid"),
            })
    q1_aggregate = None
    q1_path = out_root / "q1_anchor_scan" / "aggregate.json"
    if q1_path.is_file():
        q1_aggregate = read_json(q1_path)
    summary = {
        "schema_version": "demo_realign_quick_summary_v2_1",
        "created_at": utc_now(),
        "out_root": str(out_root.resolve()),
        "status_counts": dict(sorted(counts.items())),
        "latest_status_count": len(latest),
        "q1": q1_aggregate,
        "q2_case_count": len(q2_cases),
        "q3_case_count": len(q3_cases),
        "q2_selected_repair_case_count": sum(
            bool(read_json(path).get("final_non_gt_selection", {}).get("selected")) for path in q2_cases
        ),
        "q3_selected_repair_case_count": sum(
            bool((read_json(path).get("final_non_gt_selection") or {}).get("selected")) for path in q3_cases
        ),
        "q2_selected_ground_truth_anchor_count": sum(
            bool((read_json(path).get("final_non_gt_selection") or {}).get("selected"))
            and str((read_json(path).get("final_non_gt_selection") or {}).get("anchor_mode")) in {"gt_oracle", "gt_oracle_fallback"}
            for path in q2_cases
        ),
        "q2_selected_with_context_agreement_count": sum(
            bool(((read_json(path).get("final_non_gt_selection") or {}).get("context_agreement") or {}).get("supported"))
            for path in q2_cases
        ),
        "repair_candidate_count": len(repair_rows),
        "repair_delta_summary_sec": numeric_summary(
            row["delta_boundary_mae_sec"] for row in repair_rows if row["delta_boundary_mae_sec"] is not None
        ),
        "non_gt_accept_count": sum(bool(row["accepted_non_gt"]) for row in repair_rows),
        "structurally_invalid_candidate_count": sum(row["structurally_valid"] is False for row in repair_rows),
    }
    failure_summary = {
        "schema_version": "demo_realign_quick_failure_summary_v2_1",
        "created_at": utc_now(),
        "failure_count": len(failures),
        "failures": failures,
    }
    if repair_rows:
        write_csv(out_root / "repair_candidates.csv", repair_rows)
    atomic_json(out_root / "summary.json", summary)
    atomic_json(out_root / "failure_summary.json", failure_summary)
    return summary, failure_summary
