from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "scripts/evaluation/collect_qwen_fa_immediate_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("immediate_collector", COLLECTOR_PATH)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def test_official_fix_timestamp_matches_lis_neighbor_repair() -> None:
    assert collector.official_fix_timestamp([0, 80, 40, 160]) == [0, 80, 80, 160]
    assert collector.official_fix_timestamp([0, 80, 160]) == [0, 80, 160]


def test_time_coverage_bins_timestamp_slots(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "item_id": "a",
                "split": "train",
                "character_count": 2,
                "timestamp_segment_sec": 0.08,
                "timestamp_class_ids": [0, 1, 375, 376],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "coverage.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/evaluation/analyze_qwen_fa_time_coverage.py"),
            "--dataset",
            f"toy::{labels}::train",
            "--out",
            str(out),
        ],
        check=True,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["datasets"]["toy"]["timestamp_slot_count"] == 4
    assert data["datasets"]["toy"]["time_bins"]["000-030"]["count"] == 2
    assert data["datasets"]["toy"]["time_bins"]["030-060"]["count"] == 2
