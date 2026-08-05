from copy import deepcopy
from pathlib import Path

from lyricalign.research_v7.detector_v2_coverage import REQUIRED_CELLS, validate_coverage_matrix


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
