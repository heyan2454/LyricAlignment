"""Read-only M4Singer manifest and character-to-phoneme preparation helpers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import wave
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any
from pypinyin import Style, pinyin


SPECIAL_PHONEMES = {"<AP>", "<SP>", "<SIL>"}
PINYIN_INITIALS = {
    "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x",
    "zh", "ch", "sh", "r", "z", "c", "s", "y", "w",
}
NORMALIZATION_VERSION = "m4singer_text_v1"
LEGACY_MAPPING_VERSION = "m4singer_phoneme_grouping_v3_exact_repeated_vowel_split"
MAPPING_VERSION = "m4singer_staged_pinyin_overlay_slur_time_v1"
PINYIN_PARSE_VERSION = "m4singer_unique_pinyin_phoneme_parse_v1"
OVERLAY_VERSION = "m4singer_annotation_overlay_v1"
SLUR_TIME_ALLOCATION_VERSION = "m4singer_slur_time_allocation_v1"


@dataclass(frozen=True)
class NormalizedLyrics:
    text: str
    raw_to_normalized: list[int | None]
    normalized_to_raw: list[int]
    flags: list[str]


def source_row_sha256(raw: dict[str, Any]) -> str:
    """Return the stable hash used to anchor non-destructive source overlays."""

    return hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def apply_token_overlays(raw: dict[str, Any], overlays: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply approved, hash-anchored token overlays without mutating ``raw``.

    This is deliberately narrow: an overlay must name the original row hash,
    item, target, index and expected token.  Any mismatch is a hard error.
    """

    if not overlays:
        return dict(raw), []
    corrected = dict(raw)
    applied: list[dict[str, Any]] = []
    for overlay in overlays:
        if overlay.get("reviewer_decision") != "approved":
            continue
        if overlay.get("operation") != "replace_token" or overlay.get("target") != "phs":
            raise ValueError(f"unsupported M4Singer overlay: {overlay}")
        if overlay.get("item_id") != raw.get("item_name"):
            continue
        if overlay.get("source_row_sha256") != source_row_sha256(raw):
            raise ValueError(f"source-row hash mismatch for overlay {overlay.get('item_id')}")
        try:
            index = int(overlay["token_index"])
            phonemes = list(corrected["phs"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid overlay for {overlay.get('item_id')}") from exc
        if not 0 <= index < len(phonemes) or phonemes[index] != overlay.get("expected_value"):
            raise ValueError(f"expected token mismatch for overlay {overlay.get('item_id')} at {index}")
        phonemes[index] = str(overlay.get("replacement_value"))
        corrected["phs"] = phonemes
        applied.append(dict(overlay))
    return corrected, applied


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
    """Group phonemes by initial or a changed vowel/final token.

    M4Singer uses repeated identical finals for held/slurred vowels.  A changed
    final without an intervening initial is therefore a new zero-initial syllable
    candidate, rather than being incorrectly absorbed into the previous character.
    Special pause/breath tokens end the current candidate and remain audit-only.
    """

    groups: list[list[int]] = []
    special_indices: list[int] = []
    previous_vowel: str | None = None
    initial_pending_vowel = False
    for index, token in enumerate(phonemes):
        if token in SPECIAL_PHONEMES:
            special_indices.append(index)
            previous_vowel = None
            initial_pending_vowel = False
            continue
        if token.lower() in PINYIN_INITIALS:
            groups.append([index])
            previous_vowel = None
            initial_pending_vowel = True
        elif initial_pending_vowel:
            groups[-1].append(index)
            previous_vowel = token.lower()
            initial_pending_vowel = False
        elif not groups or previous_vowel is None:
            groups.append([index])
            previous_vowel = token.lower()
        elif token.lower() == previous_vowel:
            groups[-1].append(index)
        else:
            groups.append([index])
            previous_vowel = token.lower()
    return groups, special_indices


def split_repeated_vowels_exactly(groups: list[list[int]], phonemes: list[str]) -> tuple[list[list[int]], int]:
    """Expose repeated equal vowels as zero-initial groups, preserving indices.

    This helper does not decide whether the split is warranted.  Its returned
    ``repeat_count`` is the number of extra same-vowel tokens that can become
    separate character candidates without changing token order.
    """
    result: list[list[int]] = []
    repeat_count = 0
    for group in groups:
        if not group:
            continue
        first = 1 if phonemes[group[0]].lower() in PINYIN_INITIALS else 0
        head = group[: first + 1]
        result.append(head)
        for index in group[first + 1 :]:
            result.append([index])
            repeat_count += 1
    return result, repeat_count


def unique_pinyin_phoneme_mapping(text: str, phonemes: list[str]) -> tuple[list[list[int] | None] | None, str]:
    """Return only a unique monotonic pinyin-to-phoneme character parse.

    Heteronyms are retained as alternatives. Repeated finals may be consumed by
    one character, but a second complete allocation makes the result ambiguous.
    """
    # Query each character independently. Phrase-level pypinyin disambiguation
    # can suppress a valid heteronym (for example ``了 -> le``), whereas the
    # phoneme sequence is the evidence that must select the pronunciation.
    readings = [pinyin(char, style=Style.NORMAL, heteronym=True, errors=lambda x: [x])[0] for char in text]
    def tokens_for_reading(reading: str) -> list[tuple[str, ...]]:
        value = reading.lower()
        # Orthographic y/w initials encode zero-initial Mandarin syllables in
        # M4Singer. Convert them before the ordinary initial/final split.
        zero_initial = {"yi": "i", "ya": "ia", "yao": "iao", "ye": "ie", "you": "iou", "yan": "ian", "yin": "in", "yang": "iang", "ying": "ing", "yong": "iong", "yu": "v", "yue": "ve", "yuan": "van", "yun": "vn", "wu": "u", "wo": "uo", "wai": "uai", "wei": "uei", "wan": "uan", "wen": "uen", "wang": "uang"}
        if value in zero_initial: return [(zero_initial[value],)]
        initial = next((candidate for candidate in sorted(PINYIN_INITIALS, key=len, reverse=True) if value.startswith(candidate)), "")
        final = value[len(initial):] if initial else value
        final = {"ui": "uei", "iu": "iou", "un": "vn" if initial in {"j", "q", "x"} else "uen", "ue": "ve", "uan": "van" if initial in {"j", "q", "x"} else "uan", "u": "v" if initial in {"j", "q", "x"} else "u"}.get(final, final)
        if not final or not final.isalpha(): return []
        normal = tuple(([initial] if initial else []) + [final])
        return [normal]
    candidates: list[list[tuple[str, ...]]] = []
    for index, char in enumerate(text):
        choices = set()
        for reading in readings[index]:
            choices.update(tokens_for_reading(reading))
        if not choices:
            return None, "review_required_pinyin_parse_failure"
        candidates.append(sorted(choices))
    solutions: list[list[list[int]]] = []
    def walk(char_index: int, phoneme_index: int, mapped: list[list[int]]) -> None:
        if len(solutions) >= 2: return
        while phoneme_index < len(phonemes) and phonemes[phoneme_index] in SPECIAL_PHONEMES: phoneme_index += 1
        if char_index == len(candidates):
            if all(token in SPECIAL_PHONEMES for token in phonemes[phoneme_index:]): solutions.append(mapped)
            return
        for expected in candidates[char_index]:
            cursor = phoneme_index; indices: list[int] = []
            if len(expected) == 2:
                if cursor >= len(phonemes) or phonemes[cursor].lower() != expected[0]: continue
                indices.append(cursor); cursor += 1
            if cursor >= len(phonemes) or phonemes[cursor].lower() != expected[-1]: continue
            indices.append(cursor); cursor += 1
            # Identical repeated finals are a possible hold. Explore every
            # positive length; multiple complete paths remain deliberately ambiguous.
            while True:
                walk(char_index + 1, cursor, mapped + [indices.copy()])
                if cursor >= len(phonemes) or phonemes[cursor].lower() != expected[-1]: break
                indices.append(cursor); cursor += 1
    walk(0, 0, [])
    if not solutions: return None, "review_required_pinyin_parse_no_match"
    if len(solutions) != 1: return None, "review_required_pinyin_parse_ambiguous"
    return solutions[0], "accepted_rule_based_pinyin_validated"


def character_phoneme_mapping(
    normalized_lyrics: str, phonemes: list[str], *, is_slur: list[object] | None = None
) -> tuple[list[list[int] | None], str, list[int]]:
    """Return explicit source indices only when sequence cardinality is exact."""

    groups, special_indices = group_phonemes(phonemes)
    if not normalized_lyrics:
        return [], "rejected_empty_normalized_lyrics", special_indices
    pinyin_mapping, pinyin_status = unique_pinyin_phoneme_mapping(normalized_lyrics, phonemes)
    if pinyin_mapping is not None:
        return pinyin_mapping, pinyin_status, special_indices
    # A complete structural mapping with no cardinality defect and only held-
    # vowel/slur evidence is rule-validated as a held-vowel case. Complex
    # slur-plus-deficit cases remain review-only.
    if len(groups) == len(normalized_lyrics) and is_slur and any(bool(value) for value in is_slur):
        return groups, "accepted_rule_validated_held_vowel", special_indices
    # A failed/ambiguous pinyin validation is intentionally review-only, even
    # where a simpler cardinality grouping happened to match.
    return [None] * len(normalized_lyrics), pinyin_status, special_indices
    if len(groups) != len(normalized_lyrics):
        split_groups, repeat_count = split_repeated_vowels_exactly(groups, phonemes)
        missing_groups = len(normalized_lyrics) - len(groups)
        if missing_groups > 0 and repeat_count == missing_groups and len(split_groups) == len(normalized_lyrics):
            return split_groups, "accepted_rule_based_repeated_vowel_split", special_indices
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


def note_event_intervals(notes: list[object], note_durations: list[object]) -> list[tuple[float, float, list[int]]] | None:
    """Collapse repeated M4Singer note metadata into time-indexed note events."""

    if len(notes) != len(note_durations):
        return None
    try:
        pairs = [(int(note), float(duration)) for note, duration in zip(notes, note_durations, strict=True)]
    except (TypeError, ValueError):
        return None
    if any(duration < 0 or duration != duration or duration == float("inf") for _, duration in pairs):
        return None
    events: list[tuple[float, float, list[int]]] = []
    cursor = 0.0
    previous: tuple[int, float] | None = None
    for index, pair in enumerate(pairs):
        if pair != previous:
            events.append((cursor, cursor + pair[1], [index]))
            cursor += pair[1]
            previous = pair
        else:
            events[-1][2].append(index)
    return events


def slur_time_allocate_mapping(
    text: str,
    phonemes: list[str],
    phoneme_durations: list[object],
    notes: list[object],
    note_durations: list[object],
    is_slur: list[object],
    character_time_anchors: list[dict[str, Any]] | None,
    *,
    max_boundary_error_sec: float = 0.03,
) -> tuple[list[list[int] | None] | None, dict[str, Any]]:
    """Time-validate a legacy repeated-vowel candidate for a slur review item.

    The legacy grouping remains the only source of phoneme ownership.  This
    incremental stage accepts it only when every character has an independent
    time anchor and its phoneme boundaries agree with collapsed MIDI events.
    It never fabricates an allocation from MIDI pitch or duration alone.
    """

    evidence: dict[str, Any] = {"method": SLUR_TIME_ALLOCATION_VERSION, "eligible": False}
    if not any(bool(value) for value in is_slur) or not character_time_anchors or len(character_time_anchors) != len(text):
        evidence["reason"] = "requires_slur_and_complete_character_time_anchors"
        return None, evidence
    groups, _ = group_phonemes(phonemes)
    split_groups, repeat_count = split_repeated_vowels_exactly(groups, phonemes)
    if len(split_groups) < len(text) or len(split_groups) > 64:
        evidence.update({"reason": "legacy_candidate_cardinality_mismatch", "legacy_group_count": len(groups), "split_group_count": len(split_groups), "character_count": len(text), "repeat_split_count": repeat_count})
        return None, evidence
    # This partitions only the existing legacy groups.  It never creates or
    # reorders phoneme ownership; timing may select among those candidates.
    partitions = list(combinations(range(1, len(split_groups)), len(text) - 1))
    if not partitions or len(partitions) > 256:
        evidence.update({"reason": "legacy_candidate_partition_count_out_of_range", "candidate_partition_count": len(partitions)})
        return None, evidence
    phoneme_times = phoneme_intervals(phoneme_durations, len(phonemes))
    events = note_event_intervals(notes, note_durations)
    if phoneme_times is None or events is None:
        evidence["reason"] = "invalid_phoneme_or_midi_time_metadata"
        return None, evidence
    note_boundaries = [value for start, end, _ in events for value in (start, end)]
    scored: list[tuple[float, list[list[int]], list[float], list[float], list[list[int]]]] = []
    for boundaries in partitions:
        starts = (0, *boundaries)
        ends = (*boundaries, len(split_groups))
        candidate = [[index for group in split_groups[start:end] for index in group] for start, end in zip(starts, ends, strict=True)]
        candidate_times = mapped_character_intervals(candidate, phoneme_durations)
        if any(interval is None for interval in candidate_times):
            continue
        anchor_errors: list[float] = []
        note_errors: list[float] = []
        note_indices: list[list[int]] = []
        valid = True
        for interval, anchor in zip(candidate_times, character_time_anchors, strict=True):
            assert interval is not None
            try:
                anchor_start, anchor_end = float(anchor["start_sec"]), float(anchor["end_sec"])
            except (KeyError, TypeError, ValueError):
                valid = False; break
            anchor_errors.extend((abs(interval[0] - anchor_start), abs(interval[1] - anchor_end)))
            note_errors.extend((min(abs(interval[0] - value) for value in note_boundaries), min(abs(interval[1] - value) for value in note_boundaries)))
            note_indices.append([index for index, (start, end, _) in enumerate(events) if end > interval[0] and start < interval[1]])
        if valid:
            scored.append((max(anchor_errors + note_errors, default=float("inf")), candidate, anchor_errors, note_errors, note_indices))
    if not scored:
        evidence["reason"] = "invalid_character_time_anchor"
        return None, evidence
    scored.sort(key=lambda item: item[0])
    max_error, candidate, anchor_errors, note_errors, note_indices = scored[0]
    unique_best = len(scored) == 1 or scored[1][0] > max_error
    evidence.update({"eligible": True, "legacy_group_count": len(groups), "repeat_split_count": repeat_count, "candidate_partition_count": len(partitions), "max_character_anchor_error_sec": max(anchor_errors, default=None), "max_note_boundary_error_sec": max(note_errors, default=None), "max_error_sec": max_error, "source_note_event_indices": note_indices})
    if max_error > max_boundary_error_sec or not unique_best:
        evidence["reason"] = "three_axis_time_disagreement"
        return None, evidence
    evidence["reason"] = "accepted_unique_legacy_candidate_with_three_axis_time_agreement"
    return candidate, evidence


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


def prepare_item(raw: dict[str, Any], audio_root: Path, *, include_audio_hash: bool = False, overlays: list[dict[str, Any]] | None = None, character_time_anchors: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Prepare one manifest item and its traceable, timestamp-free character records."""

    source_hash = source_row_sha256(raw)
    raw, applied_overlays = apply_token_overlays(raw, overlays)
    item_name = str(raw["item_name"])
    singer_id, song_id, segment_id = item_name.split("#", maxsplit=2)
    audio_relpath = f"{singer_id}#{song_id}/{segment_id}.wav"
    audio_path = audio_root / audio_relpath
    lyrics_raw = str(raw.get("txt", ""))
    normalized = normalize_lyrics(lyrics_raw)
    phonemes = [str(value) for value in raw.get("phs", [])]
    mapping, mapping_status, special_indices = character_phoneme_mapping(normalized.text, phonemes, is_slur=list(raw.get("is_slur", [])))
    time_evidence: dict[str, Any] | None = None
    if mapping_status.startswith("review_required"):
        time_mapping, time_evidence = slur_time_allocate_mapping(
            normalized.text, phonemes, list(raw.get("ph_dur", [])), list(raw.get("notes", [])),
            list(raw.get("notes_dur", [])), list(raw.get("is_slur", [])), character_time_anchors,
        )
        if time_mapping is not None:
            mapping = time_mapping
            mapping_status = "accepted_rule_based_slur_time_allocation"
    metadata = audio_metadata(audio_path)
    character_intervals = mapped_character_intervals(mapping, list(raw.get("ph_dur", [])))
    # The final character is allowed to precede the WAV end: M4Singer commonly
    # carries a trailing pause/breath token.  Requiring a lyric character to end
    # at the file boundary wrongly rejects valid phoneme-derived boundaries.
    duration_metadata_ok = bool(
        character_intervals
        and all(interval is not None for interval in character_intervals)
        and metadata.get("duration_sec") is not None
        and character_intervals[0][0] >= 0.0
        and character_intervals[-1][1] <= float(metadata["duration_sec"]) + 0.10
    )
    if metadata["audio_status"] != "ok":
        status = "rejected"
        status_reason = "decode_failure"
    elif mapping_status.startswith("rejected"):
        status = "rejected"
        status_reason = "empty_lyrics"
    elif mapping_status in {"review_required_auto_phoneme_grouping", "accepted_rule_based_repeated_vowel_split", "accepted_rule_based_pinyin_validated", "accepted_rule_validated_held_vowel", "accepted_rule_based_slur_time_allocation"} and duration_metadata_ok:
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
        "mapping_status": "accepted_rule_based" if mapping_status == "review_required_auto_phoneme_grouping" and status == "accepted" else mapping_status,
        "mapping_version": MAPPING_VERSION,
        "overlay_version": OVERLAY_VERSION if applied_overlays else None,
        "applied_overlays": applied_overlays,
        "source_row_sha256": source_hash,
        "length_source": "native_short",
        "source_item_ids": [item_name],
        "join_points_sec": [],
        "content_hash": hashlib.sha256(
            json.dumps(source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "status": status,
        "status_reason": status_reason,
        "validation_basis": "rule_validated" if status == "accepted" else "review_required",
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
            "mapping_status": "accepted_rule_based" if mapping_status == "review_required_auto_phoneme_grouping" and status == "accepted" else mapping_status,
            "mapping_method": "phoneme_duration_cumulative_v1" if status == "accepted" else "none",
            "mapping_confidence": "rule_validated" if status == "accepted" else "review",
            "quality_flags": [] if status == "accepted" else [status_reason],
            "mapping_notes": {
                "special_phoneme_indices": special_indices,
                "source_phoneme_tokens": [phonemes[i] for i in source_indices] if source_indices else [],
                "applied_overlays": applied_overlays,
                "time_boundary_status": "not_available_from_meta_json",
                "slur_time_allocation": time_evidence,
            },
        }
        for index, (char, source_indices) in enumerate(zip(normalized.text, mapping, strict=True))
    ]
    return manifest, annotations
