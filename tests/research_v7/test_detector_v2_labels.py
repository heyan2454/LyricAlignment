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
