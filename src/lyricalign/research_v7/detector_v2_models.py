# -*- coding: utf-8 -*-
"""Detector V2 模型阶梯（Phase2-2，18 §9 / 20 §7，detector_v2_models.py）。

模型阶梯（18 §9，同一 evidence、同一 split 上比较）：
  1) rule_baseline         —— 单信号图谱 rule（可配置信号-阈值映射）；
  2) standardized_logistic —— 标准化手写 Logistic（风格同 region_assessor，但不复用其
                              模型/阈值，也不导入旧 E1 detector/risk score，见 21 §1）；
  3) constrained_gbdt      —— 受限深度回归树梯度提升（numpy，无 sklearn）；
  4) small_mlp             —— tanh 隐层 + logistic 输出的小型 MLP；
     hidden_linear_probe   —— 只对 H 特征做线性 probe（ridge → sigmoid）；
  5) sequence_model        —— 冻结的小型 1D CNN（1 卷积层 + max 池化 + 线性头，
                              numpy；pilot 后三选一，当前实现 CNN1D 为默认）。

输入契约：所有模型只消费特征矩阵（detector_v2_features 输出，None 以 NaN 表示），
绝不接触 GT/mutation/family。H blocked 时（信号矩阵全 NaN/缺失）对应组合标
`status=blocked`，不伪造零、不训练。缺失值在 train 上取列均值 impute（全缺失列
impute 0 → 标准化后贡献 0），predict_fn 携带 train 统计量，val/test 不再重算。

p_bad 语义：unit 为 bad（unsafe）的概率，越高越可疑。operating point 只在 val 上
冻结（protected_recall_95/99，同时公开 safe_accept_rate），见 18 §10/§11。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np

DEFAULT_SIGNALS = ("H", "R", "O", "V")
ABLATION_COMBOS = (
    ("H",),
    ("R",),
    ("O",),
    ("H", "R"),
    ("H", "O"),
    ("R", "O"),
    ("H", "R", "O"),
    ("H", "R", "O", "V"),
)
DEFAULT_RECALLS = (0.95, 0.99)
MODEL_KINDS = ("standardized_logistic", "constrained_gbdt", "small_mlp")

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _as_float(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return arr.reshape(1)
    return arr


def _impute_stats(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """train 上拟合 impute 均值与标准化统计量（全缺失列 impute 0 → 贡献 0）。"""
    n, d = X.shape
    finite = np.isfinite(X)
    col_impute = np.where(
        finite.any(axis=0), np.nanmean(X, axis=0), np.zeros(d))
    Ximp = np.where(finite, X, col_impute)
    mean = Ximp.mean(axis=0)
    std = Ximp.std(axis=0) + 1e-9
    return col_impute, mean, std


def _impute_standardize(X: np.ndarray, stats: tuple | None = None
                        ) -> tuple[np.ndarray, tuple]:
    if stats is None:
        stats = _impute_stats(X)
    col_impute, mean, std = stats
    finite = np.isfinite(X)
    Ximp = np.where(finite, X, col_impute)
    return (Ximp - mean) / std, stats


def _bce_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


# ---------------------------------------------------------------------------
# operating point：val 冻结 protected_recall_95/99 + safe_accept_rate
# ---------------------------------------------------------------------------

def protected_operating_points(p_bad: np.ndarray, y: np.ndarray, *,
                               recalls: Sequence[float] = DEFAULT_RECALLS) -> dict:
    """单 p_bad 线上的两个冻结工作点。

    定义：accept  ⇔ p_bad < threshold；protected（reject∪uncertain）⇔ p_bad >= threshold。
    protected_recall = unsafe 且 p_bad >= threshold 的比例；safe_accept_rate = 正确 unit
    中 p_bad < threshold 的比例。val 无正例 → 全部指标 null（18 §11 空分母必须为 null）。
    """
    p = _as_float(p_bad).ravel()
    y = _as_float(y).ravel()
    if len(p) != len(y):
        raise ValueError(f"p_bad length {len(p)} != y length {len(y)}")
    n_pos = int(np.sum(y > 0.5))
    n_safe = len(y) - n_pos
    out: dict = {}
    for r in recalls:
        key = f"protected_recall_{int(round(r * 100))}"
        if n_pos == 0:
            out[key] = {
                "threshold": None, "protected_recall": None, "safe_accept_rate": None,
                "recall_achieved": None, "n_unsafe": 0, "n_safe": n_safe,
                "note": "no_positive_val",
            }
            continue
        order = np.argsort(-p)
        cum = 0
        achieved = None
        threshold = None
        last_pos: int | None = None
        for idx in order:
            if y[idx] > 0.5:
                cum += 1
                last_pos = idx
            if cum / n_pos >= r:
                threshold = float(p[idx])
                achieved = float(cum / n_pos)
                break
        if threshold is None:
            threshold = float(p[last_pos])
            achieved = float(cum / n_pos)
        protected = (p >= threshold)
        n_protected = int(np.sum(protected & (y > 0.5)))
        n_safe_accept = int(np.sum((~protected) & (y <= 0.5)))
        out[key] = {
            "threshold": float(threshold),
            "protected_recall": round(n_protected / n_pos, 6),
            "safe_accept_rate": round(n_safe_accept / n_safe, 6) if n_safe else None,
            "recall_achieved": achieved,
            "n_unsafe": n_pos, "n_safe": n_safe, "note": None,
        }
    return out


# ---------------------------------------------------------------------------
# 1. rule baseline：单信号图谱
# ---------------------------------------------------------------------------

def rule_baseline(features: Mapping[str, Sequence[float]],
                  threshold_map: Mapping[str, Any]) -> np.ndarray:
    """单信号 rule：`features[name] > t`（默认）或 `< t`（direction="below"）→ p_bad=1。

    threshold_map: {feature_name: threshold} 或
                   {feature_name: {"threshold": t, "direction": "above"|"below"}}。
    任一 rule 命中 → p_bad=1.0，否则 0.0；缺失值（NaN/None）不触发 rule。
    """
    rules: list[tuple[np.ndarray, bool]] = []
    for name, spec in threshold_map.items():
        if name not in features:
            raise KeyError(f"rule feature {name!r} not in features")
        if isinstance(spec, Mapping):
            threshold = float(spec["threshold"])
            direction = str(spec.get("direction", "above"))
        else:
            threshold = float(spec)
            direction = "above"
        if direction not in ("above", "below"):
            raise ValueError(f"direction must be above|below, got {direction!r}")
        values = _as_float(features[name])
        if np.isfinite(values).any():
            finite = np.isfinite(values)
            base = np.zeros(len(values), dtype=float)
            if direction == "above":
                base[finite & (values > threshold)] = 1.0
            else:
                base[finite & (values < threshold)] = 1.0
            rules.append(base)
    if not rules:
        raise ValueError("threshold_map must contain at least one feature rule")
    return np.maximum.reduce(rules)


# ---------------------------------------------------------------------------
# 2. 标准化 Logistic（numpy 手写，参考 region_assessor.LogisticAssessor 风格）
# ---------------------------------------------------------------------------

def standardized_logistic(X: np.ndarray, y: np.ndarray, *,
                          epochs: int = 200, lr: float = 0.05,
                          l2: float = 1e-4, seed: int = 0
                          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, Callable]:
    """L2 logistic 梯度下降；返回 (beta, mean, std, predict_fn)。

    beta 首位为 bias；mean/std 为 train 标准化统计量；predict_fn(X_new) → p_bad
    数组（train 统计量闭合在闭包内，val/test 不再重算）。
    """
    del seed  # 梯度下降确定性，无需随机种子
    y = _as_float(y).ravel()
    n, d = X.shape
    if len(y) != n:
        raise ValueError(f"X rows {n} != y length {len(y)}")
    Xs, stats = _impute_standardize(_as_float(X))
    mean, std = stats[1], stats[2]
    Xb = np.hstack([np.ones((n, 1)), Xs])
    w = np.zeros(d + 1)
    for _ in range(epochs):
        p = _sigmoid(Xb @ w)
        grad = Xb.T @ (p - y) / n + l2 * w
        w -= lr * grad

    def predict_fn(X_new: np.ndarray) -> np.ndarray:
        Xn, _ = _impute_standardize(_as_float(X_new), stats)
        Xb_new = np.hstack([np.ones((len(Xn), 1)), Xn])
        return _sigmoid(Xb_new @ w)

    return w, mean, std, predict_fn


# ---------------------------------------------------------------------------
# 3. 受限 GBDT（深度受限回归树 + 梯度提升，numpy）
# ---------------------------------------------------------------------------

def _node_leaf(pred: float) -> dict:
    return {"pred": float(pred), "feature": None, "threshold": None,
            "left": None, "right": None}


def _build_tree(X: np.ndarray, y: np.ndarray, depth: int,
                max_depth: int, min_leaf: int) -> dict:
    n = len(y)
    if n == 0:
        return _node_leaf(0.0)
    if depth >= max_depth or n < 2 * min_leaf:
        return _node_leaf(float(np.mean(y)))
    parent_ss = float(np.sum((y - np.mean(y)) ** 2))
    best_gain = 1e-12
    best = None
    for feat in range(X.shape[1]):
        col = X[:, feat]
        order = np.argsort(col)
        xs = col[order]
        ys = y[order]
        uniq = np.unique(xs)
        if len(uniq) <= 1:
            continue
        if len(uniq) > 32:
            cuts = np.quantile(xs, np.linspace(0.0, 1.0, 33))
            cuts = np.unique(cuts)[1:-1]
        else:
            cuts = uniq
        cum = np.cumsum(ys)
        cum_sq = np.cumsum(ys ** 2)
        left = 0
        for cut in cuts:
            while left < n and xs[left] <= cut:
                left += 1
            if left < min_leaf or n - left < min_leaf:
                continue
            s_l = cum[left - 1] if left else 0.0
            s_l2 = cum_sq[left - 1] if left else 0.0
            s_r = cum[n - 1] - s_l
            s_r2 = cum_sq[n - 1] - s_l2
            ss = (s_l2 - s_l * s_l / left) + (s_r2 - s_r * s_r / (n - left))
            gain = parent_ss - ss
            if gain > best_gain:
                best_gain = gain
                best = (float(cut), feat, ys, xs, order)
    if best is None:
        return _node_leaf(float(np.mean(y)))
    cut, feat, ys, xs, order = best
    left_mask = col <= cut
    if left_mask.sum() < min_leaf or (~left_mask).sum() < min_leaf:
        return _node_leaf(float(np.mean(y)))
    node = {
        "feature": feat, "threshold": float(cut),
        "left": _build_tree(X[left_mask], y[left_mask], depth + 1, max_depth, min_leaf),
        "right": _build_tree(X[~left_mask], y[~left_mask], depth + 1, max_depth, min_leaf),
        "pred": None,
    }
    return node


def _tree_predict(node: dict, X: np.ndarray) -> np.ndarray:
    out = np.zeros(len(X))
    if node["feature"] is None:
        out[:] = node["pred"]
        return out
    mask = X[:, node["feature"]] <= node["threshold"]
    if node["left"] is not None:
        out[mask] = _tree_predict(node["left"], X[mask])
    if node["right"] is not None:
        out[~mask] = _tree_predict(node["right"], X[~mask])
    return out


def constrained_gbdt(X: np.ndarray, y: np.ndarray, *,
                     n_trees: int = 50, max_depth: int = 3,
                     lr: float = 0.1, min_leaf: int = 2) -> dict:
    """受限 GBDT（LSBoost + 深度受限回归树，squared loss 残差提升，预测 clip 到 [0,1]）。"""
    y = _as_float(y).ravel()
    n, d = X.shape
    if len(y) != n:
        raise ValueError(f"X rows {n} != y length {len(y)}")
    Xs, stats = _impute_standardize(_as_float(X))
    base = float(np.mean(y))
    F = np.full(n, base)
    trees: list[dict] = []
    loss_history: list[float] = []
    for _ in range(n_trees):
        residual = y - F
        tree = _build_tree(Xs, residual, 0, max_depth, min_leaf)
        trees.append(tree)
        F += lr * _tree_predict(tree, Xs)
        loss_history.append(float(np.mean(residual ** 2)))
    p = np.clip(F, 0.0, 1.0)

    def predict_fn(X_new: np.ndarray) -> np.ndarray:
        Xn, _ = _impute_standardize(_as_float(X_new), stats)
        Fn = np.full(len(Xn), base)
        for tree in trees:
            Fn += lr * _tree_predict(tree, Xn)
        return np.clip(Fn, 0.0, 1.0)

    return {"kind": "constrained_gbdt", "predict_fn": predict_fn,
            "trees": trees, "base": base, "shrinkage": lr,
            "n_trees": n_trees, "max_depth": max_depth,
            "train_mse_per_tree": loss_history}


# ---------------------------------------------------------------------------
# 4a. 小型 MLP（tanh 隐层 + logistic 输出）
# ---------------------------------------------------------------------------

def small_mlp(X: np.ndarray, y: np.ndarray, *,
              hidden: int = 16, epochs: int = 100, lr: float = 0.01,
              seed: int = 0) -> dict:
    """两层 MLP（tanh → sigmoid），BCE 梯度下降；返回权重 dict 与 predict_fn。"""
    y = _as_float(y).ravel()
    n, d = X.shape
    if len(y) != n:
        raise ValueError(f"X rows {n} != y length {len(y)}")
    Xs, stats = _impute_standardize(_as_float(X))
    rng = np.random.RandomState(seed)
    W1 = rng.normal(0.0, 1.0 / math.sqrt(d), (d, hidden))
    b1 = np.zeros(hidden)
    W2 = rng.normal(0.0, 1.0 / math.sqrt(hidden), (hidden, 1))
    b2 = np.zeros(1)
    y_col = y.reshape(n, 1)
    loss_history: list[float] = []
    for _ in range(epochs):
        a1 = np.tanh(Xs @ W1 + b1)
        p = _sigmoid(a1 @ W2 + b2)
        loss_history.append(_bce_loss(y_col, p))
        dz = (p - y_col) / n
        dW2 = a1.T @ dz
        db2 = dz.sum(axis=0)
        da1 = dz @ W2.T
        dact = da1 * (1.0 - a1 ** 2)
        dW1 = Xs.T @ dact
        db1 = dact.sum(axis=0)
        W2 -= lr * dW2
        b2 -= lr * db2
        W1 -= lr * dW1
        b1 -= lr * db1

    def predict_fn(X_new: np.ndarray) -> np.ndarray:
        Xn, _ = _impute_standardize(_as_float(X_new), stats)
        a1 = np.tanh(Xn @ W1 + b1)
        return _sigmoid(a1 @ W2 + b2).ravel()

    return {"kind": "small_mlp", "weights": {"W1": W1, "b1": b1, "W2": W2, "b2": b2},
            "predict_fn": predict_fn, "loss_history": loss_history,
            "hidden": hidden, "epochs": epochs, "lr": lr}

# ---------------------------------------------------------------------------
# 4b. hidden linear probe：只对 H 特征做线性 probe（ridge → sigmoid）
# ---------------------------------------------------------------------------

def hidden_linear_probe(X_h: np.ndarray, y: np.ndarray, *, l2: float = 1e-2,
                        epochs: int = 200, lr: float = 0.1) -> dict:
    """H 特征线性 probe：标准化 + 闭式 ridge 方向 + 一维 logistic 校准。

    只接受 H 特征矩阵（调用方从统一 feature table 选出 H 列）；H blocked
    （全 NaN）时由 run_ablation 拦截，不在这里伪造零。返回权重 dict 与 predict_fn。
    """
    y = _as_float(y).ravel()
    n, d = X_h.shape
    if len(y) != n:
        raise ValueError(f"X_h rows {n} != y length {len(y)}")
    Xs, stats = _impute_standardize(_as_float(X_h))
    Xb = np.hstack([np.ones((n, 1)), Xs])
    eye = np.eye(Xb.shape[1])
    w = np.linalg.solve(Xb.T @ Xb + l2 * eye, Xb.T @ y)
    z = Xb @ w
    scale = np.zeros(2)  # (a, b): p = sigmoid(a * z + b)
    for _ in range(epochs):
        p = _sigmoid(scale[0] * z + scale[1])
        err = (p - y) / n
        scale[0] -= lr * float(err @ z)
        scale[1] -= lr * float(err.sum())

    def predict_fn(X_new: np.ndarray) -> np.ndarray:
        Xn, _ = _impute_standardize(_as_float(X_new), stats)
        Xb_new = np.hstack([np.ones((len(Xn), 1)), Xn])
        return _sigmoid(scale[0] * (Xb_new @ w) + scale[1])

    return {"kind": "hidden_linear_probe", "weights": w,
            "calibration": scale, "l2": l2, "predict_fn": predict_fn}


# ---------------------------------------------------------------------------
# 5. 序列模型：冻结的小型 1D CNN（numpy：1 卷积层 + max 池化 + 线性头）
# ---------------------------------------------------------------------------

def sequence_model(X_seq: np.ndarray, y_seq: np.ndarray, *,
                   kind: str = "cnn1d", kernels: int = 4,
                   kernel_size: int = 3, epochs: int = 100,
                   lr: float = 0.05, seed: int = 0) -> dict:
    """小型 1D CNN（pilot 后三选一，当前实现 CNN1D 为默认）。

    输入 (n, T, d) 固定长度序列（canonical 顺序由调用方保持，见 20 §7：
    不得把同一首歌不同窗口随机打散）。统计量在 train 上按特征跨时间池化拟合。
    """
    if kind != "cnn1d":
        raise ValueError(
            f"sequence_model kind {kind!r} not implemented; pilot 后三选一，"
            f"当前仅实现 'cnn1d'")
    y = _as_float(y_seq).ravel()
    X = _as_float(X_seq)
    n, T, d = X.shape
    if len(y) != n:
        raise ValueError(f"X_seq rows {n} != y_seq length {len(y)}")
    if kernel_size > T:
        raise ValueError(f"kernel_size {kernel_size} > sequence length {T}")
    flat = X.reshape(n * T, d)
    finite = np.isfinite(flat)
    col_impute = np.where(finite.any(axis=0), np.nanmean(flat, axis=0), np.zeros(d))
    Ximp = np.where(finite, flat, col_impute)
    mean = Ximp.mean(axis=0)
    std = Ximp.std(axis=0) + 1e-9
    stats = (col_impute, mean, std)
    Xs = ((Ximp - mean) / std).reshape(n, T, d)

    rng = np.random.RandomState(seed)
    W1 = rng.normal(0.0, 0.5, (kernels, kernel_size, d))
    b1 = np.zeros(kernels)
    W2 = rng.normal(0.0, 0.5, (kernels,))
    b2 = np.zeros(1)
    T_out = T - kernel_size + 1
    loss_history: list[float] = []

    def conv_forward(Xb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        out = np.zeros((len(Xb), T_out, kernels))
        for t in range(T_out):
            window = Xb[:, t:t + kernel_size, :]  # (m, w, d)
            out[:, t, :] = np.einsum("mwd,kwd->mk", window, W1) + b1
        return np.tanh(out), out

    for _ in range(epochs):
        a, _ = conv_forward(Xs)
        pooled = a.max(axis=1)  # (n, kernels)
        p = _sigmoid(pooled @ W2 + b2)
        loss_history.append(_bce_loss(y, p))
        dz = (p - y).reshape(n, 1) / n
        dW2 = pooled.T @ dz
        db2 = dz.sum(axis=0)
        dpool = dz * W2[None, :]
        dact = np.zeros_like(a)
        argmax = a.argmax(axis=1)  # (n, kernels)
        dact[np.arange(n)[:, None], argmax, np.arange(kernels)[None, :]] = dpool
        dact *= (1.0 - a ** 2)
        dW1 = np.zeros_like(W1)
        db1 = dact.sum(axis=(0, 1))
        for k in range(kernels):
            for t in range(T_out):
                dW1[k] += (dact[:, t, k][:, None, None]
                           * Xs[:, t:t + kernel_size, :]).sum(axis=0)
        W1 -= lr * dW1
        b1 -= lr * db1
        W2 -= lr * dW2.ravel()
        b2 -= lr * db2

    def predict_fn(X_new: np.ndarray) -> np.ndarray:
        Xn = _as_float(X_new)
        if Xn.ndim != 3 or Xn.shape[1:] != (T, d):
            raise ValueError(f"X_new shape {Xn.shape} != expected (m, {T}, {d})")
        m = len(Xn)
        flat_new = Xn.reshape(m * T, d)
        Ximp_new = np.where(np.isfinite(flat_new), flat_new, col_impute)
        Xs_new = ((Ximp_new - mean) / std).reshape(m, T, d)
        a, _ = conv_forward(Xs_new)
        pooled = a.max(axis=1)
        return _sigmoid(pooled @ W2 + b2).ravel()

    return {"kind": "sequence_cnn1d", "weights": {"W1": W1, "b1": b1,
                                                  "W2": W2, "b2": b2},
            "predict_fn": predict_fn, "loss_history": loss_history,
            "kernels": kernels, "kernel_size": kernel_size,
            "sequence_length": T, "n_features": d,
            "epochs": epochs, "lr": lr}


# ---------------------------------------------------------------------------
# evaluate_model：冻结模型在 val 上输出 p_bad
# ---------------------------------------------------------------------------

def evaluate_model(fit_predict_fn: Any, X_val: np.ndarray, y_val: np.ndarray
                   ) -> np.ndarray:
    """对 val 特征矩阵返回 p_bad 数组（0/1 之外的中间值允许，供冻结阈值）。

    fit_predict_fn 可以是冻结模型的 predict_fn（callable(X_val) → p_bad），
    也可以是 (model, predict_fn) 元组（取 predict_fn）。
    """
    if (isinstance(fit_predict_fn, tuple) and len(fit_predict_fn) == 2
            and callable(fit_predict_fn[1])):
        predict_fn = fit_predict_fn[1]
    elif callable(fit_predict_fn):
        predict_fn = fit_predict_fn
    else:
        raise TypeError("fit_predict_fn must be callable or (model, predict_fn) tuple")
    y = _as_float(y_val)
    p = _as_float(predict_fn(X_val)).ravel()
    if len(p) != len(y):
        raise ValueError(f"p_bad length {len(p)} != y_val length {len(y)}")
    return p


# ---------------------------------------------------------------------------
# run_ablation：强制 H/R/O 消融（八组合），train/val 冻结
# ---------------------------------------------------------------------------

def _all_combos(signals: Sequence[str]) -> list[tuple[str, ...]]:
    base = tuple(signals)
    return [combo for combo in ABLATION_COMBOS
            if all(s in base for s in combo)]


def _concat_signals(X_by_signal: Mapping[str, np.ndarray],
                    combo: Sequence[str]) -> np.ndarray:
    parts = []
    n = None
    for s in combo:
        arr = _as_float(X_by_signal[s])
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        if n is None:
            n = len(arr)
        elif len(arr) != n:
            raise ValueError(f"signal {s!r} rows {len(arr)} != expected {n}")
        parts.append(arr)
    return np.hstack(parts)


def _combo_blocked(X_by_signal: Mapping[str, np.ndarray],
                   combo: Sequence[str]) -> str | None:
    for s in combo:
        if s not in X_by_signal or X_by_signal[s] is None:
            return f"signal {s!r} missing from X_by_signal (blocked; R/O 组合不受影响)"
        arr = _as_float(X_by_signal[s])
        if arr.size == 0 or not np.isfinite(arr).any():
            return f"signal {s!r} has no finite features (blocked; 不伪造零)"
    return None


def _resolve_split(split_indices, n: int) -> tuple[np.ndarray, np.ndarray]:
    if split_indices is None:
        raise ValueError("split_indices 必须提供 train/val 划分（同一 evidence 重复复用）")
    if isinstance(split_indices, Mapping):
        train = _as_float(split_indices["train"]).astype(int).ravel()
        val = _as_float(split_indices["val"]).astype(int).ravel()
    else:
        train, val = split_indices
        train = np.asarray(train, dtype=int).ravel()
        val = np.asarray(val, dtype=int).ravel()
    if len(train) + len(val) != n:
        raise ValueError(
            f"split_indices must partition all {n} samples, got train {len(train)} "
            f"+ val {len(val)}")
    if np.intersect1d(train, val).size:
        raise ValueError("split_indices train/val must not overlap")
    return train, val


def _null_entry_metrics(recalls: Sequence[float]) -> dict:
    out: dict = {}
    for r in recalls:
        key = f"protected_recall_{int(round(r * 100))}"
        out[key] = {"threshold": None, "protected_recall": None,
                    "safe_accept_rate": None, "recall_achieved": None,
                    "n_unsafe": None, "n_safe": None, "note": "blocked"}
    return out


def _make_trainer(model_kind: str, seed: int):
    if model_kind == "standardized_logistic":
        def trainer(Xtr, ytr, Xva, _seed=seed):
            _, _, _, predict_fn = standardized_logistic(Xtr, ytr, seed=_seed)
            return predict_fn(Xva)
    elif model_kind == "constrained_gbdt":
        def trainer(Xtr, ytr, Xva):
            return constrained_gbdt(Xtr, ytr)["predict_fn"](Xva)
    elif model_kind == "small_mlp":
        def trainer(Xtr, ytr, Xva, _seed=seed):
            return small_mlp(Xtr, ytr, seed=_seed)["predict_fn"](Xva)
    else:
        raise ValueError(
            f"model_kind {model_kind!r} not in {MODEL_KINDS}; 序列模型/rule 走单独入口")
    return trainer


def run_ablation(X_by_signal: Mapping[str, np.ndarray], y: np.ndarray, *,
                 signals: Sequence[str] = DEFAULT_SIGNALS,
                 groups: Mapping[str, Sequence[str]] | None = None,
                 split_indices: Any,
                 model_kind: str = "standardized_logistic",
                 recalls: Sequence[float] = DEFAULT_RECALLS,
                 seed: int = 0) -> dict:
    """八组合 H/R/O 消融（H/R/O/H+R/H+O/R+O/H+R+O/H+R+O+V），输出 MODEL_SELECTION 结构。

    每个组合 train/val 冻结：只允许在 train 上拟合，val 上求 protected_recall_95/99
    operating point 与 safe_accept_rate。H blocked（缺失或全 NaN）→ 含 H 组合标
    `status=blocked`（不伪造零、不训练），R/O 组合正常。
    """
    y = _as_float(y).ravel()
    n = len(y)
    train_idx, val_idx = _resolve_split(split_indices, n)
    combos = _all_combos(signals)
    trainer = _make_trainer(model_kind, seed=seed)
    entries: list[dict] = []
    for combo in combos:
        entry: dict = {
            "combo": "+".join(combo), "signals": list(combo),
            "model": model_kind, "status": "ok",
        }
        if groups:
            entry["feature_counts"] = {s: len(groups.get(s, ())) for s in combo}
        reason = _combo_blocked(X_by_signal, combo)
        if reason:
            entry["status"] = "blocked"
            entry["blocked_reason"] = reason
            entry["n_train"] = None
            entry["n_val"] = None
            entry["n_unsafe_train"] = None
            entry["n_unsafe_val"] = None
            entry["n_features"] = None
            for key, item in _null_entry_metrics(recalls).items():
                entry[key] = item
            entries.append(entry)
            continue
        X = _concat_signals(X_by_signal, combo)
        p_val = trainer(X[train_idx], y[train_idx], X[val_idx])
        ops = protected_operating_points(p_val, y[val_idx], recalls=recalls)
        entry["n_train"] = int(len(train_idx))
        entry["n_val"] = int(len(val_idx))
        entry["n_unsafe_train"] = int(np.sum(y[train_idx] > 0.5))
        entry["n_unsafe_val"] = int(np.sum(y[val_idx] > 0.5))
        entry["n_features"] = int(X.shape[1])
        entry["operating_points"] = ops
        entries.append(entry)
    return {
        "schema": "MODEL_SELECTION.v1",
        "model": model_kind,
        "signals": list(signals),
        "recalls": [int(round(r * 100)) for r in recalls],
        "split": {"n_train": int(len(train_idx)), "n_val": int(len(val_idx)),
                  "n_total": n},
        "combos": entries,
    }
