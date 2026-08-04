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
from typing import Mapping, Sequence


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
    canonical_to_local: Mapping[int, int] | None = None,
) -> SlotPlan:
    """为 queried canonical ids 生成严格递增的本地 timestamp slots。

    P0-3 整改：canonical_to_local 把 canonical id → 本地 timestamp token index（历史/future 文本
    会占用本地 index，故 canonical 不等同 local）。若给出，local_indices = [map[c] for c in queried]；
    并校验本地严格递增。requested 仍可显式给本地 index（兼容旧测试）；二者互斥。
    """
    which = "canonical"
    if canonical_to_local is not None:
        # canonical → local 映射路径（P0-3 正确路径）
        local = [canonical_to_local[c] for c in queried_canonical_ids]
        which = "mapped"
    elif requested:
        local = list(requested)
        which = "explicit"
    else:
        local = list(queried_canonical_ids)
        which = "canonical-as-local"
    if not local:
        raise SlotPlanError("empty queried canonical ids")
    if any(i < 0 or i >= canonical_unit_count for i in queried_canonical_ids):
        raise SlotPlanError("queried canonical id out of range")
    for i in range(len(local) - 1):
        if local[i] >= local[i + 1]:
            raise SlotPlanError(f"local indices not strictly increasing: {local}")
    # density_anchor_ids 是"汇总时跨 phase 共同评估"的范围标记，非每 request 必须包含；
    # 故不硬校验必须 ∈ queried（P0-3：phase 轮换使不同 plan 覆盖不同 anchor 子集）。
    topology = detect_topology(queried_canonical_ids)
    plan = SlotPlan(
        plan_id=plan_id,
        requested_canonical_ids=tuple(queried_canonical_ids),
        local_indices=tuple(local),
        topology=topology,
        comparison_group_id=comparison_group_id,
        phase_name=phase,
        strategy=strategy if step == 1 else f"strided{step}",
        detail={
            "canonical_unit_count": canonical_unit_count,
            "common_anchors_note": f"density_common={list(density_anchor_ids)}",
            "queried_n": len(queried_canonical_ids),
            "local_source": which,
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
    selected_by_stride_phase: Mapping[str, Mapping[str, Sequence[int]]],
    canonical_to_local: Mapping[int, int],
) -> tuple[list[SlotPlan], list[int]]:
    """P0-3：为真实 density 已选集生成 slots 并求 common anchors。

    selected_by_stride_phase: {stride: {phase: [canonical_ids]}} —— 由 caller 提供每个 stride、
    每个 phase 的真实子采样（**不再 base∪stride 合成**，保证每个 phase 真稀疏）。
    canonical_to_local: canonical id → 本地 timestamp index。
    返回 (plans, common_anchors)；common_anchors = 所有 stride 的**交集**（每 phase 独立或 全局）。
    """
    plans: list[SlotPlan] = []
    # common anchors：取所有 stride 的交集（union of each stride's phases）
    all_sets = []
    for step, phases in selected_by_stride_phase.items():
        union = set()
        for ids in phases.values():
            union |= set(ids)
        all_sets.append(union)
    common = sorted(set.intersection(*all_sets)) if all_sets else []
    for step, phases in selected_by_stride_phase.items():
        for phase, ids in phases.items():
            p = plan_slots(
                plan_id=f"{plan_group}:s{step}:{phase}",
                canonical_unit_count=canonical_unit_count,
                queried_canonical_ids=sorted(set(ids)),
                strategy="contiguous" if step == 1 else f"strided{step}",
                step=step, canonical_to_local=canonical_to_local,
                density_anchor_ids=common, comparison_group_id=plan_group, phase=phase,
            )
            plans.append(p)
    return plans, common
