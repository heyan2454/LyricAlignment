"""WP6：region_assessor —— 子区间判别器（rule → logistic → 交互，train-only 拟合）。

对应 15 蓝图 §6.3：模型顺序固定 rule baseline → 标准化 logistic（unit 与 gap 分开）→
显式二阶交互 → 必要时受限浅层。只从 train 拟合；val 选 operating point（high_recall_95/99
最小阈值）；冻结后才可读 test。用 numpy（无 sklearn 依赖）。纯 CPU、可单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np


@dataclass
class LogisticAssessor:
    """带 L2 的手写 logistic（numpy 梯度下降，标准化在 train 上 fit）。"""

    beta: np.ndarray | None = None
    mean: np.ndarray | None = None
    std: np.ndarray | None = None
    intercept_lr: list[float] = None  # 可选：记录 lr
    frozen: bool = False

    def fit(self, X: np.ndarray, y: np.ndarray, *, epochs: int = 200, lr: float = 0.05, l2: float = 1e-4):
        n, d = X.shape
        self.mean = X.mean(0)
        self.std = X.std(0) + 1e-9
        Xs = (X - self.mean) / self.std
        Xs = np.hstack([np.ones((n, 1)), Xs])
        w = np.zeros(d + 1)
        for _ in range(epochs):
            z = Xs @ w
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))
            g = Xs.T @ (p - y) / n + l2 * w
            w -= lr * g
        self.beta = w
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.beta is None or self.mean is None or self.std is None:
            raise RuntimeError("fit before predict")
        Xs = (X - self.mean) / self.std
        Xs = np.hstack([np.ones((len(X), 1)), Xs])
        z = Xs @ self.beta
        return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def _high_recall_threshold(proba: np.ndarray, y: np.ndarray, target_recall: float, is_pos) -> float:
    """在 val 上找满足 target_recall 的最小概率阈值（frozen operating point）。"""
    order = np.argsort(-proba)
    cum_pos = 0
    n_pos = max(int(np.sum(y)), 1)
    thresh = 1.0
    for idx in order:
        if is_pos(y[idx]):
            cum_pos += 1
        rec = cum_pos / n_pos
        if rec >= target_recall:
            thresh = proba[idx]
            break
    return float(thresh)


def fit_and_freeze(
    train_X: np.ndarray, train_y: np.ndarray,
    val_X: np.ndarray, val_y: np.ndarray,
    *,
    recalls=(0.95, 0.99),
) -> dict:
    """fit logistic on train only; pick operating thresholds on val (frozen)."""
    m = LogisticAssessor().fit(train_X, train_y)
    proba = m.predict_proba(val_X)
    thresh = {}
    for r in recalls:
        thresh[f"high_recall_{int(r * 100)}"] = _high_recall_threshold(proba, val_y, r, lambda v: v > 0.5)
    return {"model": m, "operating_points": thresh, "train_only_gamma": None}


# rule baseline：单个特征阈值（如 raw_duration 或 margin）——由调用方指定 column。
def rule_assessor(train_features: Mapping[str, Sequence[float]], target_idx: Sequence[bool],
                  val_features, val_target) -> dict:
    """最简 rule：用某特征阈值输出 bool 判别（占位；正式用 14 §6.3 的 rule curve）。"""
    col = next(iter((k for k in train_features if "raw_duration" in k)), None)
    th = 0.12 if col else 0.0

    def pred(feats):
        return [1.0 if v > th else 0.0 for v in feats.get(col, [])] if col else [0.0] * len(val_target)

    return {"kind": "rule", "feature": col, "threshold": th, "val_pred": pred(val_features)}
