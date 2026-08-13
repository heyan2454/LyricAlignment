"""Tests for detector_audit baseline population wiring (P0).

CPU-only: fake scorer, minimal run_root with 00_inventory + fake evidence.
Verifies the 01 audit reads the production baseline population (NOT the
E5 proposal bank) and reports pending_rerun instead of silently passing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lyricalign.realign_gate import detector_audit, identity


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _window(song: str, window_index: int, window_start: float = 0.0,
            window_end: float = 60.0) -> dict:
    window_id = f"{song}:{window_index}"
    return {
        "song_id": song,
        "window_id": window_id,
        "window_index": window_index,
        "window_start_sec": window_start,
        "window_end_sec": window_end,
        "text_unit_start": 0,
        "text_unit_end": 1,
        "target_unit_ids": [0, 1],
        "canonical_unit_ids": [0, 1],
        "audio_path": f"{song}.wav",
        "audio_start_sec": window_start,
        "audio_end_sec": window_end,
        "provenance": {
            "source_window_id": window_id,
            "text_unit_start": 0,
            "text_unit_end": 1,
        },
    }


def _units(song: str, window_id: str, n: int = 2) -> list[dict]:
    return [
        {"song_id": song, "window_id": window_id,
         "canonical_unit_id": i, "start_sec": float(i), "end_sec": float(i + 1),
         "text": f"u{i}"}
        for i in range(n)
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _make_baseline_run(root: Path, n_windows: int = 2) -> list[dict]:
    """Write a minimal run_root/00_inventory (2 windows by default)."""
    songs = ["s1", "s2"]
    idx_rows, unit_rows = [], []
    for i in range(n_windows):
        song = songs[i % len(songs)]
        w = _window(song, i)
        idx_rows.append(w)
        unit_rows.extend(_units(song, w["window_id"]))
    inv = root / "00_inventory"
    inv.mkdir(parents=True, exist_ok=True)
    _write_jsonl(inv / "BASELINE_WINDOW_INDEX.jsonl", idx_rows)
    _write_jsonl(inv / "BASELINE_UNITS.jsonl", unit_rows)
    _write_jsonl(inv / "BASELINE_DETECTOR_SHADOW.jsonl", [
        {"song_id": r["song_id"], "window_id": r["window_id"],
         "window_index": r["window_index"],
         "detector_shadow": {"decision": None, "unsafe_intervals": [], "units": {}}}
        for r in idx_rows
    ])
    return idx_rows


def _baseline_evidence(request_id: str, audio_path: str, audio_start: float,
                       audio_end: float, text_units: list[str]) -> dict:
    """Fake EvidencePack whose hashes match _request_content_ok's formula."""
    rows = [
        {"global_character_index": i,
         "raw_global_start_sec": i * 0.5, "raw_global_end_sec": (i + 1) * 0.5}
        for i in range(4)
    ]
    return {
        "content_identity": "sha256:" + _hash("x"),
        "audio_hash": _hash(f"{audio_path}|{audio_start:.6f}|{audio_end:.6f}"),
        "text_hash": _hash("\x1f".join(text_units)),
        "metadata": {"request_id": request_id, "mutation": "original_raw_baseline"},
        "attempt": {
            "request": {"request_id": request_id},
            "decoder_outputs": {"raw": {"rows": rows}},
        },
    }


def _write_evidence_for_window(ev_dir: Path, idx_row: dict, units: list[dict]) -> str:
    rid = f"{idx_row['song_id']}:{idx_row['window_id']}:baseline"
    text_units = [u["text"] for u in sorted(units, key=lambda u: u["canonical_unit_id"])]
    payload = _baseline_evidence(
        rid, idx_row["audio_path"], idx_row["audio_start_sec"],
        idx_row["audio_end_sec"], text_units)
    (ev_dir / f"sha256:{_hash(rid)}.json").write_text(
        json.dumps(payload), encoding="utf-8")
    return rid


