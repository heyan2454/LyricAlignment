import pytest

from lyricalign.research_v7.detector_v2_contract import (
    DetectorOutput,
    StateInterval,
    TriState,
    UnitInterval,
    output_from_probabilities,
    states_to_intervals,
    validate_detector_output,
)


def test_states_merge_and_partition():
    intervals = states_to_intervals({
        10: TriState.ACCEPT,
        11: TriState.ACCEPT,
        12: TriState.UNCERTAIN,
        13: TriState.REJECT,
        14: TriState.REJECT,
    })
    assert [(x.interval.start, x.interval.end, x.state.value) for x in intervals] == [
        (10, 12, "accept"),
        (12, 13, "uncertain"),
        (13, 15, "reject"),
    ]
    output = DetectorOutput("req", (UnitInterval(10, 15),), intervals)
    assert validate_detector_output(output)["n_queried_units"] == 5


def test_output_from_dual_thresholds():
    output = output_from_probabilities(
        request_identity="req",
        queried_intervals=[UnitInterval(0, 4)],
        probabilities={0: 0.1, 1: 0.3, 2: 0.7, 3: 0.95},
        accept_threshold=0.2,
        reject_threshold=0.8,
    )
    assert output.to_dict()["accept_intervals"] == [[0, 1]]
    assert output.to_dict()["uncertain_intervals"] == [[1, 3]]
    assert output.to_dict()["reject_intervals"] == [[3, 4]]


def test_partition_rejects_missing_unit():
    output = DetectorOutput(
        "req",
        (UnitInterval(0, 3),),
        (StateInterval(UnitInterval(0, 2), TriState.ACCEPT),),
    )
    with pytest.raises(ValueError, match="missing"):
        validate_detector_output(output)
