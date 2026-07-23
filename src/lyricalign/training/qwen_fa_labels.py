"""Qwen Forced Aligner timestamp-label construction and round-trip checks.

This module intentionally keeps supervision in the official token-classification
form: labels exist only at the processor-inserted ``<timestamp>`` positions.
All other positions are ``IGNORE_INDEX``.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

IGNORE_INDEX = -100
LABEL_SCHEMA_VERSION = "qwen_fa_timestamp_labels_v1"


def quantize_time(time_sec: float, *, segment_sec: float, num_labels: int) -> int:
    """Quantize seconds using the verified official 80 ms-style convention."""
    if not isinstance(time_sec, (int, float)) or not math.isfinite(time_sec):
        raise ValueError(f"non-finite timestamp: {time_sec!r}")
    class_id = int(math.floor(float(time_sec) / segment_sec + 0.5))
    if not 0 <= class_id < num_labels:
        raise ValueError(
            f"timestamp class out of range: time={time_sec}, class={class_id}, labels={num_labels}"
        )
    return class_id


def labels_for_intervals(
    character_rows: list[dict[str, Any]], *, segment_sec: float, num_labels: int
) -> list[int]:
    """Return start/end class IDs ordered by character index, with hard checks."""
    rows = sorted(character_rows, key=lambda row: int(row["character_index"]))
    result: list[int] = []
    previous_start = -math.inf
    previous_end = -math.inf
    for expected_index, row in enumerate(rows):
        if int(row["character_index"]) != expected_index:
            raise ValueError(f"non-contiguous character indices for {row.get('item_id')}")
        start, end = float(row["start_sec"]), float(row["end_sec"])
        if not 0 <= start < end or start < previous_start or end < previous_end:
            raise ValueError(f"invalid/non-monotonic character interval for {row.get('item_id')}")
        result.extend((
            quantize_time(start, segment_sec=segment_sec, num_labels=num_labels),
            quantize_time(end, segment_sec=segment_sec, num_labels=num_labels),
        ))
        previous_start, previous_end = start, end
    return result


def build_label_record(
    manifest_row: dict[str, Any], character_rows: list[dict[str, Any]], *, segment_sec: float, num_labels: int
) -> dict[str, Any]:
    labels = labels_for_intervals(character_rows, segment_sec=segment_sec, num_labels=num_labels)
    text = str(manifest_row["lyrics_normalized"])
    if len(character_rows) != len(text) or len(labels) != 2 * len(text):
        raise ValueError(f"character count mismatch for {manifest_row['item_id']}")
    return {
        "schema_version": LABEL_SCHEMA_VERSION,
        "item_id": manifest_row["item_id"],
        "song_id": manifest_row["song_id"],
        "singer_id": manifest_row.get("singer_id"),
        "split": manifest_row["split"],
        "audio_relpath": manifest_row["audio_relpath"],
        "duration_sec": manifest_row["duration_sec"],
        "lyrics_normalized": text,
        "character_count": len(text),
        "timestamp_class_ids": labels,
        "timestamp_segment_sec": segment_sec,
        "num_timestamp_labels": num_labels,
        "mapping_status": manifest_row.get("mapping_status"),
        "validation_basis": manifest_row.get("validation_basis"),
    }


def build_supervision_labels(input_ids: Any, *, timestamp_token_id: int, class_ids: list[int]) -> Any:
    """Fill exactly the timestamp slots; preserve tensor backend/device of input IDs."""
    import torch

    positions = (input_ids == timestamp_token_id).nonzero(as_tuple=False).flatten()
    if len(positions) != len(class_ids):
        raise ValueError(
            f"timestamp position count mismatch: processor={len(positions)}, expected={len(class_ids)}"
        )
    labels = torch.full_like(input_ids, IGNORE_INDEX)
    labels[positions] = torch.tensor(class_ids, dtype=labels.dtype, device=labels.device)
    return labels


def collect_character_rows(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                grouped[str(row["item_id"])].append(row)
    return grouped


def label_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["split"]) for row in records)
    return {
        "schema_version": LABEL_SCHEMA_VERSION,
        "record_count": len(records),
        "split_counts": dict(sorted(counts.items())),
        "character_count": sum(int(row["character_count"]) for row in records),
        "timestamp_label_count": sum(len(row["timestamp_class_ids"]) for row in records),
    }
