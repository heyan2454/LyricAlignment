"""posterior_paths 纯函数测试（P 信号：competing coherent path）。"""

import numpy as np
import pytest

from lyricalign.research_transition_recovery_detector.posterior_paths import (
    competing_path_features,
    unit_p_features,
)


def test_competing_path_features_clear_winner():
    # 5 slots：best 路径单调 1..5 高置信，无真正 alternate path（diverse=False）
    rng = np.random.default_rng(0)
    probs = np.zeros((5, 10))
    for i in range(5):
        probs[i, i + 1] = 0.8
        probs[i, rng.integers(0, 10)] += 0.2
    probs /= probs.sum(axis=1, keepdims=True)
    f = competing_path_features(probs)
    assert f["status"] == "ok"
    assert f["second_path_diverse"] is False  # 无整体 alternate path（P=无歧义）
    assert f["differing_slot_fraction"] == 0.0


def test_competing_path_alternate_diverse():
    # 两条候选路径竞争（0.55/0.45）：diversity 过滤后存在真正 alternate path
    probs = np.zeros((5, 12))
    for i in range(5):
        probs[i, i + 1] = 0.55
        probs[i, i + 3] = 0.45
    probs /= probs.sum(axis=1, keepdims=True)
    f = competing_path_features(probs)
    assert f["status"] == "ok"
    assert f["second_path_diverse"] is True
    assert f["differing_slot_fraction"] >= 0.5
    assert f["normalized_score_gap"] is not None


def test_unit_p_features_per_unit_row():
    # 3 units × 2 slots = 6 slots；每 unit start slot 的 top2
    probs = np.zeros((6, 8))
    for i in range(6):
        probs[i, i % 8] = 0.7
        probs[i, (i + 1) % 8] = 0.3
    slot_to_unit = [0, 0, 1, 1, 2, 2]
    rows = unit_p_features(probs, slot_to_unit)
    assert len(rows) == 3
    assert rows[0]["canonical_id"] == 0
    assert rows[0]["top2_gap"] == pytest.approx(0.4)
    assert rows[2]["status"] == "ok" if False else rows[2]["top2_gap"] is not None
