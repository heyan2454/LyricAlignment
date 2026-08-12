"""Tests for realign_gate.report (05_report stage).

Pure functions over fake stage JSON/JSONL (flat schema matching real stage
artifacts); no GPU/real model dependency.
"""

from __future__ import annotations

import json

from lyricalign.realign_gate.report import build_final_report, load_stage_json, run_stage


def _write_jsonl(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_fake_run(tmp_path, *, smoke=False):
    run = tmp_path / "run"
    stages = [
        "00_inventory",
        "01_detector_audit",
        "02_behavior",
        "03_gate",
        "04_test_demo",
        "05_report",
        "00_meta",
    ]
    for stage in stages:
        (run / stage).mkdir(parents=True, exist_ok=True)

    (run / "00_inventory" / "DATA_INVENTORY.json").write_text(
        json.dumps(
            {
                "schema": "realign_gate_00_inventory_v1",
                "result_status": "ok",
                "real_gt_summary": {
                    "n_songs": 5,
                    "accepted_units": 4098,
                    "n_unlabeled_total": 182,
                    "unlabeled_by_reason": {"review_status": 182},
                },
                "constructible_windows": {
                    "n_songs": 5,
                    "constructible_windows": 12,
                },
                "demo_summary": {"n_items": 4, "by_language": {"chinese": 4}},
            }
        )
    )
    (run / "01_detector_audit" / "RAW_UNIT_METRICS.json").write_text(
        json.dumps(
            {
                "schema": "realign_gate_01_detector_audit_v1",
                "result_status": "ok",
                "requested_limit": 20 if smoke else 0,
                "full_population_size": 988,
                "evaluated_count": 20 if smoke else 988,
                "is_smoke": smoke,
                "production_audit_complete": (not smoke),
                "n_requests": 988,
                "n_hits": 988,
                "n_missing": 0,
                "missing_request_ids": [],
                "tri_unit_metrics": {
                    "per_song": {},
                    "pooled": {
                        "n_units": 761,
                        "n_accept": 685,
                        "n_uncertain": 3,
                        "n_reject": 73,
                        "accept_ratio": 0.9,
                        "uncertain_ratio": 0.0039,
                        "reject_ratio": 0.0959,
                    },
                },
                "historical_bridge": {
                    "frozen_val": {
                        "safe_accept_rate": 0.8689,
                        "protected_recall_95": 0.6552,
                        "n_val_units": 761,
                    },
                    "retrospective": {"status": "not_reproduced_source_missing"},
                },
            }
        )
    )
    (run / "01_detector_audit" / "RAW_WINDOW_METRICS.json").write_text(
        json.dumps(
            {
                "schema": "realign_gate_01_detector_audit_v1",
                "result_status": "ok",
                "requested_limit": 20 if smoke else 0,
                "full_population_size": 988,
                "evaluated_count": 20 if smoke else 988,
                "is_smoke": smoke,
                "production_audit_complete": (not smoke),
                "interval_metrics": {
                    "per_song": {},
                    "pooled": {
                        "n_windows": 12,
                        "n_unsafe_windows": 3,
                        "n_safe_windows": 9,
                        "unsafe_trigger_rate": 0.25,
                        "n_unsafe_intervals_total": 7,
                    },
                },
                "trigger_identity": {},
            }
        )
    )
    _write_jsonl(run / "02_behavior" / "CASES.jsonl", [{"case_id": i} for i in range(3)])
    _write_jsonl(run / "02_behavior" / "REQUESTS.jsonl", [{"request_id": i} for i in range(6)])
    _write_jsonl(
        run / "02_behavior" / "CANDIDATE_INDEX.jsonl", [{"request_id": i} for i in range(5)]
    )
    _write_jsonl(
        run / "03_gate" / "GT_PAIR_METRICS.jsonl",
        [
            {"case_id": i, "delta_error_ms": -250.0, "label": "improve"}
            for i in range(4)
        ]
        + [
            {"case_id": 10 + i, "delta_error_ms": 300.0, "label": "harm"}
            for i in range(1)
        ]
        + [
            {"case_id": 20 + i, "delta_error_ms": 10.0, "label": "neutral"}
            for i in range(5)
        ],
    )
    _write_jsonl(run / "03_gate" / "NO_GT_FEATURES.jsonl", [{"row": i} for i in range(8)])
    (run / "03_gate" / "ANALYSIS.json").write_text(
        json.dumps(
            {
                "schema": "realign_gate_analysis_v1",
                "result_status": "ok",
                "suggestion": "ACCEPT_WRITEBACK",
                "suggestion_note": "offline gate recommends ACCEPT_WRITEBACK (no actual writeback)",
                "splits": {
                    "dev_ratio": 0.7,
                    "seed": 42,
                    "n_dev_songs": 4,
                    "n_holdout_songs": 1,
                    "n_dev_rows": 7,
                    "n_holdout_rows": 3,
                },
                "metrics": {
                    "dev": {
                        "auroc_delta": 0.8,
                        "auroc_nbig": 0.75,
                        "auprc_delta": 0.7,
                        "n": 7,
                    },
                    "holdout": {
                        "auroc_delta": 0.72,
                        "auroc_nbig": 0.7,
                        "auprc_delta": 0.5,
                        "harm_rate": 0.2,
                        "n": 3,
                    },
                },
                "harmful_risk_writeback_holdout": 0.2,
                "n_counterexamples": 0,
                "n_ambiguous": 0,
                "duplicate_keys": {"gt_pair_metrics": 0, "no_gt_features": 0},
            }
        )
    )
    (run / "04_test_demo" / "TEST_DEMO_DETECTOR_SUMMARY.json").write_text(
        json.dumps(
            {
                "schema": "TEST_DEMO_DETECTOR_SUMMARY_v1",
                "no_gt": True,
                "n_items": 4,
                "n_failed": 0,
                "detector": {"kind": "standardized_logistic", "combo": "R", "merge": "light_merge"},
                "per_song": [{"item": "a", "suspicious_score": 1.0}],
                "ranking": ["a"],
                "failed": [],
            }
        )
    )
    _write_jsonl(
        run / "04_test_demo" / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl", [{"row": i} for i in range(6)]
    )
    (run / "00_meta" / "CONFIG.json").write_text(
        json.dumps(
            {
                "frozen_identity": {
                    "model_id": "Qwen3-ForcedAligner-0.6B-hf",
                    "model_revision": "c07281df",
                    "checkpoint_id": "r2-step-000750",
                    "detector_kind": "standardized_logistic_raw",
                    "T_accept": 0.165,
                    "T_reject": 0.168,
                },
                "constraints": {"actual_writeback": 0, "no_gt_control": True},
            }
        )
    )
    return run


def test_load_stage_json_missing_returns_none(tmp_path):
    run = _make_fake_run(tmp_path)
    assert load_stage_json(run, "00_inventory/NOPE.json") is None
    assert load_stage_json(run, "missing_stage/whatever.json") is None
    assert load_stage_json(run / "nope", "x.json") is None


def test_build_final_report_numbers_from_files(tmp_path):
    run = _make_fake_run(tmp_path)
    result = build_final_report(run)
    summary = result["final_summary"]
    audit = summary["sections"]["production_detector_audit"]
    assert audit["safe_accept_rate"] == 0.9
    assert audit["hist_safe_accept"] == 0.8689
    assert audit["retro_status"] == "not_reproduced_source_missing"
    assert audit["is_smoke"] is False
    assert audit["production_audit_complete"] is True
    assert audit["n_songs"] == 5
    gate = summary["sections"]["no_gt_gate_signal"]
    assert gate["net_improved_count"] == 3
    assert gate["net_improved_ratio"] == 0.3
    assert gate["decision"] == "ACCEPT_WRITEBACK"
    assert summary["sections"]["gt_realign_behavior"]["n_cases"] == 3
    assert summary["sections"]["test_demo_stress"]["n_items"] == 4
    assert summary["result_status"] == "ok"
    assert summary["smoke"] is False

    (run / "01_detector_audit" / "RAW_UNIT_METRICS.json").write_text(
        json.dumps(
            {
                "schema": "realign_gate_01_detector_audit_v1",
                "result_status": "ok",
                "requested_limit": 0,
                "is_smoke": False,
                "production_audit_complete": True,
                "n_requests": 988,
                "n_hits": 988,
                "n_missing": 0,
                "tri_unit_metrics": {
                    "per_song": {},
                    "pooled": {
                        "n_units": 761,
                        "accept_ratio": 0.75,
                        "uncertain_ratio": 0.0,
                        "reject_ratio": 0.25,
                    },
                },
                "historical_bridge": {
                    "frozen_val": {
                        "safe_accept_rate": 0.9,
                        "protected_recall_95": 0.5,
                        "n_val_units": 100,
                    },
                    "retrospective": {"status": "not_reproduced_source_missing"},
                },
            }
        )
    )
    result2 = build_final_report(run)
    audit2 = result2["final_summary"]["sections"]["production_detector_audit"]
    assert audit2["safe_accept_rate"] == 0.75
    assert audit2["hist_safe_accept"] == 0.9
    assert "0.7500" in result2["report_markdown"]
    assert "0.8689" not in result2["report_markdown"]


def test_markdown_contains_four_section_headings(tmp_path):
    run = _make_fake_run(tmp_path)
    md = build_final_report(run)["report_markdown"]
    for heading in [
        "## 1. Production Detector Audit",
        "## 2. GT Realign Behavior",
        "## 3. No-GT Gate Signals",
        "## 4. Test Demo Stress",
    ]:
        assert heading in md


def test_shadow_actual_writeback_noted(tmp_path):
    run = _make_fake_run(tmp_path)
    md = build_final_report(run)["report_markdown"]
    assert "actual_writeback=0" in md
    assert "NOT stateful recovery" in md


def test_holdout_weak_not_freeze_writeback_gate(tmp_path):
    run = _make_fake_run(tmp_path)
    analysis_path = run / "03_gate" / "ANALYSIS.json"
    data = json.loads(analysis_path.read_text())
    data["metrics"]["holdout"]["auroc_delta"] = None
    data["metrics"]["holdout"]["n"] = 0
    analysis_path.write_text(json.dumps(data))
    summary = build_final_report(run)["final_summary"]
    assert summary["conclusion"]["writeback_gate"] == "NOT_FROZEN"
    assert "holdout" in summary["conclusion"]["reason"]

    data["metrics"]["holdout"]["auroc_delta"] = 0.8
    data["metrics"]["holdout"]["n"] = 3
    data["harmful_risk_writeback_holdout"] = 0.9
    analysis_path.write_text(json.dumps(data))
    summary2 = build_final_report(run)["final_summary"]
    assert summary2["conclusion"]["writeback_gate"] == "NOT_FROZEN"
    assert "harmful" in summary2["conclusion"]["reason"]


def test_missing_stage_incomplete_no_crash(tmp_path):
    run = _make_fake_run(tmp_path)
    (run / "04_test_demo" / "TEST_DEMO_DETECTOR_SUMMARY.json").unlink()
    (run / "04_test_demo" / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl").unlink()
    result = build_final_report(run)
    summary = result["final_summary"]
    assert summary["result_status"] == "incomplete"
    assert summary["sections"]["test_demo_stress"]["status"] == "incomplete"
    assert "incomplete" in result["report_markdown"]


def test_run_stage_writes_files(tmp_path):
    run = _make_fake_run(tmp_path)
    summary = run_stage(run)
    assert (run / "05_report" / "FINAL_REPORT.md").exists()
    assert (run / "05_report" / "FINAL_SUMMARY.json").exists()
    assert summary["result_status"] == "ok"
    saved = json.loads((run / "05_report" / "FINAL_SUMMARY.json").read_text())
    assert saved["sections"]["no_gt_gate_signal"]["net_improved_count"] == 3


def test_smoke_run_marked_partial(tmp_path):
    """B9: limited audit run must surface smoke + partial in title/summary."""
    run = _make_fake_run(tmp_path, smoke=True)
    result = build_final_report(run)
    summary = result["final_summary"]
    assert summary["smoke"] is True
    assert summary["requested_limit"] == 20
    assert summary["production_audit_complete"] is False
    assert summary["result_status"] == "ok_smoke_partial"
    audit = summary["sections"]["production_detector_audit"]
    assert audit["is_smoke"] is True
    assert audit["evaluated_count"] == 20
    md = result["report_markdown"]
    assert "SMOKE / PARTIAL" in md
    assert "requested_limit=20" in md
    assert "NOT a production audit conclusion" in md
