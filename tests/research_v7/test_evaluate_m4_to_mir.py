# -*- coding: utf-8 -*-
"""Phase3-3a evaluate_m4_to_mir tests（合成 fixture，纯内存）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

import pytest

from evaluate_m4_to_mir import evaluate_m4_to_mir


def _rows(target, n, unsafe_frac=0.5, family="crop_late"):
    out = []
    for u in range(n):
        unsafe = u < int(n * unsafe_frac)
        feats = {"raw_duration_sec": 0.4, "raw_end_entropy": 1.0 if unsafe else 0.1,
                 "official_duration_sec": 0.4, "ro_start_shift_sec": 1.0 if unsafe else 0.0,
                 "ro_end_shift_sec": 0.0, "has_repair": 0, "repair_run_length": 0}
        out.append({"request_identity": f"mir:{u}", "canonical_unit_id": u,
                    "target": target, "label": "unsafe" if unsafe else "safe",
                    "features": feats, "family": family})
    return out


def _frozen_op():
    return {"raw": {"best_combo": "O",
                    "operating_points": {"T_accept": 0.5, "T_reject": 0.8}},
            "official": {"best_combo": "O",
                         "operating_points": {"T_accept": 0.5, "T_reject": 0.8}}}


def test_m4_to_mir_pooled_metrics():
    m4_train = {t: _rows(t, 200) for t in ("raw", "official")}
    mir_rows = _rows("official", 100, unsafe_frac=0.4) + _rows("raw", 100, unsafe_frac=0.4)
    out = evaluate_m4_to_mir(m4_train=m4_train, mir_rows=mir_rows, frozen_op=_frozen_op())
    assert "validation_basis" not in out  # main() 里注入，纯函数不混入
    for t in ("raw", "official"):
        v = out["targets"][t]
        assert v["n_train"] == 200 and v["n_score"] == 100
        m = v["tri_unit_metrics"]
        assert 0.0 <= m["reject_recall"] <= 1.0
        assert m["protected_recall"] == pytest.approx(1.0)
        assert "by_family" in v


def test_m4_to_mir_family_layers():
    m4_train = {t: _rows(t, 200) for t in ("raw", "official")}
    mir_rows = _rows("official", 60, family="end_early") + _rows("official", 40, family="crop_early")
    out = evaluate_m4_to_mir(m4_train=m4_train, mir_rows=mir_rows, frozen_op=_frozen_op())
    fams = out["targets"]["official"]["by_family"]
    assert set(fams) == {"crop_early", "end_early"}
    assert fams["end_early"]["n_units"] == 60
    assert fams["crop_early"]["n_units"] == 40


def test_m4_to_mir_insufficient_data():
    out = evaluate_m4_to_mir(m4_train={"raw": [], "official": []}, mir_rows=[],
                             frozen_op=_frozen_op())
    for t in ("raw", "official"):
        assert out["targets"][t]["status"] == "insufficient_data"


def test_m4_to_mir_filters_grey_and_unavailable():
    """仅 safe/unsafe 参与打分；grey/ambiguous/gt_unavailable 不计数。"""
    m4_train = {t: _rows(t, 200) for t in ("raw", "official")}
    mir_rows = _rows("official", 50)
    for extra_label in ("grey", "ambiguous", "gt_unavailable"):
        r = _rows("official", 1)[0]
        r["label"] = extra_label
        mir_rows.append(r)
    out = evaluate_m4_to_mir(m4_train=m4_train, mir_rows=mir_rows, frozen_op=_frozen_op())
    assert out["targets"]["official"]["n_score"] == 50
