"""Tests for realign_gate.detector_audit (01_detector_audit pure functions).

Lightweight fixtures only; no models/GPU/real files.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lyricalign.realign_gate import detector_audit, identity

def _make_fake_request(song: str = "s1", idx: int = 0, text: str = "abcdef") -> dict:
    text_units_char = list(text)
    return {
        "request_id": f"{song}:{idx}",
        "source_song_id": song,
        "audio_path": f"runs/song/{song}/{song}.wav",
        "audio_start_sec": 0.0,
        "audio_end_sec": 10.0,
        "text_units": text_units_char,
        "text_start_index": 0,
        "text_end_index": len(text_units_char),
        "timestamp_slot_indices": None,
        "workflow_mode": "strict_serial_progressive_crop",
        "mutation_type": "e5_proposal",
        "mutation_parameters": {},
        "provenance": {
            "source_window_id": f"{song}:w0",
            "text_unit_start": 0,
            "text_unit_end": 3,
        },
        "canonical_unit_ids": list(range(len(text_units_char))),
        "model_id": "Qwen3-ForcedAligner-0.6B-hf",
        "checkpoint_id": "r2-step-000750",
        "checkpoint_path": "/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750",
    }


def _make_evidence_payload(request_row: dict) -> dict:
    import hashlib

    rows = [
        {"global_character_index": i,
         "raw_global_start_sec": i * 0.5, "raw_global_end_sec": (i + 1) * 0.5}
        for i in range(4)
    ]
    audio_source = request_row.get("audio_path") or "demucs_vocal"
    audio_hash = hashlib.sha256(
        f"{audio_source}|{request_row.get('audio_start_sec', 0.0):.6f}|"
        f"{request_row.get('audio_end_sec', 60.0):.6f}".encode()).hexdigest()
    text_hash = hashlib.sha256(
        "\x1f".join(request_row["text_units"]).encode()).hexdigest()
    return {
        "content_identity": f"sha256:{hashlib.sha256(b'x').hexdigest()}",
        "audio_hash": audio_hash,
        "text_hash": text_hash,
        "metadata": {"request_id": request_row["request_id"], "mutation": "e5_proposal"},
        "attempt": {
            "request": {"request_id": request_row["request_id"]},
            "decoder_outputs": {"raw": {"rows": rows}},
        },
    }


class _FakeScorer:
    t_accept = identity.RAW_T_ACCEPT
    t_reject = identity.RAW_T_REJECT

    def score(self, rows):
        if not rows:
            return {"unsafe_intervals": [], "n_units": 0, "decision": "accept"}
        return {
            "unsafe_intervals": [[0.0, 2.0]],
            "n_units": len(rows),
            "decision": "reject",
        }


def _fake_units():
    return [
        {"canonical_unit_id": 0, "start_sec": 0.0, "end_sec": 0.5,
         "p_bad": 0.05, "state": "accept"},
        {"canonical_unit_id": 1, "start_sec": 0.5, "end_sec": 1.0,
         "p_bad": 0.05, "state": "accept"},
        {"canonical_unit_id": 2, "start_sec": 1.0, "end_sec": 1.5,
         "p_bad": 0.9, "state": "reject"},
        {"canonical_unit_id": 3, "start_sec": 1.5, "end_sec": 2.0,
         "p_bad": 0.9, "state": "reject"},
    ]


@pytest.fixture
def patch_gpu_deps(monkeypatch):
    monkeypatch.setattr(
        detector_audit, "build_frozen_scorer_from_artifacts",
        lambda *a, **k: _FakeScorer())
    monkeypatch.setattr(
        detector_audit, "score_units",
        lambda scorer, rows: {
            "units": _fake_units(),
            "n_units": len(_fake_units()),
            "decision": "reject",
        })
    yield


def test_locate_old_evidence_hit():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        req = _make_fake_request()
        payload = _make_evidence_payload(req)
        (root / "sha256:xxxx.json").write_text(
            json.dumps(payload), encoding="utf-8")
        out = detector_audit.locate_old_evidence(req, [root])
        assert out is not None
        assert out.name == "sha256:xxxx.json"


def test_locate_old_evidence_miss():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        req = _make_fake_request()
        payload = _make_evidence_payload(req)
        (root / "sha256:xxxx.json").write_text(
            json.dumps(payload), encoding="utf-8")
        req2 = _make_fake_request(song="s2")
        assert detector_audit.locate_old_evidence(req2, [root]) is None


def test_locate_old_evidence_content_mismatch():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        req = _make_fake_request()
        payload = _make_evidence_payload(req)
        payload["audio_hash"] = "0" * 64
        (root / "sha256:xxxx.json").write_text(
            json.dumps(payload), encoding="utf-8")
        assert detector_audit.locate_old_evidence(req, [root]) is None


def test_recompute_window_shadow(patch_gpu_deps):
    req = _make_fake_request()
    payload = _make_evidence_payload(req)
    out = detector_audit.recompute_window_shadow(req, payload, _FakeScorer())
    assert out["n_units"] == 4
    assert out["shadow"]["n_units"] == 4
    assert set(out["unit_states"]) == {0, 1, 2, 3}
    assert set(out["merged_states"]) == {0, 1, 2, 3}
    assert out["merged_states"][2] == "reject"


def test_audit_missing_evidence_counted(patch_gpu_deps):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        req = _make_fake_request()
        (root / "REQUESTS.jsonl").write_text(
            json.dumps(req) + "\n", encoding="utf-8")
        result = detector_audit.audit_raw_metrics(
            requests_path=root / "REQUESTS.jsonl",
            evidence_roots=[root],
            frozen_op={"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                         "best_combo": "R",
                                                         "operating_points": {}}}},
            labels_path=root / "nope.jsonl",
            evidence_dir_for_scorer=root,
            items_dirs=[root],
        )
        assert result["n_requests"] == 1
        assert result["n_hits"] == 0
        assert result["n_missing"] == 1


def test_audit_hit_recomputed(patch_gpu_deps):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        req = _make_fake_request()
        payload = _make_evidence_payload(req)
        (root / "evidence").mkdir()
        (root / "evidence" / "sha256:xxxx.json").write_text(
            json.dumps(payload), encoding="utf-8")
        (root / "REQUESTS.jsonl").write_text(
            json.dumps(req) + "\n", encoding="utf-8")
        result = detector_audit.audit_raw_metrics(
            requests_path=root / "REQUESTS.jsonl",
            evidence_roots=[root / "evidence"],
            frozen_op={"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                         "best_combo": "R",
                                                         "operating_points": {}}}},
            labels_path=root / "nope.jsonl",
            evidence_dir_for_scorer=root / "evidence",
            items_dirs=[root],
        )
        assert result["n_hits"] == 1
        assert result["n_missing"] == 0
        assert result["interval_metrics"]["pooled"]["unsafe_trigger_rate"] == 1.0


def test_audit_smoke_fields_limited(patch_gpu_deps):
    """B9: limited audit must report is_smoke + requested_limit + population."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evidence").mkdir()
        for idx in range(2):
            req = _make_fake_request(song="s1", idx=idx)
            payload = _make_evidence_payload(req)
            (root / "evidence" / f"sha256:{idx}.json").write_text(
                json.dumps(payload), encoding="utf-8")
        (root / "REQUESTS.jsonl").write_text("\n".join(
            json.dumps(_make_fake_request(song="s1", idx=i)) for i in range(2)) + "\n",
            encoding="utf-8")
        result = detector_audit.audit_raw_metrics(
            requests_path=root / "REQUESTS.jsonl",
            evidence_roots=[root / "evidence"],
            frozen_op={"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                         "best_combo": "R",
                                                         "operating_points": {}}}},
            labels_path=root / "nope.jsonl",
            evidence_dir_for_scorer=root / "evidence",
            items_dirs=[root],
            limit=1,
        )
        assert result["requested_limit"] == 1
        assert result["full_population_size"] == 2
        assert result["evaluated_count"] == 1
        assert result["is_smoke"] is True
        assert result["n_requests"] == 1


