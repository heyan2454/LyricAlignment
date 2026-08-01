"""Shared evaluation helpers for research-v6 experiment families.

The helpers keep local-vs-full metric scopes explicit, derive detector context
from cached serial traces, and compute experiment-specific diagnostics without
calling the acoustic model.
"""
from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Iterable, Sequence

from .metrics import alignment_metrics, metric_delta, partition_gt_by_seams, select_gt_rows, strip_metric_details


def row_index(row: dict[str, Any]) -> int:
    return int(row.get("global_character_index", row.get("character_index")))


def ordered(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=row_index)


def metric_scope_indices(
    *,
    rows: Iterable[dict[str, Any]] | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
    explicit: Iterable[int] | None = None,
) -> list[int]:
    if explicit is not None:
        return sorted({int(value) for value in explicit})
    if start_index is not None and end_index is not None:
        return list(range(int(start_index), int(end_index)))
    return sorted({row_index(row) for row in (rows or [])})


def candidate_record(
    name: str,
    rows: list[dict[str, Any]],
    gt: list[dict[str, Any]],
    *,
    structural: dict[str, Any],
    metric_indices: Iterable[int] | None = None,
    metric_scope: str = "full_item",
    spliced_rows: list[dict[str, Any]] | None = None,
    baseline_rows: list[dict[str, Any]] | None = None,
    seams_sec: Sequence[float] = (),
    seam_radius_sec: float = 1.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_gt = gt
    indices = None if metric_indices is None else sorted({int(value) for value in metric_indices})
    if gt and indices is not None:
        selected_gt = select_gt_rows(gt, indices=indices)
    metrics = strip_metric_details(alignment_metrics(rows, selected_gt)) if selected_gt else None
    result: dict[str, Any] = {
        "name": name,
        "structural": structural,
        "metric_scope": {
            "kind": metric_scope,
            "reference_unit_count": len(selected_gt),
            "character_start": min(indices) if indices else None,
            "character_end_exclusive": max(indices) + 1 if indices else None,
        },
        "metrics": metrics,
    }
    if spliced_rows is not None and gt:
        full_metrics = strip_metric_details(alignment_metrics(spliced_rows, gt))
        result["spliced_full_metrics"] = full_metrics
        if baseline_rows is not None:
            baseline_full = strip_metric_details(alignment_metrics(baseline_rows, gt))
            result["baseline_full_metrics"] = baseline_full
            result["spliced_delta_vs_baseline"] = metric_delta(full_metrics, baseline_full)
    if seams_sec and gt:
        near_gt, far_gt = partition_gt_by_seams(gt, seams_sec, radius_sec=seam_radius_sec)
        result["seam_stratified_metrics"] = {
            "radius_sec": seam_radius_sec,
            "near": strip_metric_details(alignment_metrics(rows, near_gt)) if near_gt else None,
            "far": strip_metric_details(alignment_metrics(rows, far_gt)) if far_gt else None,
        }
    if extra:
        result.update(extra)
    return result


def _canonical_candidate_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in rows:
        if source.get("global_character_index") is None:
            continue
        row = dict(source)
        start = row.get("start_sec", row.get("fixed_global_start_sec", row.get("official_fixed_global_start_sec")))
        end = row.get("end_sec", row.get("fixed_global_end_sec", row.get("official_fixed_global_end_sec")))
        if start is None or end is None:
            continue
        row["start_sec"] = float(start)
        row["end_sec"] = float(end)
        result.append(row)
    return ordered(result)


def detector_context_from_trace(trace: Sequence[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]], dict[int, float]]:
    """Extract text-dose, cross-window, and serial-cursor evidence from traces."""
    input_candidates: list[list[dict[str, Any]]] = []
    window_candidates: list[list[dict[str, Any]]] = []
    cursor: dict[int, float] = {}
    for trace_row in trace:
        shadow = _canonical_candidate_rows(trace_row.get("shadow_rows") or [])
        if shadow:
            window_candidates.append(shadow)
        attempt_rows: list[list[dict[str, Any]]] = []
        for attempt in trace_row.get("attempts") or []:
            probe = _canonical_candidate_rows(attempt.get("probe_rows") or [])
            if probe:
                attempt_rows.append(probe)
        input_candidates.extend(attempt_rows)
        predicted = trace_row.get("next_window_input_character_start")
        uncommitted = trace_row.get("next_uncommitted_character_start")
        if predicted is not None and uncommitted is not None:
            boundary_index = int(uncommitted)
            cursor[boundary_index] = abs(float(predicted) - float(uncommitted))
    return input_candidates, window_candidates, cursor


