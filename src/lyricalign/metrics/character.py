"""Strict character-interval validation and deterministic aggregate metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

METRIC_SCHEMA_VERSION = "character_interval_metrics_v1"


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
