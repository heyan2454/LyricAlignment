"""WP3：canonical_mapping —— input↔canonical GT 轴的可逆映射 + gap candidates。

对应 15 蓝图 §5.3：不再由 evaluator 用 position/seed 反推 mapping，而是每次 request 直接保存：
  - input_units[]（input_index, text, role=retained|inserted|replacement, canonical_unit_id）
  - removed_canonical_unit_ids[]、replaced_canonical_unit_ids[]
  - output_row_map[]（output_row_index -> input_index -> canonical_unit_id）
  - gap_candidates[]（gap_id, left/right canonical, omitted ids, positive）

mapping 生成器统一服务 extra/missing/replace 与各种 position。feature extractor 必须拒绝
这些 GT/mutation 字段进特征（本模块只负责产出映射；不消费特征）。纯 CPU、纯函数、可单测。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class InputUnit:
    input_index: int
    text: str
    role: str  # retained / inserted / replacement
    canonical_unit_id: int | None  # retained：原始 canonical；inserted/replacement：None 或 被替代的 canonical

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalMapping:
    request_id: str
    canonic_units: tuple[str, ...]
    input_units: tuple[InputUnit, ...]
    removed_canonical_unit_ids: tuple[int, ...]
    replaced_canonical_unit_ids: tuple[int, ...]
    output_row_map: tuple[tuple[int, int, int | None], ...]  # (output_row_index, input_index, canonical_id)
    gap_candidates: tuple[dict, ...] = field(default_factory=tuple)
    schema: str = "research_v7_canonical_mapping_v1"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "canonical_units": list(self.canonic_units),
            "input_units": [u.to_dict() for u in self.input_units],
            "removed_canonical_unit_ids": list(self.removed_canonical_unit_ids),
            "replaced_canonical_unit_ids": list(self.replaced_canonical_unit_ids),
            "output_row_map": [list(x) for x in self.output_row_map],
            "gap_candidates": list(self.gap_candidates),
        }


def _left_right_retained(can_units: Sequence[str], input_units: Sequence[InputUnit]):
    left = None
    right = None
    retained_sorted = [u for u in input_units if u.role == "retained"]
    if retained_sorted:
        left = retained_sorted[0].canonical_unit_id
        right = retained_sorted[-1].canonical_unit_id
    return left, right


def build_mapping(
    *,
    request_id: str,
    canonical_units: Sequence[str],
    input_units: Sequence[str],
    retained_mask: Sequence[bool],      # input_index -> 是否按原 canonical 保留
    inserted_mask: Sequence[bool],      # input_index -> 是否新增（extra）
    replacement_mask: Sequence[bool],   # input_index -> 是否被 replace（错输出）
    removed_canonical_ids: Sequence[int],
    replaced_canonical_ids: Sequence[int],
) -> CanonicalMapping:
    """从显式角色掩码构建映射。

    retained_mask/inserted_mask/replacement_mask 三者互斥（每 input unit 恰一角色）。
    canonical_unit_id：retained 取原始 canonical index；replacement 取其被替代的
    canonical id（replaced_canonical_ids 中分配）；inserted 为 None。
    """
    n = len(input_units)
    ius: list[InputUnit] = []
    rep_iter = iter(list(replaced_canonical_ids))
    for i in range(n):
        if retained_mask[i]:
            role = "retained"
            cid = i  # 未做任何删除/交换时 input i 对应 canonical i
        elif inserted_mask[i]:
            role = "inserted"
            cid = None
        elif replacement_mask[i]:
            role = "replacement"
            cid = next(rep_iter, None)
        else:
            role = "retained"  # 兜底：既非插入也非替换 → retained
            cid = i
        ius.append(InputUnit(input_index=i, text=input_units[i], role=role, canonical_unit_id=cid))

    # output_row_map：默认每个 input row 对应一次输出（decoder 逐行），canonical 用 retained。
    out_map = []
    for i, u in enumerate(ius):
        cid = u.canonical_unit_id if u.role == "retained" else None
        out_map.append((i, u.input_index, cid))

    # gap candidates：相邻 retained canonical 间若存在 removed/replaced-original，产生 positive gap。
    retained = [(u.input_index, u.canonical_unit_id) for u in ius if u.role == "retained"]
    gaps = []
    for j in range(len(retained) - 1):
        l_i, l_c = retained[j]
        r_i, r_c = retained[j + 1]
        if r_c is None or l_c is None:
            continue
        omitted = [c for c in range(l_c + 1, r_c) if c in (set(removed_canonical_ids) | set(replaced_canonical_ids))]
        if omitted:
            gaps.append({
                "gap_id": f"g:{l_c}:{r_c}",
                "left_canonical_unit_id": l_c,
                "right_canonical_unit_id": r_c,
                "omitted_canonical_unit_ids": omitted,
                "positive": True,
            })
    return CanonicalMapping(
        request_id=request_id,
        canonic_units=tuple(canonical_units),
        input_units=tuple(ius),
        removed_canonical_unit_ids=tuple(removed_canonical_ids),
        replaced_canonical_unit_ids=tuple(replaced_canonical_ids),
        output_row_map=tuple(out_map),
        gap_candidates=tuple(gaps),
    )


# --------------------------------------------------------------------------- #
# 便捷：从 mutation 名生成角色掩码（供测试/与 build_long_slot_run_manifest 接线）
# --------------------------------------------------------------------------- #
def masks_for_mutation(
    base_len: int,
    input_units: Sequence[str],
    mutation_type: str,
    *,
    base_units: Sequence[str],
) -> tuple[list, list, list, list, list]:
    """简化便捷：返回 (retained, inserted, replacement, removed_ids, replaced_ids)。

    仅用于 extra/missing/replace 的规整情形：
    - extra：input 末尾多出（base_len..len-1）→ inserted；其余 retained。
    - missing：input 比 base 短，删除的是末尾 retained 之后 → removed_ids 为缺的 canonical。
    - replace：input 与 base 等长，但内容不同→ 视为 replacement（保留前部 anchor，末尾错输出）。
    更精确的 mutation 明细应由 build_long_slot_run_manifest 用实际替换/删除集提供；
    本函数保证单元测试与 smoke 可跑。
    """
    n = len(input_units)
    retained = [False] * n
    inserted = [False] * n
    replacement = [False] * n
    removed_ids: list = []
    replaced_ids: list = []
    if mutation_type == "extra":
        for i in range(base_len):
            retained[i] = True
        for i in range(base_len, n):
            inserted[i] = True
    elif mutation_type == "missing":
        keep = min(base_len, n)
        for i in range(keep):
            retained[i] = True
        removed_ids = list(range(keep, base_len))
    elif mutation_type == "replace":
        replaced = min(base_len, n)
        for i in range(max(0, replaced - 2)):
            retained[i] = True
            if i < len(base_units) and i < len(input_units) and input_units[i] == base_units[i]:
                pass  # retained 内容一致
        # 末尾 replaced 视为错输出（简单约定：后 90% 替换）
        rstart = max(0, int(replaced * 0.1))
        for i in range(replaced):
            if i >= rstart:
                replacement[i] = True
                replaced_ids.append(i)
            else:
                retained[i] = True
    else:  # baseline
        for i in range(n):
            retained[i] = True
    return retained, inserted, replacement, removed_ids, replaced_ids
