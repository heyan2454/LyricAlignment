import json
import os

import pytest

from scripts.unit_realign.audit_round2_gates import audit_gates


@pytest.fixture
def run_root(tmp_path):
    behavior = tmp_path / "02_behavior"
    behavior.mkdir(parents=True)
    acc = {
        "status": "done",
        "eligible": {"S1": 150, "S2": 150, "S3": 150, "S4": 50, "SG": 0},
        "attempts": [{"selected": 250}],
    }
    (behavior / "SAMPLE_ACCOUNTING.json").write_text(json.dumps(acc), encoding="utf-8")
    pool = tmp_path / "05_analysis"
    pool.mkdir()
    (pool / "STRATIFIED_POOL.jsonl").write_text(
        json.dumps({"baseline_available": True, "ineligible": False}) + "\n"
        + json.dumps({"baseline_available": True, "ineligible": True}) + "\n",
        encoding="utf-8",
    )
    return str(tmp_path)


def test_audit_marks_exploratory_only(run_root):
    report = audit_gates(run_root)
    assert report["exploratory_only"] is True


def test_audit_marks_round2_gate_pass_without_exploratory_flag_semantics(run_root):
    report = audit_gates(run_root)
    assert report["round2_gate_pass"] is False
    assert report["eligible"]["total"] == 500
    assert report["selected_requests"] == 250
    assert report["eligible"]["pool"]["n_baseline_valid"] == 1
