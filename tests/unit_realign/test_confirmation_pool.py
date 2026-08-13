import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts/unit_realign/materialize_no_gt_confirmation_pool.py"
_spec = importlib.util.spec_from_file_location("materialize_no_gt_confirmation_pool", _SCRIPT)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
partition_eligible = module.partition_eligible
choose = module.choose
build_case = module.build_case


def _region(song, window, region_id, targets, interval, detector_state="UNSAFE", baseline_available=True):
    return {
        "region_id": region_id, "song_id": song, "window_index": window,
        "target_unit_ids": targets, "detector_state": detector_state,
        "seed_kind": "unsafe_region", "overlap_interval_sec": interval,
        "baseline_available": baseline_available,
    }


def test_choose_dedupes_target_unit_across_windows():
    candidates = [
        _region("s", 0, "a", [3], [0.0, 1.0]),
        _region("s", 1, "b", [3], [2.0, 3.0]),
        _region("s", 2, "c", [4], [4.0, 5.0]),
    ]
    selected, excluded, _ = choose(candidates, count=3, cap=5, seed=0)
    assert len(selected) == 2
    assert [row["region_id"] for row in selected] == ["a", "c"]
    reasons = [row["exclusion_reason"] for row in excluded]
    assert reasons.count("duplicate_target_unit") == 1


def test_choose_excludes_same_song_time_overlap():
    candidates = [
        _region("s", 0, "a", [1], [0.0, 2.0]),
        _region("s", 0, "b", [2], [1.0, 3.0]),
        _region("s", 1, "c", [3], [4.0, 5.0]),
    ]
    selected, excluded, _ = choose(candidates, count=3, cap=5, seed=0)
    assert len(selected) == 2
    reasons = [row["exclusion_reason"] for row in excluded]
    assert reasons.count("time_overlap") == 1


def test_choose_time_overlap_is_song_scoped():
    candidates = [
        _region("s1", 0, "a", [1], [0.0, 2.0]),
        _region("s2", 0, "b", [1], [0.5, 1.5]),
        _region("s1", 1, "c", [2], [3.0, 4.0]),
    ]
    selected, excluded, _ = choose(candidates, count=3, cap=5, seed=0)
    assert len(selected) == 3  # different song may overlap
    assert not excluded


def test_partition_eligible_excludes_invalid_baseline_interval():
    zero_length = _region("s", 0, "a", [1], [1.0, 1.0])
    inverted = _region("s", 0, "b", [1], [3.0, 1.0])
    missing = _region("s", 0, "c", [1], None)
    ok = _region("s", 0, "d", [1], [0.0, 1.0])
    eligible, excluded = partition_eligible([zero_length, inverted, missing, ok])
    assert [row["region_id"] for row in eligible] == ["d"]
    assert all(row["exclusion_reason"] == "ineligible_invalid_baseline_interval" for row in excluded)
    assert len(excluded) == 3


def test_choose_skips_invalid_baseline_as_ineligible():
    candidates = [
        _region("s", 0, "bad", [1], [1.0, 1.0]),
        _region("s", 0, "ok", [2], [0.0, 1.0]),
    ]
    selected, excluded, _ = choose(candidates, count=2, cap=5, seed=0)
    assert [row["region_id"] for row in selected] == ["ok"]
    assert excluded[0]["exclusion_reason"] == "ineligible_invalid_baseline_interval"


def test_build_case_writes_explicit_roles_and_context():
    region = _region("s", 0, "r", [3], [1.0, 2.0])
    detector = {"units": {
        "1": {"state": "ACCEPT", "start_sec": 0.0, "end_sec": 1.0, "p_bad": 0.1},
        "2": {"state": "ACCEPT", "start_sec": 1.0, "end_sec": 2.0, "p_bad": 0.1},
        "3": {"state": "REJECT", "start_sec": 2.0, "end_sec": 3.0, "p_bad": 0.9},
        "4": {"state": "ACCEPT", "start_sec": 3.0, "end_sec": 4.0, "p_bad": 0.1},
    }}
    case = build_case(region, detector, outside_unit_ids=[9, 10])
    assert case["active_target_unit_ids"] == [3]
    assert case["target_unit_ids"] == [3]
    assert case["fixed_context_unit_ids"] == [1, 2, 4]
    assert case["outside_unit_ids"] == [9, 10]
    assert case["baseline_audio_range_sec"] == [1.0, 2.0]
    assert case["old_units_scope"] == "whole_window_reference_not_target_or_context"
    assert {int(x["canonical_unit_id"]) for x in case["old_units"]} == {1, 2, 3, 4}


def test_main_audit_reports_excluded_and_eligible(tmp_path):
    shadow = tmp_path / "shadow.jsonl"
    shadow.write_text(json.dumps({"song_id": "s", "window_index": 0, "detector_shadow": {
        "units": {"1": {"state": "ACCEPT", "start_sec": 0.0, "end_sec": 1.0},
                  "2": {"state": "REJECT", "start_sec": 1.0, "end_sec": 2.0},
                  "3": {"state": "REJECT", "start_sec": 2.0, "end_sec": 3.0}}},
    }) + "\n")
    regions = tmp_path / "regions.jsonl"
    rows = [
        _region("s", 0, "r1", [2], [1.0, 2.0]),
        _region("s", 0, "r2", [3], [2.0, 3.0]),
        _region("s", 0, "bad", [2], [2.0, 2.0], baseline_available=False),
    ]
    regions.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "pool.jsonl"
    env = {"PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    import os
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--regions", str(regions), "--shadow", str(shadow),
         "--out", str(out), "--unsafe-count", "2", "--accept-count", "0"],
        text=True, capture_output=True, env={**os.environ, **env})
    assert proc.returncode == 0, proc.stderr
    audit = json.loads((tmp_path / "CONFIRMATION_POOL_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["eligible_total"] == 2
    assert audit["excluded_total"] == 1
    assert audit["excluded_by_reason"]["ineligible_invalid_baseline_interval"] == 1
    assert len(audit["excluded"]) == 1
    cases = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(cases) == 2
    assert all("active_target_unit_ids" in case and "fixed_context_unit_ids" in case for case in cases)
