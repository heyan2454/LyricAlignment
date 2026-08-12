"""E8 writeback-policy pure-function unit tests (synthetic data)."""
from __future__ import annotations

import pytest

from lyricalign.realign_recovery.writeback_policy import (
    STRATEGY_FULL,
    STRATEGY_IMPROVED_ONLY,
    STRATEGY_IMPROVED_REGION,
    STRATEGY_NO_WRITEBACK,
    STRATEGY_UNSAFE_MARGIN_1,
    STRATEGY_UNSAFE_MARGIN_2,
    STRATEGY_UNSAFE_ONLY,
    aggregate_counts,
    gt_state,
    is_catastrophic,
    select_covered_unit_ids,
)


def _units(states, p_bads):
    return [
        {"canonical_unit_id": cid, "state": st, "p_bad": pb}
        for cid, st, pb in zip(range(len(states)), states, p_bads)
    ]


def test_gt_state_boundaries():
    assert gt_state(0.5) == "ok"
    assert gt_state(1.0) == "ok"
    assert gt_state(1.5) == "mid"
    assert gt_state(2.0) == "mid"
    assert gt_state(2.5) == "err"
    assert gt_state(10.0) == "err"


def test_is_catastrophic():
    assert not is_catastrophic(4.9)
    assert is_catastrophic(5.0) is False
    assert is_catastrophic(5.1)


def test_select_no_writeback_and_full():
    units = _units(["accept", "reject", "accept"], [0.1, 0.9, 0.2])
    assert select_covered_unit_ids(units, STRATEGY_NO_WRITEBACK) == set()
    assert select_covered_unit_ids(units, STRATEGY_FULL) == {0, 1, 2}


def test_select_unsafe_only_and_margins():
    units = _units(["accept", "reject", "accept", "reject"],
                   [0.1, 0.9, 0.2, 0.8])
    assert select_covered_unit_ids(units, STRATEGY_UNSAFE_ONLY) == {1, 3}
    assert select_covered_unit_ids(units, STRATEGY_UNSAFE_MARGIN_1) == {0, 1, 2, 3}
    assert select_covered_unit_ids(units, STRATEGY_UNSAFE_MARGIN_2) == {0, 1, 2, 3}


def test_select_unsafe_margin_boundary_clip():
    units = _units(["reject", "accept", "accept"], [0.9, 0.2, 0.1])
    assert select_covered_unit_ids(units, STRATEGY_UNSAFE_MARGIN_1) == {0, 1}


def test_select_improved_only():
    units = _units(["accept", "accept", "accept"], [0.4, 0.5, 0.6])
    old_p_bad = {0: 0.5, 1: 0.9, 2: 0.1}
    # delta = old - new: u0 +0.1 (>0.05), u1 +0.4 (>0.05), u2 -0.5
    assert select_covered_unit_ids(units, STRATEGY_IMPROVED_ONLY, old_p_bad) == {0, 1}


def test_select_improved_only_requires_old():
    units = _units(["accept"], [0.1])
    assert select_covered_unit_ids(units, STRATEGY_IMPROVED_ONLY, {}) == set()


def test_select_improved_region_expands_runs():
    units = _units(["accept"] * 5, [0.1, 0.2, 0.3, 0.4, 0.5])
    old_p_bad = {0: 0.5, 1: 0.1, 2: 0.1, 3: 0.1, 4: 0.9}
    # improved: cid 0 (0.4>0.05), cid 4 (0.4>0.05); runs [0] and [4]
    covered = select_covered_unit_ids(units, STRATEGY_IMPROVED_REGION, old_p_bad)
    assert covered == {0, 1, 3, 4}


def test_aggregate_counts_metrics():
    rows = [
        ("err", "ok", 3.0, 0.5),   # repair err->ok
        ("err", "mid", 3.0, 1.5),  # repair err->mid
        ("err", "err", 3.0, 3.0),  # err unchanged
        ("ok", "err", 0.5, 3.0),   # damage ok->err
        ("ok", "ok", 0.5, 0.5),    # noise ok unchanged
        ("err", "ok", 6.0, 0.5),   # repair + catastrophic old
    ]
    agg = aggregate_counts(rows)
    assert agg["n_units"] == 6
    assert agg["repair"]["err_to_ok"] == 2
    assert agg["repair"]["err_to_mid"] == 1
    assert agg["repair"]["err_unchanged"] == 1
    assert agg["damage"]["ok_to_err"] == 1
    assert agg["net_improved"] == 2 - 1 - 0
    assert agg["catastrophic_old"] == 1
    assert agg["catastrophic_wb"] == 0
    assert agg["catastrophic_reduction"] == 1


def test_aggregate_counts_unknown_strategy_raises():
    units = _units(["accept"], [0.1])
    with pytest.raises(ValueError):
        select_covered_unit_ids(units, "not_a_strategy")
