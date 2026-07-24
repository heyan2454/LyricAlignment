"""Regression tests for the resumable Qwen FA training entry point."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "training" / "run_qwen_fa_lora.py"
SPEC = importlib.util.spec_from_file_location("qwen_fa_training_entrypoint", SCRIPT)
assert SPEC and SPEC.loader
ENTRYPOINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENTRYPOINT)


def _config(labels: Path, split: Path) -> dict:
    return {"data": {"labels": str(labels), "split_manifest": str(split)}, "training": {"seed": 3407}}


def test_resume_identity_rejects_changed_config_or_data(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"; labels.write_text('{"item_id":"a"}\n', encoding="utf-8")
    split = tmp_path / "split.jsonl"; split.write_text('{"item_id":"a","split":"train"}\n', encoding="utf-8")
    run_dir = tmp_path / "run"; config = _config(labels, split)
    ENTRYPOINT.write_run_identity(run_dir, config, object())
    ENTRYPOINT.verify_resume_identity(run_dir, config)

    changed = _config(labels, split)
    changed["training"]["seed"] = 9
    with pytest.raises(RuntimeError, match="configuration"):
        ENTRYPOINT.verify_resume_identity(run_dir, changed)

    labels.write_text('{"item_id":"b"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="labels identity"):
        ENTRYPOINT.verify_resume_identity(run_dir, config)


def test_checkpoint_persists_next_sampler_offset(tmp_path: Path) -> None:
    import torch

    model = torch.nn.Linear(2, 1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1.0)
    path = ENTRYPOINT.checkpoint(tmp_path, model, optimizer, scheduler, step=12, epoch=3, next_offset=28)
    state = torch.load(path / "trainer_state.pt", map_location="cpu", weights_only=False)
    assert state["step"] == 12
    assert state["epoch"] == 3
    assert state["next_offset"] == 28
    assert json.loads((path / "checkpoint_identity.json").read_text(encoding="utf-8"))["next_offset"] == 28


def test_schema_v2_execution_identity_accepts_legacy_resume_file(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"; labels.write_text('{"item_id":"a"}\n', encoding="utf-8")
    split = tmp_path / "split.jsonl"; split.write_text('{"item_id":"a","split":"train"}\n', encoding="utf-8")
    run_dir = tmp_path / "run"; config = _config(labels, split)
    legacy = {
        "stage": "r2",
        "seed": 3407,
        "configured_max_steps": 1110,
        "train_items": 0,
        "validation_items": 0,
    }
    ENTRYPOINT.write_run_identity(run_dir, config, object(), legacy)
    current = {
        "schema_version": 2,
        "stage": "r2",
        "seed": 3407,
        "configured_max_steps": 1110,
        "requested_train_items": 0,
        "requested_validation_items": 0,
        "zero_limit_semantics": "0 means use the complete frozen split, not zero selected items",
    }
    ENTRYPOINT.verify_resume_identity(run_dir, config, current)


def test_training_entrypoint_records_terminal_validation_and_resolved_counts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'last_validation_step != step' in source
    assert '"evaluation_trigger"] = "terminal"' in source
    assert 'resolved_dataset_identity.json' in source
    assert 'selected_train_items' in source
    assert 'requested_train_items' in source