def fixed_scope_for_request(request: Any, gt: Sequence[dict[str, Any]]) -> list[int]:
    """Return the fixed ownership target used across input-budget variants."""
    if not gt:
        return list(range(int(request.text_start), int(request.text_end)))
    own_start = request.ownership_start_sec
    own_end = request.ownership_end_sec
    if own_start is None or own_end is None:
        return list(range(int(request.text_start), int(request.text_end)))
    indices = []
    for row in gt:
        midpoint = 0.5 * (float(row["start_sec"]) + float(row["end_sec"]))
        index = row_index(row)
        if own_start - 1e-9 <= midpoint < own_end + 1e-9:
            indices.append(index)
    return indices or list(range(int(request.text_start), int(request.text_end)))


def add_repairability_and_safe_labels(
    features: Sequence[dict[str, Any]],
    gt: Sequence[dict[str, Any]],
    baseline_rows: Sequence[dict[str, Any]],
    decoder_candidates: dict[str, Sequence[dict[str, Any]]],
    *,
    tolerance_sec: float,
) -> list[dict[str, Any]]:
    """Label same-logits repairability and GT-safe inter-unit boundaries."""
    reference = {row_index(row): row for row in gt}
    baseline = {row_index(row): row for row in baseline_rows}
    candidates = {name: {row_index(row): row for row in rows} for name, rows in decoder_candidates.items()}

    def unit_error(row: dict[str, Any] | None, ref: dict[str, Any] | None) -> float | None:
        if row is None or ref is None:
            return None
        return max(
            abs(float(row["start_sec"]) - float(ref["start_sec"])),
            abs(float(row["end_sec"]) - float(ref["end_sec"])),
        )

    result = []
    for source in features:
        row = dict(source)
        index = row_index(row)
        base_error = unit_error(baseline.get(index), reference.get(index))
        alternative_errors = {
            name: unit_error(mapping.get(index), reference.get(index))
            for name, mapping in candidates.items()
        }
        row["gt_repairable"] = None if base_error is None else bool(
            base_error > tolerance_sec
            and any(error is not None and error <= tolerance_sec for error in alternative_errors.values())
        )
        row["gt_repairable_by_decoder"] = {
            name: (None if error is None or base_error is None else bool(base_error > tolerance_sec and error <= tolerance_sec))
            for name, error in alternative_errors.items()
        }
        current = baseline.get(index); current_gt = reference.get(index)
        following = baseline.get(index + 1); following_gt = reference.get(index + 1)
        if current is None or current_gt is None:
            row["gt_safe_boundary"] = None
        else:
            left_ok = abs(float(current["end_sec"]) - float(current_gt["end_sec"])) <= tolerance_sec
            right_ok = True if following_gt is None else (
                following is not None
                and abs(float(following["start_sec"]) - float(following_gt["start_sec"])) <= tolerance_sec
            )
            row["gt_safe_boundary"] = bool(left_ok and right_ok)
        result.append(row)
    return result


def paired_decoder_transition_metrics(
    raw_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
    gt: Sequence[dict[str, Any]],
    *,
    tolerance_sec: float = 0.16,
) -> dict[str, Any]:
    """Paired unit transitions from raw to a decoder candidate."""
    raw = {row_index(row): row for row in raw_rows}
    candidate = {row_index(row): row for row in candidate_rows}
    reference = {row_index(row): row for row in gt}
    raw_correct = raw_error = preserved_correct = repaired = harmed = still_error = 0
    movements: list[float] = []
    for index, ref in reference.items():
        r = raw.get(index); c = candidate.get(index)
        if r is None or c is None:
            continue
        raw_error_sec = max(abs(float(r["start_sec"]) - float(ref["start_sec"])), abs(float(r["end_sec"]) - float(ref["end_sec"])))
        candidate_error_sec = max(abs(float(c["start_sec"]) - float(ref["start_sec"])), abs(float(c["end_sec"]) - float(ref["end_sec"])))
        raw_ok = raw_error_sec <= tolerance_sec
        candidate_ok = candidate_error_sec <= tolerance_sec
        movements.append(max(abs(float(c["start_sec"]) - float(r["start_sec"])), abs(float(c["end_sec"]) - float(r["end_sec"]))))
        if raw_ok:
            raw_correct += 1
            if candidate_ok: preserved_correct += 1
            else: harmed += 1
        else:
            raw_error += 1
            if candidate_ok: repaired += 1
            else: still_error += 1
    return {
        "tolerance_sec": tolerance_sec,
        "paired_unit_count": raw_correct + raw_error,
        "raw_correct_unit_count": raw_correct,
        "raw_error_unit_count": raw_error,
        "raw_correct_preserved_count": preserved_correct,
        "raw_correct_harmed_count": harmed,
        "raw_error_repaired_count": repaired,
        "raw_error_still_error_count": still_error,
        "raw_correct_harm_rate": harmed / raw_correct if raw_correct else None,
        "raw_error_repair_rate": repaired / raw_error if raw_error else None,
        "movement_mean_sec": statistics.fmean(movements) if movements else None,
        "movement_max_sec": max(movements, default=None),
    }


