"""Tests for WP9 E6 recovery-basin atlas / classify (AA-review P1 fixes)."""
from __future__ import annotations

from lyricalign.unit_realign.recovery_atlas import (
    MECH_COARSE,
    MECH_ITERATIVE,
    CLASS_COARSE,
    CLASS_ITERATIVE,
    CLASS_UNRECOVERABLE,
    _row_recovered_buckets,
    classify_region,
)


def _coarse_key():
    return f"best_{MECH_COARSE}_100ms"


def _iter_key():
    return f"best_{MECH_ITERATIVE}_100ms"


def test_row_recovered_buckets_proportion_not_bool():
    """AA-review P1: coarse_fine target_recovered_* is a proportion, not a boolean."""
    # 50% recovery at 100ms must NOT mark the 100ms bucket reached.
    buckets = _row_recovered_buckets({"target_recovered_100": 0.5,
                                      "target_recovered_200": 1.0})
    assert buckets[100] is False
    assert buckets[200] is True
    # full recovery marks reached.
    assert _row_recovered_buckets({"target_recovered_100": 1.0})[100] is True
    # split booleans unaffected.
    assert _row_recovered_buckets({"recovered_strict_100": True})[100] is True


def test_classify_coarse_only_reached_at_full_recovery():
    # When coarse did NOT reach 100ms (partial proportion -> bucket False), it
    # should not be classified coarse based on a partial hit.
    row2 = {"baseline_present_gt": True, "iteration": None,
            _iter_key(): False, _coarse_key(): False}
    assert classify_region(row2) == CLASS_UNRECOVERABLE


def test_classify_coarse_reached():
    row = {"baseline_present_gt": True, "iteration": None,
           _iter_key(): False, _coarse_key(): True}
    assert classify_region(row) == CLASS_COARSE


def test_classify_iterative_beats_unrecoverable():
    row = {"baseline_present_gt": True, "iteration": 2,
           _iter_key(): True, _coarse_key(): False}
    assert classify_region(row) == CLASS_ITERATIVE
