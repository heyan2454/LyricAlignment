from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate


def rows() -> list[dict]:
    return [
        {"item_id": "song", "character_index": 0, "normalized_character": "你", "start_sec": 0.0, "end_sec": 1.0},
        {"item_id": "song", "character_index": 1, "normalized_character": "好", "start_sec": 1.0, "end_sec": 2.0},
    ]


def test_perfect_and_global_shift_fixture() -> None:
    perfect = evaluate(rows(), rows())
    assert perfect["mean_iou"] == 1.0 and perfect["boundary_mae_sec"] == 0.0
    shifted = [dict(row, start_sec=row["start_sec"] + 0.5, end_sec=row["end_sec"] + 0.5) for row in rows()]
    result = evaluate(rows(), shifted)
    assert result["boundary_mae_sec"] == 0.5
    assert result["mean_iou"] == pytest.approx(1 / 3)


def test_missing_duplicate_zero_duration_and_reverse_order_hard_fail() -> None:
    with pytest.raises(ValueError, match="key mismatch"):
        evaluate(rows(), rows()[:1])
    duplicate = rows() + [dict(rows()[0])]
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(rows(), duplicate)
    zero = rows(); zero[0]["end_sec"] = 0.0
    with pytest.raises(ValueError, match="invalid interval"):
        evaluate(rows(), zero)
    reverse = rows(); reverse[1]["start_sec"] = 0.5; reverse[1]["end_sec"] = 0.8
    with pytest.raises(ValueError, match="reverse order"):
        evaluate(rows(), reverse)


def test_overlap_is_reported_but_not_misclassified_as_reverse_order() -> None:
    overlapping = rows()
    overlapping[1]["start_sec"] = 0.5
    result = evaluate(overlapping, overlapping)
    assert result["reference_adjacent_overlap_count"] == 1
