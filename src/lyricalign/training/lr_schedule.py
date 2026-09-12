"""Cyclic cosine learning-rate factor, as a pure function.

Why this exists: the product runs are long-window jobs that a person may stop at any time.  A single
cosine spanned over the configured `max_steps` leaves the learning rate near its peak whenever the
run is stopped early (at 1/3 of the horizon it is still ~80 % of peak), so the checkpoints that
exist are all "hot" ones and the annealed end never happens.  Restarting the cosine every
`cycle_len` steps guarantees a fully annealed, deliverable checkpoint at a known, recurring moment,
and a per-cycle peak decay keeps later restarts from washing out what the previous cycle refined.

The functions here return only a multiplier in [0, 1]; the trainer applies them to its own peak
learning rates, so this stays testable without torch.
"""

from __future__ import annotations

from typing import Any


def _validate(cycle_len: int, warmup_ratio: float) -> None:
    if int(cycle_len) <= 1:
        raise ValueError(f"cycle_len must be > 1, got {cycle_len!r}")
    if not 0.0 <= float(warmup_ratio) < 1.0:
        raise ValueError(f"warmup_ratio must be in [0, 1), got {warmup_ratio!r}")


def warmup_steps_for(cycle_len: int, warmup_ratio: float = 0.05) -> int:
    _validate(cycle_len, warmup_ratio)
    return max(1, int(round(cycle_len * float(warmup_ratio))))


def cycle_index(step: int, *, cycle_len: int) -> int:
    """Which restart cycle a (1-based-ish) step falls into; cycle 0 is the first."""
    _validate(cycle_len, 0.05)
    return max(0, int(step - 1)) // int(cycle_len) if step > 0 else 0


def is_cycle_end(step: int, *, cycle_len: int) -> bool:
    _validate(cycle_len, 0.05)
    return step > 0 and step % int(cycle_len) == 0


def cyclic_cosine_factor(step: int, *, cycle_len: int, warmup_ratio: float = 0.05,
                         cycle_peak_decay: float = 1.0) -> float:
    """Multiplier for the peak learning rate at `step` under a cyclic cosine schedule.

    Shape per cycle: linear warmup for `warmup_ratio` of the cycle, then cosine from 1.0 down to 0.0
    at the cycle boundary.  Each new cycle's peak is scaled by ``cycle_peak_decay ** cycle_index``,
    so restarts get progressively gentler instead of re-heating to the original peak.
    """
    import math

    _validate(cycle_len, warmup_ratio)
    if step < 0:
        raise ValueError(f"step must be >= 0, got {step!r}")
    cycle = int(cycle_len)
    warm = warmup_steps_for(cycle, warmup_ratio)
    # 1-based position inside the cycle, so an exact cycle boundary lands on the last (fully
    # annealed) step instead of the next cycle's warmup
    idx = ((int(step) - 1) // cycle) if step > 0 else 0
    pos_in_cycle = int(step) - idx * cycle
    peak = float(cycle_peak_decay) ** idx
    if pos_in_cycle <= 0:
        return 0.0
    if pos_in_cycle <= warm:
        return peak * (pos_in_cycle / float(warm))
    progress = (pos_in_cycle - warm) / float(max(1, cycle - warm))
    progress = min(1.0, max(0.0, progress))
    return peak * 0.5 * (1.0 + math.cos(math.pi * progress))


def schedule_summary(steps: list[int], *, cycle_len: int, warmup_ratio: float = 0.05,
                     cycle_peak_decay: float = 1.0) -> dict[str, Any]:
    """Diagnostics for a planned schedule: the factor at each requested step."""
    return {
        "cycle_len": int(cycle_len),
        "warmup_steps": warmup_steps_for(cycle_len, warmup_ratio),
        "cycle_peak_decay": float(cycle_peak_decay),
        "factors": {int(s): round(cyclic_cosine_factor(s, cycle_len=cycle_len,
                                                       warmup_ratio=warmup_ratio,
                                                       cycle_peak_decay=cycle_peak_decay), 4)
                    for s in steps},
        "cycle_ends_within": [s for s in range(1, max(steps) + 1)
                              if is_cycle_end(s, cycle_len=cycle_len)],
    }
