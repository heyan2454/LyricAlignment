from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.datasets.audit import classify_item, summarize
from lyricalign.datasets.m4singer import apply_token_overlays, character_phoneme_mapping, normalize_lyrics, prepare_item, source_row_sha256


def test_normalization_preserves_raw_positions_and_removes_spacing_punctuation() -> None:
    result = normalize_lyrics("你， 好！Ａ")
    assert result.text == "你好A"
    assert result.raw_to_normalized == [0, None, None, 1, None, 2]
    assert result.normalized_to_raw == [0, 3, 5]
    assert normalize_lyrics(result.text).text == result.text


def test_mapping_only_exposes_source_indices_for_exact_group_count() -> None:
    mapping, status, special = character_phoneme_mapping("好的", ["h", "ao", "<SP>", "d", "e"])
    assert mapping == [[0, 1], [3, 4]]
    assert status == "accepted_rule_based_pinyin_validated"
    assert special == [2]
    mapping, status, _ = character_phoneme_mapping("好的", ["h", "ao"])
    assert mapping == [None, None]
    assert status == "review_required_pinyin_parse_no_match"


def test_changed_vowel_starts_zero_initial_group_but_repeated_vowel_is_held() -> None:
    mapping, status, _ = character_phoneme_mapping("好我", ["h", "ao", "uo"])
    assert mapping == [[0, 1], [2]]
    assert status == "accepted_rule_based_pinyin_validated"


def test_unique_pinyin_parse_recovers_zero_initial_and_rejects_ambiguous_repeats() -> None:
    mapping, status, _ = character_phoneme_mapping("题一啊", ["t", "i", "i", "a"])
    assert mapping == [[0, 1], [2], [3]]
    assert status == "accepted_rule_based_pinyin_validated"
    mapping, status, _ = character_phoneme_mapping("啊啊", ["a", "a", "a"])
    assert mapping == [None, None]
    assert status == "review_required_pinyin_parse_ambiguous"
    mapping, status, _ = character_phoneme_mapping("好", ["h", "ao", "ao"])
    assert mapping == [[0, 1, 2]]
    assert status == "accepted_rule_based_pinyin_validated"


def test_pinyin_parse_keeps_zero_initial_reading_of_polyphonic_character() -> None:
    mapping, status, _ = character_phoneme_mapping("走入无边人海里", ["z", "ou", "r", "u", "u", "b", "ian", "r", "en", "h", "ai", "l", "i"])
    assert mapping == [[0, 1], [2, 3], [4], [5, 6], [7, 8], [9, 10], [11, 12]]
    assert status == "accepted_rule_based_pinyin_validated"


def test_pinyin_parse_maps_qu_to_m4singer_v_and_held_only_fallback() -> None:
    mapping, status, _ = character_phoneme_mapping("去哪啊", ["q", "v", "n", "a", "a"])
    assert mapping == [[0, 1], [2, 3], [4]]
    assert status == "accepted_rule_based_pinyin_validated"
    mapping, status, _ = character_phoneme_mapping("好", ["h", "ai"], is_slur=[False, True])
    assert mapping == [[0, 1]]
    assert status == "accepted_rule_validated_held_vowel"


def test_wang_is_normal_uang_and_overlay_is_single_record_hash_anchored() -> None:
    mapping, status, _ = character_phoneme_mapping("忘", ["uang"])
    assert mapping == [[0]]
    assert status == "accepted_rule_based_pinyin_validated"
    raw = {"item_name": "Alto-1#空空#0019", "phs": ["van"]}
    overlay = {"item_id": raw["item_name"], "source_row_sha256": source_row_sha256(raw), "operation": "replace_token", "target": "phs", "token_index": 0, "expected_value": "van", "replacement_value": "uang", "reviewer_decision": "approved"}
    corrected, applied = apply_token_overlays(raw, [overlay])
    assert raw["phs"] == ["van"]
    assert corrected["phs"] == ["uang"]
    assert applied == [overlay]


