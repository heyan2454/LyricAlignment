# -*- coding: utf-8 -*-
"""F1 sgcv：p_bad 校准 song-grouped CV + uncertain 成本模型（23 方向 2）测试。

合成数据（8 首歌随机 p/y + song_id）验证：5 折歌单不重叠、isotonic 单调不减、
cost model 四象限计数与 n_scan 行数、schema 字段齐全。纯内存，无模型加载。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research_v7"))

import numpy as np
import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "research_v7"
           / "analyze_pbad_calibration_sgcv.py")
_spec = importlib.util.spec_from_file_location("analyze_pbad_calibration_sgcv", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _synth_rows(n_songs=8, per_song=120, seed=7):
    rng = np.random.RandomState(seed)
    rows = []
    for s in range(n_songs):
        for i in range(per_song):
            x1 = rng.uniform(-2, 2)
            x2 = rng.uniform(-2, 2)
            p = 1.0 / (1.0 + np.exp(-(0.8 * x1 - 0.5 * x2)))
            y = 1 if rng.rand() < p else 0
            rows.append({
                "request_identity": f"req_{s}", "canonical_unit_id": i,
                "label": "unsafe" if y else "safe", "song_id": f"song_{s}",
                "features": {"raw_x1": x1, "raw_x2": x2,
                             "official_x1": x1 ** 2, "official_x2": abs(x2),
                             "cv_x1": 0.1 * x1}})
    return rows


_FROZEN = {"raw": {"small_mlp": {"best_combo": "R+O",
                                  "operating_points": {"T_accept": 0.35, "T_reject": 0.6}},
                   "standardized_logistic": {"best_combo": "O",
                                             "operating_points": {"T_accept": 0.3,
                                                                  "T_reject": 0.55}}},
           "official": {"standardized_logistic": {"best_combo": "R",
                                                  "operating_points": {"T_accept": 0.3,
                                                                       "T_reject": 0.55}}}}


def test_song_grouped_folds_no_overlap_all_songs():
    rows = _synth_rows()
    folds = mod.song_grouped_folds(rows, k=5, seed=0)
    assert len(folds) == 5
    all_val = []
    for f in folds:
        assert len(f["val_songs"]) >= 1
        assert len(f["train_rows"]) > 0 and len(f["val_rows"]) > 0
        tr_songs = set(f["train_songs"])
        va_songs = set(f["val_songs"])
        assert not (tr_songs & va_songs), f"fold {f['fold']} 歌单重叠"
        all_val.extend(va_songs)
    assert sorted(all_val) == sorted({f"song_{s}" for s in range(8)})
    n_total = sum(len(f["val_rows"]) for f in folds)
    assert n_total == len(rows)


def test_sgcv_core_schema_and_metrics():
    rows = _synth_rows()
    entry = {"model_kind": "standardized_logistic", "combo": "R+O",
             "T_accept": 0.3, "T_reject": 0.55}
    cv = mod.sgcv_calibration_core(rows, entry, k=5, seed=0)
    assert cv["k"] == 5 and cv["seed"] == 0
    assert cv["model_kind"] == "standardized_logistic" and cv["combo"] == "R+O"
    assert cv["n_train_songs"] == 8 and cv["n_units"] == 960
    assert len(cv["folds"]) == 5
    for fo in cv["folds"]:
        for method in ("raw", "temperature", "isotonic"):
            assert {"brier", "ece"} <= set(fo[method])
            assert 0.0 <= fo[method]["brier"] <= 0.25
            assert fo[method]["ece"] is not None and fo[method]["ece"] >= 0.0
    for metric in ("raw_brier", "raw_ece", "temperature_brier",
                   "temperature_ece", "isotonic_brier", "isotonic_ece"):
        s = cv["summary"][metric]
        assert {"mean", "std", "values"} <= set(s)
        assert len(s["values"]) == 5
        assert s["mean"] == pytest.approx(np.mean([v for v in s["values"] if v is not None]))
    assert {"raw", "isotonic"} <= set(cv["pooled_oof"])
    for m in cv["pooled_oof"]:
        assert {"brier", "ece"} <= set(cv["pooled_oof"][m])
    assert {"p", "v"} <= set(cv["isotonic_curve_fold0"])
    assert len(cv["isotonic_curve_fold0"]["p"]) == len(cv["isotonic_curve_fold0"]["v"])


def test_isotonic_pav_monotone_non_decreasing():
    rng = np.random.RandomState(3)
    p = rng.uniform(0, 1, 500)
    y = (rng.rand(500) < 0.2 + 0.6 * p).astype(float)
    ps, vs = mod.isotonic_pav(p, y)
    assert np.all(np.diff(vs) >= -1e-12)
    assert np.all(np.diff(ps) >= 0)
    assert np.min(vs) >= 0.0 and np.max(vs) <= 1.0


def test_cost_model_quadrants_and_scan_rows():
    rng = np.random.RandomState(11)
    p = rng.uniform(0.0, 1.0, 1000)
    y = (rng.rand(1000) < 0.25 + 0.5 * p).astype(float)
    C1, C2, C3 = 10.0, 5.0, 1.0
    cm = mod.cost_model(p, y, T_accept=0.3, T_reject=0.7,
                        C1=C1, C2=C2, C3=C3, n_scan=41)
    q = cm["frozen_quadrants"]
    assert q["n_accept"] + q["n_uncertain"] + q["n_reject"] == q["n_total"] == 1000
    assert q["n_safe_accept"] + q["n_safe_uncertain"] + q["n_safe_reject"] \
        + q["n_unsafe_accept"] + q["n_unsafe_uncertain"] + q["n_unsafe_reject"] == 1000
    expect = (C1 * q["n_unsafe_accept"]
              + C2 * (q["n_unsafe_accept"] + q["n_unsafe_uncertain"])
              + C3 * q["n_uncertain"])
    assert cm["frozen_total_cost"] == pytest.approx(expect)
    assert len(cm["curve"]) == 41
    T_rej = cm["frozen_thresholds"]["T_reject"]
    expect_missed = int(np.sum((y > 0.5) & (p < T_rej)))
    for row in cm["curve"]:
        tau = row["tau"]
        n_unc = int(np.sum((p >= tau) & (p < T_rej)))
        n_acc = int(np.sum((y > 0.5) & (p < tau)))
        assert row["n_unsafe_not_rejected"] == expect_missed
        assert row["n_uncertain"] == n_unc
        assert row["total_cost"] == pytest.approx(C1 * n_acc + C2 * expect_missed + C3 * n_unc)
        assert row["tau"] >= 0.0 and row["tau"] <= 1.0
    taus = [r["tau"] for r in cm["curve"]]
    assert taus == sorted(taus)


def test_frozen_entry_selection():
    entry = mod._frozen_entry(_FROZEN, "raw", None)
    assert entry["model_kind"] == "small_mlp" and entry["combo"] == "R+O"
    assert entry["T_accept"] == pytest.approx(0.35)
    entry = mod._frozen_entry(_FROZEN, "official", None)
    assert entry["model_kind"] == "standardized_logistic"
    entry = mod._frozen_entry(_FROZEN, "raw", "standardized_logistic")
    assert entry["combo"] == "O" and entry["T_reject"] == pytest.approx(0.55)
    with pytest.raises(ValueError):
        mod._frozen_entry(_FROZEN, "raw", "constrained_gbdt")
