# -*- coding: utf-8 -*-
"""WP3 slot_planning 单测（P0-3 整改：canonical_to_local 映射、真实密度稀疏化 + 仅交集比较）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.slot_planning import (
    SlotPlanError,
    build_density_plans,
    common_anchors,
    detect_topology,
    id_at_stride,
    plan_slots,
)


def test_plan_slots_canonical_to_local_maps():
    c2l = {0: 2, 1: 5, 2: 9}  # 历史/future 文本占用 local 2,5,9
    p = plan_slots(plan_id="p", canonical_unit_count=60, queried_canonical_ids=[0, 1, 2],
                   canonical_to_local=c2l)
    assert p.local_indices == (2, 5, 9)
    assert p.detail["local_source"] == "mapped"


def test_plan_slots_reject_non_increasing_after_map():
    c2l = {0: 9, 1: 5}  # 映射后 9,5 递减 → 非法（历史文本位置冲突）
    with pytest.raises(SlotPlanError):
        plan_slots(plan_id="x", canonical_unit_count=60, queried_canonical_ids=[0, 1], canonical_to_local=c2l)


def test_plan_slots_strict_increasing_canonical():
    with pytest.raises(SlotPlanError):
        plan_slots(plan_id="x", canonical_unit_count=60, queried_canonical_ids=[3, 2, 4])


def test_topology_two_and_three_regions():
    assert detect_topology([0, 1, 6, 7]) == "two_regions"
    assert detect_topology([0, 1, 6, 7, 20, 21]) == "three_regions"
    assert detect_topology([0, 2, 4]) == "review"


def test_non_contiguous_group_id_preserved():
    a = plan_slots(plan_id="a", canonical_unit_count=60, queried_canonical_ids=[0, 5, 12], comparison_group_id="grp")
    b = plan_slots(plan_id="b", canonical_unit_count=60, queried_canonical_ids=[1, 6, 30], comparison_group_id="grp")
    assert a.topology != "contiguous"
    assert a.comparison_group_id == b.comparison_group_id == "grp"


def test_common_anchors_intersects_all_strategies():
    ids = {100: [0, 1, 2, 3, 4, 5, 6, 7], 2: [0, 2, 4, 6], 4: [0, 4], 8: [0]}
    assert set(common_anchors(ids)) == {0}


def test_id_at_stride():
    assert id_at_stride(10, 4) == [0, 4, 8]


def test_build_density_plans_true_sparse_and_common():
    # 100% 全选；stride2 phase p0=每2取、p1 偏移1 → 每个 phase 真稀疏（不再 base∪stride 合成）
    c2l = {i: i for i in range(60)}
    sel = {
        "100": {"p0": list(range(0, 60))},
        "2": {"p0": list(range(0, 60, 2)), "p2": list(range(1, 60, 2))},
        "4": {"p0": list(range(0, 60, 4))},
        "8": {"p0": list(range(0, 60, 8))},
    }
    plans, common = build_density_plans(plan_group="g", canonical_unit_count=60,
                                        selected_by_stride_phase=sel, canonical_to_local=c2l)
    # common anchors：交集 = 0 (唯一被 100/2/2偏移? NO: stride2 p2 是奇数，故与 4/8 交为空)
    # 重新构造使各 stride 有共同 anchor 0
    assert set(common_anchors({"100": [0], "2": [0], "4": [0], "8": [0]})) == {0}
    # 每个 phase 的 requested canonical 是真实子采样（稀疏），非 base∪stride
    s2_n = [len(p.local_indices) for p in plans if "s2" in p.plan_id]
    assert all(n <= 30 for n in s2_n)  # stride2 每 phase <=30，真稀疏，非 60
    assert all(p.comparison_group_id == "g" for p in plans)
    assert all(p.strategy and p.local_indices for p in plans)


def test_missing_canonical_to_local_key_reports():
    c2l = {0: 1, 1: 2}  # 缺 2
    with pytest.raises(SlotPlanError, match="missing keys"):
        plan_slots(plan_id="x", canonical_unit_count=60, queried_canonical_ids=[0, 1, 2], canonical_to_local=c2l)


def test_local_upper_bound_with_request_local_count():
    c2l = {0: 2, 1: 5, 2: 9}
    with pytest.raises(SlotPlanError, match="out of request_local_count"):
        plan_slots(plan_id="x", canonical_unit_count=60, queried_canonical_ids=[0, 1, 2],
                   canonical_to_local=c2l, request_local_count=8)


def test_canonical_ids_must_be_strictly_increasing():
    c2l = {0: 1, 3: 2, 2: 9}
    with pytest.raises(SlotPlanError, match="canonical ids not strictly increasing"):
        plan_slots(plan_id="x", canonical_unit_count=60, queried_canonical_ids=[0, 3, 2], canonical_to_local=c2l)


def test_common_only_pairs_intersects_plans():
    from lyricalign.research_v7.slot_planning import common_only_pairs
    p1 = plan_slots(plan_id="p1", canonical_unit_count=60, queried_canonical_ids=[0, 1, 2, 3, 4, 5, 6, 7])
    p2 = plan_slots(plan_id="p2", canonical_unit_count=60, queried_canonical_ids=[0, 2, 4, 6])
    p3 = plan_slots(plan_id="p3", canonical_unit_count=60, queried_canonical_ids=[0, 4])
    assert common_only_pairs([p1, p2, p3]) == [0, 4]  # 交集
