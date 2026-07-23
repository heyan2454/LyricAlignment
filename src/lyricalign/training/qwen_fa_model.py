"""Verified freezing and PEFT injection for Qwen Forced Aligner experiments."""

from __future__ import annotations

import re
from typing import Any


def freeze_all(model: Any) -> None:
    for parameter in model.parameters():
        parameter.requires_grad = False


def unfreeze_projector(model: Any) -> list[str]:
    module = model.get_submodule("model.multi_modal_projector")
    for parameter in module.parameters():
        parameter.requires_grad = True
    return [name for name, parameter in model.named_parameters() if parameter.requires_grad]


def unfreeze_classifier(model: Any) -> list[str]:
    module = model.get_submodule("score")
    for parameter in module.parameters():
        parameter.requires_grad = True
    return [name for name, parameter in model.named_parameters() if parameter.requires_grad]


def audio_attention_target_regex(model: Any, scope: str) -> tuple[str, list[str]]:
    layers = model.get_submodule("model.audio_tower").layers
    count = len(layers)
    selected = range(count // 2, count) if scope == "top_half" else range(count)
    indices = "|".join(str(index) for index in selected)
    pattern = rf"^model\.audio_tower\.layers\.({indices})\.self_attn\.(q_proj|k_proj|v_proj|out_proj)$"
    targets = [name for name, _ in model.named_modules() if re.fullmatch(pattern, name)]
    expected = len(list(selected)) * 4
    if len(targets) != expected:
        raise RuntimeError(f"LoRA target discovery failed: found={len(targets)}, expected={expected}, scope={scope}")
    return pattern, targets


def apply_audio_lora(model: Any, *, scope: str, r: int = 8, alpha: int = 16, dropout: float = 0.05) -> tuple[Any, list[str]]:
    """Apply LoRA strictly to audio-tower attention; language model is excluded."""
    from peft import LoraConfig, TaskType, get_peft_model

    pattern, targets = audio_attention_target_regex(model, scope)
    config = LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, bias="none", target_modules=pattern, task_type=TaskType.TOKEN_CLS)
    adapted = get_peft_model(model, config)
    module_names = {name for name, _ in adapted.named_modules()}
    hit = [target for target in targets if any(name.endswith(f"{target}.lora_A") for name in module_names)]
    if len(hit) != len(targets):
        raise RuntimeError(f"PEFT injected {len(hit)} LoRA targets; expected {len(targets)}")
    if any("language_model" in name for name in hit):
        raise RuntimeError("LoRA unexpectedly reached language model")
    return adapted, targets


def trainable_parameter_summary(model: Any) -> dict[str, Any]:
    trainable = {name: parameter.numel() for name, parameter in model.named_parameters() if parameter.requires_grad}
    total = sum(parameter.numel() for parameter in model.parameters())
    return {"total_parameters": total, "trainable_parameters": sum(trainable.values()), "frozen_parameters": total - sum(trainable.values()),
            "trainable_ratio": sum(trainable.values()) / total if total else 0.0, "trainable_parameter_tensors": trainable}
