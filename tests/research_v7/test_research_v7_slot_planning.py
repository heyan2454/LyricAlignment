# -*- coding: utf-8 -*-
"""WP3 slot_planning 单测（15 蓝图 §6.1 最低单测）。"""
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


def test_plan_slots_keeps_order_and_topology_contiguous():
    p = plan_slots(plan_id="p1", canonical_unit_count=60, queried_canonical_ids=[0, 1, 2, 3],
                   comparison_group_id="g1")
    assert p.local_indices == (0, 1, 2, 3)
    assert p.topology == "contiguous"
    assert list(p.requested_canonical_ids) == [0, 1, 2, 3]


def test_reject_non_increasing():
    with pytest.raises(SlotPlanError):
        plan_slots(plan_id="x", canonical_unit_count=60, queried_canonical_ids=[3, 2, 4], comparison_group_id="g")


def test_reject_out_of_range():
    with pytest.raises(SlotPlanError):
        plan_slots(plan_id="x", canonical_unit_count=10, queried_canonical_ids=[0, 12], comparison_group_id="g")


def test_topology_two_and_three_regions():
    assert detect_topology([0, 1, 6, 7]) == "two_regions"
    assert detect_topology([0, 1, 6, 7, 20, 21]) == "three_regions"
    assert detect_topology([0, 2, 4]) == "review"


def test_non_contiguous_slot_group_id_preserved():
    a = plan_slots(plan_id="a", canonical_unit_count=60, queried_canonical_ids=[0, 5, 12], comparison_group_id="grp")
    b = plan_slots(plan_id="b", canonical_unit_count=60, queried_canonical_ids=[1, 6, 30], comparison_group_id="grp")
    assert a.topology != "contiguous"
    assert a.comparison_group_id == b.comparison_group_id == "grp"


def test_common_anchors_intersects_all_strategies():
    ids = {100: [0, 1, 2, 3, 4, 5, 6, 7], 2: [0, 2, 4, 6], 4: [0, 4], 8: [0]}
    anchors = common_anchors(ids)
    assert set(anchors) == {0}


def test_id_at_stride():
    assert id_at_stride(10, 4) == [0, 4, 8]


def test_build_density_plans_phase_rotation():
    plans = build_density_plans(plan_group="g", canonical_unit_count=16, base_ids=[0, 1, 2, 3], step=4, phase_offsets=[0, 1, 2])
    assert len(plans) == 3
    assert plans[0].phase_name == "p0"
    assert plans[1].phase_name == "p1"
    assert plans[2].phase_name == "p2"
    assert all(p.comparison_group_id == "g" for p in plans)
