"""Tests for the TrackView visualization projection (07 plan WP2)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from lyricalign.demo.track_view import (
    as_renderer_track,
    build_track,
    rows_from_forward_evidence,
    track_rows_ready,
)

CONTROLLER = Path(__file__).resolve().parents[2] / "scripts" / "realign_recovery" / "visualization" / "visualization_controller.py"


def _load_controller():
    spec = importlib.util.spec_from_file_location("visualization_controller", CONTROLLER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["visualization_controller"] = mod
    spec.loader.exec_module(mod)
    return mod


def _decoder_evidence_payload(canonical_ids=(72, 73, 74, 75, 76, 77, 78, 79), text=None):
    """Mock a research_v7 attempt evidence payload shaped like test-demo-045-narrow."""
    text = text or "可沉浸于自我疗伤"
    rows = []
    for local_idx, canonical in enumerate(canonical_ids):
        s = 35.0 + 0.35 * local_idx
        rows.append({
            "global_character_index": local_idx,  # window-LOCAL index, like real evidence
            "official_fixed_global_start_sec": s,
            "official_fixed_global_end_sec": s + 0.3,
            "start_sec": s,
            "end_sec": s + 0.3,
        })
    return {
        "attempt": {
            "status": "ok",
            "request": {
                "request_id": "test-demo-045-narrow",
                "canonical_ids": list(canonical_ids),
                "text_units": list(text),
                "canonical_to_local": {str(c): i for i, c in enumerate(canonical_ids)},
                "local_to_canonical": list(range(len(canonical_ids))),
            },
            "decoder_outputs": {"official": {"rows": rows}},
        },
    }


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


def test_rows_from_decoder_restores_document_global_index_and_text():
    """WP2 L-review P0 regression: window-local index must map to doc-global canonical."""
    ctrl = _load_controller()
    payload = _decoder_evidence_payload()
    rows = ctrl.rows_from_decoder(payload, decoder_kind="official")
    gcis = [r["global_character_index"] for r in rows]
    assert gcis == [72, 73, 74, 75, 76, 77, 78, 79]  # NOT collapsed to 0-7
    assert "".join(r["display_text"] for r in rows) == "可沉浸于自我疗伤"


def test_rows_from_decoder_two_windows_do_not_collapse():
    """Different windows must not collapse to the same global index (L-review P0)."""
    ctrl = _load_controller()
    w0 = _decoder_evidence_payload(canonical_ids=tuple(range(72, 80)), text="可沉浸于自我疗伤")
    w1 = _decoder_evidence_payload(canonical_ids=tuple(range(80, 88)), text="歌曲明天再续写")
    rows = ctrl.rows_from_decoder(w0, "official") + ctrl.rows_from_decoder(w1, "official")
    gcis = sorted(r["global_character_index"] for r in rows)
    # 16 distinct doc-global indexes spanning both windows, no collapse.
    assert len(set(gcis)) == 16
    assert min(gcis) == 72 and max(gcis) == 87
