"""Product-facing metrics for Detector V2 tri-state interval outputs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .detector_v2_contract import DetectorOutput, TriState, UnitInterval, validate_detector_output


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def output_unit_states(output: DetectorOutput) -> dict[int, TriState]:
    validate_detector_output(output)
    states: dict[int, TriState] = {}
    for row in output.state_intervals:
        for unit in row.interval.units():
            states[unit] = row.state
    return states


def tri_state_unit_metrics(
    *,
    output: DetectorOutput,
    unsafe_units: Iterable[int],
    safe_units: Iterable[int],
    grey_units: Iterable[int] = (),
) -> dict:
    """Compute false-accept, reject/protected recall and safe-result cost.

    Empty denominators return ``None``; they are never promoted to perfect recall.
    """
    states = output_unit_states(output)
    unsafe = set(unsafe_units)
    safe = set(safe_units)
    grey = set(grey_units)
    if unsafe & safe or unsafe & grey or safe & grey:
        raise ValueError("unsafe/safe/grey labels must be disjoint")
    unknown = (unsafe | safe | grey) - set(states)
    if unknown:
        raise ValueError(f"GT units outside detector output: {sorted(unknown)[:10]}")

    unsafe_accept = sum(states[u] == TriState.ACCEPT for u in unsafe)
    unsafe_reject = sum(states[u] == TriState.REJECT for u in unsafe)
    unsafe_uncertain = sum(states[u] == TriState.UNCERTAIN for u in unsafe)
    safe_accept = sum(states[u] == TriState.ACCEPT for u in safe)
    safe_reject = sum(states[u] == TriState.REJECT for u in safe)
    safe_uncertain = sum(states[u] == TriState.UNCERTAIN for u in safe)

    return {
        "n_unsafe_units": len(unsafe),
        "n_safe_units": len(safe),
        "n_grey_units": len(grey),
        "unsafe_false_accept_rate": _rate(unsafe_accept, len(unsafe)),
        "reject_recall": _rate(unsafe_reject, len(unsafe)),
        "protected_recall": _rate(unsafe_reject + unsafe_uncertain, len(unsafe)),
        "safe_accept_rate": _rate(safe_accept, len(safe)),
        "safe_reject_rate": _rate(safe_reject, len(safe)),
        "safe_uncertain_rate": _rate(safe_uncertain, len(safe)),
        "counts": {
            "unsafe_accept": unsafe_accept,
            "unsafe_reject": unsafe_reject,
            "unsafe_uncertain": unsafe_uncertain,
            "safe_accept": safe_accept,
            "safe_reject": safe_reject,
            "safe_uncertain": safe_uncertain,
        },
    }


def interval_capture_metrics(
    *,
    output: DetectorOutput,
    unsafe_intervals: Sequence[UnitInterval],
    cover_fractions: Sequence[float] = (0.75, 1.0),
    long_interval_min_units: int = 3,
) -> dict:
    """Evaluate reject-only and protected coverage of true unsafe intervals."""
    states = output_unit_states(output)
    result: dict[str, float | int | None] = {"n_unsafe_intervals": len(unsafe_intervals)}
    for fraction in cover_fractions:
        if not 0.0 < fraction <= 1.0:
            raise ValueError("cover fractions must be in (0, 1]")
        reject_hits = 0
        protected_hits = 0
        for interval in unsafe_intervals:
            units = list(interval.units())
            if any(u not in states for u in units):
                raise ValueError(f"unsafe interval {interval} outside detector output")
            reject_fraction = sum(states[u] == TriState.REJECT for u in units) / len(units)
            protected_fraction = sum(states[u] != TriState.ACCEPT for u in units) / len(units)
            reject_hits += reject_fraction >= fraction
            protected_hits += protected_fraction >= fraction
        suffix = str(int(round(fraction * 100)))
        result[f"reject_interval_recall_at_{suffix}"] = _rate(reject_hits, len(unsafe_intervals))
        result[f"protected_interval_recall_at_{suffix}"] = _rate(protected_hits, len(unsafe_intervals))

    long_intervals = [x for x in unsafe_intervals if x.end - x.start >= long_interval_min_units]
    fully_accepted = 0
    longest_accepted_run = 0
    for interval in unsafe_intervals:
        current = 0
        all_accept = True
        for unit in interval.units():
            if states[unit] == TriState.ACCEPT:
                current += 1
                longest_accepted_run = max(longest_accepted_run, current)
            else:
                current = 0
                all_accept = False
        if interval in long_intervals and all_accept:
            fully_accepted += 1
    result["n_long_unsafe_intervals"] = len(long_intervals)
    result["long_unsafe_interval_fully_accepted_rate"] = _rate(fully_accepted, len(long_intervals))
    result["longest_consecutive_unsafe_accept_run"] = longest_accepted_run
    return result
