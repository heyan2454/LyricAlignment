from __future__ import annotations

import json

import pytest

from lyricalign.research_transition_recovery_detector.session_state import (
    PHASE_STATUSES,
    SessionState,
)


def test_begin_complete_flow(tmp_path):
    ss = SessionState(tmp_path / "run")
    assert ss.phase_status("phase_1") == "pending"
    ss.begin_phase("phase_1")
    assert ss.phase_status("phase_1") == "in_progress"
    assert ss.data["current_phase"] == "phase_1"
    ss.complete_phase("phase_1")
    assert ss.phase_status("phase_1") == "complete"


def test_invalid_status_rejected(tmp_path):
    ss = SessionState(tmp_path / "run")
    ss.begin_phase("phase_1")
    with pytest.raises(ValueError):
        ss.complete_phase("phase_1", status="bogus_status")
    assert ss.phase_status("phase_1") == "in_progress"


def test_all_statuses_accepted(tmp_path):
    ss = SessionState(tmp_path / "run")
    ss.begin_phase("phase_1")
    for status in PHASE_STATUSES:
        ss.complete_phase("phase_1", status=status)


def test_resume_restores_phases(tmp_path):
    root = tmp_path / "run"
    ss1 = SessionState(root)
    ss1.begin_phase("phase_1")
    ss1.complete_phase("phase_1")
    ss1.begin_phase("phase_2")
    ss2 = SessionState(root)
    assert ss2.phase_status("phase_1") == "complete"
    assert ss2.phase_status("phase_2") == "in_progress"
    assert ss2.data["current_phase"] == "phase_2"


def test_gpu_seconds_accumulate_and_resume(tmp_path):
    root = tmp_path / "run"
    ss1 = SessionState(root, hard_budget_seconds=100)
    ss1.update_gpu_seconds(10.5)
    ss1.update_gpu_seconds(2.25)
    assert ss1.data["gpu_seconds_used"] == pytest.approx(12.75)
    ss2 = SessionState(root)
    assert ss2.data["gpu_seconds_used"] == pytest.approx(12.75)
    ss2.update_gpu_seconds(-3.0)
    assert ss2.data["gpu_seconds_used"] == pytest.approx(9.75)


def test_event_log_lines_grow(tmp_path):
    root = tmp_path / "run"
    ss = SessionState(root)
    assert not ss.events_path.exists()
    ss.begin_phase("phase_1")
    ss.complete_phase("phase_1")
    ss.update_gpu_seconds(5.0)
    lines = ss.events_path.read_text("utf-8").strip().splitlines()
    assert len(lines) == 3
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["phase_begin", "phase_end", "gpu_update"]
    ss.begin_phase("phase_2")
    assert len(ss.events_path.read_text("utf-8").strip().splitlines()) == 4


def test_complete_phase_then_begin_raises(tmp_path):
    ss = SessionState(tmp_path / "run")
    ss.begin_phase("phase_1")
    ss.complete_phase("phase_1")
    with pytest.raises(ValueError, match="already complete"):
        ss.begin_phase("phase_1")


def test_state_file_atomic_and_hard_budget(tmp_path):
    ss = SessionState(tmp_path / "run", hard_budget_seconds=12345)
    assert ss.data["hard_budget_seconds"] == 12345
    ss.begin_phase("phase_1")
    assert ss.state_path.exists()
    assert not list((tmp_path / "run").glob("*.tmp"))
