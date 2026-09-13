"""CPU tests for monotone minimum-duration constrained timestamp decoding."""

from __future__ import annotations

import numpy as np
import pytest

from lyricalign.inference.constrained_timestamps import slot_logprobs, viterbi_monotone


def peaked(n_bins: int, *bins: int, high: float = 0.0, low: float = -20.0) -> np.ndarray:
    row = np.full(n_bins, low, dtype=np.float64)
    for index in bins:
        row[index] = high
    return row


def test_argmax_solution_is_kept_when_it_is_already_legal():
    starts = np.stack([peaked(20, 1), peaked(20, 6)])
    ends = np.stack([peaked(20, 4), peaked(20, 9)])
    result = viterbi_monotone(starts, ends, min_duration=1)
    assert result["starts"] == [1, 6] and result["ends"] == [4, 9]
    assert result["argmax_legal"] is True
    assert result["score"] == pytest.approx(result["argmax_score"])


def test_overlapping_characters_are_pushed_apart_by_the_constraint():
    starts = np.stack([peaked(20, 0), peaked(20, 0)])
    ends = np.stack([peaked(20, 8), peaked(20, 10)])
    result = viterbi_monotone(starts, ends, min_duration=1)
    assert result["argmax_legal"] is False
    assert result["starts"][1] >= result["ends"][0]
    assert result["ends"][1] >= result["starts"][1] + 1
    assert result["score"] <= result["argmax_score"]


def test_minimum_duration_is_enforced():
    starts = np.stack([peaked(10, 5)])
    ends = np.stack([peaked(10, 5)])
    result = viterbi_monotone(starts, ends, min_duration=3)
    assert result["ends"][0] - result["starts"][0] >= 3
    assert result["argmax_legal"] is False


def test_monotone_constraint_holds_across_a_long_sequence():
    rng = np.random.default_rng(7)
    starts = rng.normal(size=(12, 64))
    ends = rng.normal(size=(12, 64))
    result = viterbi_monotone(starts, ends, min_duration=2)
    for index in range(12):
        assert result["ends"][index] - result["starts"][index] >= 2
        if index:
            assert result["ends"][index - 1] <= result["starts"][index]
    # a stricter constraint can only lower the optimum
    assert result["score"] <= viterbi_monotone(starts, ends, min_duration=1)["score"] + 1e-9


def test_infeasible_when_the_sequence_cannot_fit():
    starts = np.full((2, 4), 0.0)
    ends = np.full((2, 4), 3.0)
    result = viterbi_monotone(starts, ends, min_duration=3)
    assert result["feasible"] is False and result["starts"] == []


def test_slot_logprobs_reads_two_slots_per_character():
    torch = pytest.importorskip("torch")
    n_bins = 8
    logits = torch.full((1, 8, n_bins), -10.0)
    ids = torch.tensor([[1, 9, 1, 9, 1, 9, 1, 9]])
    logits[0, 1, 6] = 10.0
    logits[0, 3, 2] = 10.0
    probabilities = slot_logprobs(logits, ids, timestamp_token_id=9, num_classes=n_bins)
    assert probabilities.shape == (2, 2, n_bins)   # four slots = two characters
    assert int(probabilities[0, 0].argmax()) == 6
    assert int(probabilities[0, 1].argmax()) == 2
    result = viterbi_monotone(probabilities[:, 0, :], probabilities[:, 1, :], min_duration=1)
    assert result["ends"][0] >= result["starts"][0] + 1


def test_empty_input_is_feasible_and_empty():
    result = viterbi_monotone(np.zeros((0, 5)), np.zeros((0, 5)))
    assert result["feasible"] is True and result["starts"] == [] and result["score"] == 0.0


def test_bad_min_duration_is_rejected():
    with pytest.raises(ValueError):
        viterbi_monotone(np.zeros((1, 5)), np.zeros((1, 5)), min_duration=0)