def _write_cfg(root: Path, evidence_dir: Path, audit_source: str = "baseline",
               old_requests: str | None = None) -> Path:
    cfg = root / "00_meta" / "CONFIG.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    inputs = {
        "frozen_op": {"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                         "best_combo": "R",
                                                         "operating_points": {}}}},
        "old_run_evidence_roots": [str(evidence_dir)],
        "baseline_evidence_roots": [str(evidence_dir)],
        "labels_path": str(root / "nope.jsonl"),
        "evidence_dir_for_scorer": str(evidence_dir),
        "items_dirs": [str(root / "items")],
    }
    if old_requests:
        inputs["old_run_requests"] = old_requests
    cfg.write_text(json.dumps({
        "audit_source": audit_source,
        "inputs": inputs,
    }, ensure_ascii=False), encoding="utf-8")
    return cfg


class _FakeScorer:
    t_accept = identity.RAW_T_ACCEPT
    t_reject = identity.RAW_T_REJECT

    def score(self, rows):
        return {"unsafe_intervals": [], "n_units": len(rows), "decision": "accept"}


def _fake_score_units(scorer, rows):
    units = [
        {"canonical_unit_id": i, "start_sec": i * 0.5, "end_sec": (i + 1) * 0.5,
         "p_bad": 0.05, "state": "accept"}
        for i in range(len(rows))
    ]
    return {"units": units, "n_units": len(units), "decision": "accept"}


@pytest.fixture
def patch_gpu_deps(monkeypatch):
    monkeypatch.setattr(
        detector_audit, "build_frozen_scorer_from_artifacts",
        lambda *a, **k: _FakeScorer())
    monkeypatch.setattr(
        detector_audit, "score_units", _fake_score_units)
    yield


