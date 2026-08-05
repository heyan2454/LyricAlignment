from copy import deepcopy
from pathlib import Path

from lyricalign.research_v7.detector_v2_coverage import (
    REQUIRED_CELLS,
    populate_status_from_artifacts,
    validate_coverage_matrix,
)


def _complete_matrix(tmp_path: Path):
    matrix = {}
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    for path in REQUIRED_CELLS:
        cursor = matrix
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = {
            "status": "complete",
            "artifact": artifact.name,
            "n_requests": 1,
        }
    return matrix


def test_complete_matrix_passes(tmp_path):
    report = validate_coverage_matrix(_complete_matrix(tmp_path), repo_root=tmp_path)
    assert report["ok"], report


def test_missing_cell_fails(tmp_path):
    matrix = _complete_matrix(tmp_path)
    del matrix["serial"]["closed_loop"]
    report = validate_coverage_matrix(matrix, repo_root=tmp_path)
    assert not report["ok"]
    assert any("serial.closed_loop" in x for x in report["errors"])


def test_forbidden_old_metric_fails(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["reports"] = {"wrong_output_recall": 1.0}
    report = validate_coverage_matrix(matrix, repo_root=tmp_path)
    assert not report["ok"]
    assert any("forbidden" in x for x in report["errors"])


def test_hidden_blocked_requires_reason_and_blocks_hidden_combinations(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["ablations"]["H"] = {"status": "blocked", "reason": "hook audit failed"}
    report = validate_coverage_matrix(matrix, repo_root=tmp_path)
    assert not report["ok"]
    assert any("cannot be complete" in x for x in report["errors"])


def test_partial_with_note_passes(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["gates"]["gt_label_audit"] = {"status": "partial", "note": "GT_LABEL_AUDIT.json found"}
    report = validate_coverage_matrix(matrix, repo_root=tmp_path, run_root=tmp_path)
    assert report["ok"], report


def test_partial_without_note_fails(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["gates"]["gt_label_audit"] = {"status": "partial"}
    report = validate_coverage_matrix(matrix, repo_root=tmp_path, run_root=tmp_path)
    assert not report["ok"]
    assert any("requires note" in x for x in report["errors"])


def test_pending_and_blocked_not_misreported_complete(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["gates"]["request_identity_audit"] = {"status": "pending"}
    matrix["stress"]["replace_1_2_4_8"] = {"status": "blocked", "reason": "budget exceeded"}
    report = validate_coverage_matrix(matrix, repo_root=tmp_path, run_root=tmp_path)
    assert report["ok"], report


def test_blocked_without_reason_fails(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["gates"]["hidden_extraction_audit"] = {"status": "blocked"}
    report = validate_coverage_matrix(matrix, repo_root=tmp_path, run_root=tmp_path)
    assert not report["ok"]
    assert any("requires reason" in x for x in report["errors"])


def test_missing_artifact_fails_with_run_root(tmp_path):
    matrix = _complete_matrix(tmp_path)
    matrix["metrics"]["tristate_unit"]["artifact"] = "missing_artifact.json"
    report = validate_coverage_matrix(matrix, repo_root=tmp_path, run_root=tmp_path)
    assert not report["ok"]
    assert any("artifact does not exist" in x for x in report["errors"])


def test_populate_status_marks_partial_from_run_root(tmp_path):
    for name in ("GT_LABEL_AUDIT.json", "REQUEST_IDENTITY_AUDIT.json", "MISSING_EXTRA_STRESS.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    matrix = {}
    for path in REQUIRED_CELLS:
        cursor = matrix
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = {"status": "pending"}
    populated = populate_status_from_artifacts(matrix, tmp_path)
    assert set(populated) == {
        "gates.gt_label_audit",
        "gates.request_identity_audit",
        "stress.missing_extra_stress",
    }
    report = validate_coverage_matrix(matrix, repo_root=tmp_path, run_root=tmp_path)
    assert report["ok"], report
    assert matrix["gates"]["gt_label_audit"]["status"] == "partial"
    assert matrix["gates"]["gt_label_audit"]["note"]
