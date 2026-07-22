"""Deterministic, read-only M4Singer schema and mismatch audit helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any

from lyricalign.datasets.m4singer import (
    SPECIAL_PHONEMES,
    PINYIN_INITIALS,
    audio_metadata,
    character_phoneme_mapping,
    mapped_character_intervals,
    normalize_lyrics,
    phoneme_intervals,
    group_phonemes,
)

TAXONOMY = ("accepted_rule_based", "slur_or_repeated_vowel", "multiple_note_groups_per_character", "lyrics_syllable_count_mismatch", "mandarin_syllable_parse_failure", "zero_initial_or_special_syllable_case", "duration_metadata_mismatch", "invalid_or_non_monotonic_duration", "latin_or_digit", "missing_required_metadata", "unclassified_mapping_failure")

CLASSIFICATION_VERSION = "m4singer_b_tier_primary_reason_v2"


def _b_tier_reason(raw: dict[str, Any], normalized_text: str, phonemes: list[str], mapping_status: str, durations: list[tuple[float, float]] | None, audio: dict[str, Any]) -> tuple[str, list[str], dict[str, int]]:
    """Return deterministic B-tier reason, auxiliary tags, and inspectable counts."""
    groups, _ = group_phonemes(phonemes)
    slur_count = sum(bool(value) for value in raw.get("is_slur", []))
    group_delta = len(groups) - len(normalized_text)
    zero_initial_groups = sum(bool(group) and phonemes[group[0]].lower() not in PINYIN_INITIALS for group in groups)
    notes = list(raw.get("notes", []))
    multi_note_groups = sum(len({notes[index] for index in group if index < len(notes) and notes[index] != 0}) > 1 for group in groups)
    details = {"slur_marker_count": slur_count, "syllable_group_delta": group_delta, "zero_initial_group_count": zero_initial_groups, "multiple_note_group_count": multi_note_groups}
    tags = []
    if slur_count: tags.append("has_slur_marker")
    if group_delta: tags.append("syllable_group_count_mismatch")
    if zero_initial_groups: tags.append("zero_initial_group")
    if multi_note_groups: tags.append("multiple_note_values_within_group")
    # Priority records the most direct structural blocker.  Combining slur and
    # cardinality is explicit instead of allowing the slur marker to hide it.
    if any(char.isascii() and (char.isalpha() or char.isdigit()) for char in normalized_text):
        return "latin_or_digit", tags, details
    if durations is None:
        return "invalid_or_non_monotonic_duration", tags, details
    if audio["audio_status"] != "ok" or (durations and abs(durations[-1][1] - float(audio["duration_sec"])) > 0.10):
        return "duration_metadata_mismatch", tags, details
    if slur_count and group_delta > 0:
        return ("single_slur_with_excess_syllable_group" if slur_count == 1 and group_delta == 1 else "multiple_slur_with_excess_syllable_groups"), tags, details
    if slur_count and group_delta < 0:
        return ("single_slur_with_one_missing_syllable_group" if slur_count == 1 and group_delta == -1 else "multiple_or_complex_slur_with_missing_syllable_groups"), tags, details
    if slur_count > 1:
        return "multiple_slur_or_repeated_vowel_markers", tags, details
    if slur_count == 1:
        return "single_slur_or_repeated_vowel_marker", tags, details
    if zero_initial_groups:
        return "zero_initial_or_special_syllable_case", tags, details
    if multi_note_groups:
        return "multiple_note_groups_per_character", tags, details
    if mapping_status != "review_required_auto_phoneme_grouping" and group_delta > 0:
        return "excess_syllable_groups_for_lyrics", tags, details
    if mapping_status != "review_required_auto_phoneme_grouping" and group_delta < 0:
        return "missing_syllable_groups_for_lyrics", tags, details
    return "unclassified_mapping_failure", tags, details


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
    primary_reason = "accepted_rule_based"
    secondary_tags: list[str] = []
    reason_details: dict[str, int] = {}
    character_intervals = mapped_character_intervals(mapping, list(raw["ph_dur"]))
    if durations is not None and audio["audio_status"] == "ok" and mapping_status == "review_required_auto_phoneme_grouping" and character_intervals and all(interval is not None for interval in character_intervals) and character_intervals[-1][1] <= float(audio["duration_sec"]) + 0.10:
        category = "accepted_rule_based"
    else:
        primary_reason, secondary_tags, reason_details = _b_tier_reason(raw, normalized.text, phonemes, mapping_status, durations, audio)
        if "slur" in primary_reason:
            category = "slur_or_repeated_vowel"
        elif primary_reason in {"excess_syllable_groups_for_lyrics", "missing_syllable_groups_for_lyrics"}:
            category = "lyrics_syllable_count_mismatch"
        else:
            category = primary_reason
    return {
        "item_id": item_id, "song_id": song_id, "singer_id": singer_id, "status": "processed",
        "error_code": None, "taxonomy": category, "primary_reason": primary_reason, "secondary_tags": secondary_tags, "reason_details": reason_details, "classification_version": CLASSIFICATION_VERSION, "mapping_status": mapping_status,
        "normalized_character_count": len(normalized.text), "phoneme_count": len(phonemes),
        "syllable_group_count": len([entry for entry in mapping if entry]), "special_phoneme_count": len(special), "contains_special_non_lyric_token": bool(special), "special_token_types": special_types,
        "normalization_flags": normalized.flags, "audio": audio,
        "duration_sum_sec": durations[-1][1] if durations else None,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(record["status"] for record in records)
    taxonomy = Counter(record["taxonomy"] for record in records)
    primary_reasons = Counter(record.get("primary_reason", record["taxonomy"]) for record in records)
    mismatch_total = sum(count for name, count in taxonomy.items() if name != "accepted_rule_based")
    return {
        "total": len(records), "processed": statuses["processed"], "failed": statuses["failed"],
        "accepted_rule_based": taxonomy["accepted_rule_based"], "mismatch_total": mismatch_total,
        "taxonomy_counts": {name: taxonomy[name] for name in TAXONOMY},
        "primary_reason_counts": dict(sorted(primary_reasons.items())), "classification_version": CLASSIFICATION_VERSION,
        "unknown_ratio": taxonomy["unclassified_mapping_failure"] / mismatch_total if mismatch_total else 0.0,
    }
