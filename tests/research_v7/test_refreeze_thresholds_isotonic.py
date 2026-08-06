# -*- coding: utf-8 -*-
"""refreeze_thresholds_isotonic.py 测试：isotonic 映射单调、prot95 达标、
constraint_violated 路径、comparison 字段（backlog #3）。"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research_v7" / "refreeze_thresholds_isotonic.py"
_spec = importlib.util.spec_from_file_location("refreeze_thresholds_isotonic", _SCRIPT)
MOD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MOD)


def _rows(p_vals, labels, song="s"):
    rows = []
    for i, (p, lab) in enumerate(zip(p_vals, labels)):
        rows.append({"song_id": song, "label": lab,
                     "features": {"official_start_sec": i, "raw_start_sec": i,
                                  "ro_peak_align": p, "has_left_neighbor": 1.0,
                                  "official_repair_start_shift_sec": p,
                                  "repair_end_shift_sec": p}})
    return rows


def test_isotonic_pav_monotone():
    rng = np.random.RandomState(0)
    p = np.sort(rng.rand(200))
    y = (np.sin(p * 30) > 0.5).astype(float)
    ps, vs = MOD.isotonic_pav(p, y)
    assert np.all(np.diff(vs) >= -1e-12)
    assert len(ps) == len(vs) == len(p)
    assert 0.0 <= vs.min() <= vs.max() <= 1.0


def test_refreeze_feasible_path():
    rng = np.random.RandomState(1)
    n_tr, n_va = 1200, 300
    tr_p = np.concatenate([rng.rand(n_tr // 2) * 0.2, 0.8 + rng.rand(n_tr // 2) * 0.2])
    tr_y = (np.arange(n_tr) >= n_tr // 2).astype(int)
    tr = _rows(tr_p, ["unsafe" if v else "safe" for v in tr_y])
    va_p = np.concatenate([rng.rand(n_va // 2) * 0.2, 0.8 + rng.rand(n_va // 2) * 0.2])
    va_y = (np.arange(n_va) >= n_va // 2).astype(int)
    va = _rows(va_p, ["unsafe" if v else "safe" for v in va_y])
    entry = {"model_kind": "small_mlp", "combo": "R+O",
             "old": {"T_accept": 0.5, "T_reject": 0.6,
                     "protected_recall_95": 0.9, "safe_accept_rate": 0.1,
                     "constraint_violated": True}}
    out = MOD.refreeze_target(train_rows=tr, val_rows=va, entry=entry,
                              min_safe_accept_rate=0.1)
    assert out["status"] == "ok"
    assert out["new"]["protected_recall_95"] >= 0.95 - 1e-9
    assert "T_accept" in out["new"] and "T_reject" in out["new"]
    assert set(out["comparison"]) == {"old_vs_new", "delta"}
    assert len(out["isotonic_curve"]["p"]) == len(out["isotonic_curve"]["v"])
    assert out["old"]["safe_accept_rate"] == 0.1


def test_refreeze_no_unsafe_val():
    tr_p = np.linspace(0.1, 0.9, 50)
    tr = _rows(tr_p, ["unsafe"] * 25 + ["safe"] * 25)
    va = _rows([0.1, 0.2], ["safe", "safe"])
    out = MOD.refreeze_target(train_rows=tr, val_rows=va,
                              entry={"model_kind": "small_mlp", "combo": "R+O",
                                     "old": {"T_accept": 0.4, "T_reject": 0.6}},
                              min_safe_accept_rate=0.2)
    assert out["status"] == "no_unsafe_val"
    assert out["new"]["constraint_violated"] is True


def test_refreeze_high_constraint_violated():
    rng = np.random.RandomState(2)
    n_tr, n_va = 1200, 300
    tr_p = np.concatenate([rng.rand(n_tr // 2) * 0.2, 0.8 + rng.rand(n_tr // 2) * 0.2])
    tr_y = (np.arange(n_tr) >= n_tr // 2).astype(int)
    tr = _rows(tr_p, ["unsafe" if v else "safe" for v in tr_y])
    va_p = np.concatenate([rng.rand(n_va // 2) * 0.2, 0.8 + rng.rand(n_va // 2) * 0.2])
    va_y = (np.arange(n_va) >= n_va // 2).astype(int)
    va = _rows(va_p, ["unsafe" if v else "safe" for v in va_y])
    out = MOD.refreeze_target(train_rows=tr, val_rows=va,
                              entry={"model_kind": "small_mlp", "combo": "R+O",
                                     "old": {"T_accept": None, "T_reject": None}},
                              min_safe_accept_rate=0.99)
    assert out["status"] == "ok"
    assert out["new"]["protected_recall_95"] >= 0.95 - 1e-9
