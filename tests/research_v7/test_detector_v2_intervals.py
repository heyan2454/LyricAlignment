import pytest

from lyricalign.research_v7.detector_v2_contract import TriState, UnitInterval
from lyricalign.research_v7.detector_v2_intervals import (
    freeze_thresholds,
    light_merge,
    tristate_from_p_bad,
)


def _states(values: dict[int, str]) -> dict[int, TriState]:
    return {unit: TriState(state) for unit, state in values.items()}


def test_light_merge_fills_single_unit_holes():
    merged = light_merge({0: "accept", 1: "accept", 2: "reject", 3: "accept", 4: "accept"})
    assert merged == _states({0: "accept", 1: "accept", 2: "accept", 3: "accept", 4: "accept"})
    merged = light_merge({0: "reject", 1: "reject", 2: "accept", 3: "reject", 4: "reject"})
    assert merged == _states({0: "reject", 1: "reject", 2: "reject", 3: "reject", 4: "reject"})


def test_light_merge_fills_cascaded_holes():
    merged = light_merge({0: "accept", 1: "reject", 2: "accept", 3: "reject", 4: "accept"})
    assert merged == _states({0: "accept", 1: "accept", 2: "accept", 3: "accept", 4: "accept"})


def test_light_merge_expands_reject_one_unit_each_side():
    merged = light_merge({0: "accept", 1: "accept", 2: "reject", 3: "reject", 4: "accept", 5: "accept"})
    assert merged == _states(
        {0: "accept", 1: "uncertain", 2: "reject", 3: "reject", 4: "uncertain", 5: "accept"}
    )


def test_light_merge_no_over_expansion():
    merged = light_merge({0: "accept", 1: "accept", 2: "accept", 3: "reject", 4: "reject", 5: "accept", 6: "accept", 7: "accept"})
    assert merged == _states(
        {0: "accept", 1: "accept", 2: "uncertain", 3: "reject", 4: "reject", 5: "uncertain", 6: "accept", 7: "accept"}
    )
    merged = light_merge({0: "reject", 1: "reject", 2: "accept", 3: "accept"})
    assert merged == _states({0: "reject", 1: "reject", 2: "uncertain", 3: "accept"})


def test_light_merge_long_runs_unchanged():
    values = {0: "reject", 1: "reject", 2: "reject", 3: "reject"}
    assert light_merge(values) == _states(values)
    values = {0: "accept", 1: "accept", 2: "accept", 3: "accept"}
    assert light_merge(values) == _states(values)


def test_light_merge_accept_hole_between_uncertain_fills():
    merged = light_merge({0: "accept", 1: "uncertain", 2: "accept", 3: "uncertain", 4: "accept"})
    assert merged == _states({0: "accept", 1: "uncertain", 2: "uncertain", 3: "uncertain", 4: "accept"})


def test_tristate_from_p_bad_fills_hole():
    output = tristate_from_p_bad({0: 0.1, 1: 0.9, 2: 0.1}, accept_threshold=0.2, reject_threshold=0.8)
    result = output.to_dict()
    assert result["accept_intervals"] == [[0, 3]]
    assert result["reject_intervals"] == []
    assert result["uncertain_intervals"] == []


def test_tristate_from_p_bad_expands_reject():
    output = tristate_from_p_bad({0: 0.1, 1: 0.9, 2: 0.95, 3: 0.1}, accept_threshold=0.2, reject_threshold=0.8)
    result = output.to_dict()
    assert result["accept_intervals"] == []
    assert result["reject_intervals"] == [[1, 3]]
    assert result["uncertain_intervals"] == [[0, 1], [3, 4]]
    assert output.request_identity == "detector_v2_frozen"


def test_tristate_from_p_bad_rejects_bad_thresholds():
    with pytest.raises(ValueError):
        tristate_from_p_bad({0: 0.1}, accept_threshold=0.8, reject_threshold=0.2)
    with pytest.raises(ValueError):
        tristate_from_p_bad({}, accept_threshold=0.2, reject_threshold=0.8)


def test_freeze_thresholds_synthetic_meets_targets():
    probabilities: dict[int, float] = {}
    labels: dict[int, str] = {}
    for unit in range(10):
        probabilities[unit] = 0.1
        labels[unit] = "safe"
    for unit in range(10, 20):
        probabilities[unit] = 0.2
        labels[unit] = "safe"
    for unit in range(20, 30):
        probabilities[unit] = 0.3
        labels[unit] = "safe"
    for unit in range(30, 35):
        probabilities[unit] = 0.5
        labels[unit] = "grey"
    for start, score in ((35, 0.75), (45, 0.85), (55, 0.95)):
        for k in range(10):
            probabilities[start + k] = score
            labels[start + k] = "unsafe"
    frozen = freeze_thresholds(probabilities, labels)
    assert frozen is not None
    assert frozen["T_accept"] == 0.5
    assert frozen["T_reject"] == 0.75
    assert frozen["protected_recall_95"] == 1.0
    assert frozen["protected_recall_99"] == 1.0
    assert frozen["safe_accept_rate"] == 1.0
    assert frozen["n_val_units"] == 65
    assert frozen["T_accept"] < frozen["T_reject"]


def test_freeze_thresholds_empty_unsafe_is_none():
    probabilities = {u: 0.1 + 0.01 * u for u in range(10)}
    labels = {u: "safe" for u in range(10)}
    assert freeze_thresholds(probabilities, labels) is None
    assert freeze_thresholds({}, {}) is None


def test_freeze_thresholds_default_targets_used():
    probabilities = {u: 0.95 for u in range(10)}
    labels = {u: "unsafe" for u in range(10)}
    frozen = freeze_thresholds(probabilities, labels)
    assert frozen is not None
    assert frozen["T_accept"] < frozen["T_reject"]
    assert frozen["protected_recall_99"] == 1.0
    assert "protected_recall_95" in frozen