def detector_selection_components(report: dict[str, Any]) -> dict[str, Any]:
    """Return transparent, non-learned components for candidate ranking.

    The previous implementation collapsed heterogeneous terms with arbitrary
    weights.  Research-v6 now ranks lexicographically: fewer detected risk
    spans first, then lower maximum and mean active risk.  The full components
    are persisted so the decision remains auditable.
    """
    features = list(report.get("features") or [])
    if not features:
        return {
            "risk_span_count": math.inf,
            "maximum_risk_score": math.inf,
            "mean_risk_score": math.inf,
            "feature_count": 0,
        }
    scores = [float(row.get("risk_score", 0.0)) for row in features]
    return {
        "risk_span_count": int(len(report.get("risk_spans") or [])),
        "maximum_risk_score": max(scores, default=math.inf),
        "mean_risk_score": statistics.fmean(scores),
        "feature_count": len(scores),
    }


def detector_selection_key(report_or_components: dict[str, Any]) -> tuple[float, float, float]:
    components = (
        report_or_components
        if "risk_span_count" in report_or_components
        else detector_selection_components(report_or_components)
    )
    return (
        float(components.get("risk_span_count", math.inf)),
        float(components.get("maximum_risk_score", math.inf)),
        float(components.get("mean_risk_score", math.inf)),
    )


def detector_selection_score(report: dict[str, Any]) -> float:
    """Compatibility scalar; selection code should use detector_selection_key."""
    components = detector_selection_components(report)
    if not math.isfinite(float(components["risk_span_count"])):
        return math.inf
    # Stable monotone serialization only; not used as a weighted scientific
    # objective.  Keeping this field avoids breaking old result readers.
    return (
        float(components["risk_span_count"]) * 1_000_000.0
        + float(components["maximum_risk_score"]) * 1_000.0
        + float(components["mean_risk_score"])
    )


