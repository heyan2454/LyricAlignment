from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoke_script", ROOT / "scripts" / "smoke" / "run_qwen_forced_aligner_smoke.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_overlap_is_not_reported_as_reverse_order() -> None:
    result = MODULE.validate_alignment(
        [
            {"start_time": 0.0, "end_time": 1.0},
            {"start_time": 0.9, "end_time": 1.5},
        ],
        2.0,
        expected_item_count=2,
    )
    assert result["warnings"] == []
    assert result["interval_overlap"]["count"] == 1
    assert result["warning_counts"].get("start_time_decreased", 0) == 0
    assert result["warning_counts"].get("end_time_decreased", 0) == 0


def test_reverse_order_is_separated_from_overlap() -> None:
    result = MODULE.validate_alignment(
        [
            {"start_time": 1.0, "end_time": 2.0},
            {"start_time": 0.5, "end_time": 1.5},
        ],
        3.0,
        expected_item_count=2,
    )
    assert "start_time_decreased" in result["warnings"]
    assert "end_time_decreased" in result["warnings"]
    assert result["interval_overlap"]["count"] == 1


def test_resume_requires_matching_success_identity() -> None:
    identity = {
        "model_id_or_path": "model",
        "resolved_revision": "rev-a",
    }
    record = {
        "status": "success",
        "model": identity,
        "config": {"config_hash": "cfg"},
        "input": {"audio_sha256": "audio", "text_sha256": "text"},
    }
    assert MODULE.should_skip_existing(
        record,
        model_identity=identity,
        config_hash="cfg",
        audio_sha256="audio",
        text_sha256="text",
    )
    failed = dict(record, status="failed")
    assert not MODULE.should_skip_existing(
        failed,
        model_identity=identity,
        config_hash="cfg",
        audio_sha256="audio",
        text_sha256="text",
    )
    changed_revision = dict(identity, resolved_revision="rev-b")
    assert not MODULE.should_skip_existing(
        record,
        model_identity=changed_revision,
        config_hash="cfg",
        audio_sha256="audio",
        text_sha256="text",
    )


def test_zero_and_near_zero_durations_are_explicit_diagnostics() -> None:
    result = MODULE.validate_alignment(
        [{"start_time": 0.0, "end_time": 0.0}, {"start_time": 0.1, "end_time": 0.11}],
        1.0,
    )
    assert "zero_duration" in result["warnings"]
    assert "near_zero_duration" in result["warnings"]
