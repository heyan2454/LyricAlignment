"""Detector V2 tri-state interval contracts.

Intervals are half-open canonical-unit ranges ``[start, end)``. A detector output
must cover every queried unit exactly once with one of ACCEPT/REJECT/UNCERTAIN.
This module is intentionally model-independent and contains no GT logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence


class TriState(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, order=True)
class UnitInterval:
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or not isinstance(self.end, int):
            raise TypeError("interval bounds must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid half-open interval [{self.start}, {self.end})")

    def units(self) -> range:
        return range(self.start, self.end)


@dataclass(frozen=True)
class StateInterval:
    interval: UnitInterval
    state: TriState
    score_min: float | None = None
    score_max: float | None = None


@dataclass(frozen=True)
class DetectorOutput:
    request_identity: str
    queried_intervals: tuple[UnitInterval, ...]
    state_intervals: tuple[StateInterval, ...]
    schema_version: str = "detector_v2_output_v1"

    def to_dict(self) -> dict:
        grouped = {state.value: [] for state in TriState}
        for row in self.state_intervals:
            grouped[row.state.value].append([row.interval.start, row.interval.end])
        return {
            "schema_version": self.schema_version,
            "request_identity": self.request_identity,
            "queried_intervals": [[x.start, x.end] for x in self.queried_intervals],
            "accept_intervals": grouped[TriState.ACCEPT.value],
            "reject_intervals": grouped[TriState.REJECT.value],
            "uncertain_intervals": grouped[TriState.UNCERTAIN.value],
        }


def _unit_set(intervals: Iterable[UnitInterval]) -> set[int]:
    out: set[int] = set()
    for interval in intervals:
        units = set(interval.units())
        overlap = out & units
        if overlap:
            raise ValueError(f"overlapping intervals at units {sorted(overlap)[:10]}")
        out.update(units)
    return out


def validate_detector_output(output: DetectorOutput) -> dict:
    """Validate exact, disjoint tri-state coverage of queried intervals."""
    if not output.request_identity:
        raise ValueError("request_identity is required")
    queried = _unit_set(output.queried_intervals)
    predicted = _unit_set(row.interval for row in output.state_intervals)
    outside = predicted - queried
    missing = queried - predicted
    if outside:
        raise ValueError(f"predicted units outside queried intervals: {sorted(outside)[:10]}")
    if missing:
        raise ValueError(f"queried units missing a tri-state decision: {sorted(missing)[:10]}")
    return {
        "ok": True,
        "n_queried_units": len(queried),
        "n_state_intervals": len(output.state_intervals),
    }


def states_to_intervals(unit_states: Mapping[int, TriState | str]) -> tuple[StateInterval, ...]:
    """Merge adjacent units with the same state into half-open intervals."""
    if not unit_states:
        return ()
    ordered = sorted((int(k), TriState(v)) for k, v in unit_states.items())
    rows: list[StateInterval] = []
    start, previous, state = ordered[0][0], ordered[0][0], ordered[0][1]
    for unit, next_state in ordered[1:]:
        if unit != previous + 1 or next_state != state:
            rows.append(StateInterval(UnitInterval(start, previous + 1), state))
            start, state = unit, next_state
        previous = unit
    rows.append(StateInterval(UnitInterval(start, previous + 1), state))
    return tuple(rows)


def output_from_probabilities(
    *,
    request_identity: str,
    queried_intervals: Sequence[UnitInterval],
    probabilities: Mapping[int, float],
    accept_threshold: float,
    reject_threshold: float,
) -> DetectorOutput:
    """Create a tri-state output from frozen dual thresholds."""
    if not 0.0 <= accept_threshold < reject_threshold <= 1.0:
        raise ValueError("require 0 <= accept_threshold < reject_threshold <= 1")
    queried = _unit_set(queried_intervals)
    if set(probabilities) != queried:
        missing = queried - set(probabilities)
        extra = set(probabilities) - queried
        raise ValueError(f"probability coverage mismatch; missing={sorted(missing)[:5]} extra={sorted(extra)[:5]}")
    states: dict[int, TriState] = {}
    for unit, score in probabilities.items():
        value = float(score)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"invalid probability for unit {unit}: {value}")
        if value <= accept_threshold:
            states[unit] = TriState.ACCEPT
        elif value >= reject_threshold:
            states[unit] = TriState.REJECT
        else:
            states[unit] = TriState.UNCERTAIN
    output = DetectorOutput(
        request_identity=request_identity,
        queried_intervals=tuple(queried_intervals),
        state_intervals=states_to_intervals(states),
    )
    validate_detector_output(output)
    return output
