"""Tests for WP8 P6 adaptive expansion orchestration."""
from __future__ import annotations

import pytest

from lyricalign.unit_realign.adaptive_expansion import (
    region_recovery,
    rank_mechanisms,
    select_regions_for_expansion,
)


def _e2_row():
    return {"region_id": "r2", "song_id": "s2", "strict_200_recovery": 0.9,
            "strict_100_recovery": 0.8, "fixed_context_displacement_ms": 10.0,
            "catastrophic_regression": False, "forward_count": 5}


def _e4_row():
    return {"region_id": "r4", "song_id": "s4", "target_recovered_200": 0.95,
            "target_recovered_100": 0.85, "fixed_context_displacement_ms": 5.0,
            "catastrophic_regression": False, "forward_cost": 2}


def _e1_row():
    return {"region_id": "r1", "song_id": "s1", "case_pct_recovered": 90.0,
            "fixed_context_displacement_ms": 20.0, "catastrophic_regression": False}


def test_region_recovery_reads_real_runner_fields():
    """Y-review P0: real FINAL field names must be recognized."""
    assert region_recovery(_e2_row())["strict_200"] == 0.9
    assert region_recovery(_e4_row())["strict_200"] == 0.95
    assert region_recovery(_e1_row())["strict_200"] == 0.9  # case_pct/100 -> 0.9


def test_rank_mechanisms_ranks_real_fields_and_fails_closed():
    rank = rank_mechanisms({"E2": [_e2_row()], "E4": [_e4_row()], "E1": [_e1_row()]}, top_k=2)
    ranked = {m["mechanism_id"]: m for m in rank}
    assert "E4" in ranked and ranked["E4"]["recovery_score"] > 0.9
    assert len(rank) <= 2
    # fail-closed: a mechanism with no recovery field raises, not silent-zero.
    with pytest.raises(ValueError):
        rank_mechanisms({"BAD": [{"family": "R-X"}]}, top_k=2)


def _population(songs=10, regions_per_song=30):
    out = []
    for s in range(songs):
        for i in range(regions_per_song):
            out.append({"region_id": f"s{s}:r{i}", "song_id": f"song{s}",
                        "target_unit_ids": [i], "baseline_available": True,
                        "overlap_interval_sec": [float(i), float(i + 1)]})
    return out


def test_select_regions_disjoint_song_held_out():
    pop = _population(songs=50, regions_per_song=30)
    screening_ids = {p["region_id"] for p in pop[:60]}
    sel = select_regions_for_expansion(
        pop, mechanism_subset=["R-U"], target_n=200, per_song_cap=6,
        screening_region_ids=screening_ids, confirmation_target=40, seed=0,
    )
    main_ids = {r["region_id"] for r in sel["main"]}
    conf_ids = {r["region_id"] for r in sel["confirmation"]}
    assert main_ids & screening_ids == set()
    assert conf_ids & screening_ids == set()
    main_songs = {r["song_id"] for r in sel["main"]}
    conf_songs = {r["song_id"] for r in sel["confirmation"]}
    assert main_songs & conf_songs == set()  # song-held-out
    assert len(main_ids) >= 200 and len(conf_ids) == 40
