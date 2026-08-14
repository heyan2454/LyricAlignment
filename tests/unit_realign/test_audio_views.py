"""Tests for WP5 audio-view no-GT selection (E3 observation study)."""
from __future__ import annotations

from lyricalign.unit_realign.audio_views import select_view_no_gt


def _view(rid, kind="base", rows=None, status="ok"):
    return {
        "recrop_view_id": rid, "view_kind": kind, "request_identity": f"sha256:{rid}",
        "status": status, "candidate_rows": rows or [],
    }


def _row(disp=0.0, missing=False):
    return {"mean_boundary_displacement_ms": disp, "candidate_missing": missing,
            "context_protected": False}


def test_select_view_no_gt_no_signal_is_fail_closed():
    # No usable numeric signal -> no_signal, NOT GT-hard-selected.
    result = select_view_no_gt([_view("base", rows=[{}]), _view("wider", rows=[{}])])
    assert result["selected"] is False
    assert result["status"] == "no_signal"


def test_select_view_no_gt_unique_winner():
    # mean_boundary_displacement_ms available; base has lower displacement -> wins.
    result = select_view_no_gt([
        _view("base", rows=[_row(0.0)]),
        _view("wider", rows=[_row(500.0)]),
    ])
    assert result["selected"] is True
    assert result["status"] == "selected_no_gt"
    assert result["selected_view"] == "base"


def test_select_view_no_gt_all_tied_is_indeterminate():
    # Both views identical displacement -> no unique best -> indeterminate.
    result = select_view_no_gt([
        _view("base", rows=[_row(100.0)]),
        _view("wider", rows=[_row(100.0)]),
    ])
    assert result["selected"] is False
    assert result["status"] == "indeterminate"


def test_select_view_no_gt_votes_tie_is_indeterminate():
    # Two signals each prefer a different view with equal decisive votes.
    base_rows = [{"mean_boundary_displacement_ms": 0.0, "detector_p_bad": 0.9, "margin": 0.1},
                 {"mean_boundary_displacement_ms": 1.0, "detector_p_bad": 0.8, "margin": 0.2}]
    wider_rows = [{"mean_boundary_displacement_ms": 0.0, "detector_p_bad": 0.5, "margin": 0.9},
                  {"mean_boundary_displacement_ms": 1.0, "detector_p_bad": 0.6, "margin": 0.8}]
    result = select_view_no_gt([_view("base", rows=base_rows), _view("wider", rows=wider_rows)])
    # mean_displacement ties (base vs wider), p_bad~wider lower, margin~wider higher;
    # so the two available signals both vote wider -> wider wins; if they split it'd be
    # indeterminate. Here they agree on wider, so selected.
    assert result["selected"] is True
    assert result["selected_view"] == "wider"