def choose_budget_candidates(candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {}
    ordered_candidates = sorted(candidates, key=lambda row: int(row["amount"]))
    shortest = ordered_candidates[0]
    longest = ordered_candidates[-1]
    controller_candidates = [row for row in ordered_candidates if row.get("coverage_relation") != "core_target_truncated"] or ordered_candidates
    detector = min(
        controller_candidates,
        key=lambda row: (
            detector_selection_key(
                row.get("detector_selection_components")
                or {
                    "risk_span_count": math.inf,
                    "maximum_risk_score": math.inf,
                    "mean_risk_score": float(row.get("detector_selection_score", math.inf)),
                }
            ),
            int(row["amount"]),
        ),
    )
    def candidate_metrics(row: dict[str, Any]) -> dict[str, Any]:
        candidate = row.get("candidate")
        if not isinstance(candidate, dict):
            return {}
        metrics = candidate.get("metrics")
        return metrics if isinstance(metrics, dict) else {}

    # Demo items without GT deliberately have ``metrics: null``.  They remain
    # useful for structural and no-GT selection, but cannot enter the oracle
    # comparison used only for labelled data.
    oracle_rows = [
        row for row in ordered_candidates
        if candidate_metrics(row).get("all_penalized_boundary_mae_sec") is not None
    ]
    oracle = min(
        oracle_rows,
        key=lambda row: (
            float(candidate_metrics(row)["all_penalized_boundary_mae_sec"]),
            -float(candidate_metrics(row).get("coverage") or 0.0),
            int(row["amount"]),
        ),
    ) if oracle_rows else None
    sequential = controller_candidates[-1]
    for row in controller_candidates:
        report = row.get("detector_report") or {}
        if not report.get("risk_spans"):
            sequential = row
            break
    def brief(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "amount": row["amount"],
            "candidate_name": row["candidate"]["name"],
            "detector_selection_score": row.get("detector_selection_score"),
            "metrics": row["candidate"].get("metrics"),
        }
    return {
        "oracle_best": brief(oracle),
        "fixed_shortest": brief(shortest),
        "fixed_longest": brief(longest),
        "detector_selected": brief(detector),
        "sequential_expansion": brief(sequential),
    }


def first_failure_and_recovery(details: Sequence[dict[str, Any]], tolerance_sec: float, recovery_units: int = 3) -> dict[str, Any]:
    failures = [position for position, row in enumerate(details) if float(row["max_abs_error_sec"]) > tolerance_sec]
    if not failures:
        return {"first_failure_character_index": None, "recovery_character_distance": 0, "persistent_failure": False}
    first = failures[0]
    recovery = None
    for position in range(first + 1, len(details)):
        tail = details[position: position + recovery_units]
        if len(tail) == recovery_units and all(float(row["max_abs_error_sec"]) <= tolerance_sec for row in tail):
            recovery = position - first
            break
    return {
        "first_failure_character_index": int(details[first]["character_index"]),
        "recovery_character_distance": recovery,
        "persistent_failure": recovery is None,
    }


def seam_metrics(prediction_rows: Sequence[dict[str, Any]], gt: Sequence[dict[str, Any]], seams_sec: Sequence[float], tolerance_sec: float) -> dict[str, Any]:
    if not gt or not seams_sec:
        return {"applicable": False, "seam_count": len(seams_sec)}
    near, far = partition_gt_by_seams(gt, seams_sec, radius_sec=1.0)
    return {
        "applicable": True,
        "seam_count": len(seams_sec),
        "near": strip_metric_details(alignment_metrics(prediction_rows, near)) if near else None,
        "far": strip_metric_details(alignment_metrics(prediction_rows, far)) if far else None,
        "tolerance_sec": tolerance_sec,
    }


def serial_diagnostics(
    prediction_rows: Sequence[dict[str, Any]],
    trace: Sequence[dict[str, Any]],
    gt: Sequence[dict[str, Any]],
    *,
    tolerance_sec: float,
    seams_sec: Sequence[float] = (),
) -> dict[str, Any]:
    full = alignment_metrics(prediction_rows, gt) if gt else None
    gt_by_time = ordered(gt)
    def cursor_at(time_sec: float) -> int:
        for row in gt_by_time:
            if float(row["start_sec"]) >= time_sec - 1e-9:
                return row_index(row)
        return len(gt_by_time)
    windows = []
    cursor_distances = []
    for row in trace:
        start = float(row.get("effective_input_start_sec", row.get("input_start_sec", 0.0)))
        observed = row.get("input_character_start_before")
        expected = cursor_at(start) if gt else None
        distance = None if observed is None or expected is None else int(observed) - int(expected)
        if distance is not None:
            cursor_distances.append(abs(distance))
        windows.append({
            "window_index": row.get("window_index"),
            "input_start_sec": start,
            "observed_input_cursor": observed,
            "gt_input_cursor": expected,
            "cursor_distance_units": distance,
            "planned_input_character_start": row.get("planned_input_character_start"),
            "planned_input_cursor_applied": row.get("planned_input_cursor_applied", False),
            "silent_core_skipped": bool(row.get("silent_core_skipped")),
        })
    details = [] if full is None else full.get("details", [])
    return {
        "gt_available": bool(gt),
        "window_count": len(trace),
        "window_cursor_diagnostics": windows,
        "cursor_distance_mean_abs_units": statistics.fmean(cursor_distances) if cursor_distances else None,
        "cursor_distance_max_abs_units": max(cursor_distances, default=None),
        "missing_unit_count": None if full is None else full["missing_unit_count"],
        "prediction_extra_unit_count": max(0, len({row_index(row) for row in prediction_rows}) - len({row_index(row) for row in gt})) if gt else None,
        "first_failure_recovery": first_failure_and_recovery(details, tolerance_sec) if details else None,
        "seam_metrics": seam_metrics(prediction_rows, gt, seams_sec, tolerance_sec),
    }


def silence_boundary_diagnostics(
    prediction_rows: Sequence[dict[str, Any]],
    gt: Sequence[dict[str, Any]],
    silences: Sequence[dict[str, Any]],
    *,
    context_units: int = 4,
) -> dict[str, Any]:
    if not silences:
        return {"applicable": False, "reason": "no_detected_silence", "silence_count": 0}
    if not gt:
        return {"applicable": True, "gt_available": False, "silence_count": len(silences), "boundaries": []}
    gt_ordered = ordered(gt)
    pred = {row_index(row): row for row in prediction_rows}
    boundaries = []
    for silence in silences:
        start = float(silence["start_sec"]); end = float(silence["end_sec"])
        before = [row for row in gt_ordered if float(row["end_sec"]) <= start + 1e-9][-context_units:]
        after = [row for row in gt_ordered if float(row["start_sec"]) >= end - 1e-9][:context_units]
        def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
            errors = []
            missing = 0
            for ref in rows:
                candidate = pred.get(row_index(ref))
                if candidate is None:
                    missing += 1; continue
                errors.extend([
                    abs(float(candidate["start_sec"]) - float(ref["start_sec"])),
                    abs(float(candidate["end_sec"]) - float(ref["end_sec"])),
                ])
            return {"unit_count": len(rows), "missing": missing, "boundary_mae_sec": statistics.fmean(errors) if errors else None}
        boundaries.append({
            "start_sec": start, "end_sec": end, "duration_sec": end - start,
            "before": summarize(before), "after": summarize(after),
        })
    return {"applicable": True, "gt_available": True, "silence_count": len(silences), "boundaries": boundaries}


def causal_effect(
    baseline_rows: Sequence[dict[str, Any]],
    changed_rows: Sequence[dict[str, Any]],
    gt: Sequence[dict[str, Any]],
    *,
    intervention_time_sec: float,
) -> dict[str, Any]:
    if not gt:
        return {"gt_available": False}
    post_gt = [row for row in gt if float(row["start_sec"]) >= intervention_time_sec - 1e-9]
    baseline = strip_metric_details(alignment_metrics(baseline_rows, post_gt))
    changed = strip_metric_details(alignment_metrics(changed_rows, post_gt))
    return {
        "gt_available": True,
        "intervention_time_sec": intervention_time_sec,
        "post_intervention_reference_units": len(post_gt),
        "baseline_post_metrics": baseline,
        "changed_post_metrics": changed,
        "delta_vs_baseline": metric_delta(changed, baseline),
    }


def independent_line_localization(document: Any, audio_profile: dict[str, Any], duration_sec: float) -> list[dict[str, Any]]:
    """Independent energy-mass/proportional line-localization baseline.

    It consumes no character alignment.  Sustained vocal activity defines the
    usable time span; lyric line character counts allocate cumulative duration.
    """
    lines = list(document.lines)
    if not lines:
        return []
    first = audio_profile.get("first_sustained_activity_sec")
    start = 0.0 if first is None else max(0.0, float(first))
    end = float(duration_sec)
    total_units = sum(max(1, int(line.character_end) - int(line.character_start)) for line in lines)
    cursor = start
    result = []
    for position, line in enumerate(lines):
        units = max(1, int(line.character_end) - int(line.character_start))
        line_end = end if position == len(lines) - 1 else cursor + (end - start) * units / total_units
        result.append({
            "line_index": line.line_index,
            "character_start": line.character_start,
            "character_end": line.character_end,
            "coarse_start_sec": cursor,
            "coarse_end_sec": line_end,
            "source": "independent_vocal_span_proportional_line_localizer_v1",
        })
        cursor = line_end
    return result


def line_localization_metrics(line_spans: Sequence[dict[str, Any]], document: Any, gt: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not gt:
        return {"gt_available": False, "line_count": len(line_spans)}
    gt_by = {row_index(row): row for row in gt}
    errors = []
    details = []
    for span, line in zip(line_spans, document.lines, strict=False):
        refs = [gt_by[index] for index in range(line.character_start, line.character_end) if index in gt_by]
        if not refs:
            continue
        gt_start = min(float(row["start_sec"]) for row in refs)
        gt_end = max(float(row["end_sec"]) for row in refs)
        onset = abs(float(span["coarse_start_sec"]) - gt_start)
        offset = abs(float(span["coarse_end_sec"]) - gt_end)
        errors.extend([onset, offset])
        details.append({"line_index": line.line_index, "onset_error_sec": onset, "offset_error_sec": offset})
    return {"gt_available": True, "line_count": len(details), "boundary_mae_sec": statistics.fmean(errors) if errors else None, "details": details}
