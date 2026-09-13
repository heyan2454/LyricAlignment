from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "exposure_response_fit", ROOT / "scripts" / "evaluation" / "exposure_response_fit.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_fit_recovers_a_known_power_law():
    exposure = {"0-0.25s": 0.50, "0.25-0.5s": 0.25, "0.5-1s": 0.125, "1-2s": 0.0625, "2s+": 0.03125}
    # miss = 0.02 * exposure ** -0.5  =>  exponent must come back as -0.5
    miss = {name: 0.02 * value ** -0.5 for name, value in exposure.items()}
    fitted = MODULE.fit(exposure, miss)
    assert fitted["status"] == "fitted" and fitted["n_buckets"] == 5
    assert abs(fitted["exponent"] + 0.5) < 1e-6
    assert abs(fitted["correlation"] + 1.0) < 1e-6      # 完美负相关
    assert fitted["slope_se"] < 1e-6


def test_fit_refuses_thin_and_zero_inflated_inputs():
    assert MODULE.fit({"0-0.25s": 0.5, "0.25-0.5s": 0.5}, {"0-0.25s": 0.01, "0.25-0.5s": 0.02})["status"] == "insufficient_data"
    # a bucket with zero misses cannot be log-fitted -> it is dropped, leaving 2 points -> insufficient
    exposure = {"a-0.25s": 0.4, "0.25-0.5s": 0.3, "0.5-1s": 0.2, "1-2s": 0.1}
    miss = {"0.25-0.5s": 0.0, "0.5-1s": 0.02, "1-2s": 0.05}
    assert MODULE.fit(exposure, miss)["status"] == "insufficient_data"


def test_prediction_uses_the_share_multiplier_not_the_item_multiplier():
    exposure = {"0-0.25s": 0.5, "0.25-0.5s": 0.3, "1-2s": 0.15, "2s+": 0.05}
    miss = {"0-0.25s": 0.01, "0.25-0.5s": 0.02, "1-2s": 0.06, "2s+": 0.10}
    fitted = MODULE.fit(exposure, miss)
    prediction = MODULE.predict(fitted, exposure, miss, gain_by_bucket={"2s+": 2.0})
    block = prediction["2s+"]
    assert block["miss_predicted"] == round(0.10 * 2.0 ** fitted["exponent"], 4)
    assert block["band_95"][0] <= block["miss_predicted"] <= block["band_95"][1]


def test_item_stats_counts_characters_not_just_items(tmp_path: Path):
    rows = [
        {"split": "train", "timestamp_segment_sec": 0.08, "timestamp_class_ids": [0, 20, 20, 25]},   # 1.6s 长
        {"split": "train", "timestamp_segment_sec": 0.08, "timestamp_class_ids": [0, 5, 5, 9]},       # 全短
        {"split": "validation", "timestamp_class_ids": [0, 40]},
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    counts = MODULE._item_stats(path, "train", 1.0)
    assert counts["items_total"] == 2 and counts["items_with_long"] == 1
    assert counts["characters_total"] == 4 and counts["characters_in_long_items"] == 2
