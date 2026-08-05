# -*- coding: utf-8 -*-
"""Detector V2 feature extraction tests (Phase2-1, 18 §7 / 20 §3, 纯内存无模型)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from lyricalign.research_v7.detector_v2_evidence import (
    EvidenceRow,
    HiddenView,
    OfficialView,
    RawView,
)
from lyricalign.research_v7.detector_v2_features import (
    all_feature_keys,
    build_neighbors,
    feature_schema,
    is_repaired,
    repair_run_lengths,
    unit_feature_row,
)


def make_row(
    raw_start=1.0,
    raw_end=1.4,
    o_start=1.05,
    o_end=1.35,
    rs_shift=None,
    re_shift=None,
    topk=(),
    h_available=False,
    h_start=None,
    h_end=None,
    cross_view=None,
    unit_id=0,
):
    return EvidenceRow(
        request_identity="sha256:x", view_id="full", canonical_unit_id=unit_id,
        raw=RawView(start_sec=raw_start, end_sec=raw_end,
                    start_entropy=0.4, end_entropy=0.6,
                    start_margin=0.7, end_margin=0.3, topk=tuple(topk)),
        official=OfficialView(start_sec=o_start, end_sec=o_end,
                              repair_start_shift_sec=rs_shift,
                              repair_end_shift_sec=re_shift),
        hidden=HiddenView(available=h_available, schema="boundary_last4_v1",
                          start=h_start or {}, end=h_end or {}),
        cross_view=cross_view or {},
    )


def neighbors_for(rows, index):
    return build_neighbors(rows, index)


def test_r_features_values():
    row = make_row(topk=(0.8, 0.15, 0.05))
    f = unit_feature_row(row)
    assert f["raw_start_entropy"] == 0.4
    assert f["raw_end_entropy"] == 0.6
    assert f["raw_start_margin"] == 0.7
    assert f["raw_end_margin"] == 0.3
    assert f["raw_top1_top2_margin"] == pytest.approx(0.65)
    assert f["raw_topk_span"] == pytest.approx(0.75)
    assert f["raw_topk_variance"] == pytest.approx(0.110556, abs=1e-4)
    assert f["raw_duration_sec"] == pytest.approx(0.4)
    assert f["raw_zero_duration"] == 0.0
    assert f["raw_inverted"] == 0.0
    assert f["raw_gap_to_prev_sec"] is None
    assert f["raw_gap_to_next_sec"] is None


def test_raw_zero_and_inverted_flags():
    zero = unit_feature_row(make_row(raw_start=2.0, raw_end=2.0))
    assert zero["raw_duration_sec"] == 0.0
    assert zero["raw_zero_duration"] == 1.0
    assert zero["raw_inverted"] == 1.0
    rev = unit_feature_row(make_row(raw_start=3.0, raw_end=2.5))
    assert rev["raw_duration_sec"] == 0.0
    assert rev["raw_zero_duration"] == 0.0
    assert rev["raw_inverted"] == 1.0


def test_topk_short_and_pair_formats():
    f1 = unit_feature_row(make_row(topk=(0.9,)))
    assert f1["raw_top1_top2_margin"] is None
    assert f1["raw_topk_span"] is None
    assert f1["raw_topk_variance"] is None
    f2 = unit_feature_row(make_row(topk=((12, 0.7), (5, 0.2), (7, 0.1))))
    assert f2["raw_top1_top2_margin"] == pytest.approx(0.5)
    assert f2["raw_topk_span"] == pytest.approx(0.6)
    f3 = unit_feature_row(make_row(topk=("bad", 0.3)))
    assert f3["raw_top1_top2_margin"] is None
    assert f3["raw_topk_variance"] is None


def test_missing_raw_values_are_none_not_zero():
    row = make_row(raw_start=None, raw_end=None)
    f = unit_feature_row(row)
    assert f["raw_duration_sec"] is None
    assert f["raw_zero_duration"] is None
    assert f["raw_inverted"] is None
    assert f["raw_start_entropy"] == 0.4


def test_o_features_values():
    row = make_row(rs_shift=0.05, re_shift=-0.05)
    f = unit_feature_row(row)
    assert f["official_duration_sec"] == pytest.approx(0.3)
    assert f["ro_start_shift_sec"] == pytest.approx(0.05)
    assert f["ro_end_shift_sec"] == pytest.approx(-0.05)
    assert f["repair_start_shift_sec"] == pytest.approx(0.05)
    assert f["repair_end_shift_sec"] == pytest.approx(-0.05)
    assert f["has_repair"] == 1.0
    assert f["repair_run_length"] is None


def test_has_repair_zero_shift_is_not_repair():
    row = make_row(rs_shift=0.0, re_shift=0.0)
    assert is_repaired(row) is False
    assert unit_feature_row(row)["has_repair"] == 0.0


def test_hidden_available_features():
    row = make_row(h_available=True,
                   h_start={"norm": 1.2, "variance": 0.3, "vector": [1.0, 0.0]},
                   h_end={"norm": 0.8, "variance": 0.1, "vector": [0.0, 1.0]})
    f = unit_feature_row(row)
    assert f["hidden_start_norm"] == pytest.approx(1.2)
    assert f["hidden_end_norm"] == pytest.approx(0.8)
    assert f["hidden_start_variance"] == pytest.approx(0.3)
    assert f["hidden_end_variance"] == pytest.approx(0.1)
    assert f["hidden_start_end_cosine"] == pytest.approx(0.0)
    assert f["hidden_start_end_l2"] == pytest.approx(2 ** 0.5)


def test_hidden_cosine_parallel_vectors():
    row = make_row(h_available=True,
                   h_start={"vector": [1.0, 2.0]}, h_end={"vector": [2.0, 4.0]})
    f = unit_feature_row(row)
    assert f["hidden_start_end_cosine"] == pytest.approx(1.0)
    assert f["hidden_start_norm"] is None


def test_hidden_blocked_all_none_ro_continue():
    row = make_row(h_available=False)
    f = unit_feature_row(row)
    for key in ("hidden_start_norm", "hidden_end_norm", "hidden_start_variance",
                "hidden_end_variance", "hidden_start_end_cosine", "hidden_start_end_l2"):
        assert f[key] is None, key
    assert f["raw_duration_sec"] == pytest.approx(0.4)
    assert f["official_duration_sec"] == pytest.approx(0.3)


def test_neighborhood_diffs():
    prev = make_row(raw_start=0.0, raw_end=0.5, o_start=0.0, o_end=0.55, unit_id=0)
    cur = make_row(raw_start=1.0, raw_end=1.4, o_start=1.05, o_end=1.35, unit_id=1)
    nxt = make_row(raw_start=1.8, raw_end=2.4, o_start=1.9, o_end=2.4, unit_id=2)
    f = unit_feature_row(cur, build_neighbors([prev, cur, nxt], 1))
    assert f["raw_dur_diff_prev"] == pytest.approx(-0.1)
    assert f["raw_dur_diff_next"] == pytest.approx(0.2)
    assert f["raw_dur_diff2"] == pytest.approx(0.3)
    assert f["raw_start_diff_prev"] == pytest.approx(1.0)
    assert f["raw_start_diff_next"] == pytest.approx(0.8)
    assert f["raw_start_diff2"] == pytest.approx(-0.2)
    assert f["raw_end_diff_prev"] == pytest.approx(0.9)
    assert f["raw_end_diff_next"] == pytest.approx(1.0)
    assert f["raw_end_diff2"] == pytest.approx(0.1)
    assert f["official_dur_diff_prev"] == pytest.approx(-0.25)
    assert f["official_dur_diff_next"] == pytest.approx(0.2)
    assert f["official_dur_diff2"] == pytest.approx(0.45)


def test_neighborhood_median_deviation():
    prev = make_row(raw_start=0.0, raw_end=0.5, unit_id=0)
    cur = make_row(raw_start=0.6, raw_end=1.0, unit_id=1)
    nxt = make_row(raw_start=1.1, raw_end=1.5, unit_id=2)
    f = unit_feature_row(cur, build_neighbors([prev, cur, nxt], 1))
    assert f["raw_dur_median_dev"] == pytest.approx(0.0)
    assert f["raw_start_median_dev"] == pytest.approx(0.6 - statistics_median(0.0, 0.6, 1.1))
    outlier = make_row(raw_start=0.6, raw_end=0.7, unit_id=1)
    f2 = unit_feature_row(outlier, build_neighbors([prev, outlier, nxt], 1))
    assert f2["raw_dur_median_dev"] == pytest.approx(0.1 - statistics_median(0.5, 0.1, 0.4))


def test_gap_and_overlap_vs_neighbors():
    prev = make_row(raw_start=0.0, raw_end=0.5, unit_id=0)
    cur = make_row(raw_start=0.6, raw_end=1.0, unit_id=1)
    ovl = make_row(raw_start=0.45, raw_end=1.0, unit_id=1)
    nxt = make_row(raw_start=1.2, raw_end=1.6, unit_id=2)
    f = unit_feature_row(cur, build_neighbors([prev, cur, nxt], 1))
    assert f["raw_gap_to_prev_sec"] == pytest.approx(0.1)
    assert f["raw_gap_to_next_sec"] == pytest.approx(0.2)
    f2 = unit_feature_row(ovl, build_neighbors([prev, ovl, nxt], 1))
    assert f2["raw_gap_to_prev_sec"] == pytest.approx(-0.05)


def test_repair_run_lengths():
    rows = [make_row(unit_id=i, rs_shift=(0.05 if i in (0, 1, 2, 4) else None))
            for i in range(5)]
    assert repair_run_lengths(rows) == [3, 3, 3, 0, 1]
    f = unit_feature_row(rows[1], build_neighbors(rows, 1))
    assert f["repair_run_length"] == 3
    f_edge = unit_feature_row(rows[4], build_neighbors(rows, 4))
    assert f_edge["repair_run_length"] == 1
    f_non = unit_feature_row(rows[3], build_neighbors(rows, 3))
    assert f_non["repair_run_length"] == 0


def test_cross_view_features():
    row = make_row(cross_view={"n_views": 2, "start_diff_sec": 0.03, "end_diff_sec": -0.02})
    f = unit_feature_row(row)
    assert f["cv_n_views"] == 2
    assert f["cv_start_diff_sec"] == pytest.approx(0.03)
    assert f["cv_end_diff_sec"] == pytest.approx(-0.02)
    assert f["cv_posterior_distance"] is None


def test_cross_view_posterior_distance_from_vectors():
    row = make_row(cross_view={"n_views": 2,
                               "posterior_vectors": [[1.0, 0.0], [0.0, 1.0]]})
    f = unit_feature_row(row)
    assert f["cv_posterior_distance"] == pytest.approx(2 ** 0.5)


def test_leak_assertion_rejects_family_in_cross_view():
    row = make_row(cross_view={"family": "replace"})
    with pytest.raises(ValueError, match="forbidden label fields"):
        unit_feature_row(row)


def test_leak_assertion_rejects_gt_in_neighbor_row():
    cur = make_row(unit_id=1)
    bad = make_row(unit_id=0)
    bad = EvidenceRow(
        request_identity=bad.request_identity, view_id=bad.view_id,
        canonical_unit_id=bad.canonical_unit_id, raw=bad.raw, official=bad.official,
        hidden=bad.hidden, cross_view={"gt_start_sec": 0.0},
    )
    with pytest.raises(ValueError, match="forbidden label fields"):
        unit_feature_row(cur, {"prev": bad})


def test_leak_assertion_accepts_clean_neighbors():
    prev = make_row(raw_start=0.0, raw_end=0.5, unit_id=0)
    cur = make_row(unit_id=1)
    f = unit_feature_row(cur, {"prev": prev})
    assert f["raw_gap_to_prev_sec"] == pytest.approx(0.5)


def test_feature_schema_matches_output_keys():
    schema = feature_schema()
    assert set(schema) == {"R", "O", "H", "neighborhood", "cross_view"}
    row = make_row(topk=(0.8, 0.15, 0.05), h_available=True,
                   h_start={"norm": 1.0}, h_end={"norm": 0.5})
    f = unit_feature_row(row, {"prev": make_row(unit_id=0)},
                          {"n_views": 2, "start_diff_sec": 0.01})
    assert set(f) == set(all_feature_keys())
    assert all(isinstance(v, (float, int)) or v is None for v in f.values())
    assert len(schema["R"]) == 12
    assert len(schema["O"]) == 7
    assert len(schema["H"]) == 6
    assert len(schema["neighborhood"]) == 24
    assert len(schema["cross_view"]) == 4


def test_unit_feature_row_roundtrip_all_none_default():
    row = make_row()
    f = unit_feature_row(row)
    assert f["raw_duration_sec"] == pytest.approx(0.4)
    assert f["official_duration_sec"] == pytest.approx(0.3)
    assert f["repair_run_length"] is None
    assert f["cv_n_views"] is None


def statistics_median(a, b, c):
    import statistics
    return statistics.median([a, b, c])
