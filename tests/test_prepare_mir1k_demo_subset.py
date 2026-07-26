from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "demo" / "prepare_mir1k_demo_subset.py"
    spec = importlib.util.spec_from_file_location("prepare_mir1k_demo_subset_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_items():
    rows = []
    for index in range(17):
        rows.append({
            "item_id": f"item{index:02d}",
            "song_id": f"s{index:02d}.wav",
            "singer_id": f"singer{index % 8}",
            "duration_sec": 30.0 + index * 3.0,
            "character_rate_per_sec": 0.5 + (index % 6) * 0.2,
            "gap_ratio": (index % 5) * 0.03,
            "mean_character_duration_sec": 0.2 + (index % 4) * 0.05,
            "coverage_ratio": 0.5 + (index % 7) * 0.05,
        })
    return rows


def test_selection_is_deterministic_and_role_counts_are_frozen() -> None:
    module = load_module()
    first = module.select_subset(fake_items(), development_count=8, heldout_count=4, seed=20260727)
    second = module.select_subset(fake_items(), development_count=8, heldout_count=4, seed=20260727)
    assert first == second
    assert sum(row["selection_role"] == "development" for row in first) == 8
    assert sum(row["selection_role"] == "heldout" for row in first) == 4
    assert sum(row["selection_role"] == "spare" for row in first) == 5
    assert any("longest" in row["selection_reasons"] for row in first if row["selection_role"] == "development")
    assert any("highest_character_rate" in row["selection_reasons"] for row in first if row["selection_role"] == "development")
