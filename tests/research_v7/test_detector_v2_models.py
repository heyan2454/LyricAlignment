# -*- coding: utf-8 -*-
"""Detector V2 models tests (Phase2-2, 18 §9 / 20 §7, 纯内存无模型无 sklearn)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
import pytest

from lyricalign.research_v7.detector_v2_models import (
    ABLATION_COMBOS,
    constrained_gbdt,
    evaluate_model,
    hidden_linear_probe,
    protected_operating_points,
    rule_baseline,
    run_ablation,
    sequence_model,
    small_mlp,
    standardized_logistic,
)


def separable_data(n=160, seed=7):
    rng = np.random.RandomState(seed)
    X = rng.uniform(-2.0, 2.0, (n, 2))
    y = (X[:, 0] + 1.5 * X[:, 1] > 0.3).astype(float)
    return X, y


def split(n, train_frac=0.7, seed=3):
    rng = np.random.RandomState(seed)
    idx = rng.permutation(n)
    cut = int(n * train_frac)
    return idx[:cut], idx[cut:]


def accuracy(p_bad, y):
    return float(np.mean((p_bad > 0.5).astype(float) == y))


# ---------------------------------------------------------------------------
# 标准化 Logistic
# ---------------------------------------------------------------------------

def test_standardized_logistic_learns_separable():
    X, y = separable_data()
    tr, va = split(len(y))
    beta, mean, std, predict_fn = standardized_logistic(X[tr], y[tr])
    assert beta.shape == (3,)
    assert mean.shape == (2,) and std.shape == (2,)
    p = predict_fn(X[va])
    assert p.shape == (len(va),)
    assert float(p.min()) >= 0.0 and float(p.max()) <= 1.0
    assert accuracy(p, y[va]) > 0.9
    assert abs(beta[1] / beta[2] - 1.0 / 1.5) < 0.5  # 学到大致正确方向


def test_standardized_logistic_nan_imputation():
    X, y = separable_data()
    X_bad = X.copy()
    X_bad[::3, 0] = np.nan
    tr, va = split(len(y))
    _, _, _, predict_fn = standardized_logistic(X_bad[tr], y[tr])
    p = predict_fn(X_bad[va])
    assert np.isfinite(p).all()
    assert accuracy(p, y[va]) > 0.85


def test_standardized_logistic_consistent_predict_on_nan():
    X, y = separable_data(80)
    tr, va = split(len(y))
    _, _, _, predict_fn = standardized_logistic(X[tr], y[tr], epochs=300, lr=0.1)
    p1 = predict_fn(X[va])
    p2 = predict_fn(X[va])
    assert np.allclose(p1, p2)


# ---------------------------------------------------------------------------
# rule baseline
# ---------------------------------------------------------------------------

def test_rule_baseline_thresholds():
    features = {
        "entropy": np.array([0.1, 0.6, 0.9, 0.3]),
        "margin": np.array([0.8, 0.4, 0.1, 0.7]),
    }
    p = rule_baseline(features, {"entropy": 0.8, "margin": 0.6})
    assert p.tolist() == [1.0, 0.0, 1.0, 1.0]
    p2 = rule_baseline(features, {"margin": {"threshold": 0.5, "direction": "below"}})
    assert p2.tolist() == [0.0, 1.0, 1.0, 0.0]
    p3 = rule_baseline(features, {"entropy": {"threshold": 0.5, "direction": "above"}})
    assert p3.tolist() == [0.0, 1.0, 1.0, 0.0]
    assert rule_baseline(features, {"entropy": 10.0}).tolist() == [0.0, 0.0, 0.0, 0.0]
    assert rule_baseline(features, {"entropy": 0.0}).tolist() == [1.0, 1.0, 1.0, 1.0]


def test_rule_baseline_missing_does_not_fire_and_bad_keys_fail():
    features = {"entropy": np.array([0.1, np.nan, 0.9])}
    assert rule_baseline(features, {"entropy": 0.5}).tolist() == [0.0, 0.0, 1.0]
    with pytest.raises(KeyError):
        rule_baseline(features, {"nope": 0.5})
    with pytest.raises(ValueError):
        rule_baseline(features, {"entropy": {"threshold": 0.5, "direction": "sideways"}})


def quadrant_data(n=200, seed=9):
    """轴对齐象限可分数据：决策树类模型可精确拟合。"""
    rng = np.random.RandomState(seed)
    X = rng.uniform(-2.0, 2.0, (n, 2))
    y = ((X[:, 0] > 0.0) & (X[:, 1] > 0.0)).astype(float)
    return X, y


# ---------------------------------------------------------------------------
# GBDT
# ---------------------------------------------------------------------------

def test_gbdt_separable():
    X, y = quadrant_data()
    tr, va = split(len(y))
    m = constrained_gbdt(X[tr], y[tr])
    assert m["kind"] == "constrained_gbdt"
    assert len(m["trees"]) == 50
    assert len(m["train_mse_per_tree"]) == 50
    p = m["predict_fn"](X[va])
    assert p.shape == (len(va),)
    assert float(p.min()) >= 0.0 and float(p.max()) <= 1.0
    assert accuracy(p, y[va]) > 0.95
    assert m["train_mse_per_tree"][-1] <= m["train_mse_per_tree"][0]


def test_gbdt_depth_limited():
    X, y = separable_data(80)
    tr, _ = split(len(y))
    m = constrained_gbdt(X[tr], y[tr], max_depth=1)
    assert all(t["feature"] is None or t["left"]["feature"] is None
               for t in m["trees"])


# ---------------------------------------------------------------------------
# MLP
# ---------------------------------------------------------------------------

def test_mlp_converges_and_separable():
    X, y = separable_data()
    tr, va = split(len(y))
    m = small_mlp(X[tr], y[tr], hidden=16, epochs=200, lr=0.05, seed=0)
    assert m["kind"] == "small_mlp"
    assert set(m["weights"]) == {"W1", "b1", "W2", "b2"}
    assert len(m["loss_history"]) == 200
    assert m["loss_history"][-1] < m["loss_history"][0]
    p = m["predict_fn"](X[va])
    assert accuracy(p, y[va]) > 0.9


def test_mlp_default_params_loss_decreases():
    X, y = separable_data(120)
    tr, _ = split(len(y))
    m = small_mlp(X[tr], y[tr])
    assert m["loss_history"][-1] < m["loss_history"][0]


# ---------------------------------------------------------------------------
# hidden linear probe
# ---------------------------------------------------------------------------

def test_hidden_linear_probe_on_h_features():
    X_h, y = separable_data(120)
    tr, va = split(len(y))
    m = hidden_linear_probe(X_h[tr], y[tr])
    assert m["kind"] == "hidden_linear_probe"
    assert m["weights"].shape == (3,)
    p = m["predict_fn"](X_h[va])
    assert np.isfinite(p).all()
    assert accuracy(p, y[va]) > 0.9


# ---------------------------------------------------------------------------
# 序列模型 CNN1D
# ---------------------------------------------------------------------------

def cnn_data(n_pos=60, n_neg=60, seed=11):
    rng = np.random.RandomState(seed)
    T, d = 8, 1
    pos = np.zeros((n_pos, T, d))
    pos[:, 0:2, :] = 1.0
    neg = np.zeros((n_neg, T, d))
    neg[:, -2:, :] = 1.0
    X = np.vstack([pos, neg]) + rng.normal(0, 0.05, (n_pos + n_neg, T, d))
    y = np.array([1.0] * n_pos + [0.0] * n_neg)
    perm = rng.permutation(len(y))
    return X[perm], y[perm]


def test_sequence_model_cnn1d_separable_pattern():
    X, y = cnn_data()
    tr, va = split(len(y), train_frac=0.7)
    m = sequence_model(X[tr], y[tr], kind="cnn1d", kernels=4,
                       kernel_size=3, epochs=150, lr=0.05, seed=0)
    assert m["kind"] == "sequence_cnn1d"
    assert m["sequence_length"] == 8 and m["n_features"] == 1
    assert len(m["loss_history"]) == 150
    assert m["loss_history"][-1] < m["loss_history"][0]
    p = m["predict_fn"](X[va])
    assert accuracy(p, y[va]) > 0.9


def test_sequence_model_rejects_other_kinds_and_bad_shape():
    X, y = cnn_data(10, 10)
    tr, _ = split(len(y), train_frac=0.7)
    with pytest.raises(ValueError, match="cnn1d"):
        sequence_model(X[tr], y[tr], kind="transformer")
    m = sequence_model(X[tr], y[tr])
    with pytest.raises(ValueError, match="expected"):
        m["predict_fn"](X[tr][:, :4, :])


# ---------------------------------------------------------------------------
# evaluate_model
# ---------------------------------------------------------------------------

def test_evaluate_model_returns_p_bad():
    X, y = separable_data(120)
    tr, va = split(len(y))
    _, _, _, predict_fn = standardized_logistic(X[tr], y[tr])
    p = evaluate_model(predict_fn, X[va], y[va])
    assert isinstance(p, np.ndarray)
    assert p.shape == (len(va),)
    assert float(p.min()) >= 0.0 and float(p.max()) <= 1.0
    p2 = evaluate_model((None, predict_fn), X[va], y[va])
    assert np.allclose(p, p2)
    with pytest.raises(TypeError):
        evaluate_model("not-a-model", X[va], y[va])


# ---------------------------------------------------------------------------
# operating points
# ---------------------------------------------------------------------------

def test_protected_operating_points_sane():
    rng = np.random.RandomState(0)
    p = rng.uniform(0.0, 1.0, 200)
    y = (p > 0.7).astype(float)
    ops = protected_operating_points(p, y)
    for key in ("protected_recall_95", "protected_recall_99"):
        item = ops[key]
        assert item["threshold"] is not None
        assert 0.0 <= item["protected_recall"] <= 1.0
        assert item["safe_accept_rate"] is not None
    assert ops["protected_recall_95"]["threshold"] >= ops["protected_recall_99"]["threshold"]


def test_protected_operating_points_no_positive_is_null():
    ops = protected_operating_points(np.zeros(50), np.zeros(50))
    assert ops["protected_recall_95"]["threshold"] is None
    assert ops["protected_recall_95"]["protected_recall"] is None
    assert ops["protected_recall_95"]["note"] == "no_positive_val"


# ---------------------------------------------------------------------------
# run_ablation：八组合 + H blocked
# ---------------------------------------------------------------------------

def _ablation_inputs(n=120, seed=5):
    rng = np.random.RandomState(seed)
    base = rng.uniform(-1.0, 1.0, (n, 2))
    y = (base[:, 0] + base[:, 1] > 0.0).astype(float)
    noise = lambda d: rng.normal(0, 0.3, (n, d))
    return {
        "H": base + noise(2),
        "R": base + noise(2),
        "O": base + noise(2),
        "V": base + noise(1),
    }, y


def test_run_ablation_eight_combos_structure():
    X_by_signal, y = _ablation_inputs()
    tr, va = split(len(y))
    result = run_ablation(X_by_signal, y, split_indices=(tr, va))
    assert result["schema"] == "MODEL_SELECTION.v1"
    assert result["model"] == "standardized_logistic"
    assert [c["combo"] for c in result["combos"]] == [
        "H", "R", "O", "H+R", "H+O", "R+O", "H+R+O", "H+R+O+V"]
    assert [tuple(c["signals"]) for c in result["combos"]] == list(ABLATION_COMBOS)
    json.dumps(result)  # 必须 JSON 可序列化
    for entry in result["combos"]:
        assert entry["status"] == "ok"
        assert entry["model"] == "standardized_logistic"
        assert entry["n_train"] + entry["n_val"] == len(y)
        for key in ("protected_recall_95", "protected_recall_99"):
            op = entry["operating_points"][key]
            assert op["threshold"] is not None
            assert op["protected_recall"] >= 0.95
            assert op["safe_accept_rate"] is not None
        assert entry["n_features"] >= 1


def test_run_ablation_dict_split_and_model_kind():
    X_by_signal, y = _ablation_inputs()
    tr, va = split(len(y))
    result = run_ablation(X_by_signal, y,
                          split_indices={"train": tr, "val": va},
                          model_kind="small_mlp", seed=1)
    assert result["model"] == "small_mlp"
    assert all(c["model"] == "small_mlp" for c in result["combos"])


def test_run_ablation_h_blocked_not_fabricated():
    X_by_signal, y = _ablation_inputs()
    X_by_signal["H"] = np.full((len(y), 6), np.nan)
    tr, va = split(len(y))
    result = run_ablation(X_by_signal, y, split_indices=(tr, va))
    h_combos = [c for c in result["combos"] if "H" in c["signals"]]
    ro_combos = [c for c in result["combos"] if "H" not in c["signals"]]
    assert len(h_combos) == 5 and len(ro_combos) == 3
    for entry in h_combos:
        assert entry["status"] == "blocked"
        assert entry["blocked_reason"]
        assert entry["n_train"] is None
        for key in ("protected_recall_95", "protected_recall_99"):
            assert entry[key]["threshold"] is None
            assert entry[key]["protected_recall"] is None
    for entry in ro_combos:
        assert entry["status"] == "ok"
        assert entry["operating_points"]["protected_recall_95"]["threshold"] is not None


def test_run_ablation_missing_signal_blocked():
    X_by_signal, y = _ablation_inputs()
    del X_by_signal["V"]
    tr, va = split(len(y))
    result = run_ablation(X_by_signal, y, split_indices=(tr, va))
    v_combo = [c for c in result["combos"] if c["combo"] == "H+R+O+V"][0]
    assert v_combo["status"] == "blocked"
    assert "missing" in v_combo["blocked_reason"]
    ok_combo = [c for c in result["combos"] if c["combo"] == "H+R+O"][0]
    assert ok_combo["status"] == "ok"


def test_run_ablation_partial_nan_trains_with_impute():
    X_by_signal, y = _ablation_inputs()
    X_by_signal["R"] = X_by_signal["R"].copy()
    X_by_signal["R"][::2, 0] = np.nan
    tr, va = split(len(y))
    result = run_ablation(X_by_signal, y, split_indices=(tr, va))
    entry = [c for c in result["combos"] if c["combo"] == "R"][0]
    assert entry["status"] == "ok"
    assert np.isfinite(entry["operating_points"]["protected_recall_95"]["threshold"])


def test_run_ablation_split_validation():
    X_by_signal, y = _ablation_inputs(80)
    tr, va = split(len(y))
    with pytest.raises(ValueError, match="partition"):
        run_ablation(X_by_signal, y, split_indices=(tr, va[: len(va) - 3]))
    with pytest.raises(ValueError, match="partition"):
        run_ablation(X_by_signal, y, split_indices=(tr, tr))
    with pytest.raises(ValueError):
        run_ablation(X_by_signal, y, split_indices=None)


def test_run_ablation_no_positive_val_is_null_not_blocked():
    X_by_signal, y = _ablation_inputs(100)
    y = np.zeros_like(y)  # 全是 safe 的 val 场景
    tr, va = split(len(y))
    result = run_ablation(X_by_signal, y, split_indices=(tr, va))
    entry = [c for c in result["combos"] if c["combo"] == "R"][0]
    assert entry["status"] == "ok"
    assert entry["operating_points"]["protected_recall_95"]["note"] == "no_positive_val"
