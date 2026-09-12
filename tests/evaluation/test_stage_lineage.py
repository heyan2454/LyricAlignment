"""Tests for per-stage degeneracy attribution and the pinned-to-window-anchor detector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyricalign.analysis import structural_compliance as S


def _write(path: Path, units: list[dict], *, window_trace: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "identity": {"audio": {"path": "/a.wav", "sha256": "s"}, "request_hash": "r",
                     "schema_version": "sv", "window": {"policy": "p", "core_sec": 60.0}},
        "summary": {"audio_duration_sec": 300.0, "language": "English"},
        "window_trace": window_trace,
        "characters": units,
    }, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def fake_batch(tmp_path: Path) -> Path:
    # unit 0: sane raw, then pinned to the window input boundary (64.48) by the fixed stage
    # unit 1: sane all the way through
    # unit 2: negative at raw (decoder defect), stays negative-free after fixed
    good = [{"character": "Oh", "unit_type": "word",
             "raw_global_start_sec": 70.0, "raw_global_end_sec": 70.4,
             "fixed_global_start_sec": 64.48, "fixed_global_end_sec": 64.48,
             "selected_start_sec": 64.48, "selected_end_sec": 64.48,
             "start_sec": 64.48, "end_sec": 64.48},
            {"character": "bear", "unit_type": "word",
             "raw_global_start_sec": 70.5, "raw_global_end_sec": 71.0,
             "fixed_global_start_sec": 70.5, "fixed_global_end_sec": 71.0,
             "selected_start_sec": 70.5, "selected_end_sec": 71.0,
             "start_sec": 70.5, "end_sec": 71.0},
            {"character": "low", "unit_type": "word",
             "raw_global_start_sec": 72.0, "raw_global_end_sec": 71.0,   # negative raw
             "fixed_global_start_sec": 72.0, "fixed_global_end_sec": 72.4,
             "selected_start_sec": 72.0, "selected_end_sec": 72.4,
             "start_sec": 72.0, "end_sec": 72.4}]
    _write(tmp_path / "s1" / S.ALIGN_RELPATH, good,
           window_trace=[{"window_index": 0, "core_start_sec": 66.48, "core_end_sec": 126.33,
                          "input_start_sec": 64.48, "input_end_sec": 136.33,
                          "committed_character_start": 0, "committed_character_end": 3}])
    return tmp_path


def test_stage_lineage_locates_the_damage_at_the_fixed_stage(fake_batch: Path):
    res = S.stage_lineage_attribution(fake_batch)
    tt = res["totals"]
    assert tt["raw"]["degenerate_share"] == pytest.approx(1 / 3, abs=1e-4)    # negative-raw unit
    assert tt["fixed"]["degenerate_share"] == pytest.approx(1 / 3, abs=1e-4)  # a different unit
    assert res["stage_transitions_degenerate_share_delta"]["raw->fixed"] == pytest.approx(0.0)
    # per-song net semantics: one unit created by fixed (+1) and one raw-negative unit made legal (-1)
    # cancel, which is why the unit-level created count lives in compression_damage()
    assert res["per_song"][0]["net_added_by_fixed"] == 0
    assert res["per_song"][0]["net_added_by_selected"] == 0
    assert res["sum_of_positive_net_additions_by_stage"].get("net_added_by_fixed", 0) == 0


def test_pinned_to_window_input_detector(fake_batch: Path):
    res = S.stage_lineage_attribution(fake_batch)
    pw = res["pinned_to_window_input"]
    assert pw["units"] == 1                        # the block pinned to 64.48 = window input_start
    assert pw["songs_affected"] == 1
    assert pw["top_songs"][0]["song"] == "s1"
    assert res["per_song"][0]["pinned_to_window_input_share"] == pytest.approx(1 / 3, abs=1e-4)


def test_missing_artifacts_are_survivable(tmp_path: Path):
    (tmp_path / "junk").mkdir()
    res = S.stage_lineage_attribution(tmp_path)
    assert res["per_song"] == []
    assert res["pinned_to_window_input"]["units"] == 0
    assert res["stage_transitions_degenerate_share_delta"] == {}


def test_triage_by_song_separates_repairable_from_destroyed(fake_batch: Path):
    """The triage table must send high-degeneracy songs to re-decode, not to a cosmetic fix."""
    from lyricalign.analysis import structural_compliance as S

    df, _meta = S.load_batch(fake_batch)
    df = S.flag_violations(df)
    df, _rep = S.repair(df)
    lin = S.stage_lineage_attribution(fake_batch)
    table = S.triage_by_song(df, lin, language="English")
    assert len(table) == 1
    row = table.iloc[0]
    assert row["units"] == 3
    assert row["illegal_share"] > 0.0                     # one unit pinned to the window anchor
    assert row["pinned_units"] == 1
    assert row["triage"] in {"review", "repair+review", "re-decode", "ship-ok"}
    assert "median_repair_shift_sec" in table.columns


def test_triage_bands_are_monotone():
    from lyricalign.analysis import structural_compliance as S

    bands = S.TRIAGE_BANDS
    thresholds = [lo for lo, _ in bands]
    assert thresholds == sorted(thresholds, reverse=True)
    labels = [label for _, label in bands]
    assert labels == ["re-decode", "repair+review", "review", "ship-ok"]


def test_stage_key_pairs_are_not_conflated():
    """Regression guard: an earlier version paired the start-key list with the wrong end-key list and
    reported the whole `fixed` stage as missing."""
    char = {"fixed_global_start_sec": 1.0, "fixed_global_end_sec": 2.0,
            "raw_global_start_sec": 1.0, "raw_global_end_sec": 2.0}
    assert S._stage_bounds(char, "fixed") == (1.0, 2.0)
    assert S._stage_bounds(char, "raw") == (1.0, 2.0)
    assert S._stage_bounds(char, "selected") == (None, None)
    assert S._stage_bounds({"official_fixed_start_sec": 3.0, "official_fixed_end_sec": 4.0},
                           "fixed") == (3.0, 4.0)
