"""WP3：canonical_mapping —— input↔canonical GT 轴的可逆映射 + gap candidates（P0-2 整改）。

对应 15 蓝图 §5.3：不再由 evaluator 用 position/seed 反推，也不允许按 index 猜 canonical id。
整改（17 review P0-2）：
  - canonical id 由 manifest 显式传入（input_canonical_ids，允许 None=inserted）；
  - 增加 <START>/<END> sentinel gap，覆盖 head/tail omission、全删、100% replace；
  - output_row_map 对 replacement 保留被替代 canonical id（不丢 None），跨视图可逆；并支持显式
    output→canonical 映射（output_row_canonical_ids）。
  - 对所有 mutation position 提供单测。

作用域只限 mapping；feature/GT 字段不被本模块消费。纯 CPU、纯函数、可单测。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Sequence

START = -1   # <START> sentinel canonical id
END = -2     # <END> sentinel canonical id


@dataclass(frozen=True)
class InputUnit:
    input_index: int
    text: str
    role: str  # retained / inserted / replacement
    canonical_unit_id: int | None  # retained/replacement：对应 canonical；inserted：None

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
    schema: str = "research_v7_canonical_mapping_v2"  # 版本号提升：显式 canonical id + sentinel

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


def _next_retained_canonical(ius, from_idx, lookahead=True):
    """从 from_idx 起向 lookahead 方向找第一个 retained 的 canonical id。"""
    seq = range(from_idx + 1, len(ius)) if lookahead else range(from_idx - 1, -1, -1)
    for i in seq:
        if ius[i].canonical_unit_id is not None:
            return i, ius[i].canonical_unit_id
    return None, None


def build_gaps(ius, removed, replaced, canonic_n, *, head_tail=True):
    """生成 gap candidates：相邻 retained canonical 间含 removed/replaced；含 sentinel 处理。"""
    removed_replaced = set(removed) | set(replaced)
    retained = [(u.input_index, u.canonical_unit_id) for u in ius
                if u.role == "retained" and u.canonical_unit_id is not None]
    gaps = []
    # 中部 gap：相邻 retained 之间
    for j in range(len(retained) - 1):
        l_i, l_c = retained[j]
        r_i, r_c = retained[j + 1]
        lo, hi = min(l_c, r_c), max(l_c, r_c)
        omitted = [c for c in range(lo + 1, hi) if c in removed_replaced]
        if omitted:
            gaps.append({"gap_id": f"g:{lo}:{hi}", "left_canonical_unit_id": lo,
                         "right_canonical_unit_id": hi, "omitted_canonical_unit_ids": omitted,
                         "positive": True})
    if head_tail and retained:
        first_c = retained[0][1]
        head_omitted = [c for c in range(0, first_c) if c in removed_replaced]
        if head_omitted:
            gaps.append({"gap_id": f"g:START:{first_c}", "left_canonical_unit_id": START,
                         "right_canonical_unit_id": first_c, "omitted_canonical_unit_ids": head_omitted,
                         "positive": True})
        last_c = retained[-1][1]
        tail_omitted = [c for c in range(last_c + 1, canonic_n) if c in removed_replaced]
        if tail_omitted:
            gaps.append({"gap_id": f"g:{last_c}:END", "left_canonical_unit_id": last_c,
                         "right_canonical_unit_id": END, "omitted_canonical_unit_ids": tail_omitted,
                         "positive": True})
    elif not retained:
        # P0-2：100% replace/全删 → whole-region omission candidate（覆盖所有 removed/replaced canonical）
        whole = [c for c in range(canonic_n) if c in removed_replaced]
        if whole:
            gaps.append({"gap_id": "g:START:END", "left_canonical_unit_id": START,
                         "right_canonical_unit_id": END, "omitted_canonical_unit_ids": whole,
                         "whole_region_omission": True, "positive": True})
    return tuple(gaps)


def build_mapping(
    *,
    request_id: str,
    canonical_units: Sequence[str],
    input_units: Sequence[str],
    role: Sequence[str],                      # retained / inserted / replacement
    input_canonical_ids: Sequence[int | None], # 显式 canonical id，None=inserted（不允许按 index 猜）
    removed_canonical_ids: Sequence[int] = (),
    replaced_canonical_ids: Sequence[int] = (),
    output_row_canonical_ids: Sequence[int | None] | None = None,
    output_row_input_indices: Sequence[int | None] | None = None,
    canonic_n: int | None = None,
) -> CanonicalMapping:
    """显式 canonical mapping（P0-2 round2：完整约束校验）。"""
    n = len(input_units)
    if len(input_canonical_ids) != n:
        raise ValueError("input_canonical_ids must match len(input_units)")
    if len(role) != n:
        raise ValueError("role must match len(input_units)")
    allowed = {"retained", "inserted", "replacement"}
    canonical_n = len(canonical_units) if canonic_n is None else canonic_n
    # P0-2 约束：role 枚举、id 范围/唯一、inserted 必 None、retained/replacement 必非 None
    seen_ids = set()
    for i in range(n):
        r = role[i]; cid = input_canonical_ids[i]
        if r not in allowed:
            raise ValueError(f"role {r!r} not in {allowed}")
        if r == "inserted":
            if cid is not None:
                raise ValueError("inserted unit must have canonical_unit_id=None")
        else:  # retained / replacement
            if cid is None:
                raise ValueError(f"{r} unit must have non-None canonical id")
            if not (0 <= cid < canonical_n):
                raise ValueError(f"canonical id {cid} out of range [0,{canonical_n})")
            if cid in seen_ids:
                raise ValueError(f"duplicate canonical id {cid} in retained/replacement units")
            seen_ids.add(cid)
    ius = [InputUnit(input_index=i, text=input_units[i], role=role[i], canonical_unit_id=input_canonical_ids[i])
           for i in range(n)]
    # P0-2 review：retained/replacement 的 canonical 轴按 input 顺序须严格递增（不只唯一）
    prev = -1
    for u in ius:
        if u.role in ("retained", "replacement") and u.canonical_unit_id is not None:
            if u.canonical_unit_id <= prev:
                raise ValueError("retained/replacement canonical ids must be strictly increasing along input order")
            prev = u.canonical_unit_id
    # output_row_input_indices 显式表达 decoder 缺/重/插入行（可 null；值为 input index 或 None=本行非对应输入）
    if output_row_canonical_ids is not None:
        # 若调用方也提供 output_row_input_indices，用它；否则默认 row_i==input_i
        ori = output_row_input_indices
        if ori is not None and len(ori) != len(output_row_canonical_ids):
            raise ValueError("output_row_input_indices len != output_row_canonical_ids len")
        # review3-3 mark(6)：校验 input index 范围与 output canonical id 范围
        for idx in (ori or []):
            if idx is not None and not (0 <= idx < n):
                raise ValueError(f"output_row_input_index {idx} out of input range [0,{n})")
        for oc in output_row_canonical_ids:
            if oc is not None and not (0 <= oc < canonical_n):
                raise ValueError(f"output_row_canonical_id {oc} out of canonical range [0,{canonical_n})")
        out_map = [(row_i, (ori[row_i] if ori is not None else row_i), c)
                   for row_i, c in enumerate(output_row_canonical_ids)]
    else:
        out_map = [(i, ius[i].input_index, ius[i].canonical_unit_id) for i in range(n)]
    gaps = build_gaps(ius, removed_canonical_ids, replaced_canonical_ids, canonical_n)
    return CanonicalMapping(
        request_id=request_id,
        canonic_units=tuple(canonical_units),
        input_units=tuple(ius),
        removed_canonical_unit_ids=tuple(removed_canonical_ids),
        replaced_canonical_unit_ids=tuple(replaced_canonical_ids),
        output_row_map=tuple(out_map),
        gap_candidates=gaps,
    )