def test_audit_full_population_not_smoke(patch_gpu_deps):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "evidence").mkdir()
        req = _make_fake_request()
        payload = _make_evidence_payload(req)
        (root / "evidence" / "sha256:x.json").write_text(
            json.dumps(payload), encoding="utf-8")
        (root / "REQUESTS.jsonl").write_text(
            json.dumps(req) + "\n", encoding="utf-8")
        result = detector_audit.audit_raw_metrics(
            requests_path=root / "REQUESTS.jsonl",
            evidence_roots=[root / "evidence"],
            frozen_op={"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                         "best_combo": "R",
                                                         "operating_points": {}}}},
            labels_path=root / "nope.jsonl",
            evidence_dir_for_scorer=root / "evidence",
            items_dirs=[root],
        )
        assert result["is_smoke"] is False
        assert result["requested_limit"] == 0
        assert result["full_population_size"] == 1
        assert result["evaluated_count"] == 1


def test_pooled_unit_tally_no_cross_song_cid_collision():
    """cid is per-song local; pooled must key on (song_id, cid)."""
    windows = [
        {"song_id": "s1", "unit_states": {0: "accept", 1: "reject"}},
        {"song_id": "s2", "unit_states": {0: "reject", 1: "accept"}},
    ]
    pooled = detector_audit._unit_tally_states(None, windows)
    assert pooled["n_units"] == 4
    assert pooled["n_accept"] == 2
    assert pooled["n_reject"] == 2
    per_s1 = detector_audit._unit_tally_states("s1", windows)
    assert per_s1["n_units"] == 2
    assert per_s1["n_accept"] == 1
    assert per_s1["n_reject"] == 1


