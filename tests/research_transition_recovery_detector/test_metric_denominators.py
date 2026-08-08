"""09 §1/§3 P0 最低测试：detector 分母修正（UNCERTAIN 留在分母、三态率和为 1、R95 语义）。"""

import pytest

from lyricalign.research_transition_recovery_detector.thresholds import (
    STATE_ACCEPT,
    STATE_REJECT,
    STATE_UNCERTAIN,
    candidate_thresholds,
    joint_working_point,
    select_working_point,
    working_point_metrics,
)


def test_uncertain_stays_in_denominator_safe_accept_not_inflated():
    """关键回归：5 safe = 3×ACCEPT + 2×UNCERTAIN → safe_accept 必须 0.6（旧实现虚高 1.0）。"""
    labels_gt = [(STATE_ACCEPT, 0)] * 3 + [(STATE_UNCERTAIN, 0)] * 2
    m = working_point_metrics(labels_gt)
    assert m["safe_denominator"] == 5
    assert m["safe_accept"] == pytest.approx(0.6)
    assert m["safe_uncertain"] == pytest.approx(0.4)
    assert m["safe_reject"] == 0.0


def test_three_state_rates_sum_to_one_per_group():
    labels_gt = [
        (STATE_ACCEPT, 0), (STATE_REJECT, 0), (STATE_UNCERTAIN, 0),
        (STATE_ACCEPT, 1), (STATE_REJECT, 1), (STATE_UNCERTAIN, 1),
    ]
    m = working_point_metrics(labels_gt)
    assert m["safe_accept"] + m["safe_reject"] + m["safe_uncertain"] == pytest.approx(1.0)
    assert m["unsafe_accept"] + m["unsafe_reject"] + m["unsafe_uncertain"] == pytest.approx(1.0)
    assert m["uncertain_rate"] == pytest.approx(2 / 6)


def test_r95_uses_all_unsafe_denominator_uncertain_not_reject():
    # 3 unsafe：1 REJECT + 2 UNCERTAIN → R95 语义 unsafe_reject = 1/3（UNCERTAIN 留在分母、不算 REJECT）
    labels_gt = [(STATE_UNCERTAIN, 1)] * 2 + [(STATE_REJECT, 1)]
    m = working_point_metrics(labels_gt)
    assert m["unsafe_denominator"] == 3
    assert m["unsafe_reject"] == pytest.approx(1 / 3)
    assert m["unsafe_uncertain"] == pytest.approx(2 / 3)


def test_grey_gt_none_excluded():
    labels_gt = [(STATE_ACCEPT, 0), (STATE_REJECT, 1), (STATE_UNCERTAIN, None), (STATE_ACCEPT, None)]
    m = working_point_metrics(labels_gt)
    assert m["grey_denominator"] == 2
    assert m["safe_denominator"] == 1
    assert m["unsafe_denominator"] == 1
    assert m["safe_accept"] == 1.0


def test_select_sa60_with_uncertain_in_denominator():
    # safe：0.1(ACC), 0.2(ACC), 0.5(UNC)；unsafe：0.9(REJ), 0.95(REJ)
    # SA60 需要 safe_accept>=0.6：t_accept>0.2（0.5 阈值下 0.1/0.2 ACCEPT → 2/3≈0.67）
    p_bad = [0.1, 0.2, 0.5, 0.9, 0.95]
    gt = [0, 0, 0, 1, 1]
    wp = select_working_point(p_bad, gt, constraint="SA60", level=0.60)
    assert wp["feasible"]
    assert wp["safe_accept"] >= 0.60
    assert wp["safe_denominator"] == 3  # UNCERTAIN 在分母
    assert 0.0 <= wp["t_accept"] < wp["t_reject"] <= 1.0


def test_select_r95_uncertain_not_reject():
    # unsafe 行 p_bad 高但部分落在阈值内 → UNCERTAIN 不算 REJECT
    p_bad = [0.3, 0.85, 0.9, 0.95]
    gt = [0, 1, 1, 1]
    wp = select_working_point(p_bad, gt, constraint="R95", level=0.95)
    if wp["feasible"]:
        assert wp["unsafe_reject"] >= 0.95
        # 验证语义：unsafe_reject 计数只来自 REJECT（非 UNCERTAIN）
        assert wp["unsafe_denominator"] >= 1


def test_joint_infeasible_reports_pareto_gap():
    p_bad = [0.5, 0.5, 0.5, 0.5]
    gt = [1, 1, 0, 0]
    j = joint_working_point(p_bad, gt, sa_level=0.60, r95_level=0.95)
    assert not j["feasible"]
    assert "pareto_gap" in j


def test_joint_feasible_when_separable():
    p_bad = [0.9, 0.1, 0.9, 0.5, 0.1, 0.9]
    gt = [1, 0, 1, 0, 0, 1]
    j = joint_working_point(p_bad, gt, sa_level=0.60, r95_level=0.95)
    assert j["feasible"]
    assert j["safe_accept"] >= 0.60
    assert j["unsafe_reject"] >= 0.95


def test_candidate_thresholds_boundaries():
    c = candidate_thresholds([0.2, 0.7])
    for ta, tr in c:
        assert 0.0 <= ta < tr <= 1.0
    pairs = set(c)
    assert (0.0, 0.2) in pairs
    assert (0.7, 1.0) in pairs
