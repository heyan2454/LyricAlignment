"""Tests for the raw-degeneracy forensics (synthetic timelines, no real batches touched)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lyricalign.analysis import raw_degeneracy_forensics as F


def _unit(i, raw_s, raw_e, fixed_s, fixed_e, *, ent=0.5, anchor=None):
    row = {"global_character_index": i, "character": chr(0x4E00 + i), "unit_type": "cjk_character",
           "raw_global_start_sec": raw_s, "raw_global_end_sec": raw_e,
           "fixed_global_start_sec": fixed_s, "fixed_global_end_sec": fixed_e,
           "selected_start_sec": fixed_s, "selected_end_sec": fixed_e,
           "start_sec": fixed_s, "end_sec": fixed_e,
           "raw_start_entropy": ent, "raw_end_entropy": ent,
           "raw_start_margin": 1.0 - ent, "raw_end_margin": 1.0 - ent,
           "inference_source": "strict_serial_core", "owner_window_index": 0}
    return row


@pytest.fixture()
def batch(tmp_path: Path) -> Path:
    chars = [_unit(0, 1.0, 1.5, 5.0, 5.0, anchor=5.0),        # raw fine, later pinned -> collapse
             _unit(1, 3.0, 2.0, 3.0, 3.4),                     # raw negative (1.0 s reversal)
             _unit(2, 6.0, 6.5, 6.0, 6.5),                     # clean
             _unit(3, 8.0, 7.0, 8.0, 8.4),                     # raw negative, healed later
             _unit(4, 9.0, 9.2, 9.0, 9.0),                     # collapse created at fixed
             _unit(5, 10.0, 10.4, 10.0, 10.4)]
    doc = {"identity": {"audio": {"sha256": "s", "path": "/a.wav"}, "request_hash": "r",
                        "schema_version": "sv", "window": {"policy": "p", "core_sec": 60.0}},
           "summary": {"audio_duration_sec": 30.0, "language": "Chinese", "window_count": 1},
           "window_trace": [{"window_index": 0, "input_start_sec": 5.0, "core_start_sec": 6.0,
                             "core_end_sec": 20.0, "committed_character_start": 0,
                             "committed_character_end": 6}],
           "characters": chars}
    d = tmp_path / "s1" / "alignments/r2/vocal/windowed"
    d.mkdir(parents=True)
    (d / "alignment.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_load_all_stages_and_flags(batch: Path):
    df = F.load_all_stages(batch)
    assert len(df) == 6 and df["song"].nunique() == 1
    assert int(df["raw_negative"].sum()) == 2
    assert int(df["pinned_to_window_anchor"].sum()) == 1        # fixed_s == window input_start (5.0)
    assert int(df["fixed_degenerate"].sum()) == 2


def test_profile_reports_magnitude_and_language(batch: Path):
    prof = F.profile(F.load_all_stages(batch))
    assert prof["units"] == 6
    assert prof["raw_negative_units"] == 2
    assert prof["by_language"]["Chinese"]["negative"] == 2
    assert prof["raw_negative_share"] == pytest.approx(2 / 6, abs=1e-3)   # share over ALL units
    # guards the DataFrame.size-vs-len mistake made once already (reported 209%)
    assert 0.0 <= prof["raw_negative_share"] <= 1.0
    for v in prof["by_language"].values():
        assert 0.0 <= v["share"] <= 1.0
    for v in prof["by_unit_type"].values():
        assert 0.0 <= v["negative_share"] <= 1.0 and 0.0 <= v["zero_share"] <= 1.0
    m = prof["magnitude"]
    assert m["max_sec"] == pytest.approx(1.0)                   # the largest reversal here is 1.0 s
    assert 0.0 <= m["gt_1s_share"] <= 1.0


def test_predicts_collapse_uses_within_batch_rates(batch: Path):
    out = F.predicts_collapse(F.load_all_stages(batch))
    assert out["available"] is True
    assert out["raw_degenerate"]["units"] == 2
    assert out["raw_clean"]["units"] == 4
    # the collapse rates must be reported for both populations, and lifts finite
    for k in ("lift_pinned", "lift_fixed_degenerate"):
        assert out[k] is None or np.isfinite(out[k])
    ce = out["collapse_explained_by_raw_degeneracy"]
    # both collapsed units were fine at raw (one pinned to the anchor, one collapsed at fixed),
    # so the covered share is 0 here — the real batch measures ~50% (see round-15 report)
    assert ce["collapsed_units"] == 2 and ce["were_already_raw_degenerate"] == 0


def test_top_examples_sorted_by_magnitude(batch: Path):
    ex = F.top_examples(F.load_all_stages(batch), k=5)
    assert ex and ex[0]["raw_dur_sec"] <= ex[-1]["raw_dur_sec"]
    assert {"song", "raw", "raw_dur_sec", "pinned"} <= set(ex[0])


def test_empty_batch_is_survivable(tmp_path: Path):
    df = F.load_all_stages(tmp_path)
    assert df.empty
    assert F.profile(df)["units"] == 0
    assert F.predicts_collapse(df) == {"available": False}
    assert F.top_examples(df) == []


def test_zero_runs_distinguishes_blocks_from_singletons():
    import pandas as pd
    from lyricalign.analysis import raw_degeneracy_forensics as RDF

    # song a: one run of 5; song b: three singletons; the run must not cross the song boundary
    rows = []
    for i in range(8):
        rows.append({"song": "a", "unit_index": i, "start_sec": i * 1.0,
                     "end_sec": i * 1.0 + (0.0 if i < 5 else 0.5)})
    for i in range(8):
        rows.append({"song": "b", "unit_index": i, "start_sec": i * 1.0,
                     "end_sec": i * 1.0 + (0.0 if i % 3 == 0 else 0.5)})
    d = pd.DataFrame(rows)
    d["flag_zero_or_negative"] = (d["end_sec"] - d["start_sec"]) <= 1e-6
    out = RDF.zero_runs(d)
    assert out["zero_units"] == 8
    assert out["runs"] == 4                     # one block of 5 in a, three singletons in b
    assert out["max_run_length"] == 5
    assert out["share_of_zero_units_in_runs_of_5_plus"] == pytest.approx(5 / 8, abs=1e-4)
    assert out["longest_runs"][0]["song"] == "a"


def test_zero_length_profile_is_not_confounded_by_song_density():
    """Song-level density must come from the timeline span, which degenerate units cannot shrink."""
    import pandas as pd
    from lyricalign.analysis import raw_degeneracy_forensics as RDF

    rows = []
    for i in range(60):
        rows.append({"song": "dense", "unit_index": i, "start_sec": i * 0.5, "end_sec": i * 0.5 + 0.5})
    for i in range(60):
        rows.append({"song": "sparse", "unit_index": i, "start_sec": i * 2.0, "end_sec": i * 2.0 + 2.0})
    d = pd.DataFrame(rows)
    d["flag_zero_or_negative"] = False
    cf = RDF.context_features(d)
    dens = cf.groupby("song")["song_density_chars_per_sec"].median()
    assert dens["dense"] > dens["sparse"]        # density tracks the real timing, not degeneracy
    prof = RDF.zero_length_profile(d)
    assert prof["zero_units"] == 0
