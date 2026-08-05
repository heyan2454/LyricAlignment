"""Detector V2 interval post-processing and threshold freezing.

Phase 2-3 of the Detector V2 pipeline: model output ``p_bad(unit)`` is
turned into tri-state units with frozen dual thresholds, followed by light
merging (fill single-unit holes, buffer rejects by one unit) and a
validation-set threshold freeze honoring protected-recall targets.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .detector_v2_contract import (
    DetectorOutput,
    StateInterval,
    TriState,
    UnitInterval,
    output_from_probabilities,
    states_to_intervals,
    validate_detector_output,
)
from .detector_v2_metrics import tri_state_unit_metrics


def _runs(states: Mapping[int, TriState]) -> list[tuple[int, int, TriState]]:
    if not states:
        return []
    ordered = sorted(states)
    runs: list[tuple[int, int, TriState]] = []
    start = previous = ordered[0]
    state = states[start]
    for unit in ordered[1:]:
        if unit != previous + 1 or states[unit] != state:
            runs.append((start, previous + 1, state))
            start, state = unit, states[unit]
        previous = unit
    runs.append((start, previous + 1, state))
    return runs


def light_merge(unit_states: Mapping[int, TriState | str]) -> dict[int, TriState]:
    """Apply the only two allowed merging operations.

    a) Fill length-1 ACCEPT/REJECT islands that are surrounded on both sides
       by the same state (merged into that state); iterated to fixpoint so
       cascades are resolved.
    b) Each remaining REJECT run extends at most 1 unit on each side, turning
       that neighbor into UNCERTAIN (if the neighbor exists).
    c) No other expansion is ever performed.
    """
    states: dict[int, TriState] = {int(k): TriState(v) for k, v in unit_states.items()}
    changed = True
    while changed:
        changed = False
        for start, end, state in _runs(states):
            if end - start != 1 or state not in (TriState.ACCEPT, TriState.REJECT):
                continue
            left = states.get(start - 1)
            right = states.get(end)
            if left is not None and right is not None and left == right and left != state:
                states[start] = left
                changed = True
    for start, end, state in _runs(states):
        if state != TriState.REJECT:
            continue
        if start - 1 in states and states[start - 1] != TriState.REJECT:
            states[start - 1] = TriState.UNCERTAIN
        if end in states and states[end] != TriState.REJECT:
            states[end] = TriState.UNCERTAIN
    return states


def tristate_from_p_bad(
    probabilities: Mapping[int, float],
    accept_threshold: float,
    reject_threshold: float,
    *,
    request_identity: str = "detector_v2_frozen",
    queried_intervals: Sequence[UnitInterval] | None = None,
) -> DetectorOutput:
    """Threshold p_bad into tri-state units, apply light_merge, emit output.

    The initial thresholding runs through
    :func:`lyricalign.research_v7.detector_v2_contract.output_from_probabilities`
    so threshold and coverage validation are inherited; the merged result is
    re-encoded with the contract's interval helpers.
    """
    if not probabilities:
        raise ValueError("probabilities must not be empty")
    if queried_intervals is None:
        units = sorted(int(u) for u in probabilities)
        queried_intervals = [UnitInterval(units[0], units[-1] + 1)]
    initial = output_from_probabilities(
        request_identity=request_identity,
        queried_intervals=queried_intervals,
        probabilities=probabilities,
        accept_threshold=accept_threshold,
        reject_threshold=reject_threshold,
    )
    raw_states: dict[int, TriState] = {
        unit: row.state for row in initial.state_intervals for unit in row.interval.units()
    }
    merged = light_merge(raw_states)
    output = DetectorOutput(
        request_identity=request_identity,
        queried_intervals=tuple(queried_intervals),
        state_intervals=states_to_intervals(merged),
    )
    validate_detector_output(output)
    return output


def freeze_thresholds(
    probabilities: Mapping[int, float],
    labels: Mapping[int, str],
    *,
    target_protected_recalls: tuple[float, ...] = (0.95, 0.99),
    min_safe_accept_rate: float = 0.0,
) -> dict | None:
    """Freeze T_reject/T_accept on a validation set; None if no unsafe units.

    Candidates are the sorted unique p_bad values of every labelled unit
    (0.0/1.0 sentinels added). T_accept is the largest candidate whose
    unsafe_false_accept_rate does not exceed ``1 - max(targets)``; T_reject
    is the largest candidate above T_accept whose reject-only recall reaches
    ``min(targets)`` (falling back to the smallest candidate above T_accept
    when the target is not attainable). Reported recalls and rates are
    computed with :func:`tri_state_unit_metrics` on the final frozen output
    after light merging; empty unsafe sets return None rather than fabricated
    thresholds.

    ``min_safe_accept_rate > 0`` (22 §Phase B dual constraint): after the
    protection-first pass, walk reject candidates downward while
    ``safe_accept_rate >= min_safe_accept_rate`` holds, keeping protection;
    when the constraint cannot be met at any reject threshold, the
    protection-first point is returned with ``constraint_violated=True``.
    """
    if not target_protected_recalls:
        raise ValueError("target_protected_recalls must not be empty")
    for target in target_protected_recalls:
        if not 0.0 < target < 1.0:
            raise ValueError(f"target_protected_recalls must lie in (0, 1): {target}")
    if not 0.0 <= min_safe_accept_rate <= 1.0:
        raise ValueError(f"min_safe_accept_rate must lie in [0, 1]: {min_safe_accept_rate}")
    units = sorted(int(u) for u in probabilities)
    if not units:
        return None
    unsafe = {u for u in units if labels.get(u) == "unsafe"}
    if not unsafe:
        return None
    safe = {u for u in units if labels.get(u) == "safe"}

    candidates = sorted({float(probabilities[u]) for u in units})
    if candidates[0] > 0.0:
        candidates = [0.0] + candidates
    if candidates[-1] < 1.0:
        candidates = candidates + [1.0]

    max_target = max(target_protected_recalls)
    bound = 1.0 - max_target
    accept_threshold = candidates[0]
    for threshold in candidates:
        false_accept = sum(probabilities[u] <= threshold for u in unsafe) / len(unsafe)
        if false_accept <= bound:
            accept_threshold = threshold
        else:
            break

    min_target = min(target_protected_recalls)
    reject_candidates = [t for t in candidates if t > accept_threshold]
    reject_threshold = reject_candidates[0]
    for threshold in reject_candidates:
        reject_recall = sum(probabilities[u] >= threshold for u in unsafe) / len(unsafe)
        if reject_recall >= min_target:
            reject_threshold = threshold
        else:
            break

    constraint_violated = False
    if min_safe_accept_rate > 0.0:
        output_tmp = tristate_from_p_bad(
            probabilities, accept_threshold, reject_threshold,
            queried_intervals=[UnitInterval(units[0], units[-1] + 1)])
        safe_accept = tri_state_unit_metrics(
            output=output_tmp, unsafe_units=unsafe, safe_units=safe)["safe_accept_rate"]
        if safe_accept < min_safe_accept_rate:
            constraint_violated = True
            for threshold in reject_candidates:
                if threshold >= reject_threshold:
                    continue
                out_t = tristate_from_p_bad(
                    probabilities, accept_threshold, threshold,
                    queried_intervals=[UnitInterval(units[0], units[-1] + 1)])
                m = tri_state_unit_metrics(output=out_t, unsafe_units=unsafe, safe_units=safe)
                if m["safe_accept_rate"] >= min_safe_accept_rate \
                        and m["protected_recall"] >= min_target:
                    reject_threshold = threshold
                    constraint_violated = False
                    break

    output = tristate_from_p_bad(
        probabilities,
        accept_threshold,
        reject_threshold,
        queried_intervals=[UnitInterval(units[0], units[-1] + 1)],
    )
    metrics = tri_state_unit_metrics(output=output, unsafe_units=unsafe, safe_units=safe)
    result: dict = {
        "T_accept": accept_threshold,
        "T_reject": reject_threshold,
        "safe_accept_rate": metrics["safe_accept_rate"],
        "n_val_units": len(units),
    }
    if constraint_violated:
        result["constraint_violated"] = True
    for target in target_protected_recalls:
        result[f"protected_recall_{int(round(target * 100))}"] = metrics["protected_recall"]
    return result
