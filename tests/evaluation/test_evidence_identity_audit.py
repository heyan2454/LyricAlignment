"""Tests for the identity/comparability gate using synthetic batch directories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyricalign.analysis import evidence_identity_audit as A


def _write(path: Path, *, sha, req, schema, plan, units, text=None, shift=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    chars = []
    for i in range(units):
        chars.append({"character": (text[i] if text else chr(0x4E00 + i)),
                      "selected_start_sec": i * 1.0 + shift, "selected_end_sec": i * 1.0 + 0.5 + shift})
    doc = {"identity": {"audio": {"path": f"/a/{sha}.wav", "sha256": sha},
                        "request_hash": req, "schema_version": schema,
                        "decoder": {"kind": "official" if schema else ""},
                        "window": plan},
           "summary": {"audio_duration_sec": units + 1.0, "language": "Chinese"},
           "characters": chars, "window_trace": []}
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def batches(tmp_path: Path):
    a = tmp_path / "batchA"
    b = tmp_path / "batchB"          # same plan and audio, identical output
    c = tmp_path / "batchC"          # text drift: one unit dropped
    d = tmp_path / "batchD"          # no identity recorded at all
    plan = {"policy": "p7", "core_sec": 60.0, "left_context_sec": 10.0,
            "skip_silent_windows": True, "silence_aware_window_plan": False}
    _write(a / "s1" / A.ALIGN_RELPATH, sha="SHA1", req="R1", schema="serial_v7", plan=plan, units=6)
    _write(a / "s2" / A.ALIGN_RELPATH, sha="SHA2", req="R2", schema="serial_v7", plan=plan, units=6)
    _write(b / "s1" / A.ALIGN_RELPATH, sha="SHA1", req="R9", schema="serial_v7", plan=plan, units=6)
    _write(b / "s2" / A.ALIGN_RELPATH, sha="SHA2", req="R8", schema="serial_v7", plan=plan, units=6)
    # the slot-style batch mirrors the real one: unit drift plus *no* recorded identity at all
    _write(c / "s1" / A.ALIGN_RELPATH, sha="", req="", schema="", plan={}, units=6,
           text=[chr(0x4E00 + i) for i in range(1, 7)])
    _write(c / "s2" / A.ALIGN_RELPATH, sha="", req="", schema="", plan={}, units=5)
    _write(d / "s1" / A.ALIGN_RELPATH, sha="", req="", schema="", plan={}, units=6)
    return a, b, c, d


def test_duplicate_run_is_flagged_not_identified(batches):
    a, b, c, d = batches
    res = A.audit_pair("a_vs_b", A.collect(a), A.collect(b))
    assert res["verdict"] == "not_identified"
    assert res["same_window_plan_share"] == 1.0
    assert res["outputs_identical_share"] == 1.0
    assert "same configuration run twice" in res["reason"]


def test_index_drift_is_flagged_not_comparable(batches):
    a, b, c, d = batches
    res = A.audit_pair("a_vs_c", A.collect(a), A.collect(c))
    assert res["verdict"] == "not_comparable"
    assert res["text_mismatch_songs"] >= 1
    assert res["unit_count_mismatch_songs"] >= 1


def test_genuine_output_difference_is_identified(batches, tmp_path: Path):
    a, b, c, d = batches
    e = tmp_path / "batchE"
    plan = {"policy": "p7", "core_sec": 60.0, "left_context_sec": 10.0}
    _write(e / "s1" / A.ALIGN_RELPATH, sha="SHA1", req="R5", schema="serial_v7", plan=plan,
           units=6, shift=0.5)
    _write(e / "s2" / A.ALIGN_RELPATH, sha="SHA2", req="R6", schema="serial_v7", plan=plan,
           units=6, shift=0.5)
    coll_a, coll_e = A.collect(a), A.collect(e)
    res = A.audit_pair("a_vs_e", coll_a, coll_e)
    assert res["verdict"] == "identified"
    assert res["outputs_identical_share"] == 0.0
    assert res["median_max_shift_sec"] == pytest.approx(0.5)


def test_identity_hygiene_flags_unattributable_batches(batches):
    a, b, c, d = batches
    hyg = A.audit_identity_hygiene({"ktv": A.collect(a), "slot": A.collect(c), "bare": A.collect(d)})
    assert hyg["ktv"]["share_missing_audio_sha"] == 0.0
    # the fixture's plan records skip_silent_windows, so ktv is fully attributable...
    assert hyg["ktv"]["share_recording_silence_flags"] == 1.0
    assert hyg["ktv"]["median_window_flags_recorded"] == 5.0
    # ...while the slot-style batch records nothing at all
    assert hyg["slot"]["share_recording_silence_flags"] == 0.0
    assert hyg["slot"]["median_window_flags_recorded"] == 0.0
    assert hyg["slot"]["share_missing_schema_version"] == 1.0
    assert hyg["slot"]["share_missing_audio_sha"] == 1.0
    assert hyg["bare"]["share_missing_request_hash"] == 1.0
    assert hyg["ktv"]["degenerate_share"] == 0.0


def test_collect_skips_non_song_dirs(tmp_path: Path):
    (tmp_path / "_logs").mkdir()
    (tmp_path / "notadir.txt").write_text("x", encoding="utf-8")
    assert A.collect(tmp_path) == {}