def test_pooled_unit_tally_conservative_merge():
    """Same unit across windows keeps the most severe state."""
    windows = [
        {"song_id": "s1", "unit_states": {0: "accept"}},
        {"song_id": "s1", "unit_states": {0: "reject"}},
    ]
    pooled = detector_audit._unit_tally_states(None, windows)
    assert pooled["n_units"] == 1
    assert pooled["n_reject"] == 1


def test_build_case_pool_fields():
    audit = {
        "windows": [
            {
                "song_id": "s1",
                "window_id": "s1:w1",
                "target_unit_ids": [1],
                "decision": "reject",
            }
        ]
    }
    pool = detector_audit.build_case_pool(audit)
    assert pool[0]["case_id"] == "s1:s1:w1:r0:0"
    assert pool[0]["song_id"] == "s1"
    assert pool[0]["window_id"] == "s1:w1"
    assert pool[0]["target_unit_ids"] == [1]
    assert pool[0]["stratum_placeholder"] is None
    assert pool[0]["old_detector_state"] == "REJECT"
    assert pool[0]["old_error_ms"] is None
    assert pool[0]["source"] == "01_detector_audit"


def test_build_case_pool_gt_error():
    audit = {
        "windows": [
            {
                "song_id": "s1",
                "window_id": "s1:w1",
                "target_unit_ids": [1],
                "decision": "reject",
                "old_units": [{"canonical_unit_id": 1, "start_sec": 0.0, "end_sec": 1.0}],
            }
        ]
    }
    real_gt = {"s1": {1: {"start_sec": 0.0, "end_sec": 0.5}}}
    pool = detector_audit.build_case_pool(audit, real_gt)
    assert pool[0]["old_error_ms"] == 500.0
    assert pool[0]["gt_bound_target_units"] == 1
    assert pool[0]["gt_target_units"] == 1
    assert pool[0]["old_units"] == audit["windows"][0]["old_units"]

    audit2 = {
        "windows": [
            {
                "song_id": "s1",
                "window_id": "s1:w2",
                "target_unit_ids": [2],
                "decision": "accept",
                "old_units": [{"canonical_unit_id": 2, "start_sec": 0.0, "end_sec": 1.0}],
            }
        ]
    }
    pool2 = detector_audit.build_case_pool(audit2, real_gt)
    assert pool2[0]["old_error_ms"] is None
    assert pool2[0]["gt_bound_target_units"] == 0


def test_historical_bridge():
    bridge = detector_audit.historical_bridge()
    assert bridge["frozen_val"]["safe_accept_rate"] == identity.RAW_VAL_SAFE_ACCEPT_RATE
    assert bridge["frozen_val"]["protected_recall_95"] == identity.RAW_VAL_PROTECTED_RECALL
    assert bridge["retrospective"]["status"] == "not_reproduced_source_missing"


