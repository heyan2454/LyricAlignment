# -*- coding: utf-8 -*-
"""Detector V2 label contract tests (18 §5): safe/unsafe/grey/ambiguous + raw/official targets."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from lyricalign.research_v7.detector_v2_labels import (
    LabeledUnit,
    boundary_errors,
    label_request_units,
    label_unit,
    summarize_labels,
)


def test_boundary_errors_missing_geometry():
    err = boundary_errors(0.0, 1.0, None, None)
    assert err["missing_geometry"] is True


def test_label_safe():
    label, audit = label_unit(gt_start_sec=1.0, gt_end_sec=1.5,
                              pred_start_sec=1.04, pred_end_sec=1.52)
    assert label == "safe"
    assert audit["worst_abs_error_sec"] == 0.04


def test_label_unsafe_over_250ms():
    label, audit = label_unit(gt_start_sec=1.0, gt_end_sec=1.5,
                              pred_start_sec=1.3, pred_end_sec=1.7)
    assert label == "unsafe"


def test_label_grey_band():
    label, audit = label_unit(gt_start_sec=1.0, gt_end_sec=1.5,
                              pred_start_sec=1.18, pred_end_sec=1.5)
    assert label == "grey"


def test_label_missing_output_unsafe():
    label, audit = label_unit(gt_start_sec=1.0, gt_end_sec=1.5,
                              pred_start_sec=None, pred_end_sec=None)
    assert label == "unsafe"
    assert "missing_output_geometry" in audit["reason"]


def test_label_inversion_unsafe():
    label, audit = label_unit(gt_start_sec=1.0, gt_end_sec=1.5,
                              pred_start_sec=1.6, pred_end_sec=1.4,
                              pred_valid_time=False)
    assert label == "unsafe"


def test_label_ambiguous_independent():
    label, audit = label_unit(gt_start_sec=1.0, gt_end_sec=1.5,
                              pred_start_sec=1.01, pred_end_sec=1.51,
                              occurrence_ambiguous=True)
    assert label == "ambiguous"


def test_label_request_units_raw_and_official():
    rows = [
        {"canonical_unit_id": 0, "raw_global_start_sec": 1.04, "raw_global_end_sec": 1.52,
         "official_fixed_global_start_sec": 1.02, "official_fixed_global_end_sec": 1.51},
        {"canonical_unit_id": 1, "raw_global_start_sec": 2.0, "raw_global_end_sec": 2.4,
         "official_fixed_global_start_sec": 2.3, "official_fixed_global_end_sec": 2.7},
    ]
    gt = {0: (1.0, 1.5), 1: (2.0, 2.5), 2: (3.0, 3.5)}
    raw = label_request_units(request_identity="r", target="raw", rows=rows, canonical_gt=gt)
    off = label_request_units(request_identity="r", target="official", rows=rows, canonical_gt=gt)
    by = {x.canonical_unit_id: x for x in raw}
    assert by[0].label == "safe"
    assert by[1].label == "safe"      # raw 2.0-2.4 vs gt 2.0-2.5: worst 0.1 == safe 上限
    assert by[2].label == "unsafe"    # missing output row
    off_by = {x.canonical_unit_id: x for x in off}
    assert off_by[1].label == "unsafe"  # official 2.3-2.7 vs gt 2.0-2.5: start 0.3 > 250ms
    # summarize denominators
    s = summarize_labels(raw)
    assert s["n_units"] == 3
    assert s["n_safe"] == 2 and s["n_unsafe"] == 1
    assert s["unsafe_rate"] == round(1 / 3, 6)


def test_summarize_empty_returns_none_rates():
    s = summarize_labels([])
    assert s["n_units"] == 0
    assert s["unsafe_rate"] is None
    assert s["safe_rate"] is None


def test_label_request_units_no_cross_target_fallback():
    """M2：raw 不回退 official 几何，official 不回退 raw 几何（缺主键=missing geometry=unsafe）。"""
    rows = [
        {"canonical_unit_id": 0, "official_fixed_global_start_sec": 1.02,
         "official_fixed_global_end_sec": 1.51},
        {"canonical_unit_id": 1, "raw_global_start_sec": 2.0, "raw_global_end_sec": 2.4},
    ]
    gt = {0: (1.0, 1.5), 1: (2.0, 2.5)}
    raw = label_request_units(request_identity="r", target="raw", rows=rows, canonical_gt=gt)
    off = label_request_units(request_identity="r", target="official", rows=rows, canonical_gt=gt)
    by = {x.canonical_unit_id: x for x in raw}
    assert by[0].label == "unsafe"          # 只有 official 几何，raw 不回退
    assert by[0].audit["reason"] == "missing_output_geometry"
    assert by[0].audit["used_keys"]["start_key"] == "raw_global_start_sec"
    assert by[1].label == "safe"
    off_by = {x.canonical_unit_id: x for x in off}
    assert off_by[0].label == "safe"        # official 几何存在
    assert off_by[1].label == "unsafe"      # 只有 raw 几何，official 不回退


def test_label_request_units_requires_same_source_both_bounds():
    """MINOR 混坐标：start 有值但 end 缺失 → missing geometry，不拼另一 target。"""
    rows = [{"canonical_unit_id": 0, "raw_global_start_sec": 1.0}]
    gt = {0: (1.0, 1.5)}
    out = label_request_units(request_identity="r", target="raw", rows=rows, canonical_gt=gt)
    assert out[0].label == "unsafe"
    assert out[0].audit["reason"] == "missing_output_geometry"
    assert out[0].audit["used_keys"]["end_present"] is False


def test_label_request_units_canonical_to_local_binding():
    """M3：行 global_character_index 是 request-local，经 canonical_to_local 逆映射得 canonical id。"""
    rows = [
        {"global_character_index": 0, "raw_global_start_sec": 1.04, "raw_global_end_sec": 1.52},
        {"global_character_index": 2, "raw_global_start_sec": 2.0, "raw_global_end_sec": 2.4},
        {"global_character_index": 1, "raw_global_start_sec": 9.0, "raw_global_end_sec": 9.5},
    ]
    c2l = {0: 0, 2: 1}            # canonical 0,2 绑定到 local 0,1；local 2 是 extra（无映射）
    gt = {0: (1.0, 1.5), 1: (2.0, 2.5), 2: (3.0, 3.5)}
    out = label_request_units(request_identity="r", target="raw", rows=rows,
                              canonical_gt=gt, canonical_to_local=c2l)
    by = {x.canonical_unit_id: x for x in out}
    assert by[0].label == "safe"           # local 0 -> canonical 0
    assert by[1].label == "unsafe"         # canonical 1 无行
    assert by[2].label == "unsafe"         # local 1 -> canonical 2：9.0-9.5 vs gt 3.0-3.5
    assert by[2].audit["reason"] == "exceeds_unsafe"


def test_label_request_units_unmapped_local_row_skipped():
    """M3：无 canonical 映射的行（extra/inserted）不入 canonical_gt 匹配。"""
    rows = [
        {"global_character_index": 0, "raw_global_start_sec": 1.0, "raw_global_end_sec": 1.5},
        {"global_character_index": 1, "raw_global_start_sec": 9.0, "raw_global_end_sec": 9.5},
    ]
    c2l = {5: 0}                  # 只有 local 0 绑 canonical 5；local 1 无映射
    gt = {5: (1.0, 1.5), 6: (2.0, 2.5)}
    out = label_request_units(request_identity="r", target="raw", rows=rows,
                              canonical_gt=gt, canonical_to_local=c2l)
    by = {x.canonical_unit_id: x for x in out}
    assert by[5].label == "safe"
    assert by[6].label == "unsafe" and by[6].audit["reason"] == "missing_output_geometry"


def test_label_request_units_missing_canonical_key_raises():
    """M3：行缺 canonical_unit_id 且无可用逆映射 → 明确报错，不静默把 local 当 canonical。"""
    rows = [{"global_character_index": 0, "raw_global_start_sec": 1.0, "raw_global_end_sec": 1.5}]
    gt = {0: (1.0, 1.5)}
    with pytest.raises(ValueError, match="canonical_unit_id"):
        label_request_units(request_identity="r", target="raw", rows=rows, canonical_gt=gt)


def test_label_request_units_ambiguous_missing_row():
    """MINOR：缺行分支先查 occurrence_ambiguous_ids → ambiguous，不直接 unsafe。"""
    rows = [{"canonical_unit_id": 0, "raw_global_start_sec": 1.04, "raw_global_end_sec": 1.52}]
    gt = {0: (1.0, 1.5), 1: (2.0, 2.5)}
    out = label_request_units(request_identity="r", target="raw", rows=rows,
                              canonical_gt=gt, occurrence_ambiguous_ids={1})
    by = {x.canonical_unit_id: x for x in out}
    assert by[0].label == "safe"
    assert by[1].label == "ambiguous"
    assert by[1].audit["reason"] == "occurrence_ambiguous"


def test_label_request_units_nan_time_unsafe():
    """MINOR NaN：时间非有限 → unsafe（invalid_time），不参与 safe/grey 判定。"""
    rows = [{"canonical_unit_id": 0, "raw_global_start_sec": float("nan"),
             "raw_global_end_sec": 1.5}]
    gt = {0: (1.0, 1.5)}
    out = label_request_units(request_identity="r", target="raw", rows=rows, canonical_gt=gt)
    assert out[0].label == "unsafe"
    assert out[0].audit["reason"] == "invalid_time"
    assert out[0].audit["non_finite_geometry"] is True
