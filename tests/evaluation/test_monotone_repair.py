"""Tests for the shadow monotone repair (never zero-length, legal by construction)."""

from __future__ import annotations

import numpy as np
import pytest

from lyricalign.analysis.monotone_repair import repair_monotone_min_duration


def _check_legal(res, min_dur=0.08):
    s, e = res["starts"], res["ends"]
    assert np.all(e > s + 1e-9)                 # no zero-length unit
    assert np.all(e - s >= min_dur - 1e-9)      # minimum duration honoured
    assert np.all(np.diff(s) >= min_dur - 1e-9)  # starts strictly spaced
    assert np.all(e[:-1] <= s[1:] + 1e-9)       # no overlap with the next unit


def test_repair_of_a_collapsed_span_is_legal_and_uses_the_raw_anchors():
    """The upstream bug makes a whole span share one timestamp; the shadow repair must not."""
    starts = np.array([0.0, 10.0, 10.0, 10.0, 10.0, 20.0])
    ends = np.array([0.5, 10.0, 10.0, 10.0, 10.0, 20.5])
    res = repair_monotone_min_duration(starts, ends)
    _check_legal(res)
    assert res["zero_length_units"] == 0
    # the anchors that were already fine are preserved
    assert res["starts"][0] == pytest.approx(0.0)
    assert res["ends"][-1] == pytest.approx(20.5)


def test_repair_of_an_inverted_pair_does_not_create_a_zero():
    res = repair_monotone_min_duration(np.array([5.0]), np.array([3.0]))
    _check_legal(res)
    assert res["ends"][0] == pytest.approx(5.08)


def test_repair_respects_audio_duration():
    starts = np.array([9.9, 9.95, 10.2])
    ends = np.array([10.0, 10.0, 10.3])
    res = repair_monotone_min_duration(starts, ends, duration=10.5)
    _check_legal(res)
    assert res["ends"][-1] <= 10.5 + 1e-9


def test_repair_handles_nan_and_empty_input():
    res = repair_monotone_min_duration(np.array([np.nan, 1.0]), np.array([np.nan, 1.2]))
    assert np.all(np.isfinite(res["starts"])) and np.all(np.isfinite(res["ends"]))
    empty = repair_monotone_min_duration(np.array([]), np.array([]))
    assert empty["starts"].size == 0


def test_repair_stage_frame_applies_per_song():
    import pandas as pd
    from lyricalign.analysis.monotone_repair import repair_stage_frame

    frame = pd.DataFrame({
        "song": ["a", "a", "b", "b"],
        "start_sec": [0.0, 0.0, 0.0, 0.0],
        "end_sec": [0.5, 0.0, 0.0, 0.4]})
    out, diag = repair_stage_frame(frame)
    assert diag["songs"] == 2
    for song, sub in out.groupby("song"):
        assert np.all(sub["end_sec"] - sub["start_sec"] >= 0.08 - 1e-9)


def test_targeted_repair_leaves_healthy_units_untouched():
    from lyricalign.analysis.monotone_repair import repair_targeted_blocks

    starts = np.array([0.0, 1.0, 2.0, 3.0, 3.0, 3.0, 6.0, 7.0])
    ends = np.array([0.9, 1.9, 2.9, 3.0, 3.0, 3.0, 6.9, 7.9])
    res = repair_targeted_blocks(starts, ends)
    # healthy units outside the collapsed run keep their exact timestamps
    for idx in (0, 1, 2, 6, 7):
        assert res["starts"][idx] == starts[idx] and res["ends"][idx] == ends[idx]
    # the collapsed run is redistributed without creating new degeneracies
    assert res["zero_length_units"] == 0 and res["illegal_units"] == 0
    assert res["blocks"] == 1 and res["repaired_units"] == 3
    assert res["untouched_units"] == 5 and res["moved_units"] == 3
    # the redistributed run stays strictly inside its healthy neighbours
    assert res["starts"][3] >= ends[2] - 1e-9
    assert res["ends"][5] <= starts[6] + 1e-9
    assert np.all(np.diff(res["starts"][3:6]) > 0)


def test_targeted_repair_fixes_inverted_units():
    from lyricalign.analysis.monotone_repair import repair_targeted_blocks

    res = repair_targeted_blocks(np.array([5.0]), np.array([3.0]))
    assert res["zero_length_units"] == 0 and res["ends"][0] > res["starts"][0]
    assert res["blocks"] == 1 and res["repaired_units"] == 1


def test_targeted_repair_is_a_noop_on_a_clean_timeline():
    from lyricalign.analysis.monotone_repair import repair_targeted_blocks

    starts = np.arange(0.0, 5.0, 1.0)
    ends = starts + 0.5
    res = repair_targeted_blocks(starts, ends)
    assert res["blocks"] == 0 and res["moved_units"] == 0
    assert np.allclose(res["starts"], starts) and np.allclose(res["ends"], ends)


