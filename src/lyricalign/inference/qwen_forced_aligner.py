"""Thin, metric-free adapter for the official Qwen forced-aligner API."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np


class QwenForcedAligner:
    """Load the Transformers-native Qwen forced aligner and expose timed inference."""

    def __init__(
        self,
        model_id_or_path: str,
        *,
        revision: str | None = None,
        device: str = "cuda",
        dtype: str = "bfloat16",
        ffmpeg_executable: str = "ffmpeg",
    ) -> None:
        self.model_id_or_path = model_id_or_path
        self.requested_revision = revision
        self.device = device
        self.dtype_name = dtype
        self.ffmpeg_executable = ffmpeg_executable
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self.model_load_sec: float | None = None
        self.resolved_revision: str | None = None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForTokenClassification, AutoProcessor
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Qwen smoke requires PyTorch, the compatible Transformers source build, "
                "huggingface_hub and ffmpeg. See requirements/README.md."
            ) from exc

        started = time.perf_counter()
        dtype = getattr(torch, self.dtype_name, None)
        if dtype is None:
            raise ValueError(f"Unsupported torch dtype: {self.dtype_name}")

        kwargs: dict[str, Any] = {}
        if self.requested_revision:
            kwargs["revision"] = self.requested_revision

        self._processor = AutoProcessor.from_pretrained(self.model_id_or_path, **kwargs)
        self._model = AutoModelForTokenClassification.from_pretrained(
            self.model_id_or_path,
            dtype=dtype,
            **kwargs,
        ).to(self.device)
        self._model.eval()
        self._torch = torch
        self.model_load_sec = time.perf_counter() - started
        self.resolved_revision = self._resolve_revision()

    def _resolve_revision(self) -> str | None:
        commit = getattr(getattr(self._model, "config", None), "_commit_hash", None)
        if commit:
            return str(commit)
        path = Path(self.model_id_or_path).expanduser()
        if path.exists() and path.parent.name == "snapshots":
            return path.name
        return self.requested_revision

    def model_identity(self) -> dict[str, Any]:
        self.load()
        return {
            "model_id_or_path": self.model_id_or_path,
            "requested_revision": self.requested_revision,
            "resolved_revision": self.resolved_revision,
            "device": self.device,
            "dtype": self.dtype_name,
        }

    def _synchronize(self) -> None:
        if self._torch is not None and str(self.device).startswith("cuda") and self._torch.cuda.is_available():
            self._torch.cuda.synchronize()

    def align_detailed(
        self,
        audio_path: str | Path,
        transcript: str,
        language: str,
    ) -> dict[str, Any]:
        """Return timestamps plus phase-level timings.

        The audio is decoded to mono 16 kHz float32 by ffmpeg. Timings are wall-clock
        measurements; CUDA is synchronized around the model forward pass.
        """

        self.load()
        audio_path = Path(audio_path)

        started = time.perf_counter()
        decoded = subprocess.run(
            [
                self.ffmpeg_executable,
                "-v",
                "error",
                "-i",
                str(audio_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "-",
            ],
            check=True,
            capture_output=True,
        )
        audio = np.frombuffer(decoded.stdout, dtype=np.float32)
        audio_decode_sec = time.perf_counter() - started
        if audio.size == 0:
            raise RuntimeError(f"ffmpeg decoded no audio samples from {audio_path}")

        started = time.perf_counter()
        inputs, word_lists = self._processor.prepare_forced_aligner_inputs(
            audio=audio,
            transcript=transcript,
            language=language,
        )
        inputs = inputs.to(self.device, getattr(self._torch, self.dtype_name))
        input_prepare_sec = time.perf_counter() - started

        self._synchronize()
        started = time.perf_counter()
        with self._torch.inference_mode():
            outputs = self._model(**inputs)
        self._synchronize()
        forward_sec = time.perf_counter() - started

        started = time.perf_counter()
        timestamps = self._processor.decode_forced_alignment(
            logits=outputs.logits,
            input_ids=inputs["input_ids"],
            word_lists=word_lists,
            timestamp_token_id=self._model.config.timestamp_token_id,
        )[0]
        alignment_decode_sec = time.perf_counter() - started

        total_alignment_sec = (
            audio_decode_sec + input_prepare_sec + forward_sec + alignment_decode_sec
        )
        return {
            "timestamps": timestamps,
            "audio_duration_sec": float(audio.size / 16000.0),
            "decoded_sample_rate_hz": 16000,
            "decoded_num_samples": int(audio.size),
            "timing": {
                "audio_decode_sec": audio_decode_sec,
                "input_prepare_sec": input_prepare_sec,
                "forward_sec": forward_sec,
                "alignment_decode_sec": alignment_decode_sec,
                "total_alignment_sec": total_alignment_sec,
            },
        }

    def align(self, audio_path: str | Path, transcript: str, language: str) -> list[dict[str, Any]]:
        """Compatibility wrapper returning only alignment items."""

        return self.align_detailed(audio_path, transcript, language)["timestamps"]
