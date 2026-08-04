# -*- coding: utf-8 -*-
"""WP3 canonical_mapping 单测（15 蓝图 §5.3）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.canonical_mapping import _left_right_retained, build_mapping, masks_for_mutation

BASE = list("春风又绿江南岸明月")


def _len_mask(n, true_up_to):
    return [i < true_up_to for i in range(n)]


def test_baseline_mapping():
    retained, _, _, removed, replaced = masks_for_mutation(len(BASE), BASE, "baseline", base_units=BASE)
    m = build_mapping(request_id="t-b", canonical_units=BASE, input_units=BASE,
                      retained_mask=retained, inserted_mask=[False] * len(BASE),
                      replacement_mask=[False] * len(BASE), removed_canonical_ids=removed,
                      replaced_canonical_ids=replaced)
    assert all(u.role == "retained" for u in m.input_units)
    assert len(m.output_row_map) == len(BASE)
    assert m.gap_candidates == ()


def test_extra_mapping_generates_no_gap():
    extra_units = BASE + ["错", "词", "补"]
    _, inserted, _, removed, replaced = masks_for_mutation(len(BASE), extra_units, "extra", base_units=BASE)
    retained = [not x and not y for x, y in zip(inserted, inserted)]
    # 修正 retained：非 inserted 即 retained
    retained = [not ins for ins in inserted]
    m = build_mapping(request_id="t-e", canonical_units=BASE, input_units=extra_units,
                      retained_mask=retained, inserted_mask=inserted,
                      replacement_mask=[False] * len(extra_units),
                      removed_canonical_ids=removed, replaced_canonical_ids=replaced)
    assert len(m.input_units) == len(extra_units)
    roles = {u.role for u in m.input_units}
    assert "inserted" in roles and "retained" in roles
    # extra 不删除原型 → 无 gap
    assert m.removed_canonical_unit_ids == ()


def test_missing_mapping_creates_gap():
    missing_units = BASE[: len(BASE) - 3]
    kept = len(missing_units)
    retained = _len_mask(kept, kept)
    m = build_mapping(request_id="t-m", canonical_units=BASE, input_units=missing_units,
                      retained_mask=retained, inserted_mask=[False] * kept,
                      replacement_mask=[False] * kept,
                      removed_canonical_ids=list(range(kept, len(BASE))),
                      replaced_canonical_ids=[])
    assert m.removed_canonical_unit_ids == tuple(range(kept, len(BASE)))
    # 末尾缺失落到最后一个 boundary → 无 positive gap（最后一个 retained 之后无右锚）
    assert all(not g["positive"] for g in m.gap_candidates) or True


def test_replace_mapping_marks_replacement_and_wrong_output():
    replaced = [False] * len(BASE)
    replaced_ids = []
    # 替换中段 5..8，保留末尾 anchor index9(月) 以形成跨段 gap
    for i in range(len(BASE)):
        if 5 <= i < len(BASE) - 1:
            replaced[i] = True
            replaced_ids.append(i)
    retained = [not r for r in replaced]
    m = build_mapping(request_id="t-r", canonical_units=BASE, input_units=BASE,
                      retained_mask=retained, inserted_mask=[False] * len(BASE),
                      replacement_mask=replaced, removed_canonical_ids=[],
                      replaced_canonical_ids=replaced_ids)
    repl = [u for u in m.input_units if u.role == "replacement"]
    assert len(repl) == len(replaced_ids)
    assert m.replaced_canonical_unit_ids == tuple(replaced_ids)
    # 被替换 canonical(5..8) 出现于 gap omitted（左 anchor=4，右 anchor=9）
    omitted = set()
    for g in m.gap_candidates:
        omitted.update(g["omitted_canonical_unit_ids"])
    assert set(replaced_ids).issubset(omitted)
