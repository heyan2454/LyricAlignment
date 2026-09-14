"""Virtual concatenation of short items into long training samples.

Why: the product runs on whole songs, but every training item is a ~2-5 s phrase, so the model never
sees a long stream — and the two failure modes we measured are exactly long-stream failures
(16.28% zero-length characters on a real batch, caused by the upstream repair at window edges, and
the ≥2 s duration cliff where 12.4% of characters miss 0.2 s versus 1.7% for short ones).

Concatenation is done *virtually*: the collator reads the original files and joins them in memory, so
no audio is duplicated on disk (the corpus is 18.8 GB and the data disk has ~25 GB free).

Timestamp bins are shifted by the cumulative offset, so the merged label sequence stays monotone by
construction; the gap between parts is real silence, which is also what the product sees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .qwen_fa_runtime import QwenFABatchCollator, decode_audio

SAMPLE_RATE = 16000


def _part_order(row: dict[str, Any]) -> str:
    return str(row.get("audio_relpath", ""))


def group_concat_records(rows: list[dict[str, Any]], *, target_sec: float = 20.0,
                         max_sec: float = 28.0, gap_sec: float = 0.4,
                         step_sec: float = 0.08, min_parts: int = 2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge consecutive items of the same song until `target_sec` is reached.

    Returns the merged records (same schema plus `audio_parts`/`source_item_ids`) and a stats record
    for the run's audit trail.  Items are ordered by their file name inside a song, which is the
    original recording order, and a group is closed before it can exceed `max_sec`.
    """
    by_song: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("singer_id", "")), str(row.get("song_id", "")))
        by_song.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    dropped = 0
    for (singer, song), items in sorted(by_song.items()):
        items = sorted(items, key=_part_order)
        current: list[dict[str, Any]] = []
        elapsed = 0.0

        def flush() -> None:
            nonlocal current, elapsed, dropped
            if len(current) >= min_parts:
                merged = merge_group(current, singer=singer, song=song, gap_sec=gap_sec, step_sec=step_sec)
                if merged is not None:
                    out.append(merged)
                else:
                    dropped += 1
            elif current:
                out.extend(current)          # a tail too short to merge stays as-is
            current, elapsed = [], 0.0

        for item in items:
            duration = float(item.get("duration_sec") or 0.0)
            if not duration or not item.get("timestamp_class_ids") or not item.get("lyrics_normalized"):
                dropped += 1
                continue
            addition = duration if not current else duration + gap_sec
            if current and elapsed + addition > max_sec:
                flush()
            if not current:
                target_pad = max_sec
            current.append(item)
            elapsed += addition
            if elapsed >= target_sec:
                flush()
        flush()
    stats = {"schema_version": "concat_view_v1", "target_sec": target_sec, "max_sec": max_sec,
             "gap_sec": gap_sec, "min_parts": min_parts, "input_items": len(rows),
             "output_records": len(out), "merged_records": sum(1 for row in out if row.get("audio_parts")),
             "dropped_or_unmergeable": dropped,
             "total_audio_sec": round(sum(float(row.get("duration_sec") or 0.0) for row in out), 1)}
    return out, stats


def merge_group(parts: list[dict[str, Any]], *, singer: str, song: str, gap_sec: float,
                step_sec: float) -> dict[str, Any] | None:
    """One merged record, or None when the parts cannot be aligned safely."""
    class_ids: list[int] = []
    lyrics: list[str] = []
    part_shifts: list[int] = []
    offset_sec = 0.0
    for index, part in enumerate(parts):
        ids = [int(value) for value in part["timestamp_class_ids"]]
        if len(ids) % 2:
            return None
        shift = int(round(offset_sec / step_sec))
        # Record the exact bin offset so the collator can place this part at `shift * step_sec`:
        # rounding the offset to the grid otherwise leaves up to half a bin (40 ms) of label/audio
        # disagreement, which flips the model's prediction to the neighbouring bin for most
        # characters after the first phrase (measured: median max-error 0 ms -> 80 ms across a join).
        part_shifts.append(shift)
        offset_sec = shift * step_sec          # the audio will be built to match this, not the nominal gap
        shifted = [value + shift for value in ids]
        if shifted and max(shifted) >= 5000:
            return None
        if class_ids and shifted and shifted[0] < class_ids[-1]:
            return None                      # never emit a non-monotone label sequence
        class_ids.extend(shifted)
        lyrics.append(str(part["lyrics_normalized"]))
        duration = float(part.get("duration_sec") or 0.0)
        offset_sec += duration + (gap_sec if index < len(parts) - 1 else 0.0)
    first = parts[0]
    return {"schema_version": "qwen_fa_timestamp_labels_v1_concat",
            "item_id": f"{singer}#{song}#concat{len(parts)}-{first.get('item_id')}",
            "song_id": song, "singer_id": singer, "split": first.get("split"),
            "audio_parts": [str(part["audio_relpath"]) for part in parts],
            "audio_relpath": str(first["audio_relpath"]),
            "lyrics_normalized": "".join(lyrics),
            "character_count": len(class_ids) // 2, "timestamp_class_ids": class_ids,
            "timestamp_segment_sec": float(first.get("timestamp_segment_sec") or step_sec),
            "num_timestamp_labels": int(first.get("num_timestamp_labels") or 5000),
            "duration_sec": round(offset_sec, 3), "part_shift_bins": part_shifts,
            "validation_basis": first.get("validation_basis"),
            "mapping_status": "concatenated_from_accepted",
            "source_item_ids": [str(part.get("item_id")) for part in parts]}


class QwenFAConcatCollator(QwenFABatchCollator):
    """Collator that reads `audio_parts` and concatenates them in memory (gap = real silence)."""

    def __init__(self, processor: Any, *, audio_root: Path, language: str, timestamp_token_id: int,
                 gap_sec: float = 0.4, sample_rate: int = SAMPLE_RATE, step_sec: float = 0.08,
                 timestamp_target: str = "absolute", timestamp_num_classes: int = 5000) -> None:
        super().__init__(processor, audio_root=audio_root, language=language,
                         timestamp_token_id=timestamp_token_id, timestamp_target=timestamp_target,
                         timestamp_num_classes=timestamp_num_classes)
        self.gap_sec = float(gap_sec)
        self.sample_rate = int(sample_rate)
        self.step_sec = float(step_sec)

    def load_audio(self, row: dict[str, Any]) -> np.ndarray:
        parts = row.get("audio_parts")
        if not parts:
            return super().load_audio(row)
        chunks = [decode_audio(self.audio_root / str(part)) for part in parts]
        shifts = row.get("part_shift_bins")
        joined: list[np.ndarray] = []
        written = 0
        for index, chunk in enumerate(chunks):
            if index == 0:
                joined.append(chunk)
                written = len(chunk)
                continue
            target = int(round(shifts[index] * self.step_sec * self.sample_rate)) if shifts \
                else written + int(round(self.gap_sec * self.sample_rate))
            pad = target - written
            if pad < 0:                      # never cut audio; fall back to a bare adjacency
                pad = 0
            joined.append(np.zeros(pad, dtype=np.float32))
            joined.append(chunk)
            written = target + len(chunk)
        return np.concatenate(joined)
