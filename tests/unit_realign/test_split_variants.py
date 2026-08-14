"""Tests for E2 fine-grain split partition logic (07 plan WP4)."""
from __future__ import annotations

from lyricalign.unit_realign.split_variants import _effective_family, partition_region


def _region_with_state(n=8):
    units = [
        {"canonical_unit_id": i, "text": str(i), "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.3,
         "state": ("REJECT" if 1 <= i <= 6 else "ACCEPT")}
        for i in range(n)
    ]
    return {"song_id": "s", "region_id": "r", "units": units,
            "detector_state": "UNSAFE", "target_unit_ids": list(range(1, 7))}


def _region_without_state(detector_state="UNSAFE"):
    units = [
        {"canonical_unit_id": i, "text": str(i), "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.3}
        for i in range(8)
    ]
    return {"song_id": "s", "region_id": "r", "units": units,
            "detector_state": detector_state, "target_unit_ids": [1, 2, 3]}


def test_partition_with_unit_state_one_unit():
    """State-carrying region splits to one subtarget per unsafe unit (no fallback)."""
    subs = partition_region(_region_with_state(), "one_unit")
    assert [s["sub_target_unit_ids"][0] for s in subs] == [1, 2, 3, 4, 5, 6]
    assert all(s["boundary_kind"] == "one_unit" for s in subs)


def test_partition_without_state_falls_back_not_empty():
    """WP4 P0 fix: a region with no unit state must not silently return empty."""
    region = _region_without_state()
    for partition in ("one_unit", "two_unit", "adaptive", "anchor_gap"):
        subs = partition_region(region, partition)
        assert subs, f"{partition} returned empty on state-missing region"
        first = subs[0]
        assert first["boundary_kind"] == "state_missing_fallback"
        assert first["meta"]["state_missing_fallback"] is True
        # fallback uses the region-level UNSAFE target ids.
        assert first["sub_target_unit_ids"] == [1, 2, 3]


def test_partition_without_state_uses_whole_units_when_no_targets():
    region = _region_without_state()
    region["target_unit_ids"] = []
    del region["detector_state"]
    subs = partition_region(region, "one_unit")
    assert subs and subs[0]["boundary_kind"] == "state_missing_fallback"


def test_effective_family_r_a_fallback_on_long_span():
    assert _effective_family("R-U", 3) == "R-U"
    assert _effective_family("R-U", 5) == "R-A"
