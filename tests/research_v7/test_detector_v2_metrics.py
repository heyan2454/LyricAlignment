from lyricalign.research_v7.detector_v2_contract import (
    DetectorOutput,
    StateInterval,
    TriState,
    UnitInterval,
)
from lyricalign.research_v7.detector_v2_metrics import interval_capture_metrics, tri_state_unit_metrics


def _output():
    return DetectorOutput(
        "req",
        (UnitInterval(0, 8),),
        (
            StateInterval(UnitInterval(0, 2), TriState.ACCEPT),
            StateInterval(UnitInterval(2, 4), TriState.UNCERTAIN),
            StateInterval(UnitInterval(4, 6), TriState.REJECT),
            StateInterval(UnitInterval(6, 8), TriState.ACCEPT),
        ),
    )


def test_tri_state_metrics_do_not_treat_uncertain_as_accept():
    result = tri_state_unit_metrics(
        output=_output(),
        unsafe_units={2, 3, 4, 5},
        safe_units={0, 1, 6, 7},
    )
    assert result["unsafe_false_accept_rate"] == 0.0
    assert result["reject_recall"] == 0.5
    assert result["protected_recall"] == 1.0
    assert result["safe_accept_rate"] == 1.0


def test_empty_denominator_is_none_not_perfect():
    result = tri_state_unit_metrics(output=_output(), unsafe_units=set(), safe_units={0, 1})
    assert result["reject_recall"] is None
    assert result["protected_recall"] is None


def test_interval_metrics_report_reject_and_protected():
    result = interval_capture_metrics(
        output=_output(),
        unsafe_intervals=[UnitInterval(2, 6), UnitInterval(6, 8)],
    )
    assert result["reject_interval_recall_at_75"] == 0.0
    assert result["protected_interval_recall_at_75"] == 0.5
    assert result["longest_consecutive_unsafe_accept_run"] == 2
