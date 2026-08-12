"""E8 writeback policy: pure per-unit decision + aggregation functions.

GT contract: these functions are no-GT.  They consume per-unit detector
decisions (``p_bad`` / ``state``) and per-unit GT *status* strings
(``ok|mid|err``) that callers derive off-line; no raw error seconds ever
enter the outputs here (only aggregate counts / status labels).

State naming avoids the ``FORBIDDEN_FEATURE_FIELDS`` literals (safe/unsafe/
grey/family/...): repair state is ``ok|mid|err`` and family is ``family_name``.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

STATE_OK = "ok"
STATE_MID = "mid"
STATE_ERR = "err"
ALL_STATES = (STATE_OK, STATE_MID, STATE_ERR)

T_OK = 1.0
T_ERR = 2.0
CATASTROPHIC_SEC = 5.0
IMPROVED_DELTA = 0.05

STRATEGY_NO_WRITEBACK = "no_writeback"
STRATEGY_FULL = "full_replacement"
STRATEGY_UNSAFE_ONLY = "unsafe_only"
STRATEGY_UNSAFE_MARGIN_1 = "unsafe_margin_1"
STRATEGY_UNSAFE_MARGIN_2 = "unsafe_margin_2"
STRATEGY_IMPROVED_ONLY = "improved_only"
STRATEGY_IMPROVED_REGION = "improved_region"

ALL_STRATEGIES = (
    STRATEGY_NO_WRITEBACK,
    STRATEGY_FULL,
    STRATEGY_UNSAFE_ONLY,
    STRATEGY_UNSAFE_MARGIN_1,
    STRATEGY_UNSAFE_MARGIN_2,
    STRATEGY_IMPROVED_ONLY,
    STRATEGY_IMPROVED_REGION,
)

_MARGIN_BY_STRATEGY = {
    STRATEGY_UNSAFE_ONLY: 0,
    STRATEGY_UNSAFE_MARGIN_1: 1,
    STRATEGY_UNSAFE_MARGIN_2: 2,
}


def gt_state(err: float) -> str:
    """Repair status from a per-unit absolute error (seconds).

    T=1.0: ``ok`` if err <= 1.0, ``mid`` if 1.0 < err <= 2.0, else ``err``.
    """
    if err <= T_OK:
        return STATE_OK
    if err <= T_ERR:
        return STATE_MID
    return STATE_ERR


def is_catastrophic(err: float) -> bool:
    return err > CATASTROPHIC_SEC


def select_covered_unit_ids(
    new_units: Iterable[Mapping[str, Any]],
    strategy: str,
    old_p_bad: Mapping[int, float] | None = None,
    improved_delta: float = IMPROVED_DELTA,
) -> set[int]:
    """Which canonical unit ids get written back under ``strategy``.

    ``new_units``: per-unit dicts with ``canonical_unit_id`` / ``p_bad`` /
    ``state`` (frozen tristate accept|uncertain|reject), any order.  Units are
    sorted by canonical id so that margin / region neighbours are well defined.
    ``old_p_bad`` maps canonical id -> baseline p_bad (only needed for the
    improved strategies).
    """
    units = sorted(new_units, key=lambda u: int(u["canonical_unit_id"]))
    cids = [int(u["canonical_unit_id"]) for u in units]
    n = len(units)
    if strategy == STRATEGY_NO_WRITEBACK:
        return set()
    if strategy == STRATEGY_FULL:
        return set(cids)
    if strategy in _MARGIN_BY_STRATEGY:
        margin = _MARGIN_BY_STRATEGY[strategy]
        covered: set[int] = set()
        for i, u in enumerate(units):
            if u.get("state") != "reject":
                continue
            for j in range(max(0, i - margin), min(n, i + margin + 1)):
                covered.add(cids[j])
        return covered
    if strategy in (STRATEGY_IMPROVED_ONLY, STRATEGY_IMPROVED_REGION):
        old_p_bad = dict(old_p_bad or {})
        improved_idx = [
            i for i, u in enumerate(units)
            if old_p_bad.get(u["canonical_unit_id"]) is not None
            and old_p_bad[u["canonical_unit_id"]] - u["p_bad"] > improved_delta
        ]
        if strategy == STRATEGY_IMPROVED_ONLY:
            return {cids[i] for i in improved_idx}
        covered = set()
        run: list[int] = []
        for i in improved_idx:
            if run and i == run[-1] + 1:
                run.append(i)
            else:
                if run:
                    covered |= _expand_run(run, cids, n)
                run = [i]
        if run:
            covered |= _expand_run(run, cids, n)
        return covered
    raise ValueError(f"unknown strategy: {strategy}")


def _expand_run(run: list[int], cids: list[int], n: int) -> set[int]:
    lo = max(0, run[0] - 1)
    hi = min(n, run[-1] + 2)
    return {cids[i] for i in range(lo, hi)}


def aggregate_counts(
    rows: Iterable[tuple[str, str, float, float]],
) -> dict[str, Any]:
    """Aggregate per-unit (old_state, wb_state, old_err, wb_err) into metrics.

    ``old_err``/``wb_err`` are only used for catastrophic counting (error > 5.0);
    per-unit error values never leave this function.
    """
    transitions: Counter[tuple[str, str]] = Counter()
    n_units = 0
    cat_old = 0
    cat_wb = 0
    for old_state, wb_state, old_err, wb_err in rows:
        transitions[(old_state, wb_state)] += 1
        n_units += 1
        if is_catastrophic(old_err):
            cat_old += 1
        if is_catastrophic(wb_err):
            cat_wb += 1

    def cnt(a: str, b: str) -> int:
        return transitions[(a, b)]

    err_to_ok = cnt(STATE_ERR, STATE_OK)
    err_to_mid = cnt(STATE_ERR, STATE_MID)
    err_unchanged = cnt(STATE_ERR, STATE_ERR)
    ok_to_mid = cnt(STATE_OK, STATE_MID)
    ok_to_err = cnt(STATE_OK, STATE_ERR)
    mid_to_err = cnt(STATE_MID, STATE_ERR)
    mid_to_ok = cnt(STATE_MID, STATE_OK)
    ok_unchanged = cnt(STATE_OK, STATE_OK)
    mid_unchanged = cnt(STATE_MID, STATE_MID)

    return {
        "n_units": n_units,
        "transitions": {
            f"{a}->{b}": cnt(a, b) for a in ALL_STATES for b in ALL_STATES
        },
        "repair": {
            "err_to_ok": err_to_ok,
            "err_to_mid": err_to_mid,
            "err_unchanged": err_unchanged,
        },
        "damage": {
            "ok_to_mid": ok_to_mid,
            "ok_to_err": ok_to_err,
            "mid_to_err": mid_to_err,
        },
        "noise": {
            "ok_unchanged": ok_unchanged,
            "mid_unchanged": mid_unchanged,
            "mid_to_ok": mid_to_ok,
        },
        "net_improved": err_to_ok - ok_to_err - mid_to_err,
        "catastrophic_old": cat_old,
        "catastrophic_wb": cat_wb,
        "catastrophic_reduction": cat_old - cat_wb,
    }


class RowAccumulator:
    """Collects (old_state, wb_state, old_err, wb_err) rows and aggregates."""

    def __init__(self) -> None:
        self._rows: list[tuple[str, str, float, float]] = []

    def add(self, old_state: str, wb_state: str, old_err: float, wb_err: float) -> None:
        self._rows.append((old_state, wb_state, old_err, wb_err))

    def extend(self, rows: Iterable[tuple[str, str, float, float]]) -> None:
        self._rows.extend(rows)

    def result(self) -> dict[str, Any]:
        return aggregate_counts(self._rows)

    def __bool__(self) -> bool:
        return bool(self._rows)
