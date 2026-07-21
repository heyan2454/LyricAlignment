"""Validation and export helpers for the public MIR-1K-partial-align labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lyricalign.audio.contract import inventory_record
from lyricalign.datasets.m4singer import audio_metadata, normalize_lyrics


def prepare_partial_align_item(raw: dict[str, Any], audio_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Prepare one manually aligned MIR-1K song as a strict OOD test-only record."""

    song_id = str(raw["song_id"])
    lyric = str(raw["lyric"])
    on_offset = raw.get("on_offset")
    if not isinstance(on_offset, list):
        raise ValueError(f"{song_id}: missing character-level on_offset annotation")
    normalized = normalize_lyrics(lyric)
    if normalized.text != lyric:
        raise ValueError(f"{song_id}: aligned lyrics must not change under normalization")
    if len(on_offset) != len(lyric):
        raise ValueError(f"{song_id}: {len(on_offset)} intervals for {len(lyric)} characters")
    audio_relpath = f"UndividedWavfile/{song_id}"
    audio_path = audio_root / audio_relpath
    audio = audio_metadata(audio_path)
    if audio["audio_status"] != "ok":
        raise ValueError(f"{song_id}: source audio is not decodable: {audio.get('audio_error')}")
    duration = float(audio["duration_sec"])
    annotations: list[dict[str, Any]] = []
    previous_start = -1.0
    previous_end = -1.0
    for index, (char, interval) in enumerate(zip(lyric, on_offset, strict=True)):
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError(f"{song_id}: invalid interval at character {index}")
        start, end = float(interval[0]), float(interval[1])
        if start < 0 or start >= end or start < previous_start or end < previous_end or end > duration + 0.05:
            raise ValueError(f"{song_id}: invalid/non-monotonic interval at character {index}: {interval}")
        annotations.append(
            {
                "schema_version": 1,
                "dataset_id": "mir1k_partial_align",
                "item_id": song_id.removesuffix(".wav"),
                "song_id": song_id,
                "character_index": index,
                "raw_character": char,
                "normalized_character": char,
                "start_sec": start,
                "end_sec": end,
                "source_phoneme_indices": None,
                "source_syllable_or_note_indices": None,
                "mapping_status": "ground_truth_character",
                "mapping_notes": {"annotation_source": "MIR1k_partial_align.json"},
            }
        )
        previous_start, previous_end = start, end
    content_hash = hashlib.sha256(
        json.dumps({"song_id": song_id, "lyric": lyric, "on_offset": on_offset}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "dataset_id": "mir1k_partial_align",
        "item_id": song_id.removesuffix(".wav"),
        "song_id": song_id,
        "singer_id": song_id.split("_", 1)[0],
        "audio_relpath": audio_relpath,
        "lyrics_raw": lyric,
        "lyrics_normalized": lyric,
        "language": "zh",
        "duration_sec": duration,
        "audio": audio,
        "vocal_source_type": "official_vocal_channel",
        "audio_contract": inventory_record(audio_path, "official_vocal_channel", include_hash=True),
        "split": "test",
        "usage": "ood_test_only",
        "annotation_level": "character",
        "annotation_source": "MIR1k_partial_align_manual",
        "mapping_status": "ground_truth_character",
        "length_source": "natural_long",
        "source_item_ids": [song_id],
        "join_points_sec": [],
        "content_hash": content_hash,
        "status": "accepted",
    }
    return manifest, annotations
