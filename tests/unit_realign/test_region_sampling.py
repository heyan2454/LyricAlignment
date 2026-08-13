from lyricalign.unit_realign.region_sampling import (
    adaptive_sample, assign_gt_stratum, balanced_replenishment, build_region_population,
)


def test_region_population_splits_unsafe_and_keeps_accept_controls():
    rows = [{
        "song_id": "s", "window_index": 0,
        "detector_shadow": {"units": {
            str(i): {"state": "REJECT" if 2 <= i <= 10 else "ACCEPT"} for i in range(12)
        }},
    }]
    pop = build_region_population(rows, max_units=8)
    unsafe = [r for r in pop if r["seed_kind"] == "unsafe_region"]
    assert len(unsafe) == 44  # all 1..8 contiguous spans in a 9-unit unsafe run
    assert [2] in [r["target_unit_ids"] for r in unsafe]
    assert list(range(2, 10)) in [r["target_unit_ids"] for r in unsafe]
    assert any(r["seed_kind"] == "accept_control" for r in pop)


def test_adaptive_sample_is_song_fair_and_audits_exhaustion():
    population = [{"region_id": f"{song}{i}", "song_id": song}
                  for song in ("a", "b") for i in range(3)]
    rows, audit = adaptive_sample(population, target=5, per_song_cap=2)
    assert len(rows) == 4
    assert audit["status"] == "exhausted"
    assert audit["selected_per_song"] == {"a": 2, "b": 2}


def test_evaluator_strata_are_song_scoped_and_refill_avoids_overlap():
    population = [
        {"region_id": "a", "song_id": "s1", "target_unit_ids": [0], "detector_state": "ACCEPT", "origin": "natural", "overlap_interval_sec": [0, 1]},
        {"region_id": "b", "song_id": "s2", "target_unit_ids": [0], "detector_state": "UNSAFE", "origin": "natural", "overlap_interval_sec": [2, 3]},
        {"region_id": "c", "song_id": "s3", "target_unit_ids": [1], "detector_state": "UNSAFE", "origin": "natural", "overlap_interval_sec": [4, 5]},
    ]
    strata = assign_gt_stratum(population, {("s1", 0): {"max_boundary_error_ms": 0}, ("s2", 0): {"max_boundary_error_ms": 0}, ("s3", 1): {"max_boundary_error_ms": 1200}})
    assert [r["stratum"] for r in strata] == ["S1", "S2", "S3"]
    selected, audit = balanced_replenishment(strata, target_per_stratum=1)
    assert audit["status"] == "exhausted"
    assert {r["region_id"] for r in selected} == {"a", "b", "c"}


def test_invalid_baseline_interval_is_not_eligible_for_gt_stratum():
    population = build_region_population([{"song_id": "s", "window_index": 0, "detector_shadow": {
        "units": {"0": {"state": "REJECT", "start_sec": 1.0, "end_sec": 1.0}}}}])
    assert population[0]["baseline_available"] is False
    stratum = assign_gt_stratum(population, {("s", 0): {"max_boundary_error_ms": 1200}})[0]
    assert stratum["stratum"] is None
    assert stratum["stratum_status"] == "ineligible_invalid_baseline_interval"


def test_refill_resume_inherits_prior_target_and_time_overlap_constraints():
    population = [
        {"region_id": "old", "song_id": "s", "target_unit_ids": [1], "stratum": "S1", "origin": "natural", "overlap_interval_sec": [0, 1]},
        {"region_id": "same_unit", "song_id": "s", "target_unit_ids": [1], "stratum": "S1", "origin": "natural", "overlap_interval_sec": [2, 3]},
        {"region_id": "same_time", "song_id": "s", "target_unit_ids": [2], "stratum": "S1", "origin": "natural", "overlap_interval_sec": [.5, 1.5]},
        {"region_id": "fresh", "song_id": "s", "target_unit_ids": [3], "stratum": "S1", "origin": "natural", "overlap_interval_sec": [2, 3]},
    ]
    selected, _ = balanced_replenishment(
        population, target_per_stratum=2, prior_selected=[population[0]], per_song_cap=4,
    )
    assert [row["region_id"] for row in selected] == ["fresh"]
