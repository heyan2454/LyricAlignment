"""P 信号 v2：exact k-best monotonic DP 的验收测试。

覆盖 11 计划 D4 要求：
1. 唯一路径 case；
2. 两条明显路径 case；
3. repeated-occurrence 双峰路径 case；
4. 第二路径违反单调性 case；
5. second path 与 first path 相同必须被拒绝；
6. 随机小矩阵 brute-force oracle 比较（k-best 排序与 score）。
"""
from __future__ import annotations

import itertools

import numpy as np

from lyricalign.research_transition_recovery_detector.posterior_paths import (
    _kbest_paths,
    competing_path_features,
    unit_p_features,
)


def _monotone_paths(n_slots: int, n_classes: int) -> list[tuple[int, ...]]:
    """穷举所有单调（非递减）class 序列。"""
    out = []
    for seq in itertools.product(range(n_classes), repeat=n_slots):
        if all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)):
            out.append(seq)
    return out


def _path_score(probs: np.ndarray, classes: tuple[int, ...]) -> float:
    score = 0.0
    for i, c in enumerate(classes):
        p = float(probs[i, c])
        if p <= 0.0:
            return -float("inf")
        score += np.log(p)
    return score


def test_unique_path_single_mode():
    """单峰 posterior：只有唯一一条单调路径，无 distinct second。"""
    probs = np.array(
        [
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    feat = competing_path_features(probs)
    assert feat["status"] == "unique_posterior"
    assert feat["has_distinct_second_path"] is False
    assert feat["second_path_score"] is None
    assert feat["differing_slot_fraction"] == 0.0


def test_two_distinct_paths():
    """两条明显路径：best 与 second 在不同 slot 上不同。"""
    probs = np.array(
        [
            [0.6, 0.4],
            [0.6, 0.4],
            [0.6, 0.4],
        ],
        dtype=np.float32,
    )
    feat = competing_path_features(probs)
    assert feat["status"] == "ok"
    assert feat["has_distinct_second_path"] is True
    assert feat["differing_slot_fraction"] > 0.0
    assert feat["second_path_classes"] is not None
    assert feat["best_path_classes"] != feat["second_path_classes"]


def test_repeated_occurrence_bimodal():
    """repeated-occurrence 双峰：存在可区分 second path 且有非零位移。"""
    probs = np.array(
        [
            [0.0, 0.9, 0.1],
            [0.0, 0.9, 0.1],
            [0.1, 0.0, 0.9],
            [0.1, 0.0, 0.9],
        ],
        dtype=np.float32,
    )
    feat = competing_path_features(probs)
    assert feat["status"] == "ok"
    assert feat["has_distinct_second_path"] is True
    assert feat["differing_slot_fraction"] > 0.0
    assert feat["max_time_displacement"] >= 1
    assert feat["second_path_classes"] != feat["best_path_classes"]


def test_nonmonotonic_second_rejected():
    """第二路径违反单调性：DP 输出仍必须单调。"""
    probs = np.array(
        [
            [0.001, 0.999],
            [0.999, 0.001],
            [0.001, 0.999],
        ],
        dtype=np.float32,
    )
    # per-slot argmax = [1, 0, 1] 非单调；DP 只输出单调路径
    paths = _kbest_paths(probs, k=4)
    for p in paths:
        cls = p["classes"]
        assert all(cls[i] <= cls[i + 1] for i in range(len(cls) - 1))


def test_duplicate_best_rejected_as_second():
    """second path 与 best 相同必须被拒绝（min_changed_slots 阈值）。

    构造：只有两个可行单调路径 [0,0] 与 [0,1]，best=[0,0]（score 高），
    second=[0,1] 差异仅 1 个 slot。min_changed_slots=2 时必须拒绝。
    """
    probs = np.array(
        [
            [0.99, 0.01],
            [0.01, 0.99],
        ],
        dtype=np.float32,
    )
    # 单调路径：all -> [0,0],[0,1],[1,1]（[1,0] 非单调被拒）
    # best=[0,1]（0.99*0.99 最高），候选 [0,0] 与 [1,1] 差异各 1 slot
    feat = competing_path_features(probs, min_changed_slots=2)
    assert feat["has_distinct_second_path"] is False
    assert feat["status"] in ("unique_posterior", "no_distinct_path_under_constraints")


def test_kbest_matches_brute_force_oracle():
    """随机小矩阵：_kbest_paths 的 top-k 排序与 score 必须与穷举一致。"""
    rng = np.random.default_rng(0)
    for trial in range(20):
        n_slots = int(rng.integers(2, 5))
        n_classes = int(rng.integers(2, 5))
        logits = rng.normal(size=(n_slots, n_classes))
        probs = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs /= probs.sum(axis=1, keepdims=True)
        probs = probs.astype(np.float32)

        # 穷举所有单调路径
        all_paths = []
        for seq in _monotone_paths(n_slots, n_classes):
            score = _path_score(probs, seq)
            if np.isfinite(score):
                all_paths.append((score, list(seq)))
        all_paths.sort(key=lambda x: -x[0])

        k = 3
        kbest = _kbest_paths(probs, k=k)
        assert len(kbest) == min(k, len(all_paths)), (
            f"trial {trial}: kbest len {len(kbest)} != expected {min(k, len(all_paths))}")
        for i, p in enumerate(kbest):
            assert p["classes"] == all_paths[i][1], (
                f"trial {trial} rank {i}: {p['classes']} != {all_paths[i][1]}")
            assert abs(p["score"] - all_paths[i][0]) < 1e-4, (
                f"trial {trial} rank {i} score: {p['score']} != {all_paths[i][0]}")


def test_unit_p_features_local_fields():
    """unit_p_features 输出 unit 级 local P 特征。"""
    probs = np.array(
        [
            [0.6, 0.4],
            [0.6, 0.4],
            [0.6, 0.4],
            [0.6, 0.4],
        ],
        dtype=np.float32,
    )
    slot_to_unit = [0, 0, 1, 1]  # unit0: slot0/1, unit1: slot2/3
    rows = unit_p_features(probs, slot_to_unit)
    assert len(rows) == 2
    for r in rows:
        assert r["status"] == "ok"
        assert "local_second_path_gap" in r
        assert "local_boundary_disagreement" in r
        assert "local_alternate_run_membership" in r
        assert "local_displacement" in r
        assert "top2_gap" in r
