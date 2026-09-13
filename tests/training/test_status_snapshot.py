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


def test_match_process_ignores_shells_that_only_mention_the_command(tmp_path):
    from pathlib import Path
    run = tmp_path / "runs" / "arm"
    lines = [
        # a queued launcher whose command text contains everything: must NOT match
        " 999 100 bash -c cat <<EOF python scripts/training/run_qwen_fa_lora.py --run-dir "
        + str(run) + " EOF",
        # the real trainer
        " 474070 2700 python scripts/training/run_qwen_fa_lora.py --config c.yaml --run-dir "
        + str(run) + " --stage r2",
    ]
    assert SNAPSHOT.match_process(lines, Path(run)) == ("474070", "0.75h")
    assert SNAPSHOT.match_process([lines[0]], Path(run)) == ("none", "-")


def test_match_process_requires_the_exact_run_dir(tmp_path):
    from pathlib import Path
    other = tmp_path / "runs" / "other_arm"
    wanted = tmp_path / "runs" / "arm"
    line = " 1 10 python run_qwen_fa_lora.py --run-dir " + str(other)
    assert SNAPSHOT.match_process([line], Path(wanted)) == ("none", "-")
