"""Deterministic, read-only M4Singer schema and mismatch audit helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any

from lyricalign.datasets.m4singer import (
    SPECIAL_PHONEMES,
    audio_metadata,
    character_phoneme_mapping,
    mapped_character_intervals,
    normalize_lyrics,
    phoneme_intervals,
)

TAXONOMY = ("accepted_rule_based", "slur_or_repeated_vowel", "multiple_note_groups_per_character", "lyrics_syllable_count_mismatch", "mandarin_syllable_parse_failure", "zero_initial_or_special_syllable_case", "duration_metadata_mismatch", "invalid_or_non_monotonic_duration", "latin_or_digit", "missing_required_metadata", "unclassified_mapping_failure")


def classify_item(raw: dict[str, Any], root: str) -> dict[str, Any]:
    """Return one complete audit record; malformed input is an explicit failure."""
    item_id = str(raw.get("item_name", ""))
    required = ("item_name", "txt", "phs", "ph_dur", "notes", "notes_dur")
    missing = [field for field in required if field not in raw]
    if missing or item_id.count("#") != 2:
        return {"item_id": item_id, "status": "failed", "error_code": "schema_required_field_missing", "taxonomy": "missing_required_metadata", "missing_fields": missing, "contains_special_non_lyric_token": False, "special_token_types": []}
    singer_id, song_id, segment_id = item_id.split("#", 2)
    normalized = normalize_lyrics(str(raw["txt"]))
    phonemes = [str(value) for value in raw["phs"]]
    mapping, mapping_status, special = character_phoneme_mapping(normalized.text, phonemes)
    audio = audio_metadata(__import__("pathlib").Path(root) / f"{singer_id}#{song_id}" / f"{segment_id}.wav")
    durations = phoneme_intervals(list(raw["ph_dur"]), len(phonemes))
    special_types = sorted({phonemes[index] for index in special})
    # First preserve the v2 A-tier gate exactly.  The remaining priority is
    # applied only to review records and identifies the first genuine mapping
    # blocker; pauses/breaths are auxiliary attributes, never a catch-all.
    category = "accepted_rule_based"
    character_intervals = mapped_character_intervals(mapping, list(raw["ph_dur"]))
    if durations is not None and audio["audio_status"] == "ok" and mapping_status == "review_required_auto_phoneme_grouping" and character_intervals and all(interval is not None for interval in character_intervals) and character_intervals[-1][1] <= float(audio["duration_sec"]) + 0.10:
        category = "accepted_rule_based"
    elif any(char.isascii() and (char.isalpha() or char.isdigit()) for char in normalized.text):
        category = "latin_or_digit"
    elif any(bool(value) for value in raw.get("is_slur", [])):
        category = "slur_or_repeated_vowel"
    elif durations is None or any(end < start for start, end in durations or []):
        category = "invalid_or_non_monotonic_duration"
    elif audio["audio_status"] != "ok" or (durations and abs(durations[-1][1] - float(audio["duration_sec"])) > 0.10):
        category = "duration_metadata_mismatch"
    elif mapping_status != "review_required_auto_phoneme_grouping":
        category = "lyrics_syllable_count_mismatch" if normalized.text else "mandarin_syllable_parse_failure"
    return {
        "item_id": item_id, "song_id": song_id, "singer_id": singer_id, "status": "processed",
        "error_code": None, "taxonomy": category, "mapping_status": mapping_status,
        "normalized_character_count": len(normalized.text), "phoneme_count": len(phonemes),
        "syllable_group_count": len([entry for entry in mapping if entry]), "special_phoneme_count": len(special), "contains_special_non_lyric_token": bool(special), "special_token_types": special_types,
        "normalization_flags": normalized.flags, "audio": audio,
        "duration_sum_sec": durations[-1][1] if durations else None,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(record["status"] for record in records)
    taxonomy = Counter(record["taxonomy"] for record in records)
    mismatch_total = sum(count for name, count in taxonomy.items() if name != "accepted_rule_based")
    return {
        "total": len(records), "processed": statuses["processed"], "failed": statuses["failed"],
        "accepted_rule_based": taxonomy["accepted_rule_based"], "mismatch_total": mismatch_total,
        "taxonomy_counts": {name: taxonomy[name] for name in TAXONOMY},
        "unknown_ratio": taxonomy["unclassified_mapping_failure"] / mismatch_total if mismatch_total else 0.0,
    }
