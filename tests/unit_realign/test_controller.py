from lyricalign.unit_realign.controller import choose_surviving_families, expansion_plan, summarize_case_family_status


def test_screening_uses_no_gt_validity_and_caps_survivors():
    requests = [{"family": "R-U", "effective_intervention": True} for _ in range(9)]
    requests += [{"family": "R-B", "effective_intervention": True} for _ in range(7)]
    result = choose_surviving_families(requests, [], min_valid=8)
    assert result["surviving_families"] == ["R-U"]
    assert result["status"] == "ready_for_expansion"


def test_expansion_resume_skips_completed_and_respects_song_cap():
    population = [{"region_id": f"{song}{i}", "song_id": song, "seed_kind": "unsafe_region"}
                  for song in ("a", "b") for i in range(3)]
    result = expansion_plan(population, completed_region_ids={"a0"}, target_regions=4, per_song_cap=2)
    assert "a0" not in {r["region_id"] for r in result["regions"]}
    assert result["selected_per_song"]["a"] <= 2


def test_screen_does_not_count_null_or_failed_as_valid_and_reports_denominators():
    rows = [{"family": "R-B", "stratum": "S3", "status": state, "effective_intervention": True}
            for state in ("selected", "not_constructible", "null", "failed", "invalid", "executed", "valid")]
    summary = summarize_case_family_status(rows)["by_family_stratum"][0]
    assert summary["selected"] == 7 and summary["valid"] == 1
    result = choose_surviving_families(rows, [], min_valid=2)
    assert result["surviving_families"] == []


def test_r_null_row_without_status_counts_as_null_not_selected():
    rows = [{"family": "R-NULL", "stratum": "S1", "effective_intervention": False}]
    summary = summarize_case_family_status(rows)["by_family_stratum"][0]
    assert summary["null"] == 1
    assert summary.get("selected_status", 0) == 0
    assert summary["selected"] == 1
