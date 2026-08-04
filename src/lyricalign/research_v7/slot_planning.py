"""WP3：slot_planning —— 从 canonical quered ids 规划本地 timestamp slot。

对应 15 蓝图 §6.1：
- 只接受 canonical queried ids（不用局部偶然 index）；
- 输出严格递增的本地 timestamp indices 与 topology（contiguous|two_regions|three_regions|review|anchors）；
- density 主比较先求 100% 与 stride 2/4/8 都命中的 common anchors；每种 stride 轮换 phase；
- 汇总只在同一 common-anchor 集合上成对比较；非连续 slot 保留同一 comparison_group_id。

纯函数、纯 CPU、可单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


class SlotPlanError(ValueError):
    pass


@dataclass(frozen=True)
class SlotPlan:
    plan_id: str
    requested_canonical_ids: tuple[int, ...]
    local_indices: tuple[int, ...]     # 严格递增的本地 timestamp token index
    topology: str
    comparison_group_id: str
    phase_name: str
    strategy: str                      # contiguous | strided<step> | anchors
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id, "requested_canonical_ids": list(self.requested_canonical_ids),
            "local_indices": list(self.local_indices), "topology": self.topology,
            "comparison_group_id": self.comparison_group_id, "phase_name": self.phase_name,
            "strategy": self.strategy, "detail": self.detail,
        }


def detect_topology(ids: Sequence[int]) -> str:
    """根据请求的 canonical 集判定拓扑（两/三区/contiguous/anchors/review）。

    按连续簇判定：1 簇=contiguous；2 簇=two_regions；>=3 簇且所有簇长度1=review；
    >=3 簇且含长度>1=three_regions；空或单点=anchors/review。
    """
    s = sorted(set(ids))
    if not s:
        return "review"
    if len(s) == 1:
        return "anchors"
    clusters = []
    cur = [s[0]]
    for i in range(1, len(s)):
        if s[i] == cur[-1] + 1:
            cur.append(s[i])
        else:
            clusters.append(cur)
            cur = [s[i]]
    clusters.append(cur)
    n = len(clusters)
    if n == 1:
        return "contiguous"
    if n == 2:
        return "two_regions" if any(len(c) > 1 for c in clusters) else "anchors"
    # n>=3：全部单点=review（分散），否则按区数（3 簇 three_regions）
    if all(len(c) == 1 for c in clusters):
        return "review"
    if n == 3:
        return "three_regions"
    return "three_regions" if any(len(c) > 1 for c in clusters) else "review"


def common_anchors(ids_by_strategy: dict[str, Sequence[int]]) -> list[int]:
    """求 100% / stride2 / stride4 / stride8 都命中的公共 canonical anchors。"""
    sets = [set(v) for v in ids_by_strategy.values() if v]
    if not sets:
        return []
    inter = set(sets[0])
    for s in sets[1:]:
        inter &= s
    return sorted(inter)


def plan_slots(
    *,
    plan_id: str,
    canonical_unit_count: int,
    queried_canonical_ids: Sequence[int],
    strategy: str = "contiguous",
    step: int = 1,
    density_anchor_ids: Sequence[int] = (),
    comparison_group_id: str = "g",
    phase: str = "p0",
    requested: Sequence[int] = (),
) -> SlotPlan:
    """为 queried canonical ids 生成本地 slots。

    requested 若给出则原样作为本地 index 顺序；否则按 incoming order。
    校验：严格递增、不越界 canonical_unit_count；density anchors 必须属于 requested。
    """
    ids = list(requested) if requested else list(queried_canonical_ids)
    if not ids:
        raise SlotPlanError("empty queried canonical ids")
    if any(i < 0 or i >= canonical_unit_count for i in ids):
        raise SlotPlanError("queried canonical id out of range")
    for i in range(len(ids) - 1):
        if ids[i] >= ids[i + 1]:
            raise SlotPlanError(f"local indices not strictly increasing: {ids}")
    if density_anchor_ids:
        for a in density_anchor_ids:
            if a not in ids:
                raise SlotPlanError(f"density anchor {a} not in queried set")

    topology = detect_topology(ids)
    plan = SlotPlan(
        plan_id=plan_id,
        requested_canonical_ids=tuple(ids),
        local_indices=tuple(ids),
        topology=topology,
        comparison_group_id=comparison_group_id,
        phase_name=phase,
        strategy=strategy if step == 1 else f"strided{step}",
        detail={
            "canonical_unit_count": canonical_unit_count,
            "common_anchors_note": f"density_common={list(density_anchor_ids)}",
            "queried_n": len(ids),
        },
    )
    return plan


def id_at_stride(canonical_unit_count: int, step: int, phase_offset: int = 0) -> list[int]:
    """stride=step 从 phase_offset 起等距取样（用于 density 对比）。"""
    return list(range(phase_offset, canonical_unit_count, step))


def build_density_plans(
    *,
    plan_group: str,
    canonical_unit_count: int,
    base_ids: Sequence[int],
    step: int,
    phase_offsets: Sequence[int],
) -> list[SlotPlan]:
    """为某 density stride，跨 phase 轮换生成 slots，并计算 common anchors。

    base_ids 是所有密度条件的保留集（100%）。phase_offsets 是 phase 轮换。
    """
    plans = []
    for po in phase_offsets:
        ids = list(base_ids)
        # 在 base 基础上用 stride 取样补充以覆盖 density（演示：把 stride 抽的加进去）
        st = id_at_stride(canonical_unit_count, step, po)
        merged = sorted(set(list(ids) + st))
        p = plan_slots(plan_id=f"{plan_group}:s{step}:p{po}", canonical_unit_count=canonical_unit_count,
                       queried_canonical_ids=merged, strategy="contiguous" if step == 1 else f"strided{step}",
                       step=step, comparison_group_id=plan_group, phase=f"p{po}")
        plans.append(p)
    return plans
