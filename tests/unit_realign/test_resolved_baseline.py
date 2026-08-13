"""Tests for the E0 resolved-baseline builder (07 plan WP1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]  # tests/unit_realign/ -> repo root
SRC = REPO / "src"
SCRIPT = REPO / "scripts" / "unit_realign" / "build_resolved_baseline.py"


def _run(tmp_path: Path) -> dict[str, dict]:
    env = dict(__import__("os").environ, PYTHONPATH=str(SRC))
    subprocess.run(
        [sys.executable, str(SCRIPT), "--out-root", str(tmp_path)],
        check=True, capture_output=True, text=True, env=env,
    )
    return {
        name: json.loads((tmp_path / name).read_text(encoding="utf-8"))
        for name in ("CURRENT_BASELINE_RESOLVED.json", "B4_BASELINE_RESOLVED.json", "BUDGET_PROJECTION.json")
    }


def test_resolved_baseline_has_required_fields_and_writeback_zero(tmp_path):
    out = _run(tmp_path)
    for role in ("current", "b4"):
        name = {"current": "CURRENT_BASELINE_RESOLVED.json", "b4": "B4_BASELINE_RESOLVED.json"}[role]
        doc = out[name]
        assert doc["actual_writeback"] == 0
        assert doc["schema_version"] == "resolved_baseline_v1"
        assert doc["cascade"]["silence_aware_window_plan"] is True
        assert doc["cascade"]["strict_silence_boundary_plan"] is False
        assert doc["cascade"]["compress_silence_audio"] is False
        assert set(doc["cascade"]) >= {
            "silence_boundary_min_sec", "strong_silence_anchor_sec",
            "silence_boundary_search_sec", "leading_silence_min_sec",
            "tail_min_core_sec", "minimum_core_sec", "core_sec",
            "left_context_sec", "right_context_sec",
        }
    # Current is full_slot + decoder raw; B4 is pre-slot serial + decoder official.
    cur = out["CURRENT_BASELINE_RESOLVED.json"]
    b4 = out["B4_BASELINE_RESOLVED.json"]
    assert cur["identity"]["request_mode"] == "full_slot"
    assert cur["identity"]["decoder_view"] == "raw"
    assert b4["identity"]["request_mode"] == "pre_slot_serial_non_slot"
    assert b4["identity"]["decoder_kind"] == "official"
    # Current runner hard-codes skip_silent=True; the serial B4 runner defaults to False
    # (align_qwen_fa_serial_demo.py --skip-silent-windows default=False). Split cascades
    # must not hide this difference (07 plan WP1 review).
    assert cur["cascade"]["skip_silent_windows"] is True
    assert b4["cascade"]["skip_silent_windows"] is False


def test_resolved_baseline_hashes_are_deterministic(tmp_path):
    a = _run(tmp_path)
    b = _run(tmp_path)
    for name in ("CURRENT_BASELINE_RESOLVED.json", "B4_BASELINE_RESOLVED.json"):
        assert a[name]["sha256"] == b[name]["sha256"], name


def test_budget_projection_within_cap(tmp_path):
    budget = _run(tmp_path)["BUDGET_PROJECTION.json"]
    assert budget["target_hours"] == 10
    assert budget["hard_cap_hours"] == 12
    # deterministic sha256 present so BUDGET can participate in artifact hashing
    assert budget["schema_version"] == "budget_projection_v1"
