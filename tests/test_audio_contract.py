from pathlib import Path
import sys
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.audio.contract import inventory_record, normalize_wav


def test_inventory_requires_declared_vocal_source_and_hashes_audio(tmp_path: Path) -> None:
    path = tmp_path / "vocal.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 10)
    record = inventory_record(path, "native_vocal", include_hash=True)
    assert record["audio_contract_version"] == "audio_contract_v2"
    assert len(record["audio_sha256"]) == 64
    with pytest.raises(ValueError, match="requires separator"):
        inventory_record(path, "model_separated_vocal")


def test_normalize_identity_sidecar_conflict_and_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"; alternate = tmp_path / "alternate.wav"; destination = tmp_path / "out.wav"
    for path, value in ((source, b"\x01\x00"), (alternate, b"\x02\x00")):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(value * 20)
    assert normalize_wav(source, destination)["status"] == "written"
    assert normalize_wav(source, destination)["status"] == "skipped_existing"
    with pytest.raises(FileExistsError, match="identity conflict"):
        normalize_wav(alternate, destination)
    assert normalize_wav(alternate, destination, overwrite=True)["status"] == "written"
    destination.with_suffix(".wav.identity.json").unlink()
    with pytest.raises(FileExistsError, match="identity conflict"):
        normalize_wav(alternate, destination)
    assert normalize_wav(alternate, destination, overwrite=True)["status"] == "written"