def test_baseline_full_coverage_ok(tmp_path, patch_gpu_deps):
    """P0: 01 audit joins baseline population by metadata.request_id."""
    run_root = tmp_path / "run"
    windows = _make_baseline_run(run_root, n_windows=2)
    ev = tmp_path / "evidence"
    ev.mkdir()
    for w in windows:
        _write_evidence_for_window(ev, w, _units(w["song_id"], w["window_id"]))
    _write_cfg(run_root, ev)

    summary = detector_audit.run_stage(run_root)
    assert summary["audit_source"] == "baseline"
    assert summary["population_kind"] == "production_raw_baseline"
    assert summary["n_requests"] == 2
    assert summary["n_hits"] == 2
    assert summary["n_missing"] == 0
    assert summary["n_pending_rerun"] == 0
    assert summary["result_status"] == "ok"
    assert summary["production_audit_complete"] is True

    raw = json.loads((run_root / "01_detector_audit" / "RAW_UNIT_METRICS.json").read_text())
    assert raw["audit_source"] == "baseline"
    assert raw["population_kind"] == "production_raw_baseline"
    assert raw["n_requests"] == 2
    assert raw["missing_request_ids"] == []

    shadow = [json.loads(l) for l in
              (run_root / "00_inventory" / "BASELINE_DETECTOR_SHADOW.jsonl")
              .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert {r["window_index"] for r in shadow} == {0, 1}
    assert all(r["detector_shadow"] for r in shadow)


def test_baseline_request_id_shape(tmp_path, patch_gpu_deps):
    """Baseline population request_id must be f\"{song}:{window}:baseline\"."""
    run_root = tmp_path / "run"
    windows = _make_baseline_run(run_root, n_windows=2)
    ev = tmp_path / "evidence"
    ev.mkdir()
    for w in windows:
        _write_evidence_for_window(ev, w, _units(w["song_id"], w["window_id"]))
    result = detector_audit.audit_baseline_population(
        run_root,
        {"raw": {"standardized_logistic": {"model_kind": "mlp",
                                            "best_combo": "R",
                                            "operating_points": {}}}},
        labels_path=run_root / "nope.jsonl",
        evidence_dir_for_scorer=ev,
        items_dirs=[run_root / "items"],
        evidence_roots=[ev],
    )
    assert [w["request_id"] for w in result["windows"]] == [
        "s1:s1:0:baseline", "s2:s2:1:baseline"
    ]
    assert result["n_requests"] == 2
    assert result["n_hits"] == 2


def test_baseline_pending_rerun_incomplete(tmp_path, patch_gpu_deps):
    """Partial evidence -> incomplete + pending_rerun, not silent pass."""
    run_root = tmp_path / "run"
    windows = _make_baseline_run(run_root, n_windows=2)
    ev = tmp_path / "evidence"
    ev.mkdir()
    w0 = windows[0]
    _write_evidence_for_window(ev, w0, _units(w0["song_id"], w0["window_id"]))
    _write_cfg(run_root, ev)

    summary = detector_audit.run_stage(run_root)
    assert summary["n_requests"] == 2
    assert summary["n_hits"] == 1
    assert summary["n_missing"] == 1
    assert summary["n_pending_rerun"] == 1
    assert summary["result_status"] == "incomplete"
    assert summary["status_reason"] == "partial_evidence_coverage"
    assert summary["production_audit_complete"] is False

    raw = json.loads((run_root / "01_detector_audit" / "RAW_UNIT_METRICS.json").read_text())
    assert raw["n_pending_rerun"] == 1
    assert raw["pending_rerun"][0]["missing_reason"] == "no_content_matching_evidence"
    assert raw["pending_rerun"][0]["request_id"] == "s2:s2:1:baseline"


def test_baseline_no_evidence_blocked(tmp_path, patch_gpu_deps):
    """No evidence at all -> blocked, never silently 'ok'."""
    run_root = tmp_path / "run"
    _make_baseline_run(run_root, n_windows=2)
    ev = tmp_path / "evidence"
    ev.mkdir()
    _write_cfg(run_root, ev)

    summary = detector_audit.run_stage(run_root)
    assert summary["n_hits"] == 0
    assert summary["n_missing"] == 2
    assert summary["result_status"] == "blocked"
    assert summary["status_reason"] == "no_evidence_hits"
    assert summary["production_audit_complete"] is False


def test_raw_requests_degraded_marker(tmp_path, patch_gpu_deps):
    """raw_requests path is preserved but marked degraded for P0 to reject."""
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    ev = tmp_path / "evidence"
    ev.mkdir()
    text_units = ["a", "b", "c", "d"]
    req = {
        "request_id": "s1:0",
        "source_song_id": "s1",
        "audio_path": "s1.wav",
        "audio_start_sec": 0.0,
        "audio_end_sec": 60.0,
        "text_units": text_units,
        "provenance": {"source_window_id": "s1:w0"},
        "workflow_mode": "strict_serial_progressive_crop",
        "mutation_type": "e5_proposal",
    }
    (run_root / "REQUESTS.jsonl").write_text(
        json.dumps(req) + "\n", encoding="utf-8")
    rid = "s1:0"
    (ev / f"sha256:{_hash(rid)}.json").write_text(json.dumps(
        _baseline_evidence(rid, req["audio_path"], req["audio_start_sec"],
                           req["audio_end_sec"], text_units)), encoding="utf-8")

    _write_cfg(run_root, ev, audit_source="raw_requests",
               old_requests=str(run_root / "REQUESTS.jsonl"))
    summary = detector_audit.run_stage(run_root)
    assert summary["audit_source"] == "raw_requests"
    assert summary["population_kind"] == "raw_requests_degraded"
    assert summary["n_hits"] == 1
    raw = json.loads((run_root / "01_detector_audit" / "RAW_UNIT_METRICS.json").read_text())
    assert raw["population_kind"] == "raw_requests_degraded"
    assert "old_run_requests" in raw["inputs"]


def test_invalid_audit_source_rejected(tmp_path, patch_gpu_deps):
    run_root = tmp_path / "run"
    _make_baseline_run(run_root, n_windows=1)
    ev = tmp_path / "evidence"
    ev.mkdir()
    cfg = _write_cfg(run_root, ev, audit_source="bogus")
    with pytest.raises(ValueError):
        detector_audit.run_stage(run_root)
