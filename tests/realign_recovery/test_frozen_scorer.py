"""E3 frozen-scorer shadow tests (WP C2, CPU acceptance).

Synthetic evidence rows with separable entropy signal; no GPU/model libraries.
"""
from __future__ import annotations

import json

import pytest

from lyricalign.realign_recovery.catastrophic_commit import (
    default_is_catastrophic,
)
from lyricalign.realign_recovery.frozen_scorer import (
    FrozenScorer,
    build_frozen_scorer,
)


def _ev_row(canonical_unit_id, *, entropy=0.1, start_sec=None, end_sec=None,
            label=None, request_identity="frozen_shadow"):
    if start_sec is None:
        start_sec = float(canonical_unit_id)
    if end_sec is None:
        end_sec = start_sec + 1.0
    row = {
        "request_identity": request_identity,
        "view_id": "official",
        "canonical_unit_id": canonical_unit_id,
        "raw": {
            "start_sec": start_sec,
            "end_sec": end_sec,
            "start_entropy": entropy,
            "end_entropy": entropy,
            "start_margin": 1.0 - entropy,
            "end_margin": 1.0 - entropy,
            "topk": [0.9, 0.05, 0.02, 0.02, 0.01],
        },
        "official": {
            "start_sec": start_sec,
            "end_sec": end_sec,
            "repair_start_shift_sec": 0.0,
            "repair_end_shift_sec": 0.0,
        },
        "hidden": {"available": False, "schema": None, "start": {}, "end": {}},
        "cross_view": {},
    }
    if label is not None:
        row["label"] = label
    return row


def _frozen_op(tmp_path, *, best_combo="R", model_kind="standardized_logistic",
               t_accept=None, t_reject=None):
    path = tmp_path / "FROZEN_OPERATING_POINTS.json"
    op = {
        "official": {
            "best_combo": best_combo,
            "model_kind": model_kind,
            "operating_points": {},
        }
    }
    if t_accept is not None and t_reject is not None:
        op["official"]["operating_points"] = {
            "T_accept": t_accept, "T_reject": t_reject}
    path.write_text(json.dumps(op), encoding="utf-8")
    return path


def _train_rows():
    unsafe = [_ev_row(i, entropy=0.9, label="unsafe") for i in range(8)]
    safe = [_ev_row(8 + i, entropy=0.05, label="safe") for i in range(8)]
    return unsafe + safe


def _build(tmp_path, **kw):
    scorer = build_frozen_scorer(
        _frozen_op(tmp_path, t_accept=0.3, t_reject=0.7), _train_rows(), **kw)
    assert isinstance(scorer, FrozenScorer)
    return scorer


def test_high_entropy_window_rejects(tmp_path):
    scorer = _build(tmp_path)
    window = [_ev_row(i, entropy=0.95, start_sec=i * 2.0) for i in range(4)]
    shadow = scorer.score(window)
    assert shadow["decision"] == "reject"
    assert shadow["n_units"] == 4
    assert shadow["unsafe_intervals"]
    for lo, hi in shadow["unsafe_intervals"]:
        assert lo < hi
    assert default_is_catastrophic(shadow) is True


def test_low_entropy_window_accepts(tmp_path):
    scorer = _build(tmp_path)
    window = [_ev_row(i, entropy=0.02) for i in range(4)]
    shadow = scorer.score(window)
    assert shadow["decision"] == "accept"
    assert shadow["unsafe_intervals"] == []
    assert default_is_catastrophic(shadow) is False


def test_empty_window_accepts(tmp_path):
    scorer = _build(tmp_path)
    shadow = scorer.score([])
    assert shadow == {"unsafe_intervals": [], "n_units": 0, "decision": "accept"}


def test_missing_threshold_raises_not_fallback(tmp_path):
    with pytest.raises(ValueError, match="T_accept"):
        build_frozen_scorer(_frozen_op(tmp_path), _train_rows())


def test_missing_target_raises(tmp_path):
    path = tmp_path / "FROZEN_OPERATING_POINTS.json"
    path.write_text(json.dumps({"raw": {"best_combo": "R"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="official"):
        build_frozen_scorer(path, _train_rows())


def test_missing_frozen_op_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_frozen_scorer(tmp_path / "missing.json", _train_rows())


def test_invalid_threshold_raises(tmp_path):
    with pytest.raises(ValueError):
        build_frozen_scorer(
            _frozen_op(tmp_path, t_accept=0.8, t_reject=0.3), _train_rows())


def test_deterministic(tmp_path):
    s1 = _build(tmp_path)
    s2 = _build(tmp_path)
    window = [_ev_row(i, entropy=0.95) for i in range(4)]
    assert s1.score(window) == s2.score(window)


def test_cross_entropy_mix_marks_reject_interval_on_seconds(tmp_path):
    scorer = _build(tmp_path)
    window = [
        _ev_row(0, entropy=0.02, start_sec=0.0, end_sec=1.0),
        _ev_row(1, entropy=0.95, start_sec=1.0, end_sec=2.0),
        _ev_row(2, entropy=0.95, start_sec=2.0, end_sec=3.0),
        _ev_row(3, entropy=0.02, start_sec=3.0, end_sec=4.0),
    ]
    shadow = scorer.score(window)
    assert shadow["decision"] == "reject"
    assert shadow["unsafe_intervals"]
    lo, hi = shadow["unsafe_intervals"][0]
    assert lo >= 1.0 and hi <= 3.0
