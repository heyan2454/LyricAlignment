"""Smoke tests for the one-command batch audit (synthetic batch, no real data touched)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "evaluation" / "audit_batch.py"


def _song(dirs: Path, name: str, units: list[tuple[float, float]], *, pinned: float | None) -> None:
    (dirs / name / "alignments/r2/vocal/windowed").mkdir(parents=True, exist_ok=True)
    chars = []
    for i, (st, en) in enumerate(units):
        chars.append({"character": chr(0x4E00 + i), "unit_type": "cjk_character",
                      "raw_global_start_sec": st, "raw_global_end_sec": en,
                      "fixed_global_start_sec": (pinned if pinned is not None else st),
                      "fixed_global_end_sec": (pinned if pinned is not None else en),
                      "selected_start_sec": (pinned if pinned is not None else st),
                      "selected_end_sec": (pinned if pinned is not None else en),
                      "start_sec": (pinned if pinned is not None else st),
                      "end_sec": (pinned if pinned is not None else en),
                      "raw_start_entropy": 0.2, "raw_end_entropy": 0.2})
    doc = {"identity": {"audio": {"path": "/a.wav", "sha256": "sha_" + name},
                        "request_hash": "rq_" + name, "schema_version": "sv",
                        "window": {"policy": "p", "core_sec": 60.0, "left_context_sec": 10.0,
                                   "skip_silent_windows": True}},
           "summary": {"audio_duration_sec": 20.0, "language": "Chinese"},
           "window_trace": [{"window_index": 0, "core_start_sec": 3.0, "core_end_sec": 12.0,
                             "input_start_sec": 1.0, "input_end_sec": 14.0,
                             "committed_character_start": 0, "committed_character_end": len(units)}],
           "characters": chars}
    (dirs / name / "alignments/r2/vocal/windowed/alignment.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_healthy_batch_passes(tmp_path: Path):
    good = tmp_path / "good"
    _song(good, "s1", [(0.0, 0.5), (0.6, 1.1), (1.2, 1.7)], pinned=None)
    res = subprocess.run([sys.executable, str(SCRIPT), "--batch", str(good), "--json"],
                         capture_output=True, text=True, cwd=REPO,
                         env={**dict(__import__('os').environ), "PYTHONPATH": str(REPO / "src")})
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    batch = payload["batches"][0]
    assert batch["verdict"] == "ship_ok", batch.get("blocking_checks")
    assert batch["checks"]["structural_legality"]["pass"] is True
    assert batch["units"] == 3


def test_pinned_block_is_blocked_and_attributed(tmp_path: Path):
    bad = tmp_path / "bad"
    # raw boundaries are sane; every other stage pins the block to the window input_start (1.0)
    _song(bad, "s1", [(2.0, 2.5), (3.0, 3.5), (4.0, 4.5)], pinned=1.0)
    res = subprocess.run([sys.executable, str(SCRIPT), "--batch", str(bad), "--json"],
                         capture_output=True, text=True, cwd=REPO,
                         env={**dict(__import__('os').environ), "PYTHONPATH": str(REPO / "src")})
    payload = json.loads(res.stdout)
    batch = payload["batches"][0]
    assert batch["verdict"] == "blocked"
    assert "structural_legality" in batch["blocking_checks"]
    assert "window_anchor_pinning" in batch["blocking_checks"]
    # the stage gate must name `fixed` as the stage that created the degeneracy
    assert batch["checks"]["stage_attribution"]["value"]["worst_stage"] == "net_added_by_fixed"
    # and the repair checker still proves legality is reachable
    assert batch["checks"]["repair_feasibility"]["value"]["post_repair_illegal_share"] == 0.0


def test_pairwise_gate_reports_duplicate_configuration(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        _song(d, "s1", [(0.0, 0.5), (0.6, 1.1)], pinned=None)
    res = subprocess.run([sys.executable, str(SCRIPT), "--batch", str(a), "--compare-batch", str(b),
                          "--json"], capture_output=True, text=True, cwd=REPO,
                         env={**dict(__import__('os').environ), "PYTHONPATH": str(REPO / "src")})
    payload = json.loads(res.stdout)
    # these two batches share audio sha *and* request hash, i.e. they are literally the same run,
    # which the stricter `not_identified` branch catches before `duplicate_configuration`
    assert payload["pairwise"]["verdict"] in {"not_identified", "duplicate_configuration"}
    assert payload["pairwise"]["outputs_identical_share"] == 1.0
    assert payload["pairwise"]["same_window_plan_share"] == 1.0
