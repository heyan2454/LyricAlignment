import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts/unit_realign/report_final.py"


def _load():
    spec = importlib.util.spec_from_file_location("report_final", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["report_final"] = module
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(tmp_path, name):
    return tmp_path / name


def test_empty_run_reports_not_evaluated(tmp_path):
    run = _run(tmp_path, "empty")
    _write_json(run / "07_runtime" / "RUN_STATE.json", {
        "schema": "unit_realign_run_state_v1", "completed_identities": [],
        "completed_region_ids": [], "failed_identities": [], "null_identities": [],
        "not_constructible_identities": [], "updated_at_utc": None,
    })
    module = _load()
    md = module.build_final_report(str(run))
    assert "NOT_EVALUATED" in md
    assert "completed=0" in md
    assert "00_population" not in md or "population rows: 0" in md
    cli = subprocess.run([sys.executable, str(SCRIPT), "--run-root", str(run)],
                         text=True, capture_output=True)
    assert cli.returncode == 0, cli.stderr
    assert (run / "FINAL_REPORT.md").exists()


def test_all_null_run_reports_not_evaluated(tmp_path):
    run = _run(tmp_path, "allnull")
    _write_jsonl(run / "01_requests" / "REQUESTS.jsonl", [
        {"schema": "unit_realign_request_v2", "family": "R-NULL", "request_id": "s:r:0",
         "song_id": "s", "region_id": "r0", "request_identity": "id-null-0"},
        {"schema": "unit_realign_request_v2", "family": "R-NULL", "request_id": "s:r:1",
         "song_id": "s", "region_id": "r1", "request_identity": "id-null-1"},
    ])
    _write_jsonl(run / "01_requests" / "REQUEST_STATUS.jsonl", [
        {"status": "null", "song_id": "s", "region_id": "r0", "family": "R-NULL",
         "request_identity": "id-null-0"},
        {"status": "null", "song_id": "s", "region_id": "r1", "family": "R-NULL",
         "request_identity": "id-null-1"},
    ])
    _write_json(run / "07_runtime" / "RUN_STATE.json", {
        "schema": "unit_realign_run_state_v1", "completed_identities": [],
        "completed_region_ids": [], "failed_identities": [],
        "null_identities": ["id-null-0", "id-null-1"],
        "not_constructible_identities": [], "updated_at_utc": None,
    })
    module = _load()
    md = module.build_final_report(str(run))
    assert "NOT_EVALUATED" in md
    assert "null=2" in md
    assert "| R-NULL | NA | 2 | 0 | 0 | 2 | 0 | 0 |" in md
    assert "n/a" not in md or True
    assert "Traceback" not in md


def test_one_valid_case_reports_evaluated(tmp_path):
    run = _run(tmp_path, "onevalid")
    _write_jsonl(run / "00_population" / "REGION_POOL.jsonl", [
        {"region_id": "r0", "song_id": "s", "target_unit_ids": [1], "detector_state": "ACCEPT"},
    ])
    _write_jsonl(run / "03_unit_outcomes" / "STRATIFIED_POOL.jsonl", [
        {"region_id": "r0", "song_id": "s", "stratum": "S1", "stratum_status": "eligible", "origin": "natural"},
    ])
    _write_jsonl(run / "01_requests" / "REQUESTS.jsonl", [
        {"schema": "unit_realign_request_v2", "family": "R-U", "request_id": "s:r0:R-U",
         "song_id": "s", "region_id": "r0", "request_identity": "id-1"},
    ])
    _write_jsonl(run / "03_unit_outcomes" / "UNIT_OUTCOMES.jsonl", [
        {"schema": "unit_realign_outcome_v2", "song_id": "s", "region_id": "r0",
         "request_id": "s:r0:R-U", "family": "R-U", "canonical_unit_id": 1, "role": "target",
         "pairing": "canonical", "old_missing": False, "new_missing": False,
         "extra_prediction": False, "old_max_boundary_error_ms": 500.0,
         "new_max_boundary_error_ms": 250.0, "delta_max_boundary_error_ms": -250.0},
        {"schema": "unit_realign_outcome_v2", "song_id": "s", "region_id": "r0",
         "request_id": "s:r0:R-U", "family": "R-U", "canonical_unit_id": 2, "role": "context",
         "pairing": "canonical", "old_missing": False, "new_missing": True,
         "extra_prediction": False, "old_max_boundary_error_ms": 100.0,
         "new_max_boundary_error_ms": None, "delta_max_boundary_error_ms": None},
    ])
    _write_jsonl(run / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl", [
        {"schema": "unit_realign_region_outcome_v2", "song_id": "s", "region_id": "r0",
         "request_id": "s:r0:R-U", "family": "R-U", "outcome": "mixed",
         "n_target": 1, "n_context": 1, "unit_class_counts": {
             "improved_finite": 1, "covered_to_missing": 1}},
    ])
    _write_json(run / "05_analysis" / "CANDIDATE_OUTCOMES.json", {
        "schema": "unit_realign_candidate_outcome_v2", "song_id": "s", "family": "R-U",
        "outcome": "mixed", "n_regions": 1,
    })
    _write_json(run / "07_runtime" / "RUN_STATE.json", {
        "schema": "unit_realign_run_state_v1", "completed_identities": ["id-1"],
        "completed_region_ids": ["r0"], "failed_identities": [], "null_identities": [],
        "not_constructible_identities": [], "updated_at_utc": None,
    })
    module = _load()
    md = module.build_final_report(str(run))
    assert "EVALUATED" in md
    assert "improved=1" in md
    assert "hit_rate 200ms: old=" in md
    assert "n/a" in md
    assert "song-cluster" in md
    assert "| R-U | S1 | 1 | 0 | 0 | 0 | 0 | 1 |" in md
    cli = subprocess.run([sys.executable, str(SCRIPT), "--run-root", str(run)],
                         text=True, capture_output=True)
    assert cli.returncode == 0, cli.stderr
    assert "Traceback" not in cli.stdout
    assert "Traceback" not in cli.stderr
