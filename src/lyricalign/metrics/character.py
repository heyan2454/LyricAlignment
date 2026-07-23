"""Strict character-interval validation and deterministic aggregate metrics."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

METRIC_SCHEMA_VERSION = "character_interval_metrics_v1"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999))
    return ordered[index]


def validate_records(rows: list[dict[str, Any]]) -> None:
    seen = set()
    per_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row.get("item_id"), row.get("character_index"))
        if key in seen:
            raise ValueError(f"duplicate character key: {key}")
        seen.add(key)
        start, end = row.get("start_sec"), row.get("end_sec")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not (0 <= start < end):
            raise ValueError(f"invalid interval: {key}")
        per_item[str(row["item_id"])].append(row)
    for item_id, item_rows in per_item.items():
        previous_start = -1.0
        previous_end = -1.0
        for row in sorted(item_rows, key=lambda value: int(value["character_index"])):
            if float(row["start_sec"]) < previous_start or float(row["end_sec"]) < previous_end:
                raise ValueError(f"reverse order: {item_id}")
            previous_start, previous_end = float(row["start_sec"]), float(row["end_sec"])


def interval_iou(left: tuple[float, float], right: tuple[float, float]) -> float:
    intersection = max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union else 0.0


def evaluate(reference: list[dict[str, Any]], prediction: list[dict[str, Any]]) -> dict[str, Any]:
    validate_records(reference)
    validate_records(prediction)
    ref = {(row["item_id"], row["character_index"]): row for row in reference}
    pred = {(row["item_id"], row["character_index"]): row for row in prediction}
    if set(ref) != set(pred):
        raise ValueError(f"prediction/reference key mismatch: missing={len(set(ref)-set(pred))}, extra={len(set(pred)-set(ref))}")
    details, absolute_boundary_errors = [], []
    for key in sorted(ref, key=lambda value: (str(value[0]), int(value[1]))):
        expected, actual = ref[key], pred[key]
        if expected.get("normalized_character") != actual.get("normalized_character"):
            raise ValueError(f"character mismatch: {key}")
        target = (float(expected["start_sec"]), float(expected["end_sec"]))
        output = (float(actual["start_sec"]), float(actual["end_sec"]))
        errors = (abs(target[0] - output[0]), abs(target[1] - output[1]))
        absolute_boundary_errors.extend(errors)
        details.append({"item_id": key[0], "character_index": key[1], "iou": interval_iou(target, output), "boundary_mae": sum(errors) / 2})
    per_item = defaultdict(list)
    for detail in details:
        per_item[detail["item_id"]].append(detail)
    overlap_count = 0
    for values in per_item.values():
        ordered = sorted(values, key=lambda value: int(value["character_index"]))
        for left, right in zip(ordered, ordered[1:]):
            left_ref, right_ref = ref[(left["item_id"], left["character_index"])], ref[(right["item_id"], right["character_index"])]
            if float(right_ref["start_sec"]) < float(left_ref["end_sec"]):
                overlap_count += 1
    return {
        "metric_schema_version": METRIC_SCHEMA_VERSION, "character_count": len(details),
        "mean_iou": sum(row["iou"] for row in details) / len(details) if details else 0.0,
        "boundary_mae_sec": sum(absolute_boundary_errors) / len(absolute_boundary_errors) if absolute_boundary_errors else 0.0,
        "per_song_macro_iou": sum(sum(row["iou"] for row in values) / len(values) for values in per_item.values()) / len(per_item) if per_item else 0.0,
        "reference_adjacent_overlap_count": overlap_count,
        "details": details,
    }


def evaluate_tolerant(reference: list[dict[str, Any]], prediction: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate model output without hiding malformed or missing predictions.

    Reference identity errors remain hard failures.  Model-output errors become
    penalized observations and are also reported separately, allowing a training
    run to finish with an honest invalid-prediction rate.
    """
    validate_records(reference)
    ref = {(row["item_id"], row["character_index"]): row for row in reference}
    pred: dict[tuple[Any, Any], dict[str, Any]] = {}
    invalid_keys: set[tuple[Any, Any]] = set()
    extra_keys: list[tuple[Any, Any]] = []
    for row in prediction:
        key = (row.get("item_id"), row.get("character_index"))
        if key not in ref:
            extra_keys.append(key)
            continue
        if key in pred:
            invalid_keys.add(key)
            continue
        if row.get("normalized_character") != ref[key].get("normalized_character"):
            raise ValueError(f"character mismatch: {key}")
        start, end = row.get("start_sec"), row.get("end_sec")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start >= end:
            invalid_keys.add(key)
            continue
        pred[key] = row
    per_song: dict[str, list[float]] = defaultdict(list)
    onset_errors: list[float] = []
    offset_errors: list[float] = []
    ious: list[float] = []
    joint_thresholds = {0.08: 0, 0.16: 0, 0.24: 0}
    zero_duration = sum(
        int(isinstance(row.get("start_sec"), (int, float)) and row.get("start_sec") == row.get("end_sec"))
        for row in prediction if (row.get("item_id"), row.get("character_index")) in ref
    )
    negative_duration = sum(
        int(isinstance(row.get("start_sec"), (int, float)) and isinstance(row.get("end_sec"), (int, float)) and row["start_sec"] > row["end_sec"])
        for row in prediction if (row.get("item_id"), row.get("character_index")) in ref
    )
    for key, expected in ref.items():
        target = (float(expected["start_sec"]), float(expected["end_sec"]))
        actual = pred.get(key)
        if actual is None or key in invalid_keys:
            # One second is a transparent fixed penalty, at least as large as
            # the item-local reference span. This makes missing output visible.
            penalty = max(1.0, target[1] - target[0])
            onset_error = offset_error = penalty
            iou = 0.0
        else:
            output = (float(actual["start_sec"]), float(actual["end_sec"]))
            onset_error, offset_error = abs(target[0] - output[0]), abs(target[1] - output[1])
            iou = interval_iou(target, output) if output[1] > output[0] else 0.0
        boundary = (onset_error + offset_error) / 2
        song = str(expected.get("song_id") or expected["item_id"])
        per_song[song].append(boundary)
        onset_errors.append(onset_error); offset_errors.append(offset_error); ious.append(iou)
        for threshold in joint_thresholds:
            joint_thresholds[threshold] += int(onset_error <= threshold and offset_error <= threshold)
    count = len(ref)
    return {
        "metric_schema_version": "character_interval_metrics_v2_tolerant",
        "character_count": count,
        "song_count": len(per_song),
        "song_macro_boundary_mae_sec": sum(sum(values) / len(values) for values in per_song.values()) / len(per_song) if per_song else 0.0,
        "all_item_penalized_boundary_mae_sec": sum((a + b) / 2 for a, b in zip(onset_errors, offset_errors)) / count if count else 0.0,
        "valid_only_boundary_mae_sec": sum((a + b) / 2 for a, b in zip(onset_errors, offset_errors) if a < 1.0 or b < 1.0) / max(1, count - len(invalid_keys)),
        "onset_mae_sec": sum(onset_errors) / count if count else 0.0,
        "onset_median_sec": median(onset_errors) if onset_errors else 0.0,
        "onset_p90_sec": percentile(onset_errors, 0.9),
        "offset_mae_sec": sum(offset_errors) / count if count else 0.0,
        "offset_median_sec": median(offset_errors) if offset_errors else 0.0,
        "offset_p90_sec": percentile(offset_errors, 0.9),
        "mean_iou": sum(ious) / count if count else 0.0,
        "joint_within_80ms": joint_thresholds[0.08] / count if count else 0.0,
        "joint_within_160ms": joint_thresholds[0.16] / count if count else 0.0,
        "joint_within_240ms": joint_thresholds[0.24] / count if count else 0.0,
        "zero_duration_rate": zero_duration / count if count else 0.0,
        "negative_duration_rate": negative_duration / count if count else 0.0,
        "invalid_prediction_rate": len(invalid_keys) / count if count else 0.0,
        "missing_prediction_rate": sum(1 for key in ref if key not in pred) / count if count else 0.0,
        "extra_prediction_count": len(extra_keys),
        "item_coverage": sum(1 for key in ref if key in pred and key not in invalid_keys) / count if count else 0.0,
        "song_coverage": sum(1 for song, values in per_song.items() if values) / len(per_song) if per_song else 0.0,
    }
