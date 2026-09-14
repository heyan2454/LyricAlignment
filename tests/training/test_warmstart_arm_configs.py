from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
A = ROOT / "configs/training/qwen_fa_lora_warmstart_control_20260914.yaml"
B = ROOT / "configs/training/qwen_fa_lora_warmstart_oversample_20260914.yaml"


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else key))
        return out
    if isinstance(value, list):
        out = {}
        for index, item in enumerate(value):
            out.update(_flatten(item, f"{prefix}[{index}]"))
        return out
    return {prefix: value}


def test_the_two_arms_differ_only_in_the_data_mix():
    first = yaml.safe_load(A.read_text(encoding="utf-8"))
    second = yaml.safe_load(B.read_text(encoding="utf-8"))
    flat_first, flat_second = _flatten(first), _flatten(second)
    differing = {key for key in set(flat_first) | set(flat_second) if flat_first.get(key) != flat_second.get(key)}
    assert differing, "两臂必须有一处差别，否则不是 A/B"
    assert all(key.startswith("training.duration_oversample") for key in differing), differing


def test_shared_scheduling_hyperparameters_are_identical():
    first = yaml.safe_load(A.read_text(encoding="utf-8"))["training"]
    second = yaml.safe_load(B.read_text(encoding="utf-8"))["training"]
    for key in ("projector_lr", "lora_lr", "save_steps", "disk_floor_gb", "dtype"):
        assert first[key] == second[key], key
    assert first["lr_schedule"] == second["lr_schedule"]
    assert first["init_from_checkpoint"] == second["init_from_checkpoint"]
    assert first["eval_funnel"] == second["eval_funnel"]
    a_steps = yaml.safe_load(A.read_text(encoding="utf-8"))["stages"]["r2"]["max_steps"]
    b_steps = yaml.safe_load(B.read_text(encoding="utf-8"))["stages"]["r2"]["max_steps"]
    assert a_steps == b_steps


def test_control_arm_has_no_oversampling_and_treatment_is_strong_enough():
    control = yaml.safe_load(A.read_text(encoding="utf-8"))["training"]
    treatment = yaml.safe_load(B.read_text(encoding="utf-8"))["training"]
    assert control.get("duration_oversample") in (None, {}), "对照臂不能带任何配比改动"
    assert treatment["duration_oversample"]["long_sec"] == 1.0
    # factor=3 只给 ×1.69 的份额增益（饱和上限 ×2.58），null 结果无法否证暴露假设
    assert treatment["duration_oversample"]["factor"] >= 6, treatment["duration_oversample"]


def test_concat_arm_refuses_to_mix_both_interventions():
    concat = yaml.safe_load((ROOT / "configs/training/qwen_fa_lora_concat20_20260914.yaml").read_text())
    assert concat["training"]["concat_samples"]["enabled"] is True
    assert "duration_oversample" not in concat["training"], "拼接臂必须只改样本长度这一个变量"


def _flat(path: Path) -> dict:
    return _flatten(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_c_arm_differs_from_control_only_in_loss_weighting():
    """C 是 B 失败时的判定实验，必须只带一个变量，且不得同时带条目复制。"""
    control = ROOT / "configs/training/qwen_fa_lora_warmstart_control_20260914.yaml"
    treatment = ROOT / "configs/training/qwen_fa_lora_warmstart_lossweight_20260914.yaml"
    first, second = _flat(control), _flat(treatment)
    differing = {key for key in set(first) | set(second) if first.get(key) != second.get(key)}
    assert differing, "C 与 A 必须有一处差别"
    assert all(key.startswith("training.loss_weighting") for key in differing), differing
    weighting = yaml.safe_load(treatment.read_text(encoding="utf-8"))["training"]["loss_weighting"]
    assert weighting["enabled"] is True
    assert weighting["slot"] == "offset", "按今晚证据只加权长字符结束点"
    assert weighting["long_sec"] == 1.0 and weighting["weight"] >= 2.0
    # 不得夹带条目复制：C 的意义正在于没有覆盖代价
    oversample = yaml.safe_load(treatment.read_text(encoding="utf-8"))["training"].get("duration_oversample")
    assert not oversample, f"C 臂不能带条目复制：{oversample}"


def test_c_arm_keeps_the_same_optimisation_budget_as_a():
    control = yaml.safe_load((ROOT / "configs/training/qwen_fa_lora_warmstart_control_20260914.yaml").read_text(encoding="utf-8"))
    treatment = yaml.safe_load((ROOT / "configs/training/qwen_fa_lora_warmstart_lossweight_20260914.yaml").read_text(encoding="utf-8"))
    assert control["stages"]["r2"]["max_steps"] == treatment["stages"]["r2"]["max_steps"] == 600
    assert control["training"]["save_steps"] == treatment["training"]["save_steps"]
