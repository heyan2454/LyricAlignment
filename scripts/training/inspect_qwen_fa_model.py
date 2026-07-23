#!/usr/bin/env python3
"""Record actual Qwen FA module paths and verify the requested LoRA scope."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from pathlib import Path
from typing import Any


def parameter_summary(model: Any) -> dict[str, Any]:
    total = sum(parameter.numel() for parameter in model.parameters())
    trainable = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    return {"total_parameters": total, "trainable_parameters": trainable, "frozen_parameters": total - trainable,
            "trainable_ratio": trainable / total if total else 0.0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-ForcedAligner-0.6B-hf")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dtype", default="bfloat16")
    args = parser.parse_args()
    import torch
    import transformers
    from transformers import AutoModelForTokenClassification, AutoProcessor

    model = AutoModelForTokenClassification.from_pretrained(args.model, revision=args.revision, dtype=args.dtype)
    processor = AutoProcessor.from_pretrained(args.model, revision=args.revision)
    named_modules = dict(model.named_modules())
    audio_layers = [name for name in named_modules if name.startswith("model.audio_tower.layers.") and name.endswith(".self_attn")]
    targets = [name for name in named_modules if name.startswith("model.audio_tower.layers.") and name.endswith((".q_proj", ".k_proj", ".v_proj", ".out_proj"))]
    top_half = [name for name in targets if int(name.split(".")[3]) >= len(audio_layers) // 2]
    structure = {
        "model_id": args.model, "model_revision": args.revision, "processor_revision": args.revision,
        "transformers_version": transformers.__version__, "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "timestamp_segment_sec": float(processor.timestamp_segment_time) / 1000.0,
        "timestamp_token_id": model.config.timestamp_token_id, "timestamp_num_labels": model.config.num_labels,
        "audio_tower": "model.audio_tower", "audio_tower_layer_count": len(audio_layers),
        "multi_modal_projector": "model.multi_modal_projector", "timestamp_classifier": "score", "language_model": "model.language_model",
        "candidate_audio_attention_targets": targets, "top_half_audio_attention_targets": top_half,
        "initial_parameter_summary": parameter_summary(model),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "model_structure.txt").write_text("\n".join(f"{name}\t{type(module).__name__}" for name, module in model.named_modules()) + "\n", encoding="utf-8")
    (args.out_dir / "lora_target_modules.json").write_text(json.dumps({"top_half": top_half, "all_audio_attention": targets}, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "trainable_parameter_summary.json").write_text(json.dumps(structure["initial_parameter_summary"], indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "model_identity.json").write_text(json.dumps(structure, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: structure[key] for key in ("audio_tower_layer_count", "timestamp_segment_sec", "timestamp_num_labels")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
