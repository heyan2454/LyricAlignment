"""Minimal, explicit runtime primitives for Qwen FA LoRA training."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .qwen_fa_labels import build_supervision_labels


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def decode_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True, capture_output=True,
    )
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if not len(audio):
        raise ValueError(f"ffmpeg decoded empty audio: {path}")
    return audio


class QwenFABatchCollator:
    """Build official processor inputs and timestamp-only labels at batch time."""

    def __init__(self, processor: Any, *, audio_root: Path, language: str, timestamp_token_id: int) -> None:
        self.processor = processor
        self.audio_root = audio_root
        self.language = language
        self.timestamp_token_id = timestamp_token_id

    def __call__(self, records: list[dict[str, Any]]) -> tuple[Any, list[list[str]]]:
        audio = [decode_audio(self.audio_root / row["audio_relpath"]) for row in records]
        inputs, words = self.processor.prepare_forced_aligner_inputs(
            audio=audio, transcript=[row["lyrics_normalized"] for row in records], language=self.language
        )
        labels = []
        for index, row in enumerate(records):
            labels.append(build_supervision_labels(
                inputs["input_ids"][index], timestamp_token_id=self.timestamp_token_id,
                class_ids=list(row["timestamp_class_ids"]),
            ))
        import torch
        inputs["labels"] = torch.stack(labels)
        return inputs, words


def move_inputs(inputs: Any, device: str, dtype: Any) -> dict[str, Any]:
    """Move float tensors to BF16 but preserve integer ids, masks, and labels."""
    import torch
    result = {}
    for name, value in inputs.items():
        if not isinstance(value, torch.Tensor):
            result[name] = value
        elif value.is_floating_point():
            result[name] = value.to(device=device, dtype=dtype)
        else:
            result[name] = value.to(device=device)
    return result


def decoded_character_predictions(
    processor: Any, logits: Any, input_ids: Any, word_lists: list[list[str]], timestamp_token_id: int,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decoded = processor.decode_forced_alignment(logits, input_ids, word_lists, timestamp_token_id)
    rows: list[dict[str, Any]] = []
    for record, items in zip(records, decoded):
        for index, item in enumerate(items):
            rows.append({"item_id": record["item_id"], "song_id": record["song_id"], "character_index": index,
                         "normalized_character": item["text"], "start_sec": item["start_time"], "end_sec": item["end_time"]})
    return rows
