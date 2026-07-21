from pathlib import Path
import sys
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.mir1k import prepare_partial_align_item


def make_audio(root: Path) -> None:
    directory = root / "UndividedWavfile"
    directory.mkdir()
    with wave.open(str(directory / "singer_1.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 32000)


def test_prepare_partial_align_item_exports_test_only_character_gt(tmp_path: Path) -> None:
    make_audio(tmp_path)
    manifest, annotations = prepare_partial_align_item(
        {"song_id": "singer_1.wav", "lyric": "你好", "on_offset": [[0.1, 0.5], [0.5, 1.0]]}, tmp_path
    )
    assert manifest["split"] == "test"
    assert manifest["usage"] == "ood_test_only"
    assert manifest["length_source"] == "natural_long"
    assert [item["start_sec"] for item in annotations] == [0.1, 0.5]


def test_prepare_partial_align_rejects_non_monotonic_intervals(tmp_path: Path) -> None:
    make_audio(tmp_path)
    with pytest.raises(ValueError, match="invalid/non-monotonic"):
        prepare_partial_align_item(
            {"song_id": "singer_1.wav", "lyric": "你好", "on_offset": [[0.5, 0.8], [0.4, 1.0]]}, tmp_path
        )
