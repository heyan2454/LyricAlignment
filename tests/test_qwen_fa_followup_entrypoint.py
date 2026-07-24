import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_followup_configs_preserve_matched_budget_and_seed_gate() -> None:
    r1 = yaml.safe_load((ROOT / "configs/training/qwen_fa_lora_full_r1_v1.yaml").read_text())
    r2 = yaml.safe_load((ROOT / "configs/training/qwen_fa_lora_full_r2_v1.yaml").read_text())
    seed2 = yaml.safe_load((ROOT / "configs/training/qwen_fa_lora_seed2_pilot_v1.yaml").read_text())
    for key in ("micro_batch_size", "gradient_accumulation", "projector_lr", "weight_decay", "warmup_ratio", "eval_steps", "save_steps"):
        assert r1["training"][key] == r2["training"][key]
    assert r1["stages"]["r1"]["train_items"] == 0
    assert r1["stages"]["r1"]["max_steps"] == r2["stages"]["r2"]["max_steps"] == 1110
    assert seed2["training"]["seed"] == 20260724
    assert seed2["stages"]["r1"]["max_steps"] == seed2["stages"]["r2"]["max_steps"] == 100


def test_seed2_decision_gate_uses_validation_metrics_only(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    out = tmp_path / "decision.json"
    r1.write_text(json.dumps({"metric": {"song_macro_boundary_mae_sec": 0.09, "invalid_prediction_rate": 0.02, "item_coverage": 0.98}}))
    r2.write_text(json.dumps({"metric": {"song_macro_boundary_mae_sec": 0.06, "invalid_prediction_rate": 0.015, "item_coverage": 0.985}}))
    subprocess.run([
        sys.executable, str(ROOT / "scripts/training/decide_qwen_fa_seed2.py"),
        "--r1-evaluation", str(r1), "--r2-evaluation", str(r2), "--seed", "20260724", "--out", str(out),
    ], check=True)
    decision = json.loads(out.read_text())
    assert decision["test_or_ood_used_for_decision"] is False
    assert decision["recommend_full_r2_second_seed"] is True


def test_entrypoints_are_shell_syntax_valid() -> None:
    for relative in (
        "scripts/training/run_qwen_fa_followup_overnight.sh",
        "scripts/training/launch_qwen_fa_followup_detached.sh",
    ):
        subprocess.run(["bash", "-n", str(ROOT / relative)], check=True)
