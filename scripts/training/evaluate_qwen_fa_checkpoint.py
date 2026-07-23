#!/usr/bin/env python3
"""Evaluate a frozen Qwen FA projector/LoRA checkpoint on a sealed split."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate_tolerant
from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, decoded_character_predictions, move_inputs, read_jsonl


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen3-ForcedAligner-0.6B-hf")
    p.add_argument("--revision", required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--characters", type=Path, required=True)
    p.add_argument("--audio-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--split", help="Evaluate only this frozen split (for example: test).")
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--device", default="cuda")
    args = p.parse_args()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForTokenClassification, AutoProcessor

    processor = AutoProcessor.from_pretrained(args.model, revision=args.revision)
    base = AutoModelForTokenClassification.from_pretrained(args.model, revision=args.revision, dtype="bfloat16")
    model = PeftModel.from_pretrained(base, args.checkpoint / "adapter").to(args.device)
    saved = torch.load(args.checkpoint / "projector.pt", map_location="cpu", weights_only=True)
    parameters = dict(model.named_parameters())
    missing = set(saved) - set(parameters)
    if missing:
        raise RuntimeError(f"projector checkpoint names not found: {sorted(missing)[:3]}")
    for name, value in saved.items():
        parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))
    records = read_jsonl(args.labels)
    if args.split:
        records = [row for row in records if row.get("split") == args.split]
        if not records:
            raise ValueError(f"no records in requested split: {args.split}")
    chars = read_jsonl(args.characters)
    by_item: dict[str, list[dict]] = {}
    for row in chars: by_item.setdefault(row["item_id"], []).append(row)
    collator = QwenFABatchCollator(processor, audio_root=args.audio_root, language="Chinese", timestamp_token_id=model.config.timestamp_token_id)
    dtype = torch.bfloat16
    predictions: list[dict] = []
    losses: list[float] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(records), args.batch_size):
            chunk = records[start:start + args.batch_size]
            inputs, words = collator(chunk)
            batch = move_inputs(inputs, args.device, dtype)
            output = model(**batch)
            losses.append(float(output.loss))
            predictions.extend(decoded_character_predictions(processor, output.logits, batch["input_ids"], words, model.config.timestamp_token_id, chunk))
    reference = [row for record in records for row in by_item[record["item_id"]]]
    metrics = evaluate_tolerant(reference, predictions)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "predictions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({"loss": sum(losses) / len(losses), "metric": metrics}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"loss": sum(losses) / len(losses), "metric": metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