def test_slur_time_stage_only_extends_a_legacy_repeat_candidate_with_three_axis_agreement(tmp_path: Path) -> None:
    raw = {"item_name": "Alto-1#demo#0004", "txt": "啊啊", "phs": ["a", "a", "a"], "ph_dur": [0.5, 0.5, 0.5], "notes": [60, 62, 62], "notes_dur": [0.5, 1.0, 1.0], "is_slur": [1, 1, 1]}
    audio_dir = tmp_path / "Alto-1#demo"; audio_dir.mkdir()
    with wave.open(str(audio_dir / "0004.wav"), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(b"\x00\x00" * 24000)
    # The pure mapping is ambiguous; the independent anchors select the legacy split.
    mapping, status, _ = character_phoneme_mapping(raw["txt"], raw["phs"], is_slur=raw["is_slur"])
    assert mapping == [None, None]
    assert status == "review_required_pinyin_parse_ambiguous"
    manifest, annotations = prepare_item(raw, tmp_path, character_time_anchors=[{"character_index": 0, "start_sec": 0.0, "end_sec": 0.5}, {"character_index": 1, "start_sec": 0.5, "end_sec": 1.5}])
    assert manifest["status"] == "accepted"
    assert manifest["mapping_status"] == "accepted_rule_based_slur_time_allocation"
    assert [row["source_phoneme_indices"] for row in annotations] == [[0], [1, 2]]


def test_prepare_item_keeps_relative_audio_path_and_no_timestamps(tmp_path: Path) -> None:
    audio_dir = tmp_path / "Alto-1#demo"
    audio_dir.mkdir()
    with wave.open(str(audio_dir / "0000.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    manifest, annotations = prepare_item(
        {"item_name": "Alto-1#demo#0000", "txt": "好的", "phs": ["h", "ao", "d", "e"]}, tmp_path
    )
    assert manifest["audio_relpath"] == "Alto-1#demo/0000.wav"
    assert manifest["status"] == "review_required"
    assert manifest["length_source"] == "native_short"
    assert [x["source_phoneme_indices"] for x in annotations] == [[0, 1], [2, 3]]
    assert all(x["start_sec"] is None and x["end_sec"] is None for x in annotations)


def test_trailing_pause_does_not_invalidate_character_boundaries(tmp_path: Path) -> None:
    audio_dir = tmp_path / "Alto-1#demo"
    audio_dir.mkdir()
    with wave.open(str(audio_dir / "0001.wav"), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    manifest, annotations = prepare_item(
        {"item_name": "Alto-1#demo#0001", "txt": "好", "phs": ["h", "ao", "<SP>"], "ph_dur": [0.4, 0.4, 0.2]}, tmp_path
    )
    assert manifest["status"] == "accepted"
    assert annotations[0]["end_sec"] == 0.8


def test_audit_taxonomy_is_conserved_and_exact_mapping_is_not_a_mismatch(tmp_path: Path) -> None:
    audio_dir = tmp_path / "Alto-1#demo"
    audio_dir.mkdir()
    with wave.open(str(audio_dir / "0000.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    record = classify_item(
        {"item_name": "Alto-1#demo#0000", "txt": "好", "phs": ["h", "ao"], "ph_dur": [0.5, 0.5], "notes": [60], "notes_dur": [1.0]}, str(tmp_path)
    )
    assert record["taxonomy"] == "accepted_rule_based"
    summary = summarize([record])
    assert summary["processed"] + summary["failed"] == summary["total"]
    assert summary["accepted_rule_based"] + summary["mismatch_total"] == summary["total"]


def test_special_token_is_attribute_not_primary_reason(tmp_path: Path) -> None:
    audio_dir = tmp_path / "Alto-1#demo"; audio_dir.mkdir()
    with wave.open(str(audio_dir / "0002.wav"), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(b"\x00\x00" * 16000)
    record = classify_item({"item_name": "Alto-1#demo#0002", "txt": "好", "phs": ["h", "ao", "d", "e", "<SP>"], "ph_dur": [0.2, 0.2, 0.2, 0.2, 0.2], "notes": [], "notes_dur": [], "is_slur": [True]}, str(tmp_path))
    assert record["taxonomy"] == "slur_or_repeated_vowel"
    assert record["contains_special_non_lyric_token"]


def test_zero_initial_and_special_token_do_not_mask_pinyin_parse_failure(tmp_path: Path) -> None:
    audio_dir = tmp_path / "Alto-1#demo"; audio_dir.mkdir()
    with wave.open(str(audio_dir / "0003.wav"), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(b"\x00\x00" * 16000)
    record = classify_item(
        {
            "item_name": "Alto-1#demo#0003", "txt": "我好", "phs": ["uo", "<SP>"],
            "ph_dur": [0.5, 0.5], "notes": [], "notes_dur": [],
        },
        str(tmp_path),
    )
    assert record["mapping_status"] == "review_required_pinyin_parse_no_match"
    assert record["taxonomy"] == "mandarin_syllable_parse_failure"
    assert "zero_initial_group" in record["secondary_tags"]
    assert record["contains_special_non_lyric_token"]
