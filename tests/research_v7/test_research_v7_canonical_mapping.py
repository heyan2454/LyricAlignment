# -*- coding: utf-8 -*-
"""WP3 canonical_mapping 单测（P0-2 整改：显式 canonical id、sentinel gap、可逆 row-map）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.research_v7.canonical_mapping import START, END, build_mapping

BASE = list("一二三四五六七八九十甲乙")  # 12 字（明确长度）


def _cids(input_len):
    return list(range(input_len))  # 显式：input i -> canonical i（无插入时）


def test_baseline_mapping_explicit_canonical():
    n = len(BASE)
    m = build_mapping(request_id="t-b", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * n, input_canonical_ids=_cids(n))
    assert all(u.role == "retained" for u in m.input_units)
    assert len(m.output_row_map) == n
    assert m.gap_candidates == ()


def test_identity_canonical_id_must_be_explicit():
    with pytest.raises(ValueError):
        # len mismatch → 显式传入被强制
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * 5, input_canonical_ids=_cids(6))


def test_head_missing_sentinel_gap():
    # 删掉 canonical 0..2（head missing）
    kept = list(BASE[3:])
    n = len(kept)
    role = ["retained"] * n
    # input i -> canonical i+3（head 缺 0,1,2）
    cids = [i + 3 for i in range(n)]
    removed = [0, 1, 2]
    m = build_mapping(request_id="t-hm", canonical_units=BASE, input_units=kept,
                      role=role, input_canonical_ids=cids, removed_canonical_ids=removed)
    gaps = list(m.gap_candidates)
    head_gap = [g for g in gaps if g["left_canonical_unit_id"] == START]
    assert head_gap and head_gap[0]["omitted_canonical_unit_ids"] == [0, 1, 2]
    assert head_gap[0]["right_canonical_unit_id"] == 3


def test_tail_missing_sentinel_gap():
    kept = list(BASE[: len(BASE) - 3])
    n = len(kept)
    removed = list(range(n, len(BASE)))
    m = build_mapping(request_id="t-tm", canonical_units=BASE, input_units=kept,
                      role=["retained"] * n, input_canonical_ids=_cids(n), removed_canonical_ids=removed)
    tail_gap = [g for g in m.gap_candidates if g["right_canonical_unit_id"] == END]
    assert tail_gap and tail_gap[0]["omitted_canonical_unit_ids"] == removed


def test_middle_replace_sentinel_and_middle_gap():
    # 替换 canonical 4..9 为错输出（replacement），保留首尾 anchor 0..3 和 10,11
    n = len(BASE)
    kept_front = [BASE[i] for i in range(4)]
    kept_tail = [BASE[i] for i in range(10, 12)]
    repl = list("甲乙丙丁戊己")  # 6 个 replacement，长 6
    input_units = kept_front + repl + kept_tail
    role = ["retained"] * 4 + ["replacement"] * len(repl) + ["retained"] * 2
    cids = list(range(4)) + list(range(4, 10)) + list(range(10, 12))  # replacement 保留被替代 canonical
    replaced = list(range(4, 10))
    m = build_mapping(request_id="t-mr", canonical_units=BASE, input_units=input_units,
                      role=role, input_canonical_ids=cids, replaced_canonical_ids=replaced)
    # 中部 gap：4..9 被 replaced → omitted=[4,5,6,7,8,9]
    mid = [g for g in m.gap_candidates if g["left_canonical_unit_id"] == 3 and g["right_canonical_unit_id"] == 10]
    assert mid and set(mid[0]["omitted_canonical_unit_ids"]) == set(replaced)
    # replacement 的 output_row_map 保留被替代 canonical（不丢 None）
    mrow = [x for x in m.output_row_map if x[1] in range(4, 10)]
    assert all(x[2] is not None for x in mrow)


def test_100pct_replace_head_tail():
    # 全替换：无 retained → 应产生 whole-region omission candidate（review P0-2），row-map 全保留
    n = len(BASE)
    repl = list("子丑寅卯辰巳午未申酉戌亥")[:n]
    role = ["replacement"] * n
    cids = list(range(n))
    m = build_mapping(request_id="t-100", canonical_units=BASE, input_units=repl,
                      role=role, input_canonical_ids=cids, replaced_canonical_ids=list(range(n)))
    assert len([u for u in m.input_units if u.role == "replacement"]) == n
    # 全删/全替 → whole-region omission gap 覆盖全部 canonical
    whole = [g for g in m.gap_candidates if g.get("whole_region_omission")]
    assert whole and set(whole[0]["omitted_canonical_unit_ids"]) == set(range(n))


def test_bad_role_rejected():
    with pytest.raises(ValueError):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["bad"] * len(BASE), input_canonical_ids=list(range(len(BASE))))


def test_inserted_must_be_none():
    with pytest.raises(ValueError):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["inserted"] * len(BASE), input_canonical_ids=list(range(len(BASE))))


def test_retained_must_be_non_none():
    with pytest.raises(ValueError):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * len(BASE), input_canonical_ids=[None] * len(BASE))


def test_duplicate_canonical_id_rejected():
    with pytest.raises(ValueError):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * len(BASE), input_canonical_ids=[0, 0] + list(range(2, len(BASE))))


def test_output_row_canonical_ids_can_be_multiline():
    # decoder 缺行：output rows 数 != input 数合法（表达缺行）
    n = len(BASE)
    out_rows = list(range(n - 1)) + [None]  # 末行缺(canonly None)
    m = build_mapping(request_id="t-ml", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * n, input_canonical_ids=list(range(n)),
                      output_row_canonical_ids=out_rows)
    assert len(m.output_row_map) == n
    assert m.output_row_map[-1][2] is None  # 缺行表达为 None


def test_100pct_replace_produces_whole_region_omission():
    n = len(BASE)
    m = build_mapping(request_id="t-wr", canonical_units=BASE, input_units=BASE,
                      role=["replacement"] * n, input_canonical_ids=list(range(n)),
                      replaced_canonical_ids=list(range(n)))
    whole = [g for g in m.gap_candidates if g.get("whole_region_omission")]
    assert whole and whole[0]["omitted_canonical_unit_ids"] == list(range(n))


def test_retained_canonical_axis_must_be_strictly_increasing():
    # retained/replacement canonical 沿 input 顺序必须严格递增（review）
    n = len(BASE)
    with pytest.raises(ValueError, match="strictly increasing"):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * n, input_canonical_ids=[0, 2, 1] + list(range(3, n)))


def test_output_row_input_indices_express_missing_double():
    # decoder 少行 + 插入行：output_row_input_indices 显式给 input index 或 None
    n = len(BASE)
    out_canon = list(range(n - 1)) + [None]          # 末行 canonical None（缺映射）
    out_input = list(range(n - 1)) + [None]          # 末行无对应 input
    m = build_mapping(request_id="t-ori", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * n, input_canonical_ids=list(range(n)),
                      output_row_canonical_ids=out_canon, output_row_input_indices=out_input)
    assert m.output_row_map[-1] == (n - 1, None, None)  # 缺行：(row, input=None, canonical=None)
    assert m.output_row_map[0] == (0, 0, 0)


def test_output_row_input_index_out_of_range_rejected():
    n = len(BASE)
    with pytest.raises(ValueError, match="out of input range"):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * n, input_canonical_ids=list(range(n)),
                      output_row_canonical_ids=list(range(n)),
                      output_row_input_indices=[99] + list(range(1, n)))  # 99 超出 input 范围


def test_output_row_canonical_out_of_range_rejected():
    n = len(BASE)
    with pytest.raises(ValueError, match="out of canonical range"):
        build_mapping(request_id="x", canonical_units=BASE, input_units=BASE,
                      role=["retained"] * n, input_canonical_ids=list(range(n)),
                      output_row_canonical_ids=[n] + list(range(1, n)))  # n 越界 canonical
