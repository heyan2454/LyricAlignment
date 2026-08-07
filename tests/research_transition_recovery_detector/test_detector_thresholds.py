"""Phase 6：detector features / thresholds 纯函数测试（no label leak 关键）。"""

import pytest

from lyricalign.research_transition_recovery_detector.detector_features import (
    extract_unit_features,
    rows_to_matrix,
)
from lyricalign.research_transition_recovery_detector.thresholds import (
    STATE_ACCEPT,
    STATE_REJECT,
    STATE_UNCERTAIN,
    candidate_thresholds,
    joint_working_point,
    select_working_point,
    tristate_labels,
    working_point_metrics,
)


def make_row(**overrides):
    base = {
        "global_character_index": 0,
        "fixed_global_start_sec": 10.0,
        "fixed_global_end_sec": 10.5,
        "raw_start_entropy": 0.5,
        "raw_end_entropy": 0.6,
        "raw_start_margin": 0.3,
        "raw_end_margin": 0.2,
        "raw_start_top1_probability": 0.7,
        "raw_end_top1_probability": 0.65,
        "official_fixed_global_start_sec": 10.2,
        "raw_start_topk_probabilities": [0.7, 0.2, 0.1],
    }
    base.update(overrides)
    return base


def test_extract_features_basic():
    f = extract_unit_features(make_row())
    assert f["raw_start_entropy"] == pytest.approx(0.5)
    assert f["raw_official_start_diff_sec"] == pytest.approx(0.2)
    assert f["start_top2_gap_sec"] == pytest.approx(0.5)
    assert f["raw_end_entropy"] == pytest.approx(0.6)


def test_extract_features_missing_fields():
    f = extract_unit_features({"global_character_index": 0})
    assert all(v is None for v in f.values())


def test_rows_to_matrix_labels():
    gt = {0: {"start_sec": 10.1}, 1: {"start_sec": 20.0}}
    rows = [make_row(), make_row(global_character_index=1, fixed_global_start_sec=24.0)]
    feats, labels = rows_to_matrix(rows, gt, tolerance_sec=0.32)
    assert labels == [0.0, 1.0]  # 10.0 vs 10.1 safe; 24.0 vs 20.0 unsafe
    assert feats[1]["raw_start_entropy"] == 0.5


def test_no_label_leak():
    """label 只由 gt 参数 + fixed_global_start_sec 决定；row 中任何其他字段不得影响 label。"""
    gt = {0: {"start_sec": 10.1}}
    rows = [
        make_row(gt_leak=1.0, suspicious="high", raw_start_top1_probability=0.0),
        make_row(gt_leak=0.0, suspicious="low", raw_start_top1_probability=0.99),
    ]
    feats, labels = rows_to_matrix(rows, gt, tolerance_sec=0.32)
    assert labels == [0.0, 0.0]  # 两行预测相同 → 标签相同，不随其他字段变化


def test_rows_to_matrix_no_gt():
    feats, labels = rows_to_matrix([make_row()], None)
    assert labels == [None]
    assert feats[0]["raw_start_margin"] == 0.3


def test_candidate_thresholds():
    c = candidate_thresholds([0.2, 0.2, 0.7, 0.0, 1.0])
    pairs = set(c)
    assert (0.0, 0.2) in pairs and (0.2, 0.7) in pairs and (0.7, 1.0) in pairs
    assert (0.2, 0.2) not in pairs  # T_accept < T_reject
    for ta, tr in c:
        assert 0.0 <= ta < tr <= 1.0


def test_tristate_labels():
    assert tristate_labels(0.1, 0.2, 0.8) == STATE_ACCEPT
    assert tristate_labels(0.9, 0.2, 0.8) == STATE_REJECT
    assert tristate_labels(0.5, 0.2, 0.8) == STATE_UNCERTAIN


def test_working_point_metrics_uncertain_not_reject():
    labels_gt = [
        (STATE_ACCEPT, 0), (STATE_ACCEPT, 1), (STATE_REJECT, 1), (STATE_REJECT, 0),
        (STATE_UNCERTAIN, 1), (STATE_UNCERTAIN, 0), (STATE_UNCERTAIN, None),
    ]
    m = working_point_metrics(labels_gt)
    assert m["safe_accept"] == 0.5
    assert m["unsafe_reject"] == 0.5  # 1 unsafe rejected + 1 unsafe accepted; UNCERTAIN 不进分母
    assert m["unsafe_denominator"] == 2
    assert m["safe_denominator"] == 2
    assert m["grey_denominator"] == 3


def test_select_sa60():
    p_bad = [0.9, 0.1, 0.85, 0.2, 0.05, 0.95, 0.15, 0.3]
    gt = [1, 0, 1, 0, 0, 1, 0, 0]
    wp = select_working_point(p_bad, gt, constraint="SA60", level=0.60)
    assert wp["feasible"]
    assert wp["safe_accept"] >= 0.60
    assert 0.0 <= wp["t_accept"] < wp["t_reject"] <= 1.0


def test_select_r95():
    p_bad = [0.9, 0.1, 0.85, 0.2, 0.05, 0.95, 0.15, 0.3]
    gt = [1, 0, 1, 0, 0, 1, 0, 0]
    wp = select_working_point(p_bad, gt, constraint="R95", level=0.95)
    assert wp["feasible"]
    assert wp["unsafe_reject"] >= 0.95


def test_joint_infeasible():
    # 无法同时 SA60 + R95：构造冲突标签（同一 p_bad 值既 safe 又 unsafe）
    p_bad = [0.5, 0.5, 0.5, 0.5]
    gt = [1, 1, 0, 0]
    j = joint_working_point(p_bad, gt, sa_level=0.60, r95_level=0.95)
    assert not j["feasible"]
    assert "pareto_gap" in j


def test_joint_feasible():
    # 三值分布：0.1 safe / 0.5 safe / 0.9 unsafe → t_accept=0.5, t_reject=0.9 联合可行
    p_bad = [0.9, 0.1, 0.9, 0.5, 0.1, 0.9]
    gt = [1, 0, 1, 0, 0, 1]
    j = joint_working_point(p_bad, gt, sa_level=0.60, r95_level=0.95)
    assert j["feasible"]
    assert j["safe_accept"] >= 0.60 and j["unsafe_reject"] >= 0.95
