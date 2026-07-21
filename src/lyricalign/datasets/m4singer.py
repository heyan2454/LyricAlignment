"""Read-only M4Singer manifest and character-to-phoneme preparation helpers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SPECIAL_PHONEMES = {"<AP>", "<SP>", "<SIL>"}
PINYIN_INITIALS = {
    "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x",
    "zh", "ch", "sh", "r", "z", "c", "s", "y", "w",
}
NORMALIZATION_VERSION = "m4singer_text_v1"
MAPPING_VERSION = "m4singer_phoneme_grouping_v1"


@dataclass(frozen=True)
class NormalizedLyrics:
    text: str
    raw_to_normalized: list[int | None]
    normalized_to_raw: list[int]
    flags: list[str]


def normalize_lyrics(text: str) -> NormalizedLyrics:
    """Apply reversible ``text_normalization_v1`` to display-only characters.

    NFKC is applied one raw codepoint at a time so the returned index maps remain
    meaningful.  Whitespace and punctuation are deliberately omitted from the
    alignment target, but never silently: each removal is recorded in ``flags``.
    Semantic transformations (Chinese conversion, number expansion and English
    pronunciation) are intentionally outside this version.
    """

    normalized: list[str] = []
    raw_to_normalized: list[int | None] = []
    normalized_to_raw: list[int] = []
    flags: list[str] = []
    for raw_index, raw_char in enumerate(text):
        converted = unicodedata.normalize("NFKC", raw_char)
        if converted != raw_char:
            flags.append("unicode_nfkc")
        if not converted:
            raw_to_normalized.append(None)
            continue
        emitted_index: int | None = None
        for char in converted:
            if char.isspace():
                flags.append("removed_whitespace")
                continue
            if unicodedata.category(char).startswith("P"):
                flags.append("removed_punctuation")
                continue
            if emitted_index is None:
                emitted_index = len(normalized)
            normalized.append(char)
            normalized_to_raw.append(raw_index)
        raw_to_normalized.append(emitted_index)
    return NormalizedLyrics(
        "".join(normalized), raw_to_normalized, normalized_to_raw, sorted(set(flags))
    )


def group_phonemes(phonemes: list[str]) -> tuple[list[list[int]], list[int]]:
    """Group M4Singer phonemes into conservative pinyin-like syllable candidates.

    The dataset stores initials/finals as separate tokens. A group begins at an
    initial token; special pause/breath tokens are excluded and returned for audit.
    This is an auditable candidate mapping, not character-level ground truth.
    """

    groups: list[list[int]] = []
    special_indices: list[int] = []
    for index, token in enumerate(phonemes):
        if token in SPECIAL_PHONEMES:
            special_indices.append(index)
            continue
        if token.lower() in PINYIN_INITIALS and groups:
            groups.append([index])
        elif groups:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups, special_indices


def character_phoneme_mapping(
    normalized_lyrics: str, phonemes: list[str]
) -> tuple[list[list[int] | None], str, list[int]]:
    """Return explicit source indices only when sequence cardinality is exact."""

    groups, special_indices = group_phonemes(phonemes)
    if not normalized_lyrics:
        return [], "rejected_empty_normalized_lyrics", special_indices
    if len(groups) != len(normalized_lyrics):
        return [None] * len(normalized_lyrics), "review_required_group_count_mismatch", special_indices
    return groups, "review_required_auto_phoneme_grouping", special_indices


def phoneme_intervals(phoneme_durations: list[object], expected_count: int) -> list[tuple[float, float]] | None:
    """Convert finite, non-negative phoneme durations into cumulative intervals."""

    if len(phoneme_durations) != expected_count:
        return None
    try:
        values = [float(value) for value in phoneme_durations]
    except (TypeError, ValueError):
        return None
    if any(value < 0 or value != value or value == float("inf") for value in values):
        return None
    cursor = 0.0
    intervals = []
    for value in values:
        intervals.append((cursor, cursor + value))
        cursor += value
    return intervals


def mapped_character_intervals(
    mapping: list[list[int] | None], phoneme_durations: list[object]
) -> list[tuple[float, float] | None]:
    """Derive traceable character intervals only for fully mapped duration data."""

    intervals = phoneme_intervals(phoneme_durations, len(phoneme_durations))
    if intervals is None:
        return [None] * len(mapping)
    result: list[tuple[float, float] | None] = []
    for source_indices in mapping:
        if not source_indices or min(source_indices) < 0 or max(source_indices) >= len(intervals):
            result.append(None)
            continue
        result.append((intervals[source_indices[0]][0], intervals[source_indices[-1]][1]))
    return result


def audio_metadata(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
            return {
                "audio_status": "ok",
                "duration_sec": frame_count / frame_rate if frame_rate else None,
                "sample_rate_hz": frame_rate,
                "channels": audio.getnchannels(),
                "sample_count": frame_count,
                "sample_width_bytes": audio.getsampwidth(),
            }
    except (FileNotFoundError, wave.Error, EOFError) as exc:
        return {"audio_status": "decode_failure", "audio_error": f"{type(exc).__name__}: {exc}"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_item(raw: dict[str, Any], audio_root: Path, *, include_audio_hash: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Prepare one manifest item and its traceable, timestamp-free character records."""

    item_name = str(raw["item_name"])
    singer_id, song_id, segment_id = item_name.split("#", maxsplit=2)
    audio_relpath = f"{singer_id}#{song_id}/{segment_id}.wav"
    audio_path = audio_root / audio_relpath
    lyrics_raw = str(raw.get("txt", ""))
    normalized = normalize_lyrics(lyrics_raw)
    phonemes = [str(value) for value in raw.get("phs", [])]
    mapping, mapping_status, special_indices = character_phoneme_mapping(normalized.text, phonemes)
    metadata = audio_metadata(audio_path)
    character_intervals = mapped_character_intervals(mapping, list(raw.get("ph_dur", [])))
    duration_metadata_ok = (
        all(interval is not None for interval in character_intervals)
        and metadata.get("duration_sec") is not None
        and abs(character_intervals[-1][1] - float(metadata["duration_sec"])) <= 0.10
        if character_intervals
        else False
    )
    if metadata["audio_status"] != "ok":
        status = "rejected"
        status_reason = "decode_failure"
    elif mapping_status.startswith("rejected"):
        status = "rejected"
        status_reason = "empty_lyrics"
    elif mapping_status == "review_required_auto_phoneme_grouping" and duration_metadata_ok:
        status = "accepted"
        status_reason = "accepted_rule_based"
    else:
        status = "review_required"
        status_reason = mapping_status
    source_payload = {
        "item_name": item_name,
        "lyrics_raw": lyrics_raw,
        "phonemes": phonemes,
        "is_slur": raw.get("is_slur", []),
        "ph_dur": raw.get("ph_dur", []),
        "notes": raw.get("notes", []),
        "notes_dur": raw.get("notes_dur", []),
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": "m4singer",
        "item_id": item_name,
        "song_id": song_id,
        "singer_id": singer_id,
        "audio_relpath": audio_relpath,
        "lyrics_raw": lyrics_raw,
        "lyrics_normalized": normalized.text,
        "raw_to_normalized": normalized.raw_to_normalized,
        "normalized_to_raw": normalized.normalized_to_raw,
        "normalization_flags": normalized.flags,
        "language": "zh",
        "duration_sec": metadata.get("duration_sec"),
        "audio": metadata,
        "split": "unassigned",
        "annotation_level": "character",
        "annotation_source": "m4singer_meta_json_phoneme_grouping",
        "mapping_status": "accepted_rule_based" if status == "accepted" else mapping_status,
        "mapping_version": MAPPING_VERSION,
        "length_source": "native_short",
        "source_item_ids": [item_name],
        "join_points_sec": [],
        "content_hash": hashlib.sha256(
            json.dumps(source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "status": status,
        "status_reason": status_reason,
        "normalization_version": NORMALIZATION_VERSION,
    }
    if include_audio_hash and metadata["audio_status"] == "ok":
        manifest["audio_sha256"] = sha256_file(audio_path)
    annotations = [
        {
            "schema_version": 1,
            "dataset_id": "m4singer",
            "item_id": item_name,
            "song_id": song_id,
            "character_index": index,
            "raw_character": lyrics_raw[normalized.normalized_to_raw[index]],
            "normalized_character": char,
            "start_sec": character_intervals[index][0] if status == "accepted" else None,
            "end_sec": character_intervals[index][1] if status == "accepted" else None,
            "source_phoneme_indices": source_indices,
            "source_syllable_or_note_indices": None,
            "mapping_status": "accepted_rule_based" if status == "accepted" else mapping_status,
            "mapping_method": "phoneme_duration_cumulative_v1" if status == "accepted" else "none",
            "mapping_confidence": "high" if status == "accepted" else "review",
            "quality_flags": [] if status == "accepted" else [status_reason],
            "mapping_notes": {
                "special_phoneme_indices": special_indices,
                "source_phoneme_tokens": [phonemes[i] for i in source_indices] if source_indices else [],
                "time_boundary_status": "not_available_from_meta_json",
            },
        }
        for index, (char, source_indices) in enumerate(zip(normalized.text, mapping, strict=True))
    ]
    return manifest, annotations
