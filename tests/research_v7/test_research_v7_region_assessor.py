# -*- coding: utf-8 -*-
"""WP6 region_assessor 单测。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.region_assessor import LogisticAssessor, fit_and_freeze


def test_logistic_fit_predicts():
    rng = np.random.RandomState(0)
    X = rng.rand(80, 3)
    y = ((X[:, 0] + 0.3 * X[:, 1]) > 0.5).astype(int)
    m = LogisticAssessor().fit(X, y)
    p = m.predict_proba(X)
    assert p.shape == (80,)
    assert ((p > 0.5) == y.astype(bool)).mean() > 0.9


def test_fit_and_freeze_returns_thresholds():
    rng = np.random.RandomState(1)
    Xt = rng.rand(100, 3)
    yt = ((Xt[:, 0] > 0.5)).astype(int)
    Xv = rng.rand(100, 3)
    yv = ((Xv[:, 0] > 0.5)).astype(int)
    out = fit_and_freeze(Xt, yt, Xv, yv)
    assert "model" in out and "operating_points" in out
    for k in ("high_recall_95", "high_recall_99"):
        assert k in out["operating_points"]
    assert 0.0 < out["operating_points"]["high_recall_95"] <= 1.0


def test_predict_requires_fit():
    import pytest

    with pytest.raises(RuntimeError):
        LogisticAssessor().predict_proba(np.zeros((2, 2)))
