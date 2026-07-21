from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.datasets.audit import classify_item, summarize
from lyricalign.datasets.m4singer import character_phoneme_mapping, normalize_lyrics, prepare_item


def test_normalization_preserves_raw_positions_and_removes_spacing_punctuation() -> None:
    result = normalize_lyrics("你， 好！Ａ")
    assert result.text == "你好A"
    assert result.raw_to_normalized == [0, None, None, 1, None, 2]
    assert result.normalized_to_raw == [0, 3, 5]
    assert normalize_lyrics(result.text).text == result.text


def test_mapping_only_exposes_source_indices_for_exact_group_count() -> None:
    mapping, status, special = character_phoneme_mapping("好的", ["h", "ao", "<SP>", "d", "e"])
    assert mapping == [[0, 1], [3, 4]]
    assert status == "review_required_auto_phoneme_grouping"
    assert special == [2]
    mapping, status, _ = character_phoneme_mapping("好的", ["h", "ao"])
    assert mapping == [None, None]
    assert status == "review_required_group_count_mismatch"


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
