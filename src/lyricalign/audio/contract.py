"""Versioned vocal-only audio contract with collision-safe normalization helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lyricalign.datasets.m4singer import audio_metadata, sha256_file

AUDIO_CONTRACT_VERSION = "audio_contract_v1"
ALLOWED_VOCAL_SOURCES = {"native_vocal", "official_vocal_channel", "model_separated_vocal"}


def inventory_record(path: Path, vocal_source_type: str, *, separator_identity: dict[str, Any] | None = None, include_hash: bool = False) -> dict[str, Any]:
    if vocal_source_type not in ALLOWED_VOCAL_SOURCES:
        raise ValueError(f"unsupported vocal source: {vocal_source_type}")
    if vocal_source_type == "model_separated_vocal" and not separator_identity:
        raise ValueError("model_separated_vocal requires separator_identity")
    metadata = audio_metadata(path)
    record: dict[str, Any] = {
        "audio_contract_version": AUDIO_CONTRACT_VERSION,
        "vocal_source_type": vocal_source_type,
        "separator_identity": separator_identity,
        "audio": metadata,
    }
    if metadata["audio_status"] == "ok" and include_hash:
        record["audio_sha256"] = sha256_file(path)
    return record


def normalized_identity(source_hash: str, *, sample_rate_hz: int = 16000, channels: int = 1) -> dict[str, Any]:
    return {"source_sha256": source_hash, "sample_rate_hz": sample_rate_hz, "channels": channels, "format": "wav_pcm_s16le", "contract_version": AUDIO_CONTRACT_VERSION}


def normalize_wav(source: Path, destination: Path, *, overwrite: bool = False, ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    """Normalize with ffmpeg through an atomic temporary file; never alter source."""
    source_hash = sha256_file(source)
    identity = normalized_identity(source_hash)
    if destination.exists():
        if not overwrite:
            existing = inventory_record(destination, "native_vocal", include_hash=True)
            if existing.get("audio_sha256"):
                return {"status": "skipped_existing", "identity": identity, "output_sha256": existing["audio_sha256"]}
            raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        subprocess.run([ffmpeg, "-nostdin", "-y", "-i", str(source), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary)], check=True, capture_output=True, text=True)
        output = audio_metadata(temporary)
        if output["audio_status"] != "ok" or output["sample_rate_hz"] != 16000 or output["channels"] != 1 or output["sample_width_bytes"] != 2:
            raise ValueError(f"normalized output violates contract: {output}")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"status": "written", "identity": identity, "output_sha256": sha256_file(destination), "audio": audio_metadata(destination)}
