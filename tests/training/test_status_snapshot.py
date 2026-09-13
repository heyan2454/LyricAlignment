"""CPU tests for the one-screen status snapshot helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("status_snapshot", ROOT / "scripts" / "training" / "status_snapshot.py")
assert SPEC and SPEC.loader
SNAPSHOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SNAPSHOT)


def test_read_jsonl_skips_blank_and_malformed_lines(tmp_path: Path):
    path = tmp_path / "metrics.jsonl"
    path.write_text('{"step": 1}\n\n{"step": 2}\n{oops\n', encoding="utf-8")
    assert [row["step"] for row in SNAPSHOT.read_jsonl(path)] == [1, 2]
    assert SNAPSHOT.read_jsonl(tmp_path / "missing.jsonl") == []


def test_process_status_reports_none_for_a_run_that_is_not_running(tmp_path: Path):
    pid, elapsed = SNAPSHOT.process_status(tmp_path / "definitely-not-a-run")
    assert pid in {"none", "unknown"} and isinstance(elapsed, str)
