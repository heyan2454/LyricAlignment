from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.training.qwen_fa_labels import build_supervision_labels, labels_for_intervals, quantize_time


def test_quantization_is_round_half_up_and_bounds_checked() -> None:
    assert quantize_time(0.04, segment_sec=0.08, num_labels=10) == 1
    assert quantize_time(0.039, segment_sec=0.08, num_labels=10) == 0
    with pytest.raises(ValueError, match="out of range"):
        quantize_time(1.0, segment_sec=0.08, num_labels=10)


def test_timestamp_labels_occupy_only_timestamp_slots() -> None:
    torch = pytest.importorskip("torch")
    ids = torch.tensor([4, 99, 7, 99, 8, 99, 99])
    labels = build_supervision_labels(ids, timestamp_token_id=99, class_ids=[1, 2, 3, 4])
    assert labels.tolist() == [-100, 1, -100, 2, -100, 3, 4]
    with pytest.raises(ValueError, match="count mismatch"):
        build_supervision_labels(ids, timestamp_token_id=99, class_ids=[1])


def test_interval_labels_require_contiguous_monotonic_characters() -> None:
    rows = [
        {"item_id": "x", "character_index": 0, "start_sec": 0.0, "end_sec": 0.08},
        {"item_id": "x", "character_index": 1, "start_sec": 0.08, "end_sec": 0.16},
    ]
    assert labels_for_intervals(rows, segment_sec=0.08, num_labels=10) == [0, 1, 1, 2]
    with pytest.raises(ValueError, match="non-contiguous"):
        labels_for_intervals([dict(rows[0], character_index=2)], segment_sec=0.08, num_labels=10)
