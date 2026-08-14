"""Tests for WP6 E4 R-U coarse->fine combination (R-CF)."""
from __future__ import annotations

from lyricalign.unit_realign.coarse_fine import (
    FOURTH_FAMILY,
    _final_rows,
    evaluate_coarse_fine,
)


def _req(rid="A"):
    return {"song_id": "s", "region_id": "r", "request_identity": f"sha256:{rid}",
            "canonical_ids": [3, 4], "target_unit_ids": [3, 4], "fixed_context_unit_ids": []}


def _bl():
    return [{"canonical_unit_id": 3, "start_sec": 1.5, "end_sec": 1.8},
            {"canonical_unit_id": 4, "start_sec": 2.0, "end_sec": 2.3}]


def _a_cand():
    return [{"canonical_unit_id": 3, "start_sec": 1.52, "end_sec": 1.8},
            {"canonical_unit_id": 4, "start_sec": 2.03, "end_sec": 2.3}]


def test_fourth_family_name():
    assert FOURTH_FAMILY == "R-CF"


def test_final_rows_falls_back_to_stage_a_when_b_not_constructible():
    """U-review P1-1: Stage A coarse result must survive a Stage B stop."""
    steps = [
        {"stage": "A", "status": "ok", "iteration": 0,
         "candidate_rows": _a_cand(), "baseline_rows": _bl(), "request": _req("A"),
         "request_identity": "sha256:A"},
        {"stage": "B", "status": "not_constructible", "iteration": 1,
         "not_constructible_reason": "non_monotonic_candidate_timeline",
         "baseline_rows": _bl(), "request": _req("B"), "request_identity": "sha256:B"},
    ]
    rows, win = _final_rows(steps)
    assert win["stage"] == "A"
    assert rows is not None and len(rows) == 2


def test_evaluate_coarse_fine_a_fallback_not_zeroed():
    rows = evaluate_coarse_fine([
        {"stage": "A", "status": "ok", "iteration": 0,
         "candidate_rows": _a_cand(), "baseline_rows": _bl(), "request": _req("A"),
         "request_identity": "sha256:A"},
        {"stage": "B", "status": "not_constructible", "iteration": 1,
         "not_constructible_reason": "non_monotonic_candidate_timeline",
         "baseline_rows": _bl(), "request": _req("B"), "request_identity": "sha256:B"},
    ])
    reg = next(r for r in rows if r.get("row_kind") == "region")
    assert reg["final_stage"] == "A"
    assert reg["stage_b_not_constructible"] is True
    assert reg["coverage"] > 0
    assert reg["target_recovered_100"] == 1.0
    assert reg["actual_writeback"] == 0


def test_final_rows_empty_when_no_ok_stage():
    rows, win = _final_rows([
        {"stage": "A", "status": "not_constructible", "iteration": 0,
         "request": _req("A"), "request_identity": None},
    ])
    assert rows is None and win is None
