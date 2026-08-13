"""Tests for the TrackView visualization projection (07 plan WP2)."""
from __future__ import annotations

from lyricalign.demo.track_view import (
    as_renderer_track,
    build_track,
    rows_from_forward_evidence,
    track_rows_ready,
)


def _request(canonical_ids=(1, 2, 3), text=("我", "们", "走")):
    return {
        "schema": "unit_realign_request_v2",
        "canonical_ids": list(canonical_ids),
        "text_units": list(text),
        "canonical_to_local": {str(c): i for i, c in enumerate(canonical_ids)},
        "local_to_canonical": [int(c) for c in canonical_ids],
    }


def test_rows_from_forward_evidence_reverse_maps_index_and_text():
    req = _request()
    evidence = [
        {"canonical_unit_id": 2, "start_sec": 0.4, "end_sec": 0.7},
        {"canonical_unit_id": 1, "start_sec": 0.1, "end_sec": 0.4},
        {"canonical_unit_id": 3, "start_sec": 0.7, "end_sec": 1.0},
    ]
    rows = rows_from_forward_evidence(req, evidence)
    assert [r["global_character_index"] for r in rows] == [0, 1, 2]  # sorted by index
    assert rows[0]["display_text"] == "我"
    assert rows[2]["display_text"] == "走"


def test_rows_from_forward_evidence_requires_complete_pair():
    req = _request()
    with_rows = [{"canonical_unit_id": 1, "start_sec": 0.1, "end_sec": 0.4}]
    rows = rows_from_forward_evidence(req, with_rows)
    track = build_track("R-U", rows)
    assert track_rows_ready(track) == []


def test_build_track_and_as_renderer_track_roundtrip():
    rows = rows_from_forward_evidence(_request(), [
        {"canonical_unit_id": 1, "start_sec": 0.1, "end_sec": 0.4},
    ])
    track = build_track(
        "R-U", rows,
        window_trace=[{"core_start_sec": 0.0, "core_end_sec": 5.0}],
        metadata={"request_identity": "sha256:x"},
    )
    assert track["schema"] == "track_view_v1"
    label, rrows, windows = as_renderer_track(track)
    assert label == "R-U"
    assert rrows[0]["global_character_index"] == 0
    assert windows[0]["core_start_sec"] == 0.0


def test_missing_index_is_reported_not_crashed():
    track = build_track("bad", [{"start_sec": 0.0, "end_sec": 1.0}])
    problems = track_rows_ready(track)
    assert any("global_character_index" in p for p in problems)
