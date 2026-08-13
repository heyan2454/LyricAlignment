import pytest

from lyricalign.unit_realign.consensus import aggregate_consensus
from lyricalign.unit_realign.unit_gate_features import assert_no_gt_feature_row, build_unit_features


def test_no_gt_features_reject_outcome_keys_and_keep_context_protection():
    rows = build_unit_features(
        baseline_rows=[{"canonical_unit_id": 0, "fixed_global_start_sec": 0., "fixed_global_end_sec": .2},
                       {"canonical_unit_id": 1, "fixed_global_start_sec": .3, "fixed_global_end_sec": .5}],
        candidate_rows=[{"canonical_unit_id": 0, "fixed_global_start_sec": .1, "fixed_global_end_sec": .3},
                        {"canonical_unit_id": 1, "fixed_global_start_sec": .3, "fixed_global_end_sec": .5}],
        song_id="s", region_id="r", request_id="q", family="R-S", target_unit_ids=[0],
    )
    assert rows[1]["context_protected"] is True
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_gt_feature_row({"delta_error_ms": 1})


def test_no_gt_firewall_rejects_nested_gt_fields_but_allows_numeric_stats():
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_gt_feature_row({"decoder_confidence": {"old_error_ms": 1.0}})
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_gt_feature_row({"duration_sec": 1.0, "decoder_confidence": {"label": "bad"}})
    assert_no_gt_feature_row({"duration_sec": 1.0, "decoder_confidence": {"mean_ms": 5.0, "p95_ms": 9.0}})


def test_consensus_groups_same_unit_across_families_only():
    rows = [
        {"song_id": "s", "region_id": "r", "canonical_unit_id": 1, "family": "R-U",
         "mean_boundary_displacement_ms": 10., "context_protected": True},
        {"song_id": "s", "region_id": "r", "canonical_unit_id": 1, "family": "R-S",
         "mean_boundary_displacement_ms": 30., "context_protected": True},
        {"song_id": "s", "region_id": "other", "canonical_unit_id": 1, "family": "R-S",
         "mean_boundary_displacement_ms": 99.},
    ]
    result = aggregate_consensus(rows)
    first = next(x for x in result if x["region_id"] == "r")
    assert first["n_families"] == 2
    assert first["median_displacement_ms"] == 20.
    assert first["mad_displacement_ms"] == 10.
