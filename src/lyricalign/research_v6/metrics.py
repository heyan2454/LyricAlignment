"""Consistent metrics for full-data research-v6 reports."""
from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Iterable, Sequence


def _index(row: dict[str, Any]) -> int:
    return int(row.get("global_character_index", row.get("character_index")))


def alignment_metrics(
    prediction_rows: Iterable[dict[str, Any]],
    gt_rows: Iterable[dict[str, Any]],
    *,
    invalid_penalty_sec: float = 1.0,
    tolerances_sec: Sequence[float] = (0.08, 0.16, 0.24),
) -> dict[str, Any]:
    pred = {_index(row): row for row in prediction_rows}
    gt = {_index(row): row for row in gt_rows}
    errors: list[float] = []
    valid_errors: list[float] = []
    joint_hits = {float(value): 0 for value in tolerances_sec}
    missing = invalid = zero = negative = overlap = 0
    previous_end: float | None = None
    details: list[dict[str, Any]] = []
    for index in sorted(gt):
        reference = gt[index]
        candidate = pred.get(index)
        if candidate is None:
            missing += 1
            errors.extend([invalid_penalty_sec, invalid_penalty_sec])
            continue
        start = float(candidate["start_sec"])
        end = float(candidate["end_sec"])
        if not math.isfinite(start) or not math.isfinite(end):
            invalid += 1
            errors.extend([invalid_penalty_sec, invalid_penalty_sec])
            continue
        duration = end - start
        if duration < -1e-9:
            negative += 1
        if duration <= 1e-9:
            zero += 1
        if previous_end is not None and start < previous_end - 1e-9:
            overlap += 1
        previous_end = end
        onset = abs(start - float(reference["start_sec"]))
        offset = abs(end - float(reference["end_sec"]))
        errors.extend([onset, offset])
        if duration >= -1e-9:
            valid_errors.extend([onset, offset])
        for tolerance in tolerances_sec:
            if onset <= tolerance and offset <= tolerance:
                joint_hits[float(tolerance)] += 1
        details.append({
            "character_index": index,
            "onset_abs_error_sec": onset,
            "offset_abs_error_sec": offset,
            "max_abs_error_sec": max(onset, offset),
            "valid": duration >= -1e-9,
        })
    total = len(gt)
    return {
        "reference_unit_count": total,
        "prediction_unit_count": len(pred),
        "missing_unit_count": missing,
        "invalid_unit_count": invalid,
        "coverage": (total - missing - invalid) / total if total else None,
        "all_penalized_boundary_mae_sec": statistics.fmean(errors) if errors else None,
        "valid_boundary_mae_sec": statistics.fmean(valid_errors) if valid_errors else None,
        "negative_duration_count": negative,
        "zero_duration_count": zero,
        "inter_unit_overlap_count": overlap,
        "joint_rates": {
            f"joint_within_{int(round(tolerance * 1000))}ms": joint_hits[float(tolerance)] / total if total else None
            for tolerance in tolerances_sec
        },
        "details": details,
    }


