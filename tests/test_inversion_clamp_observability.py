"""Pins the 2026-09-12 root-cause chain: a decoder start/end inversion is silently clamped into a
zero-length row that the shipped collapse counter does not count, and the per-stage observability
added in rounds 14/16 is what makes it visible."""

from __future__ import annotations

from lyricalign.demo.alignment_artifacts import stage_degeneracy_audit
from lyricalign.demo.karaoke import append_strict_core_commits


def _row(idx, *, fixed_start, fixed_end, raw_start, raw_end):
    return {"global_character_index": idx, "character": "a", "unit_type": "cjk_character",
            "fixed_global_start_sec": fixed_start, "fixed_global_end_sec": fixed_end,
            "raw_global_start_sec": raw_start, "raw_global_end_sec": raw_end,
            "owner_window_index": 1}


def _existing(idx, start, end):
    row = _row(idx, fixed_start=start, fixed_end=end, raw_start=start, raw_end=end)
    row["selected_start_sec"] = start
    row["selected_end_sec"] = end
    row["start_sec"] = start
    row["end_sec"] = end
    return row


def test_inverted_row_is_clamped_to_zero_without_a_negative():
    existing = [_existing(0, 5.0, 10.0)]
    # the decoder said start=12.0, end=3.0 (a 9 s inversion) inside a later window
    incoming = [_row(1, fixed_start=12.0, fixed_end=3.0, raw_start=12.0, raw_end=3.0)]
    window = {"window_index": 1, "core_start_sec": 10.0, "core_end_sec": 20.0,
              "input_start_sec": 8.0, "input_end_sec": 22.0,
              "committed_character_start": 1, "committed_character_end": 2}
    out = append_strict_core_commits(existing, incoming, window=window, duration_sec=30.0,
                                     previous_end_override_sec=10.0)
    new = out[-1]
    assert new["selected_end_sec"] >= new["selected_start_sec"]      # no negatives survive
    final_dur = new["end_sec"] - new["start_sec"]
    assert final_dur >= -1e-9
    # the blind spot, precisely: the zero-length row comes from the pre-compression clamp at
    # karaoke.py:571 (end := max(end, start)), *not* from overlap compression, so both shipped
    # counters stay silent about it -- that is why 870 inversions showed up as "4" collapsed units
    assert new["end_sec"] - new["start_sec"] <= 1e-6
    assert bool(new.get("overlap_compressed")) is False
    assert bool(new.get("overlap_compression_collapsed_to_zero")) is False


def test_per_stage_observability_flags_the_inversion():
    rows = [_row(0, fixed_start=1.0, fixed_end=1.6, raw_start=1.0, raw_end=1.6),
            _row(1, fixed_start=12.0, fixed_end=12.0, raw_start=12.0, raw_end=3.0)]
    for r in rows:
        r.setdefault("selected_start_sec", r["fixed_global_start_sec"])
        r.setdefault("selected_end_sec", r["fixed_global_end_sec"])
        r["start_sec"] = r["selected_start_sec"]
        r["end_sec"] = r["selected_end_sec"]
    out = stage_degeneracy_audit(rows)
    assert out["negative_duration_units"]["raw"] == 1               # visible at raw
    assert out["negative_duration_units"]["processor_decoded"] == 0  # invisible after the clamp
    assert out["degenerate_share"]["raw"] is not None
    assert "start_after_end_at_raw" in out["warnings"]
    assert out["start_after_end_units"]["raw"] == 1


def test_clean_batch_produces_no_start_after_end_warning():
    rows = [_row(i, fixed_start=i * 1.0, fixed_end=i * 1.0 + 0.5,
                 raw_start=i * 1.0, raw_end=i * 1.0 + 0.5) for i in range(6)]
    for r in rows:
        r["selected_start_sec"] = r["fixed_global_start_sec"]
        r["selected_end_sec"] = r["fixed_global_end_sec"]
        r["start_sec"] = r["selected_start_sec"]
        r["end_sec"] = r["selected_end_sec"]
    out = stage_degeneracy_audit(rows)
    assert all(v == 0 for v in out["start_after_end_units"].values())
    assert not any(w.startswith("start_after_end") for w in out["warnings"])
