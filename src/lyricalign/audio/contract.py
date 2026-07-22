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

AUDIO_CONTRACT_VERSION = "audio_contract_v2"
NORMALIZATION_RULE_VERSION = "normalize_wav_pcm_s16le_mono_16khz_v1"
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


def normalized_identity(source: Path, source_hash: str, *, sample_rate_hz: int = 16000, channels: int = 1) -> dict[str, Any]:
    return {"source_path": str(source.resolve()), "source_sha256": source_hash, "target_sample_rate": sample_rate_hz, "target_channels": channels, "conversion_parameters": {"codec": "pcm_s16le", "ffmpeg_args": ["-ac", str(channels), "-ar", str(sample_rate_hz), "-c:a", "pcm_s16le"]}, "conversion_rule_version": NORMALIZATION_RULE_VERSION}


def normalize_wav(source: Path, destination: Path, *, overwrite: bool = False, ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    """Normalize with ffmpeg through an atomic temporary file; never alter source."""
    source_hash = sha256_file(source)
    identity = normalized_identity(source, source_hash)
    sidecar = destination.with_suffix(destination.suffix + ".identity.json")
    if destination.exists():
        existing_hash = sha256_file(destination) if audio_metadata(destination).get("audio_status") == "ok" else None
        prior = None
        try:
            import json
            prior = json.loads(sidecar.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            pass
        valid = bool(prior and existing_hash and prior.get("identity") == identity and prior.get("output_sha256") == existing_hash)
        if valid and not overwrite:
            return {"status": "skipped_existing", "identity": identity, "output_sha256": existing_hash}
        if not overwrite:
            raise FileExistsError(f"identity conflict for {destination}; use --overwrite to replace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        subprocess.run([ffmpeg, "-nostdin", "-y", "-i", str(source), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary)], check=True, capture_output=True, text=True)
        output = audio_metadata(temporary)
        if output["audio_status"] != "ok" or output["sample_rate_hz"] != 16000 or output["channels"] != 1 or output["sample_width_bytes"] != 2:
            raise ValueError(f"normalized output violates contract: {output}")
        output_hash = sha256_file(temporary)
        import json
        sidecar_tmp = sidecar.with_suffix(sidecar.suffix + ".tmp")
        sidecar_tmp.write_text(json.dumps({"identity": identity, "output_path": str(destination.resolve()), "output_sha256": output_hash}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
        os.replace(sidecar_tmp, sidecar)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"status": "written", "identity": identity, "output_sha256": sha256_file(destination), "audio": audio_metadata(destination), "sidecar": str(sidecar)}
