"""Phase 0 GT firewall tests (A2): no-GT control, oracle no-timestamp, read-only evaluator."""

from __future__ import annotations

import copy
import json

import pytest

from lyricalign.realign_recovery import gt_firewall, SCHEMA_VERSION

CONTROL_SPEC = {
    "request": {"song_id": "demo_001", "language": "zh"},
    "audio_path": "runs/demo_001/vocal.wav",
    "text": "歌词文本",
    "raw_output_dir": "runs/demo_001/raw",
}


def test_validate_no_gt_rejects_gt_fields():
    for bad in ("gt", "gt_path", "timeline_gt", "gt_timestamps"):
        spec = dict(CONTROL_SPEC)
        spec[bad] = "some/gt/file.json"
        assert gt_firewall.validate_no_gt_request(spec) == [bad]


def test_validate_no_gt_rejects_prefix_and_substring():
    assert gt_firewall.validate_no_gt_request({"gt_char_times": []}) == ["gt_char_times"]
    assert gt_firewall.validate_no_gt_request({"my_gt_path": "x"}) == ["my_gt_path"]
    assert gt_firewall.validate_no_gt_request({"gt_timestamp": 1.0}) == ["gt_timestamp"]


def test_validate_no_gt_accepts_clean_control_spec():
    assert gt_firewall.validate_no_gt_request(CONTROL_SPEC) == []


def test_runner_rejects_gt_and_never_runs():
    spec = dict(CONTROL_SPEC)
    spec["gt"] = "runs/demo_001/gt.json"
    with pytest.raises(ValueError):
        gt_firewall.NoGTControlRunner(spec, "runs/demo_001/raw")


def test_runner_run_succeeds_with_clean_spec_and_schema():
    runner = gt_firewall.NoGTControlRunner(CONTROL_SPEC, "runs/demo_001/raw")
    artifact = runner.run()
    assert artifact["schema"] == SCHEMA_VERSION
    assert artifact["raw_output_path"].endswith("raw_output.json")
    assert artifact["writeback_state"]["actual_writeback"] == 0
    assert artifact["request_identity"]
    assert "gt" not in artifact
    json.dumps(artifact)


def test_fake_backend_proves_no_gt_object_or_path_observed():
    trace: list[str] = []
    runner = gt_firewall.NoGTControlRunner(CONTROL_SPEC, "runs/demo_001/raw", _fs_trace=trace)
    artifact = runner.run()
    assert trace
    assert not any("gt" in t.lower() for t in trace)
    assert not any("gt" in k.lower() for k in artifact)


def test_oracle_spec_rejects_character_timestamps():
    for bad in ("char_times", "char_start_sec", "char_end_sec", "gt_decoder_correction", "gt_timestamp"):
        spec = {"audio_span": [0.0, 60.0], bad: []}
        assert bad in gt_firewall.validate_oracle_spec(spec)


def test_oracle_spec_accepts_audio_and_text_span():
    spec = {"audio_span": [0.0, 60.0], "text_span": [0, 10], "unit_ids": ["u1", "u2"]}
    assert gt_firewall.validate_oracle_spec(spec) == []


def test_evaluator_produces_metrics_without_mutating_artifact():
    runner = gt_firewall.NoGTControlRunner(CONTROL_SPEC, "runs/demo_001/raw")
    artifact = runner.run()
    before = copy.deepcopy(artifact)
    binding = {"expected": "runs/demo_001/raw/raw_output.json"}
    result = gt_firewall.Evaluator(artifact, binding).evaluate()
    assert result["metrics"]["correct"] == 1
    assert result["metrics"]["schema"] == SCHEMA_VERSION
    assert result == {**artifact, "metrics": result["metrics"]}
    assert artifact == before


def test_evaluator_reports_wrong_fields_on_missing_gt_binding():
    artifact = gt_firewall.NoGTControlRunner(CONTROL_SPEC, "runs/demo_001/raw").run()
    result = gt_firewall.Evaluator(artifact, {"expected": None}).evaluate()
    assert result["metrics"]["correct"] == 0
    assert "raw_output_path" in result["metrics"]["wrong_fields"]
