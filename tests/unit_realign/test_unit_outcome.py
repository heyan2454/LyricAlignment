from lyricalign.unit_realign.unit_outcome import aggregate_candidate_outcome, aggregate_region_outcome, classify_unit_outcome, pair_unit_outcomes


def test_unit_outcome_pairs_boundaries_missing_extra_and_roles():
    gt = {
        0: {"start_sec": 0.0, "end_sec": 0.3},
        1: {"start_sec": 0.4, "end_sec": 0.8},
    }
    rows = pair_unit_outcomes(
        baseline_rows=[{"canonical_unit_id": 0, "start_sec": .05, "end_sec": .35}],
        candidate_rows=[
            {"canonical_unit_id": 0, "start_sec": .0, "end_sec": .3},
            {"canonical_unit_id": 2, "start_sec": 1., "end_sec": 1.2},
            {"canonical_unit_id": 2, "start_sec": 1., "end_sec": 1.2},
        ],
        gt_by_canonical=gt, song_id="s", region_id="r", request_id="q",
        family="R-S", target_unit_ids=[0, 1],
    )
    by_id = {row["canonical_unit_id"]: row for row in rows}
    assert by_id[0]["role"] == "target"
    assert by_id[0]["old_onset_error_ms"] == 50.0
    assert by_id[0]["new_max_boundary_error_ms"] == 0.0
    assert by_id[0]["old_max_boundary_error_le_100ms"] is True
    assert by_id[1]["new_missing"] is True
    assert by_id[2]["extra_prediction"] is True
    assert by_id[2]["candidate_duplicate_prediction"] is True


def test_unit_outcome_bucket_edges_are_inclusive():
    rows = pair_unit_outcomes(
        baseline_rows=[], candidate_rows=[{"canonical_unit_id": 0, "start_sec": .1, "end_sec": .2}],
        gt_by_canonical={0: {"start_sec": 0., "end_sec": .2}},
        song_id="s", region_id="r", request_id="q", family="R-U", target_unit_ids=[0],
    )
    assert rows[0]["new_onset_error_le_100ms"] is True
    assert rows[0]["new_onset_error_le_200ms"] is True


def test_covered_to_missing_is_catastrophic_and_never_averaged_beneficial():
    rows = [
        {"role": "target", "old_missing": False, "new_missing": True, "delta_max_boundary_error_ms": None},
        {"role": "target", "old_missing": False, "new_missing": False, "delta_max_boundary_error_ms": -500},
    ]
    assert classify_unit_outcome(rows[0]) == "covered_to_missing"
    assert aggregate_region_outcome(rows)["outcome"] == "catastrophic_harmful"


def test_unmappable_candidate_output_is_retained_as_invalid_extra():
    rows = pair_unit_outcomes(baseline_rows=[], candidate_rows=[{"prediction_local_index": 8}],
                              gt_by_canonical={}, song_id="s", region_id="r", request_id="q",
                              family="R-A", target_unit_ids=[1])
    extra = next(row for row in rows if row["role"] == "extra")
    assert extra["invalid_unpairable"] is True
    assert aggregate_region_outcome(rows)["outcome"] == "harmful"


def test_region_outcome_splits_fixed_context_and_extra_denominators():
    rows = [
        {"role": "target", "old_missing": False, "new_missing": False,
         "delta_max_boundary_error_ms": 0.0, "new_max_boundary_error_ms": 10.0, "extra_prediction": False},
        {"role": "context", "old_missing": False, "new_missing": False,
         "delta_max_boundary_error_ms": 0.0, "new_max_boundary_error_ms": 10.0, "extra_prediction": False},
        {"role": "extra", "invalid_unpairable": True, "extra_prediction": True,
         "old_missing": True, "new_missing": False, "delta_max_boundary_error_ms": None,
         "new_max_boundary_error_ms": None},
    ]
    agg = aggregate_region_outcome(rows)
    assert agg["n_target"] == 1
    assert agg["n_fixed_context"] == 1
    assert agg["n_context"] == 1
    assert agg["n_extra"] == 1
    assert agg["outcome"] == "harmful"
    cand = aggregate_candidate_outcome([agg])
    assert cand["n_fixed_context"] == 1 and cand["n_extra"] == 1


def test_degraded_requires_material_delta_not_absolute_new_error():
    baseline_poor = {"role": "context", "old_missing": False, "new_missing": False,
                     "old_max_boundary_error_ms": 1200.0, "new_max_boundary_error_ms": 1200.0,
                     "delta_max_boundary_error_ms": 0.0, "extra_prediction": False}
    assert classify_unit_outcome(baseline_poor) == "unchanged_finite"
    regression = dict(baseline_poor, new_max_boundary_error_ms=1500.0, delta_max_boundary_error_ms=300.0)
    assert classify_unit_outcome(regression) == "degraded_finite"
    assert aggregate_region_outcome([baseline_poor])["outcome"] == "neutral"
