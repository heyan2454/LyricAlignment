from pathlib import Path
import sys
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.audio.contract import inventory_record


def test_inventory_requires_declared_vocal_source_and_hashes_audio(tmp_path: Path) -> None:
    path = tmp_path / "vocal.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 10)
    record = inventory_record(path, "native_vocal", include_hash=True)
    assert record["audio_contract_version"] == "audio_contract_v1"
    assert len(record["audio_sha256"]) == 64
    with pytest.raises(ValueError, match="requires separator"):
        inventory_record(path, "model_separated_vocal")
