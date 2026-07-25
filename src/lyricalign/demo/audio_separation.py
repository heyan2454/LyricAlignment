from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PairDiagnostics:
    correlation: float
    fitted_gain: float
    residual_ratio: float
    normalized_rmse: float


@dataclass(frozen=True)
class SeparationDiagnostics:
    sample_count: int
    sample_rate: int
    mix_rms: float
    vocals_rms: float
    accompaniment_rms: float
    reconstruction_residual_ratio: float
    mix_vs_vocals: PairDiagnostics
    vocals_vs_accompaniment: PairDiagnostics
    passed: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_mono_float32(samples: np.ndarray) -> np.ndarray:
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim == 1:
        return array
    if array.ndim == 2:
        return np.mean(array, axis=1, dtype=np.float32)
    raise ValueError(f"expected mono or time-major multichannel audio, got shape={array.shape}")


def _rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def _pair_diagnostics(reference: np.ndarray, candidate: np.ndarray, *, epsilon: float) -> PairDiagnostics:
    ref = reference.astype(np.float64, copy=False)
    cand = candidate.astype(np.float64, copy=False)
    ref_rms = _rms(ref)
    cand_energy = float(np.dot(cand, cand))
    gain = float(np.dot(ref, cand) / max(cand_energy, epsilon))
    residual = ref - gain * cand
    residual_ratio = _rms(residual) / max(ref_rms, epsilon)
    normalized_rmse = _rms(ref - cand) / max(ref_rms, epsilon)

    ref_centered = ref - float(np.mean(ref))
    cand_centered = cand - float(np.mean(cand))
    denominator = float(np.linalg.norm(ref_centered) * np.linalg.norm(cand_centered))
    correlation = float(np.dot(ref_centered, cand_centered) / denominator) if denominator > epsilon else 0.0
    return PairDiagnostics(
        correlation=correlation,
        fitted_gain=gain,
        residual_ratio=float(residual_ratio),
        normalized_rmse=float(normalized_rmse),
    )


def evaluate_separation(
    mix: np.ndarray,
    vocals: np.ndarray,
    accompaniment: np.ndarray,
    *,
    sample_rate: int,
    identical_correlation: float = 0.9995,
    identical_residual_ratio: float = 0.01,
    minimum_rms: float = 1e-5,
    reconstruction_warning_ratio: float = 0.25,
    epsilon: float = 1e-12,
) -> SeparationDiagnostics:
    """Evaluate a 2-stem separation and reject silent or near-copy outputs.

    The near-copy check is deliberately strict: it only rejects a candidate when
    it is both almost perfectly correlated and explainable as a scalar copy.
    This avoids treating ordinary vocal leakage as a hard failure.
    """

    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    mix_mono = _as_mono_float32(mix)
    vocals_mono = _as_mono_float32(vocals)
    accompaniment_mono = _as_mono_float32(accompaniment)
    count = min(mix_mono.size, vocals_mono.size, accompaniment_mono.size)
    if count <= 0:
        raise ValueError("decoded audio is empty")

    mix_mono = mix_mono[:count]
    vocals_mono = vocals_mono[:count]
    accompaniment_mono = accompaniment_mono[:count]

    mix_rms = _rms(mix_mono)
    vocals_rms = _rms(vocals_mono)
    accompaniment_rms = _rms(accompaniment_mono)
    mix_vs_vocals = _pair_diagnostics(mix_mono, vocals_mono, epsilon=epsilon)
    vocals_vs_accompaniment = _pair_diagnostics(vocals_mono, accompaniment_mono, epsilon=epsilon)
    reconstruction = vocals_mono.astype(np.float64) + accompaniment_mono.astype(np.float64)
    reconstruction_residual_ratio = _rms(mix_mono.astype(np.float64) - reconstruction) / max(mix_rms, epsilon)

    failures: list[str] = []
    warnings: list[str] = []
    if mix_rms < minimum_rms:
        failures.append("mix_is_silent")
    if vocals_rms < minimum_rms:
        failures.append("vocals_is_silent")
    if accompaniment_rms < minimum_rms:
        failures.append("accompaniment_is_silent")

    if (
        abs(mix_vs_vocals.correlation) >= identical_correlation
        and mix_vs_vocals.residual_ratio <= identical_residual_ratio
    ):
        failures.append("vocals_is_near_copy_of_mix")
    if (
        abs(vocals_vs_accompaniment.correlation) >= identical_correlation
        and vocals_vs_accompaniment.residual_ratio <= identical_residual_ratio
    ):
        failures.append("vocals_and_accompaniment_are_near_identical")
    if reconstruction_residual_ratio > reconstruction_warning_ratio:
        warnings.append("stems_do_not_reconstruct_mix_closely")

    return SeparationDiagnostics(
        sample_count=int(count),
        sample_rate=int(sample_rate),
        mix_rms=mix_rms,
        vocals_rms=vocals_rms,
        accompaniment_rms=accompaniment_rms,
        reconstruction_residual_ratio=float(reconstruction_residual_ratio),
        mix_vs_vocals=mix_vs_vocals,
        vocals_vs_accompaniment=vocals_vs_accompaniment,
        passed=not failures,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )
