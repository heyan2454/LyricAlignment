#!/usr/bin/env python3
"""Write a compact auditable Stage-A batch summary, not binary tensors."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, read_jsonl

def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--labels", type=Path, required=True); p.add_argument("--audio-root", type=Path, required=True); p.add_argument("--model", required=True); p.add_argument("--revision", required=True); p.add_argument("--out", type=Path, required=True); p.add_argument("--count", type=int, default=2); args = p.parse_args()
    from transformers import AutoConfig, AutoProcessor
    processor = AutoProcessor.from_pretrained(args.model, revision=args.revision); config = AutoConfig.from_pretrained(args.model, revision=args.revision)
    records = [r for r in read_jsonl(args.labels) if r["split"] == "train"][:args.count]
    batch, words = QwenFABatchCollator(processor, audio_root=args.audio_root, language="Chinese", timestamp_token_id=config.timestamp_token_id)(records)
    items = []
    for i, row in enumerate(records):
        labels = batch["labels"][i]; positions = (labels != -100).nonzero(as_tuple=False).flatten().tolist()
        items.append({"item_id": row["item_id"], "audio_duration_sec": row["duration_sec"], "normalized_lyrics": row["lyrics_normalized"], "character_count": row["character_count"], "timestamp_token_positions": positions, "timestamp_class_ids": row["timestamp_class_ids"], "word_list": words[i]})
    summary = {"items": items, "input_tensor_shapes": {k: list(v.shape) for k,v in batch.items()}, "input_dtypes": {k: str(v.dtype) for k,v in batch.items()}, "timestamp_token_id": config.timestamp_token_id, "timestamp_segment_sec": float(processor.timestamp_segment_time)/1000}
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"items":len(items), "out":str(args.out)}, ensure_ascii=False))
if __name__ == "__main__": main()