def test_run_stage_missing_evidence_no_crash(tmp_path, patch_gpu_deps):
    run_root = tmp_path / "run"
    (run_root / "00_meta").mkdir(parents=True)
    (run_root / "00_meta" / "CONFIG.json").write_text(json.dumps({
        "inputs": {
            "old_run_requests": str(tmp_path / "REQUESTS.jsonl"),
            "frozen_op": {"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                            "best_combo": "R",
                                                            "operating_points": {}}}},
            "old_run_evidence_roots": [str(tmp_path / "evidence")],
            "labels_path": str(tmp_path / "nope.jsonl"),
            "evidence_dir_for_scorer": str(tmp_path / "evidence"),
            "items_dirs": [str(tmp_path / "items")],
        }
    }), encoding="utf-8")
    (tmp_path / "REQUESTS.jsonl").write_text(
        json.dumps(_make_fake_request()) + "\n", encoding="utf-8")
    summary = detector_audit.run_stage(run_root, audit_source="raw_requests")
    assert summary["result_status"] == "blocked"
    assert summary["status_reason"] == "no_evidence_hits"
    assert summary["n_missing"] == 1
    assert (run_root / "01_detector_audit" / "RAW_UNIT_METRICS.json").is_file()
    assert (run_root / "01_detector_audit" / "RAW_WINDOW_METRICS.json").is_file()
    assert (run_root / "01_detector_audit" / "PER_SONG.csv").is_file()
    assert (run_root / "01_detector_audit" / "CASE_POOL.jsonl").is_file()


def test_run_stage_production_audit_complete_gate(tmp_path, patch_gpu_deps):
    """B9: only a limit-free, full-coverage audit sets production_audit_complete."""
    (tmp_path / "evidence").mkdir()
    for idx in range(2):
        req = _make_fake_request(song="s1", idx=idx)
        payload = _make_evidence_payload(req)
        (tmp_path / "evidence" / f"sha256:{idx}.json").write_text(
            json.dumps(payload), encoding="utf-8")
    (tmp_path / "REQUESTS.jsonl").write_text("\n".join(
        json.dumps(_make_fake_request(song="s1", idx=i)) for i in range(2)) + "\n",
        encoding="utf-8")

    def write_cfg(limit=None):
        run_root = tmp_path / "run"
        (run_root / "00_meta").mkdir(parents=True, exist_ok=True)
        (run_root / "00_meta" / "CONFIG.json").write_text(json.dumps({
            "inputs": {
                "old_run_requests": str(tmp_path / "REQUESTS.jsonl"),
                "frozen_op": {"raw": {"standardized_logistic": {"model_kind": "mlp",
                                                                "best_combo": "R",
                                                                "operating_points": {}}}},
                "old_run_evidence_roots": [str(tmp_path / "evidence")],
                "labels_path": str(tmp_path / "nope.jsonl"),
                "evidence_dir_for_scorer": str(tmp_path / "evidence"),
                "items_dirs": [str(tmp_path / "items")],
            }
        }), encoding="utf-8")
        return run_root

    smoke_root = write_cfg()
    smoke = detector_audit.run_stage(smoke_root, limit=1, audit_source="raw_requests")
    assert smoke["is_smoke"] is True
    assert smoke["production_audit_complete"] is False
    smoke_json = json.loads((smoke_root / "01_detector_audit" / "RAW_UNIT_METRICS.json").read_text())
    assert smoke_json["is_smoke"] is True
    assert smoke_json["production_audit_complete"] is False
    assert smoke_json["requested_limit"] == 1
    assert smoke_json["full_population_size"] == 2
    assert smoke_json["evaluated_count"] == 1

    full_root = write_cfg()
    full = detector_audit.run_stage(full_root, audit_source="raw_requests")
    assert full["is_smoke"] is False
    assert full["production_audit_complete"] is True
    full_json = json.loads((full_root / "01_detector_audit" / "RAW_UNIT_METRICS.json").read_text())
    assert full_json["production_audit_complete"] is True
    win_json = json.loads((full_root / "01_detector_audit" / "RAW_WINDOW_METRICS.json").read_text())
    assert win_json["is_smoke"] is False
    assert win_json["evaluated_count"] == 2
