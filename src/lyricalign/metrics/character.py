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
    """Evaluate model output while keeping malformed and missing output visible.

    Reference identity errors remain hard failures. Prediction states are made
    disjoint per reference character:

    - valid: exactly one finite interval satisfying ``0 <= start < end``;
    - invalid: at least one prediction row exists, but the key is duplicated or
      its interval is malformed;
    - missing: no prediction row exists for the reference key.

    All-reference metrics penalize both invalid and missing output. The
    ``valid_only`` metric is computed only from valid predictions and uses the
    exact same valid set in its numerator and denominator.
    """
    import math

    validate_records(reference)
    ref = {(row["item_id"], row["character_index"]): row for row in reference}
    pred: dict[tuple[Any, Any], dict[str, Any]] = {}
    seen_reference_keys: set[tuple[Any, Any]] = set()
    invalid_keys: set[tuple[Any, Any]] = set()
    duplicate_keys: set[tuple[Any, Any]] = set()
    zero_duration_keys: set[tuple[Any, Any]] = set()
    negative_duration_keys: set[tuple[Any, Any]] = set()
    non_finite_interval_keys: set[tuple[Any, Any]] = set()
    extra_keys: list[tuple[Any, Any]] = []

    def numeric(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    for row in prediction:
        key = (row.get("item_id"), row.get("character_index"))
        if key not in ref:
            extra_keys.append(key)
            continue

        if key in seen_reference_keys:
            duplicate_keys.add(key)
            invalid_keys.add(key)
            pred.pop(key, None)
            continue
        seen_reference_keys.add(key)

        if row.get("normalized_character") != ref[key].get("normalized_character"):
            raise ValueError(f"character mismatch: {key}")

        start, end = row.get("start_sec"), row.get("end_sec")
        if numeric(start) and numeric(end):
            start_value, end_value = float(start), float(end)
            if not math.isfinite(start_value) or not math.isfinite(end_value):
                non_finite_interval_keys.add(key)
            elif start_value == end_value:
                zero_duration_keys.add(key)
            elif start_value > end_value:
                negative_duration_keys.add(key)
        if (
            not numeric(start)
            or not numeric(end)
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or not (0.0 <= float(start) < float(end))
        ):
            invalid_keys.add(key)
            continue
        pred[key] = row

    # Any duplicate makes the key unusable, even when one duplicate row looked valid.
    for key in invalid_keys:
        pred.pop(key, None)

    missing_keys = set(ref) - seen_reference_keys
    valid_keys = set(pred)
    if valid_keys & invalid_keys or valid_keys & missing_keys or invalid_keys & missing_keys:
        raise AssertionError("prediction state sets must be disjoint")
    if valid_keys | invalid_keys | missing_keys != set(ref):
        raise AssertionError("prediction states must partition the reference keys")

    per_song_penalized: dict[str, list[float]] = defaultdict(list)
    per_song_reference_keys: dict[str, set[tuple[Any, Any]]] = defaultdict(set)
    per_song_valid_keys: dict[str, set[tuple[Any, Any]]] = defaultdict(set)
    onset_errors: list[float] = []
    offset_errors: list[float] = []
    ious: list[float] = []
    valid_boundary_errors: list[float] = []
    joint_thresholds = {0.08: 0, 0.16: 0, 0.24: 0}

    for key, expected in ref.items():
        target = (float(expected["start_sec"]), float(expected["end_sec"]))
        actual = pred.get(key)
        song = str(expected.get("song_id") or expected["item_id"])
        per_song_reference_keys[song].add(key)

        if actual is None:
            # Fixed transparent penalty, never smaller than the reference span.
            penalty = max(1.0, target[1] - target[0])
            onset_error = offset_error = penalty
            iou = 0.0
        else:
            output = (float(actual["start_sec"]), float(actual["end_sec"]))
            onset_error = abs(target[0] - output[0])
            offset_error = abs(target[1] - output[1])
            iou = interval_iou(target, output)
            valid_boundary_errors.append((onset_error + offset_error) / 2)
            per_song_valid_keys[song].add(key)

        boundary = (onset_error + offset_error) / 2
        per_song_penalized[song].append(boundary)
        onset_errors.append(onset_error)
        offset_errors.append(offset_error)
        ious.append(iou)
        for threshold in joint_thresholds:
            joint_thresholds[threshold] += int(
                onset_error <= threshold and offset_error <= threshold
            )

    count = len(ref)
    valid_count = len(valid_keys)
    invalid_count = len(invalid_keys)
    missing_count = len(missing_keys)
    unusable_count = invalid_count + missing_count
    song_count = len(per_song_reference_keys)
    songs_with_any_valid = sum(bool(per_song_valid_keys[song]) for song in per_song_reference_keys)
    songs_fully_valid = sum(
        per_song_valid_keys[song] == per_song_reference_keys[song]
        for song in per_song_reference_keys
    )

    character_coverage = valid_count / count if count else 0.0
    return {
        "metric_schema_version": "character_interval_metrics_v3_tolerant",
        "prediction_state_semantics": {
            "valid": "exactly one finite prediction interval with 0 <= start_sec < end_sec",
            "invalid": "a reference key was predicted but duplicated or had a malformed interval",
            "missing": "no prediction row was emitted for the reference key",
        },
        "character_count": count,
        "prediction_row_count": len(prediction),
        "valid_prediction_count": valid_count,
        "invalid_prediction_count": invalid_count,
        "missing_prediction_count": missing_count,
        "unusable_prediction_count": unusable_count,
        "duplicate_prediction_key_count": len(duplicate_keys),
        "song_count": song_count,
        "song_macro_boundary_mae_sec": (
            sum(sum(values) / len(values) for values in per_song_penalized.values()) / song_count
            if song_count else 0.0
        ),
        "all_item_penalized_boundary_mae_sec": (
            sum((a + b) / 2 for a, b in zip(onset_errors, offset_errors)) / count
            if count else 0.0
        ),
        "valid_only_boundary_mae_sec": (
            sum(valid_boundary_errors) / valid_count if valid_count else 0.0
        ),
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
        "zero_duration_rate": len(zero_duration_keys) / count if count else 0.0,
        "negative_duration_rate": len(negative_duration_keys) / count if count else 0.0,
        "non_finite_interval_rate": len(non_finite_interval_keys) / count if count else 0.0,
        "invalid_prediction_rate": invalid_count / count if count else 0.0,
        "missing_prediction_rate": missing_count / count if count else 0.0,
        "unusable_prediction_rate": unusable_count / count if count else 0.0,
        "extra_prediction_count": len(extra_keys),
        "character_coverage": character_coverage,
        # Backward-compatible alias. New code should use character_coverage.
        "item_coverage": character_coverage,
        "song_coverage": songs_with_any_valid / song_count if song_count else 0.0,
        "complete_song_coverage": songs_fully_valid / song_count if song_count else 0.0,
    }
