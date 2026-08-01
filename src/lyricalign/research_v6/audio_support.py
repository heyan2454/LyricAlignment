"""Lightweight audio support features for detector experiments.

These features are deliberately model-independent.  They do not claim phoneme
recognition; they only expose whether predicted lyric boundaries have local
vocal/energy support and whether lyric units are placed inside sustained
silence.  More expensive ASR/CTC support can be added behind the same schema.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def materialize_item_audio(item: dict[str, Any]) -> tuple[Path, bool]:
    """Return an inference-ready path; synthesize long M4 audio only on demand."""
    path = Path(item["audio_path"]).resolve()
    if not item.get("lazy_audio_materialization"):
        return path, False
    sources = [Path(value).resolve() for value in item.get("lazy_audio_sources", [])]
    if not sources or not all(source.is_file() for source in sources):
        raise FileNotFoundError(f"missing lazy synthetic-long sources for {item.get('item_id')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    listing = path.with_suffix(".concat.txt")
    temporary = path.with_suffix(".tmp.wav")
    listing.write_text("".join("file '" + str(source).replace("'", "'\\''") + "'\n" for source in sources), encoding="utf-8")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "warning", "-f", "concat", "-safe", "0", "-i", str(listing), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(temporary)], check=True)
        temporary.replace(path)
    finally:
        listing.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
    return path, True


def cleanup_item_audio(path: Path, owned: bool) -> None:
    if owned:
        path.unlink(missing_ok=True)


def _frame_signal(audio: np.ndarray, frame: int, hop: int) -> np.ndarray:
    if len(audio) < frame:
        padded = np.pad(audio, (0, frame - len(audio)))
        return padded[None, :]
    count = 1 + (len(audio) - frame) // hop
    shape = (count, frame)
    strides = (audio.strides[0] * hop, audio.strides[0])
    return np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides).copy()


def build_audio_profile(
    audio: np.ndarray,
    *,
    sample_rate: int = 16000,
    frame_sec: float = 0.04,
    hop_sec: float = 0.02,
) -> dict[str, Any]:
    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    frame = max(16, int(round(frame_sec * sample_rate)))
    hop = max(1, int(round(hop_sec * sample_rate)))
    frames = _frame_signal(values, frame, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    log_rms = 20.0 * np.log10(rms + 1e-8)
    flux = np.zeros_like(rms)
    if len(frames) > 1:
        spectrum = np.abs(np.fft.rfft(frames * np.hanning(frame)[None, :], axis=1))
        normalized = spectrum / np.maximum(spectrum.sum(axis=1, keepdims=True), 1e-8)
        flux[1:] = np.sqrt(np.sum((normalized[1:] - normalized[:-1]) ** 2, axis=1))
    noise_floor = float(np.quantile(log_rms, 0.20)) if len(log_rms) else -120.0
    active_threshold = max(noise_floor + 8.0, float(np.quantile(log_rms, 0.55)) if len(log_rms) else -80.0)
    active = log_rms >= active_threshold
    times = np.arange(len(rms), dtype=np.float64) * hop / sample_rate + frame_sec / 2.0
    return {
        "sample_rate": sample_rate,
        "frame_sec": frame_sec,
        "hop_sec": hop_sec,
        "times_sec": times,
        "log_rms_db": log_rms,
        "spectral_flux": flux,
        "active": active,
        "active_threshold_db": active_threshold,
        "noise_floor_db": noise_floor,
        "duration_sec": len(values) / sample_rate,
    }


def _nearest_index(times: np.ndarray, value: float) -> int:
    if len(times) == 0:
        return 0
    return int(np.clip(np.searchsorted(times, value), 0, len(times) - 1))


def support_for_rows(
    rows: Iterable[dict[str, Any]],
    profile: dict[str, Any],
    *,
    boundary_radius_sec: float = 0.12,
    silence_active_fraction_max: float = 0.15,
) -> dict[int, dict[str, float]]:
    times = np.asarray(profile["times_sec"])
    log_rms = np.asarray(profile["log_rms_db"])
    flux = np.asarray(profile["spectral_flux"])
    active = np.asarray(profile["active"], dtype=bool)
    threshold = float(profile["active_threshold_db"])
    result: dict[int, dict[str, float]] = {}
    for row in rows:
        index = int(row["global_character_index"])
        start = float(row.get("start_sec", row.get("fixed_global_start_sec", row.get("raw_global_start_sec"))))
        end = float(row.get("end_sec", row.get("fixed_global_end_sec", row.get("raw_global_end_sec"))))
        boundary_values: list[float] = []
        for boundary in (start, end):
            left = _nearest_index(times, boundary - boundary_radius_sec)
            right = _nearest_index(times, boundary + boundary_radius_sec) + 1
            if right <= left:
                right = min(len(times), left + 1)
            if right > left and len(times):
                local_energy = float(np.max(log_rms[left:right]) - threshold)
                local_flux = float(np.max(flux[left:right]))
                energy_support = 1.0 / (1.0 + math.exp(-local_energy / 3.0))
                flux_support = min(1.0, local_flux / 0.25)
                boundary_values.append(max(energy_support, flux_support))
        left = _nearest_index(times, start)
        right = _nearest_index(times, max(start, end)) + 1
        interval_active = float(active[left:right].mean()) if right > left and len(active) else 0.0
        result[index] = {
            "boundary_support": min(boundary_values) if boundary_values else 0.0,
            "start_boundary_support": boundary_values[0] if boundary_values else 0.0,
            "end_boundary_support": boundary_values[-1] if boundary_values else 0.0,
            "interval_active_fraction": interval_active,
            "lyrics_in_silence": float(interval_active <= silence_active_fraction_max),
        }
    return result
