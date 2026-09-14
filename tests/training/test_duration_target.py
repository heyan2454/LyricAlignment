from __future__ import annotations

import numpy as np
import pytest
import torch

from lyricalign.training.qwen_fa_labels import (
    IGNORE_INDEX, absolute_ends_from_duration_slots, build_supervision_labels, duration_target_class_ids)


def test_duration_target_rewrites_only_the_second_slot_and_round_trips():
    class_ids = [10, 14, 20, 45, 50, 52]        # durations 4, 25, 2 bins
    converted = duration_target_class_ids(class_ids, num_classes=5000)
    assert converted == [10, 4, 20, 25, 50, 2]
    ends = absolute_ends_from_duration_slots(converted, segment_sec=0.08)
    assert ends == pytest.approx([1.12, 3.60, 4.16])   # (start+dur)*step == 原 end*step
    assert ends == pytest.approx([14 * 0.08, 45 * 0.08, 52 * 0.08])


def test_non_positive_and_overflowing_durations_are_clamped_not_dropped():
    converted = duration_target_class_ids([30, 30, 0, 4999], num_classes=5000)
    assert converted[1] == 1                       # 零时长抬到 1 个 bin
    assert converted[3] == 4999                    # 超长被夹到上界，不静默丢标签


def test_absolute_mode_is_byte_identical_to_previous_behaviour():
    input_ids = torch.tensor([1, 999, 2, 999, 3])
    class_ids = [11, 14]
    absolute = build_supervision_labels(input_ids, timestamp_token_id=999, class_ids=class_ids)
    explicit = build_supervision_labels(input_ids, timestamp_token_id=999, class_ids=class_ids,
                                        target="absolute")
    assert torch.equal(absolute, explicit)
    assert absolute.tolist() == [IGNORE_INDEX, 11, IGNORE_INDEX, 14, IGNORE_INDEX]


def test_duration_mode_supervises_the_second_slot_with_duration():
    input_ids = torch.tensor([5, 999, 6, 999])
    labels = build_supervision_labels(input_ids, timestamp_token_id=999, class_ids=[8, 12],
                                      target="duration", num_classes=5000)
    assert labels.tolist() == [IGNORE_INDEX, 8, IGNORE_INDEX, 4]


def test_odd_pair_length_and_unknown_target_are_rejected():
    with pytest.raises(ValueError):
        duration_target_class_ids([1, 2, 3], num_classes=5000)
    with pytest.raises(ValueError):
        build_supervision_labels(torch.tensor([999]), timestamp_token_id=999, class_ids=[1], target="centre")


def test_slot_times_helper_honours_the_parameterisation():
    from lyricalign.inference.constrained_timestamps import slot_times_from_probabilities
    probs = np.zeros((1, 2, 100), dtype=np.float64)
    probs[0, 0, 10] = 1.0                      # start bin 10
    probs[0, 1, 25] = 1.0                      # second bin 25
    starts_absolute, ends_absolute = slot_times_from_probabilities(probs, segment_sec=0.08)
    assert (starts_absolute[0], ends_absolute[0]) == pytest.approx((0.8, 2.0))
    starts_dur, ends_dur = slot_times_from_probabilities(probs, segment_sec=0.08, target="duration")
    assert (starts_dur[0], ends_dur[0]) == pytest.approx((0.8, 0.8 + 2.0))   # end = start + duration
    with pytest.raises(ValueError):
        slot_times_from_probabilities(probs[0], segment_sec=0.08)


def test_evaluate_variants_skips_absolute_only_decoders_in_duration_mode(tmp_path, monkeypatch):
    """duration 模式下 `fixed`/`dp` 会把时长读成位置 ⇒ 必须显式标 not_supported，而不是给一个数。"""
    import inspect
    from lyricalign.training import eval_funnel_loop
    signature = inspect.signature(eval_funnel_loop.evaluate_variants)
    assert "timestamp_target" in signature.parameters
    source = inspect.getsource(eval_funnel_loop.evaluate_variants)
    assert "not_supported_in_duration_mode" in source
    assert "if timestamp_target == \"absolute\":" in source      # 绝对解码被门住


def test_argmax_predictions_convert_duration_slots_to_absolute_ends():
    import numpy as np
    from lyricalign.training.eval_funnel_loop import argmax_character_predictions
    logits = np.full((1, 5, 60), -10.0, dtype="float32")
    # 位置 1 = 起始槽（bin 10），位置 3 = 结束/时长槽（bin 4）
    logits[0, 1, 10] = 10.0
    logits[0, 3, 4] = 10.0
    input_ids = np.array([[7, 999, 7, 999, 7]])
    records = [{"item_id": "S#x#1", "song_id": "S#x"}]
    absolute = argmax_character_predictions(
        __import__("torch").from_numpy(logits), __import__("torch").from_numpy(input_ids),
        [["啊"]], 999, records, segment_sec=0.08)
    duration = argmax_character_predictions(
        __import__("torch").from_numpy(logits), __import__("torch").from_numpy(input_ids),
        [["啊"]], 999, records, segment_sec=0.08, timestamp_target="duration")
    assert absolute[0]["start_sec"] == duration[0]["start_sec"] == 0.8
    assert absolute[0]["end_sec"] == 0.32                     # 把时长当位置读
    assert duration[0]["end_sec"] == 0.8 + 0.32               # 正确：end = start + duration
