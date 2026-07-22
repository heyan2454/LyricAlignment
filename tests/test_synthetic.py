from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.synthetic import build_synthetic_manifest, concat_wavs, shifted_annotations, validate_source_annotations


def test_synthetic_requires_adjacent_same_song_and_shifts_character_timeline(tmp_path: Path) -> None:
    rows = [
        {"item_id": "A#song#0000", "song_id": "song", "singer_id": "A", "duration_sec": 1.0, "split": "train"},
        {"item_id": "A#song#0001", "song_id": "song", "singer_id": "A", "duration_sec": 1.0, "split": "train"},
    ]
    manifest = build_synthetic_manifest(rows, 2.0, "out.wav")
    assert manifest["join_points_sec"] == [1.0]
    shifted = shifted_annotations([{"item_id": "A#song#0001", "start_sec": 0.1, "end_sec": 0.2}], manifest["cumulative_offsets"])
    assert shifted[0]["start_sec"] == 1.1
    for index in range(2):
        with wave.open(str(tmp_path / f"{index}.wav"), "wb") as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(b"\x00\x00" * 16000)
    assert concat_wavs([tmp_path / "0.wav", tmp_path / "1.wav"], tmp_path / "out.wav")[0] == 2.0


def test_synthetic_rejects_mixed_split_and_incomplete_annotations() -> None:
    rows = [{"item_id": "A#song#0000", "song_id": "song", "singer_id": "A", "duration_sec": 1.0, "split": "train", "lyrics_normalized": "甲"}, {"item_id": "A#song#0001", "song_id": "song", "singer_id": "A", "duration_sec": 1.0, "split": "validation", "lyrics_normalized": "乙"}]
    import pytest
    with pytest.raises(ValueError, match="one split"):
        build_synthetic_manifest(rows, 2, "x.wav")
    with pytest.raises(ValueError, match="incomplete"):
        validate_source_annotations([rows[0]], {})
