from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "run_qwen_fa_lora_trainer", ROOT / "scripts" / "training" / "run_qwen_fa_lora.py")
TRAINER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRAINER)

WEIGHT_NAME = "multi_modal_projector.net.0.weight"


class TinyModel:
    """Just enough surface for init_from_checkpoint, which only uses named_parameters()."""

    def __init__(self) -> None:
        self.params = {WEIGHT_NAME: torch.nn.Parameter(torch.zeros(2, 2))}

    def named_parameters(self):
        return self.params.items()


def _state(path: Path, payload: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    torch.save(payload, path / "trainer_state.pt")


def test_init_borrows_weights_and_reports_the_source_step(tmp_path: Path):
    source = tmp_path / "ckpt"
    _state(source, {"step": 12000, "trainable_state": {WEIGHT_NAME: torch.ones(2, 2)}})
    model = TinyModel()
    assert TRAINER.init_from_checkpoint(model, source) == 12000
    assert torch.equal(model.params[WEIGHT_NAME], torch.ones(2, 2))


def test_init_casts_to_the_target_dtype_and_device():
    # the run keeps the model in bf16 while a saved state may be float32
    class Bf16Model(TinyModel):
        def __init__(self) -> None:
            self.params = {WEIGHT_NAME: torch.nn.Parameter(torch.zeros(2, 2, dtype=torch.bfloat16))}

    model = Bf16Model()
    assert model.params[WEIGHT_NAME].dtype == torch.bfloat16
    source = Path("/tmp/init_dtype_probe_ckpt")
    _state(source, {"step": 7, "trainable_state": {WEIGHT_NAME: torch.full((2, 2), 0.5)}})
    TRAINER.init_from_checkpoint(model, source)
    assert model.params[WEIGHT_NAME].dtype == torch.bfloat16
    assert torch.allclose(model.params[WEIGHT_NAME].float(), torch.full((2, 2), 0.5))


def test_init_rejects_missing_empty_or_foreign_checkpoints(tmp_path: Path):
    with pytest.raises(SystemExit, match="no trainer_state.pt"):
        TRAINER.init_from_checkpoint(TinyModel(), tmp_path / "nowhere")
    empty = tmp_path / "empty"
    _state(empty, {"step": 1, "trainable_state": {}})
    with pytest.raises(SystemExit, match="empty trainable_state"):
        TRAINER.init_from_checkpoint(TinyModel(), empty)
    foreign = tmp_path / "foreign"
    _state(foreign, {"step": 2, "trainable_state": {"some.other.tensor": torch.zeros(1)}})
    with pytest.raises(SystemExit, match="not in this model"):
        TRAINER.init_from_checkpoint(TinyModel(), foreign)
