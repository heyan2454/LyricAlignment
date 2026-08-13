import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts/unit_realign/aggregate_classification.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("aggregate_classification", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_rows(tmp_path, rows):
    path = tmp_path / "UNIT_OUTCOMES.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def _target(cid, delta):
    return {"schema": "unit_realign_outcome_v2", "song_id": "s", "region_id": "r",
            "request_id": "q", "family": "R-S", "canonical_unit_id": cid, "role": "target",
            "old_missing": False, "new_missing": False, "extra_prediction": False,
            "delta_max_boundary_error_ms": delta, "new_max_boundary_error_ms": 0.0}


def _context(cid, delta):
    return {"schema": "unit_realign_outcome_v2", "song_id": "s", "region_id": "r",
            "request_id": "q", "family": "R-S", "canonical_unit_id": cid, "role": "context",
            "old_missing": False, "new_missing": False, "extra_prediction": False,
            "delta_max_boundary_error_ms": delta, "new_max_boundary_error_ms": 0.0}


def _extra():
    return {"schema": "unit_realign_outcome_v2", "song_id": "s", "region_id": "r",
            "request_id": "q", "family": "R-S", "canonical_unit_id": None,
            "prediction_local_index": 9, "role": "extra", "pairing": "invalid_unpairable",
            "old_missing": True, "new_missing": False, "covered_to_missing": False,
            "extra_prediction": True, "invalid_unpairable": True,
            "delta_max_boundary_error_ms": None, "new_max_boundary_error_ms": None}


def test_target_improved_fixed_context_degraded_is_mixed(tmp_path):
    mod = _load_module()
    rows = [_target(0, -500.0), _context(1, 500.0)]
    report = mod.aggregate(str(tmp_path), str(_write_rows(tmp_path, rows)))
    region = report["per_region"]["q::r"]
    assert region["outcome"] == "mixed"
    assert region["n_target_rows"] == 1
    assert region["n_context_rows"] == 1
    assert report["region_level"]["target_rows"] == 1
    assert report["region_level"]["fixed_context_rows"] == 1
    assert report["region_level"]["classification_counts"]["mixed"] == 1
    assert report["per_candidate"]["q"]["outcome"] == "mixed"


def test_target_improved_with_extra_unpairable_is_mixed_and_harmful(tmp_path):
    mod = _load_module()
    rows = [_target(0, -500.0), _extra()]
    report = mod.aggregate(str(tmp_path), str(_write_rows(tmp_path, rows)))
    region = report["per_region"]["q::r"]
    assert region["outcome"] == "mixed"
    assert region["extra_and_unpairable"]["n_extra"] == 1
    assert region["extra_and_unpairable"]["n_invalid_unpairable"] == 1
    assert region["n_target_rows"] == 1
    assert region["n_context_rows"] == 0
    assert region["n_fixed_context"] == 0
    assert region["n_extra"] == 1
    assert report["extra_and_unpairable"]["n_extra"] == 1
    assert report["per_candidate"]["q"]["outcome"] == "mixed"


def test_target_covered_to_missing_is_catastrophic_harmful(tmp_path):
    mod = _load_module()
    rows = [{"schema": "unit_realign_outcome_v2", "song_id": "s", "region_id": "r",
             "request_id": "q", "family": "R-S", "canonical_unit_id": 0, "role": "target",
             "old_missing": False, "new_missing": True, "extra_prediction": False,
             "delta_max_boundary_error_ms": None, "new_max_boundary_error_ms": None}]
    report = mod.aggregate(str(tmp_path), str(_write_rows(tmp_path, rows)))
    region = report["per_region"]["q::r"]
    assert region["outcome"] == "catastrophic_harmful"
    assert report["region_level"]["classification_counts"]["catastrophic_harmful"] == 1
    assert report["per_candidate"]["q"]["outcome"] == "catastrophic_harmful"


def test_extra_only_region_is_harmful_not_neutral(tmp_path):
    mod = _load_module()
    rows = [_extra()]
    report = mod.aggregate(str(tmp_path), str(_write_rows(tmp_path, rows)))
    assert report["per_region"]["q::r"]["outcome"] == "harmful"
