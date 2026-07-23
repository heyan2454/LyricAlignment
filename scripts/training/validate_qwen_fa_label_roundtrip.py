#!/usr/bin/env python3
"""Validate derived labels through the exact processor timestamp decode path."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
import hashlib
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.training.qwen_fa_labels import build_supervision_labels


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def decode_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True, capture_output=True,
    )
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if not len(audio):
        raise ValueError(f"empty audio: {path}")
    return audio


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--max-items", type=int, default=0, help="0 validates every label record")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoConfig, AutoProcessor

    kwargs = {"revision": args.revision} if args.revision else {}
    processor = AutoProcessor.from_pretrained(args.model, **kwargs)
    config = AutoConfig.from_pretrained(args.model, **kwargs)
    segment_sec = float(processor.timestamp_segment_time) / 1000.0
    labels = read_jsonl(args.labels)
    if args.max_items:
        # Deterministic hash sampling avoids validating only the first singer/song
        # in the canonical manifest while keeping a stable audit subset.
        labels = sorted(labels, key=lambda row: hashlib.sha256(str(row["item_id"]).encode()).hexdigest())[: args.max_items]
    chars: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(args.characters):
        chars[str(row["item_id"])].append(row)
    failures: list[dict[str, Any]] = []
    max_error = 0.0
    checked_characters = 0
    for index, record in enumerate(labels):
        item_id = str(record["item_id"])
        try:
            class_ids = list(record["timestamp_class_ids"])
            if record["timestamp_segment_sec"] != segment_sec:
                raise ValueError(f"segment mismatch: derived={record['timestamp_segment_sec']} processor={segment_sec}")
            if record["num_timestamp_labels"] != config.num_labels:
                raise ValueError(f"label-count mismatch: derived={record['num_timestamp_labels']} model={config.num_labels}")
            audio = decode_audio(args.audio_root / record["audio_relpath"])
            inputs, word_lists = processor.prepare_forced_aligner_inputs(audio=audio, transcript=record["lyrics_normalized"], language=args.language)
            input_ids = inputs["input_ids"][0]
            target = build_supervision_labels(input_ids, timestamp_token_id=config.timestamp_token_id, class_ids=class_ids)
            positions = (target != -100).nonzero(as_tuple=False).flatten()
            logits = torch.full((1, input_ids.shape[0], config.num_labels), -1.0, dtype=torch.float16)
            logits[0, positions, torch.tensor(class_ids)] = 1.0
            decoded = processor.decode_forced_alignment(logits, inputs["input_ids"], word_lists, config.timestamp_token_id)[0]
            reference = sorted(chars[item_id], key=lambda row: int(row["character_index"]))
            if len(decoded) != len(reference) or len(decoded) != int(record["character_count"]):
                raise ValueError(f"decoded character count={len(decoded)}, expected={len(reference)}")
            for predicted, expected in zip(decoded, reference):
                if predicted["text"] != expected["normalized_character"]:
                    raise ValueError(f"character mismatch: {predicted['text']} != {expected['normalized_character']}")
                start_error = abs(float(predicted["start_time"]) - float(expected["start_sec"]))
                end_error = abs(float(predicted["end_time"]) - float(expected["end_sec"]))
                max_error = max(max_error, start_error, end_error)
                if start_error > segment_sec / 2 + 0.002 or end_error > segment_sec / 2 + 0.002:
                    raise ValueError(f"quantization error exceeds bound: {start_error=}, {end_error=}")
                if float(predicted["start_time"]) > float(predicted["end_time"]):
                    raise ValueError("decoded reversed interval")
            checked_characters += len(reference)
        except Exception as exc:
            failures.append({"item_id": item_id, "error_type": type(exc).__name__, "error": str(exc)})
        if (index + 1) % 100 == 0:
            print(json.dumps({"checked_items": index + 1, "failures": len(failures)}, ensure_ascii=False), flush=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "label_roundtrip_failures.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in failures), encoding="utf-8")
    summary = {
        "status": "passed" if not failures else "failed", "checked_items": len(labels),
        "checked_characters": checked_characters, "failure_count": len(failures),
        "max_absolute_quantization_error_sec": max_error,
        "timestamp_segment_sec": segment_sec, "theoretical_per_boundary_error_upper_bound_sec": segment_sec / 2,
        "model_timestamp_token_id": config.timestamp_token_id, "model_num_labels": config.num_labels,
    }
    (args.out_dir / "label_roundtrip_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
