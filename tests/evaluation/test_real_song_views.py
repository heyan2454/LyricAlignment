"""Fast tests for the real-song cross-view census (synthetic alignment files only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyricalign.analysis import real_song_views as R

VIEW_NAMES = ("b4_60s_windowed", "current_silence_aware", "full_slot")
# the production guard drops sequences shorter than 8 units; the fixture uses 6
UNITS_PER_SONG = 6
SILENCE_FLAGS = {"core_sec": 10.0, "left_context_sec": 2.0,
                 "policy": "silence_aware_global_core_plan_v7",
                 "silence_aware_window_plan": True, "skip_silent_windows": True,
                 "strong_silence_anchor_sec": None}
BATCH_FLAGS = {"core_sec": 10.0, "policy": "global_core_plan_v4", "left_context_sec": 2.0}
SCHEMAS = {"b4_60s_windowed": "qwen_fa_serial_demo_v7_silence_aware_windows",
           "current_silence_aware": "qwen_fa_batch_alignment_v4_forward_overlap_compression",
           "full_slot": ""}


def _doc(units, *, schema, window_flags, audio_sha):
    return {
        "identity": {"schema_version": schema,
                     "audio": {"path": f"/audio/{audio_sha}.wav", "sha256": audio_sha},
                     "mode": "windowed",
                     "decoder": {"kind": "official"},
                     "window": window_flags},
        "summary": {"audio_duration_sec": 20.0, "language": "Chinese"},
        "characters": [{"character": c, "unit_type": "cjk_character",
                        "selected_start_sec": s, "selected_end_sec": e,
                        "raw_global_start_sec": s, "raw_global_end_sec": e,
                        "raw_start_entropy": 0.3, "raw_end_entropy": 0.4}
                       for c, s, e in units],
        "window_trace": [{"core_start_sec": 0.0, "core_end_sec": 10.0,
                          "committed_character_start": 0,
                          "committed_character_end": len(units)}],
    }


@pytest.fixture()
def fake_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(R, "MIN_UNITS", 2)
    """Two songs x three views; s1 agrees across views, s2 is shifted by 1.5 s, and the
    full_slot view drops one unit (index drift) to exercise the comparability guard."""
    roots = {name: tmp_path / name for name in VIEW_NAMES}
    monkeypatch.setattr(R, "VIEWS", roots)
    base = [chr(0x4E00 + i) for i in range(UNITS_PER_SONG)]
    # b4 differs from the batch view on song s2 only (1.5 s), which is the disagreement we
    # want the census to surface; full_slot additionally drops a unit to trigger index drift.
    offsets = {("b4_60s_windowed", "s1"): 0.0, ("b4_60s_windowed", "s2"): 1.5,
               ("current_silence_aware", "s1"): 0.0, ("current_silence_aware", "s2"): 0.0,
               ("full_slot", "s1"): 0.0, ("full_slot", "s2"): 0.0}
    for name, root in roots.items():
        for song in ("s1", "s2"):
            shift = offsets[(name, song)]
            units = [(c, i * 1.0 + shift, i * 1.0 + 0.5 + shift)
                     for i, c in enumerate(base)]
            if name == "full_slot":
                units = units[1:] + [("~", 6.0, 6.5)]
            p = root / song / "alignments" / "r2" / "vocal" / "windowed"
            p.mkdir(parents=True, exist_ok=True)
            flags = SILENCE_FLAGS if name == "b4_60s_windowed" else BATCH_FLAGS
            doc = _doc(units, schema=SCHEMAS[name], window_flags=flags, audio_sha="SHA_A")
            (p / "alignment.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_identity_provenance_records_flag_gaps(fake_views: Path):
    out = fake_views / "panel"
    stats = R.build_panel(out)
    prov = stats["identity_provenance"]
    assert prov["b4_60s_windowed"]["songs_recording_silence_flags"] == 2
    assert prov["current_silence_aware"]["songs_recording_silence_flags"] == 0
    assert prov["full_slot"]["schema_versions"] == {"": 2}
    assert stats["songs_used"] == 2


def test_comparability_guard_rejects_drifted_view(fake_views: Path):
    out = fake_views / "panel"
    stats = R.build_panel(out)
    df = R.load_frame(out / "real_song_views.jsonl.gz")
    a = R.analyse(df)
    comp = a["comparability"]
    assert comp["share_b4_cur_character_identical"] == 1.0
    assert comp["share_b4_slot_character_identical"] < 1.0
    assert "full_slot" in comp["decision"]
    pairs = a["pair_disagreement"]
    # song s2 differs by 1.5 s between the two comparable views -> half the units disagree
    assert pairs["b4_vs_cur"]["share_gt_100ms"] == pytest.approx(0.5)
    assert pairs["b4_vs_cur"]["comparable_units"] == stats["rows"]
    assert pairs["b4_vs_slot"]["comparable_units"] < stats["rows"]


def test_language_rollup_and_targeting(fake_views: Path):
    out = fake_views / "panel3"
    stats = R.build_panel(out)
    df = R.load_frame(out / "real_song_views.jsonl.gz")
    a = R.analyse(df)
    assert a["panel"]["songs"] == 2
    assert a["panel"]["languages"].get("Chinese") == stats["rows"]
    assert {"language", "units", "zero_dur_b4", "zero_dur_slot"} <= set(a["by_language"][0])
    assert a["targeting_summary"]["units_gt250ms_spread"] > 0
    assert a["posterior_predicts_disagreement_auc"]


def test_postprocess_attribution_separates_created_from_healed(fake_views: Path):
    """The attribution must count degenerate units before/after the cleanup and identify the
    pinning mechanism, without ever claiming accuracy (there is no ground truth here)."""
    out = fake_views / "panel5"
    R.build_panel(out)
    df = R.load_frame(out / "real_song_views.jsonl.gz")
    pa = R.analyse_postprocess_attribution(df)
    assert pa["views"], "expected at least one view"
    b4 = pa["views"]["b4_60s_windowed"]
    assert b4["units"] == 12                              # 2 songs x 6 units
    assert b4["raw_degenerate_share"] <= b4["selected_degenerate_share"]
    assert b4["created_by_postprocess"] >= 0 and b4["healed_by_postprocess"] >= 0
    assert b4["net_change_in_degenerate"] == (b4["created_by_postprocess"]
                                             - b4["healed_by_postprocess"])
    assert 0.0 <= b4["raw_overlap_rate"] <= 1.0
    assert b4["raw_structural_defects"]["negative_duration_share"] >= 0.0
    assert b4["selected_structural_defects"]["negative_duration_share"] == 0.0
    assert {"cjk_character"} <= set(b4["by_unit_type"])
    assert pa["headline"]["verdict"] in {
        "cleanup is degenerate-neutral", "cleanup CREATES degenerate units",
        "cleanup REMOVES degenerate units"}


def test_min_unit_guard(fake_views: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(R, "MIN_UNITS", 10)          # every synthetic song has 6 units
    out = fake_views / "panel4"
    stats = R.build_panel(out)
    assert stats["rows"] == 0
    assert stats["skipped_unit_count_mismatch"]
