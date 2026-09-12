"""Tests for the additive per-stage degeneracy accounting in the alignment artifacts helper."""

from __future__ import annotations

from lyricalign.demo.alignment_artifacts import stage_degeneracy_audit


def _row(idx, *, raw=(0.0, 0.5), fixed=(1.0, 1.0), selected=None, final=None):
    row = {"global_character_index": idx, "character": "x",
           "raw_global_start_sec": raw[0], "raw_global_end_sec": raw[1],
           "fixed_global_start_sec": fixed[0], "fixed_global_end_sec": fixed[1]}
    row["selected_start_sec"] = (selected or fixed)[0]
    row["selected_end_sec"] = (selected or fixed)[1]
    row["start_sec"] = (final or selected or fixed)[0]
    row["end_sec"] = (final or selected or fixed)[1]
    return row


def test_reports_per_stage_shares_and_net_creation():
    # row0/row1 are made degenerate by the fixed stage; row2 was negative in raw and is legalised
    rows = [_row(0), _row(1, raw=(1.0, 1.6), fixed=(1.0, 1.0)),
            _row(2, raw=(2.0, 1.0), fixed=(2.0, 2.5))]
    out = stage_degeneracy_audit(rows)
    assert out["units"] == 3
    # raw: one negative duration; fixed: that one plus the newly collapsed one; selected/final follow
    assert out["negative_duration_units"]["raw"] == 1
    assert out["zero_duration_units"]["raw"] == 0
    # the production stage name is `processor_decoded` (what my audit modules call "fixed")
    assert out["zero_duration_units"]["processor_decoded"] == 2
    assert out["degenerate_share"]["raw"] == round(1 / 3, 4)
    assert out["degenerate_share"]["processor_decoded"] == round(2 / 3, 4)
    # the fixed stage created one net degenerate unit (it also "fixed" the negative one)
    assert out["net_added_degenerate_units"]["raw->processor_decoded"] == 1
    assert out["net_added_degenerate_units"]["processor_decoded->selected"] == 0
    assert any(w.startswith("degeneracy_added_by_raw->") for w in out["warnings"])


def test_pinned_to_window_anchor_is_counted():
    trace = [{"window_index": 0, "input_start_sec": 1.0, "core_start_sec": 3.0}]
    rows = [_row(0, fixed=(1.0, 1.0)), _row(1, fixed=(1.0, 1.0)), _row(2, fixed=(4.0, 4.6))]
    out = stage_degeneracy_audit(rows, trace)
    assert out["pinned_to_window_anchor_units"] == 2
    assert out["pinned_to_window_anchor_rate"] == round(2 / 3, 4)
    assert "pinned_to_window_anchor" in out["warnings"]


def test_missing_stage_keys_do_not_raise():
    rows = [{"global_character_index": 0, "raw_global_start_sec": 0.0, "raw_global_end_sec": 0.5}]
    out = stage_degeneracy_audit(rows, None)
    assert out["units"] == 1
    assert out["known_units"]["raw"] == 1
    assert out["known_units"]["final"] == 0
    assert out["degenerate_share"]["final"] is None
    assert out["warnings"] == []


def test_clean_timeline_has_no_warnings():
    rows = [_row(i, raw=(i * 1.0, i * 1.0 + 0.5),
                 fixed=(i * 1.0 + 0.1, i * 1.0 + 0.6),
                 selected=(i * 1.0 + 0.1, i * 1.0 + 0.6),
                 final=(i * 1.0 + 0.1, i * 1.0 + 0.6)) for i in range(5)]
    out = stage_degeneracy_audit(rows, [{"window_index": 0, "input_start_sec": 99.0}])
    assert out["degenerate_share"] == {"raw": 0.0, "processor_decoded": 0.0,
                                       "selected": 0.0, "final": 0.0}
    assert all(v == 0 for v in out["net_added_degenerate_units"].values())
    assert out["pinned_to_window_anchor_units"] == 0 and out["warnings"] == []
