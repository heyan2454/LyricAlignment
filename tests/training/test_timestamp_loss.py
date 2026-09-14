from __future__ import annotations

import torch
import torch.nn.functional as F

from lyricalign.training.timestamp_loss import IGNORE_INDEX, slot_weights, weighted_timestamp_loss


def _case():
    # 3 characters: durations 0.24s (short), 1.2s (long), 0.4s (short); slots at positions 1,2,3,4,5,6
    labels = torch.full((1, 8), IGNORE_INDEX, dtype=torch.long)
    labels[0, 1:7] = torch.tensor([0, 3, 10, 25, 30, 35])
    logits = torch.randn(1, 8, 40, generator=torch.Generator().manual_seed(3))
    return logits, labels


def test_slot_weights_marks_exactly_the_two_slots_of_long_characters():
    logits, labels = _case()
    weights = slot_weights(labels, step_sec=0.08, long_sec=1.0, weight=4.0)
    assert weights.shape == labels.shape
    assert weights[0, 1].item() == 1.0 and weights[0, 2].item() == 1.0        # 0.24s
    assert weights[0, 3].item() == 4.0 and weights[0, 4].item() == 4.0         # (25-10)*0.08 = 1.2s
    assert weights[0, 5].item() == 1.0 and weights[0, 6].item() == 1.0         # 0.4s
    assert weights[0, 0].item() == 1.0 and weights[0, 7].item() == 1.0          # 非监督位不影响


def test_unit_weight_reproduces_the_plain_mean_cross_entropy():
    logits, labels = _case()
    plain = F.cross_entropy(logits.reshape(-1, logits.shape[-1]).float(), labels.reshape(-1),
                            ignore_index=IGNORE_INDEX)                     # HF 的 token-classification 归一化
    mine = weighted_timestamp_loss(logits, labels, step_sec=0.08, long_sec=1.0, weight=1.0)
    assert torch.allclose(mine, plain, atol=1e-6), (float(mine), float(plain))


def test_large_weight_concentrates_the_objective_on_the_long_pair():
    logits, labels = _case()
    per_token = F.cross_entropy(logits.reshape(-1, logits.shape[-1]).float(), labels.reshape(-1),
                                ignore_index=IGNORE_INDEX, reduction="none").view(1, 8)
    only_long = (per_token[0, 3] + per_token[0, 4]) / 2
    heavy = weighted_timestamp_loss(logits, labels, step_sec=0.08, long_sec=1.0, weight=1e6)
    assert torch.allclose(heavy, only_long, rtol=1e-3, atol=1e-5)


def test_unsupervised_batch_returns_zero_instead_of_nan():
    logits = torch.randn(1, 4, 12)
    labels = torch.full((1, 4), IGNORE_INDEX, dtype=torch.long)
    loss = weighted_timestamp_loss(logits, labels, step_sec=0.08, long_sec=1.0, weight=3.0)
    assert torch.isfinite(loss) and float(loss) == 0.0


def test_non_positive_weight_is_rejected():
    logits, labels = _case()
    try:
        weighted_timestamp_loss(logits, labels, step_sec=0.08, long_sec=1.0, weight=0.0)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "positive" in str(exc)



def test_slot_offset_weights_only_the_end_slot_of_long_characters():
    labels = torch.full((1, 8), IGNORE_INDEX, dtype=torch.long)
    labels[0, 1:7] = torch.tensor([0, 3, 10, 25, 30, 35])   # 第二字时长 (25-10)*0.08 = 1.2s
    weights = slot_weights(labels, step_sec=0.08, long_sec=1.0, weight=5.0, slot="offset")
    assert weights[0, 4].item() == 5.0                      # 只加权结束点
    assert weights[0, 3].item() == 1.0                      # 起始点保持 1
    assert weights[0, 1].item() == 1.0 and weights[0, 2].item() == 1.0
    assert weights[0, 5].item() == 1.0 and weights[0, 6].item() == 1.0      # 短字不受影响


def test_slot_onset_is_the_mirror_image_and_both_covers_the_pair():
    labels = torch.full((1, 8), IGNORE_INDEX, dtype=torch.long)
    labels[0, 1:7] = torch.tensor([0, 3, 10, 25, 30, 35])
    kwargs = dict(step_sec=0.08, long_sec=1.0, weight=5.0)
    onset = slot_weights(labels, slot="onset", **kwargs)
    offset = slot_weights(labels, slot="offset", **kwargs)
    both = slot_weights(labels, **kwargs)
    assert onset[0, 3].item() == 5.0 and onset[0, 4].item() == 1.0
    assert offset[0, 3].item() == 1.0 and offset[0, 4].item() == 5.0
    assert both[0, 3].item() == 5.0 and both[0, 4].item() == 5.0
    # 三个模式只可能在那一对槽位上不同；其余位置（含非监督位）必须恒为 1
    for name, weights in (("onset", onset), ("offset", offset), ("both", both)):
        for position in (0, 1, 2, 5, 6, 7):
            assert weights[0, position].item() == 1.0, (name, position)


def test_weighted_loss_accepts_the_slot_choice_and_still_reduces_to_plain_ce_at_unit_weight():
    logits, labels = _case()
    plain = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]).float(),
                                              labels.reshape(-1), ignore_index=IGNORE_INDEX)
    for slot in ("both", "onset", "offset"):
        value = weighted_timestamp_loss(logits, labels, step_sec=0.08, long_sec=1.0,
                                        weight=1.0, slot=slot)
        assert torch.allclose(value, plain, atol=1e-6), slot


def test_unknown_slot_choice_is_rejected_rather_than_silently_ignored():
    labels = torch.full((1, 4), IGNORE_INDEX, dtype=torch.long)
    try:
        slot_weights(labels, step_sec=0.08, long_sec=1.0, weight=2.0, slot="centre")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "both|offset|onset" in str(exc)