def test_local_overlap_resolution_trims_only_the_crossing_ends():
    """Measured semantics: starts stay put, only ends that cross the next start are trimmed."""
    from lyricalign.analysis.monotone_repair import resolve_overlaps_locally

    starts = np.array([0.0, 1.0, 1.2, 3.0, 4.0])
    ends = np.array([1.1, 1.3, 2.0, 3.5, 4.5])       # ends 0 and 1 cross their successors' starts
    res = resolve_overlaps_locally(starts, ends)
    assert res["illegal_units"] == 0 and res["zero_length_units"] == 0
    assert res["starts"].tolist() == starts.tolist()          # no start was moved
    assert res["ends"][:2].tolist() == [1.0, 1.2]             # trimmed exactly to the next start
    assert res["ends"][2:].tolist() == [2.0, 3.5, 4.5]        # untouched
    assert res["moved_units"] == 2


def test_recommended_chain_is_legal_on_a_mixed_timeline():
    from lyricalign.analysis.monotone_repair import repair_all_targeted

    starts = np.array([0.0, 1.0, 2.0, 2.0, 2.0, 5.0, 5.5])
    ends = np.array([0.9, 1.9, 2.0, 2.0, 2.0, 5.4, 5.5])
    res = repair_all_targeted(starts, ends)
    assert res["zero_length_units"] == 0
    assert res["illegal_units"] == 0
    assert res["starts"][0] == 0.0 and res["ends"][0] == 0.9


def test_default_policy_is_bit_identical_to_current_behaviour():
    """The flag must be safe: 'upstream_repaired' changes nothing at all."""
    from lyricalign.analysis.monotone_repair import apply_fixed_timestamp_policy

    raw_s = np.array([0.0, 1.0, 2.0]); raw_e = np.array([0.9, 1.9, 2.9])
    off_s = np.array([5.0, 5.0, 5.0]); off_e = np.array([5.0, 5.0, 5.0])   # collapsed by upstream
    res = apply_fixed_timestamp_policy(raw_s, raw_e, off_s, off_e)
    assert res["policy"] == "upstream_repaired"
    assert res["starts"].tolist() == off_s.tolist()
    assert res["ends"].tolist() == off_e.tolist()
    assert res["changed_units"] == 0


def test_recommended_policy_removes_the_collapse_and_uses_raw_anchors():
    from lyricalign.analysis.monotone_repair import apply_fixed_timestamp_policy

    raw_s = np.array([0.0, 1.0, 2.0]); raw_e = np.array([0.9, 1.9, 2.9])
    off_s = np.array([5.0, 5.0, 5.0]); off_e = np.array([5.0, 5.0, 5.0])
    res = apply_fixed_timestamp_policy(raw_s, raw_e, off_s, off_e,
                                       policy="raw_with_targeted_repair")
    assert res["measured"] is True
    assert res["zero_length_units"] == 0
    assert res["starts"].tolist() == raw_s.tolist()       # healthy raw values are kept verbatim
    assert res["ends"].tolist() == raw_e.tolist()


def test_experimental_policy_is_marked_unmeasured_and_unknown_names_are_rejected():
    from lyricalign.analysis.monotone_repair import apply_fixed_timestamp_policy

    raw_s = np.array([0.0, 1.0]); raw_e = np.array([0.9, 1.9])
    off_s = np.array([3.0, 3.0]); off_e = np.array([3.0, 3.0])
    res = apply_fixed_timestamp_policy(raw_s, raw_e, off_s, off_e,
                                       policy="upstream_with_block_repair")
    assert res["measured"] is False
    assert res["zero_length_units"] == 0
    with pytest.raises(ValueError):
        apply_fixed_timestamp_policy(raw_s, raw_e, off_s, off_e, policy="whatever")


def test_row_level_policy_default_is_identity_and_opted_in_policy_rewrites_rows():
    from lyricalign.analysis.monotone_repair import apply_fixed_timestamp_policy_rows

    def _rows():
        return [{"raw_local_start_sec": 0.0, "raw_local_end_sec": 0.9,
                 "official_fixed_local_start_sec": 5.0, "official_fixed_local_end_sec": 5.0},
                {"raw_local_start_sec": 1.0, "raw_local_end_sec": 1.9,
                 "official_fixed_local_start_sec": 5.0, "official_fixed_local_end_sec": 5.0}]

    same, diag_off = apply_fixed_timestamp_policy_rows(_rows())
    assert diag_off["policy"] == "upstream_repaired"
    assert [r["fixed_local_start_sec"] for r in same] == [5.0, 5.0]      # untouched by default
    assert [r["fixed_global_start_sec"] for r in same] == [5.0, 5.0]

    fixed, diag_on = apply_fixed_timestamp_policy_rows(
        _rows(), policy="raw_with_targeted_repair", offset_sec=10.0)
    assert diag_on["measured"] is True and diag_on["zero_length_units"] == 0
    assert [r["fixed_local_start_sec"] for r in fixed] == [0.0, 1.0]
    assert [r["fixed_global_end_sec"] for r in fixed] == [10.9, 11.9]
    assert all(r["fixed_timestamp_policy"] == "raw_with_targeted_repair" for r in fixed)