def aggregate_item_metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Report item macro and reference-weighted micro without mixing schemas."""
    usable = [row for row in items if row.get("metrics")]
    if not usable:
        return {"item_count": 0}
    macro_keys = ("all_penalized_boundary_mae_sec", "valid_boundary_mae_sec", "coverage")
    macro = {}
    for key in macro_keys:
        values = [
            float(row["metrics"][key])
            for row in usable
            if row["metrics"].get(key) is not None
        ]
        macro[key] = statistics.fmean(values) if values else None
    micro = {}
    for key in macro_keys:
        weighted = [
            (int(row["metrics"].get("reference_unit_count", 0)), float(row["metrics"][key]))
            for row in usable
            if row["metrics"].get(key) is not None
        ]
        total_weight = sum(weight for weight, _ in weighted)
        numerator = sum(
            weight * value for weight, value in weighted
        )
        micro[key] = numerator / total_weight if total_weight else None
    return {"item_count": len(usable), "macro": macro, "reference_weighted_micro": micro}


def grouped_aggregate(items: Sequence[dict[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in items:
        grouped[tuple(row.get(key) for key in keys)].append(row)
    return {
        "group_by": list(keys),
        "groups": [
            {
                "group": {key: value for key, value in zip(keys, group_key, strict=True)},
                "summary": aggregate_item_metrics(values),
            }
            for group_key, values in sorted(grouped.items(), key=lambda value: tuple(str(v) for v in value[0]))
        ],
    }


def select_gt_rows(
    gt_rows: Iterable[dict[str, Any]],
    *,
    indices: Iterable[int] | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
) -> list[dict[str, Any]]:
    """Select a reproducible GT evaluation scope by global unit index."""
    wanted = None if indices is None else {int(value) for value in indices}
    result = []
    for row in gt_rows:
        index = _index(row)
        if wanted is not None and index not in wanted:
            continue
        if start_index is not None and index < int(start_index):
            continue
        if end_index is not None and index >= int(end_index):
            continue
        result.append(dict(row))
    return sorted(result, key=_index)


def strip_metric_details(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    return {key: value for key, value in metrics.items() if key != "details"}


def metric_delta(candidate: dict[str, Any] | None, baseline: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None or baseline is None:
        return None
    keys = (
        "all_penalized_boundary_mae_sec",
        "valid_boundary_mae_sec",
        "coverage",
        "missing_unit_count",
        "negative_duration_count",
        "zero_duration_count",
        "inter_unit_overlap_count",
    )
    result: dict[str, Any] = {}
    for key in keys:
        left = candidate.get(key)
        right = baseline.get(key)
        result[key] = None if left is None or right is None else float(left) - float(right)
    return result


def partition_gt_by_seams(
    gt_rows: Iterable[dict[str, Any]],
    seams_sec: Sequence[float],
    *,
    radius_sec: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seams = [float(value) for value in seams_sec]
    near: list[dict[str, Any]] = []
    far: list[dict[str, Any]] = []
    for source in gt_rows:
        row = dict(source)
        midpoint = 0.5 * (float(row["start_sec"]) + float(row["end_sec"]))
        (near if any(abs(midpoint - seam) <= radius_sec for seam in seams) else far).append(row)
    return near, far


def clustered_bootstrap_macro(
    items: Sequence[dict[str, Any]],
    *,
    cluster_key: str = "source_song_id",
    metric_key: str = "all_penalized_boundary_mae_sec",
    samples: int = 1000,
    seed: int = 20260731,
) -> dict[str, Any]:
    """Cluster bootstrap an item-macro metric without treating variants as songs."""
    usable = [
        row for row in items
        if row.get("metrics") and row["metrics"].get(metric_key) is not None
    ]
    if not usable:
        return {"cluster_count": 0, "item_count": 0, "metric_key": metric_key}
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in usable:
        cluster = str(row.get(cluster_key) or row.get("item_id"))
        grouped[cluster].append(float(row["metrics"][metric_key]))
    clusters = sorted(grouped)
    cluster_values = [statistics.fmean(grouped[key]) for key in clusters]
    point = statistics.fmean(cluster_values)
    if len(cluster_values) == 1 or samples <= 0:
        return {
            "cluster_count": len(cluster_values), "item_count": len(usable),
            "metric_key": metric_key, "estimate": point,
            "ci95": [point, point], "bootstrap_samples": 0,
        }
    import random
    rng = random.Random(seed)
    estimates = []
    for _ in range(int(samples)):
        draw = [cluster_values[rng.randrange(len(cluster_values))] for _ in cluster_values]
        estimates.append(statistics.fmean(draw))
    estimates.sort()
    low = estimates[max(0, int(0.025 * len(estimates)) - 1)]
    high = estimates[min(len(estimates) - 1, int(0.975 * len(estimates)))]
    return {
        "cluster_count": len(cluster_values), "item_count": len(usable),
        "metric_key": metric_key, "estimate": point,
        "ci95": [low, high], "bootstrap_samples": len(estimates),
        "cluster_key": cluster_key, "seed": seed,
    }
