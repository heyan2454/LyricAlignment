"""CPU tests for the derived-label vs TextGrid audit (Track 1 step ①)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "audit_char_labels_vs_textgrid", ROOT / "scripts" / "evaluation" / "audit_char_labels_vs_textgrid.py")
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)

GRID = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0.0
xmax = 2.0
tiers? <exists>
size = 2
item []:
item [1]:
    class = "IntervalTier"
    name = "None"
    xmin = 0.0
    xmax = 2.0
    intervals: size = 4
    intervals [1]:
        xmin = 0.0
        xmax = 0.3
        text = "<SP>"
    intervals [2]:
        xmin = 0.3
        xmax = 0.9
        text = "关"
    intervals [3]:
        xmin = 0.9
        xmax = 1.2
        text = "<AP>"
    intervals [4]:
        xmin = 1.2
        xmax = 2.0
        text = "门"
item [2]:
    class = "IntervalTier"
    name = "None"
    xmin = 0.0
    xmax = 2.0
    intervals: size = 2
    intervals [1]:
        xmin = 0.3
        xmax = 0.9
        text = "g"
    intervals [2]:
        xmin = 1.2
        xmax = 2.0
        text = "m"
'''


def test_parser_reads_every_interval_tier_in_order():
    tiers = AUDIT.parse_interval_tiers(GRID)
    assert [len(tier) for tier in tiers] == [4, 2]
    assert tiers[0][1]["text"] == "关" and tiers[0][1]["start"] == pytest.approx(0.3)
    assert tiers[1][0]["text"] == "g"


def test_character_tier_drops_both_silence_and_audible_pause():
    chars = AUDIT.character_intervals(GRID)
    assert [row["text"] for row in chars] == ["关", "门"]
    assert chars[1]["start"] == pytest.approx(1.2)


def test_derived_intervals_pair_two_class_ids_per_character():
    assert AUDIT.derived_intervals([0, 4, 4, 8], 0.08) == [(0.0, pytest.approx(0.32)), (pytest.approx(0.32), pytest.approx(0.64))]


def test_audit_pairs_only_text_matched_items_and_ignores_unmatched_ones(tmp_path: Path):
    grid_root = tmp_path / "audio"
    (grid_root / "singer#song").mkdir(parents=True)
    (grid_root / "singer#song" / "0000.TextGrid").write_text(GRID, encoding="utf-8")
    rows = [
        {"item_id": "a", "audio_relpath": "singer#song/0000.wav", "lyrics_normalized": "关门",
         "timestamp_segment_sec": 0.08, "timestamp_class_ids": [4, 11, 15, 25]},
        {"item_id": "b", "audio_relpath": "singer#song/0000.wav", "lyrics_normalized": "开门",
         "timestamp_segment_sec": 0.08, "timestamp_class_ids": [4, 11, 15, 25]},
    ]
    result = AUDIT.audit(rows, grid_root)
    assert result["counts"]["items"] == 2 and result["counts"]["paired_items"] == 1
    assert result["counts"]["text_mismatch"] == 1
    # 关 = 0.30-0.90 vs derived 0.32-0.88 -> 20ms onset, 20ms offset; 门 = 1.20-2.00 vs 1.20-2.00 -> exact
    assert result["onset_delta_sec"]["p50"] == pytest.approx(0.02, abs=1e-9)
    assert result["long_characters"]["count"] == 0          # 门 lasts 0.8s -> below the 1.0s threshold
    assert result["text_mismatch_examples"][0]["item_id"] == "b"
