"""B3 layered runner tests (WP B4 CPU acceptance fixtures).

All layers run against a fake duck-typed backend; no model library is touched.
"""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lyricalign.realign_recovery.forward_cache import ContentAddressedCache
from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request
from lyricalign.realign_recovery.run_objects import (
    MANIFEST_SCHEMA_VERSION,
    Candidate,
    write_jsonl,
)
from lyricalign.realign_recovery.runners import (
    candidate_runner,
    decision_writeback_runner,
    episode_builder,
    evaluator,
    proposal_runner,
    serial_baseline_runner,
)

FWD = {
    "model_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
    "model_revision": "c07281df297b9905d24a508279258cccf987a064",
    "checkpoint_id": "ckpt-000750",
    "checkpoint_path": "/data/ckpt/step-000750",
    "processor_id": "Qwen/Qwen3-ForcedAligner-0.6B-hf",
    "audio_source": "song.wav",
    "audio_sha256": "a" * 64,
    "request_mode": "slot",
    "core_sec": 60,
    "left_context_sec": 10,
    "right_context_sec": 10,
    "silence_aware_window_plan": True,
    "code_version": "test-code-v1",
    "schema_version": "realign_recovery_forward_v1",
}


class FakeBackend:
    def __init__(self, root):
        self.root = root
        self.calls = 0

    def align(self, request):
        self.calls += 1
        path = self.root / f"raw_{self.calls}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "calls": self.calls,
            "audio_start_sec": request.get("audio_start_sec"),
            "text_unit_ids": request.get("text_unit_ids"),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"raw_output_path": str(path), "raw_output_sha256": sha}


def _request(**kw):
    req = dict(FWD)
    req.update(
        {
            "audio_start_sec": 0.0,
            "audio_end_sec": 60.0,
            "text_unit_ids": [0, 1, 2],
            "text_content_hash": "b" * 64,
            "id": "case-1",
            "song_id": "song-1",
            "window_index": 0,
        }
    )
    req.update(kw)
    return req


def _baseline_row(tmp_path, case_id, window_index, units, backend, **kw):
    req = _request(
        id=case_id,
        window_index=window_index,
        text_unit_ids=units,
        text_content_hash=hashlib.sha256(json.dumps(units).encode()).hexdigest(),
        **kw,
    )
    raw = backend.align(dict(FWD, **req))
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "id": case_id,
        "song_id": "song-1",
        "window_index": window_index,
        "window": {
            "audio_start_sec": 0.0,
            "audio_end_sec": 60.0,
            "text_unit_ids": list(units),
        },
        "raw_output_path": raw["raw_output_path"],
        "raw_output_sha256": raw["raw_output_sha256"],
        "state_checkpoint": {"forward": dict(FWD, audio_start_sec=0.0, audio_end_sec=60.0)},
        "detector_shadow": {"bad_window": [10.0, 50.0]},
    }


def test_baseline_runner_is_pure_and_resume_idempotent(tmp_path):
    backend = FakeBackend(tmp_path / "raw")
    summary1 = serial_baseline_runner(_request(), backend, tmp_path / "out1")
    assert summary1["cases_processed"] == 1
    lines = (tmp_path / "out1" / "baseline.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    summary2 = serial_baseline_runner(_request(), backend, tmp_path / "out1")
    assert summary2["skipped"] == 1
    assert summary2["cases_processed"] == 0
    lines2 = (tmp_path / "out1" / "baseline.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 1


def test_episode_propagation_only_first_window_and_no_effect_denominator(tmp_path):
    backend = FakeBackend(tmp_path / "raw")
    artifacts = [
        _baseline_row(tmp_path, "case-1", 0, [0, 1, 2], backend),
        _baseline_row(tmp_path, "case-1", 1, [3, 4, 5], backend),
    ]
    manifest = tmp_path / "baseline.jsonl"
    write_jsonl(str(manifest), artifacts)
    stages = [
        {"id": "P1", "units": [10, 11]},
        {"id": "P2", "units": [0, 1]},
        {"id": "P3", "units": [12]},
        {"id": "P4", "units": [13, 14]},
        {"id": "P5", "units": [15]},
    ]
    path, summary = episode_builder(
        str(manifest), tmp_path / "out", propagation_stages=stages
    )
    rows = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines()]
    natural = [r for r in rows if r["kind"] == "natural"]
    propagated = [r for r in rows if r["kind"] == "propagated"]
    assert summary["attempted"] == 5
    assert summary["no_effect"] == 1
    assert summary["effective"] == 4
    assert summary["natural"] == 2
    assert summary["propagated"] == 4
    assert len(natural) == 2 and len(propagated) == 4
    assert all(p["family"] in {"P1", "P3", "P4", "P5"} for p in propagated)
    assert all(p["source_window"]["text_unit_ids"] == [0, 1, 2] for p in propagated)
    for row in rows:
        assert row["schema_version"] == MANIFEST_SCHEMA_VERSION


def test_candidate_cache_reuse_and_distinct_proposals(tmp_path):
    backend = FakeBackend(tmp_path / "raw")
    cache = ContentAddressedCache(tmp_path / "cache")
    req = _request()
    summary = serial_baseline_runner(req, backend, tmp_path / "out")
    assert summary["cases_processed"] == 1
    backend.calls = 0
    artifact = json.loads(
        (tmp_path / "out" / "baseline.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    episode = artifact
    state = artifact["state_checkpoint"]
    signal = artifact["detector_shadow"]
    proposals = proposal_runner(episode, state, signal, tmp_path / "prop")
    assert [p.method for p in proposals] == ["R-A", "R-B", "R-C", "R-C"]
    for p in proposals:
        assert validate_no_gt_request(p.no_gt_inputs) == []
        assert validate_no_gt_request(p.to_dict()) == []

    first = candidate_runner(proposals[0], backend, cache, tmp_path / "cand1")
    assert first.status == "succeeded"
    assert backend.calls == 1

    second = candidate_runner(proposals[0], backend, cache, tmp_path / "cand2")
    assert backend.calls == 1
    assert second.status == "skipped"
    assert second.status != "realign"
    assert second.raw_output_sha256 == first.raw_output_sha256
    assert second.forward_identity == first.forward_identity

    rb = candidate_runner(proposals[1], backend, cache, tmp_path / "cand3")
    assert backend.calls == 2
    assert rb.status == "succeeded"
    assert rb.forward_identity != first.forward_identity


def test_proposal_candidate_reject_gt_fields(tmp_path):
    backend = FakeBackend(tmp_path / "raw")
    cache = ContentAddressedCache(tmp_path / "cache")
    ep = _baseline_row(tmp_path, "case-1", 0, [0, 1, 2], backend)
    with pytest.raises(ValueError):
        proposal_runner({"gt": {"x": 1}}, {}, {}, tmp_path / "out")

    proposals = proposal_runner(ep, ep["state_checkpoint"], ep["detector_shadow"], tmp_path / "prop")
    bad = proposals[0].to_dict()
    bad["gt"] = {"x": 1}
    with pytest.raises(ValueError):
        candidate_runner(bad, backend, cache, tmp_path / "cand")
    bad2 = proposals[0].to_dict()
    bad2["no_gt_inputs"]["gt_timestamps"] = [0.1, 0.2]
    with pytest.raises(ValueError):
        candidate_runner(bad2, backend, cache, tmp_path / "cand2")


def test_decision_unsafe_only_writeback_preserves_safe_ownership(tmp_path):
    candidates = [
        {
            "id": "cand-prop-R-A-0",
            "proposal_id": "prop-R-A-0",
            "forward_identity": "digest",
            "raw_output_path": "raw.json",
            "raw_output_sha256": "s",
            "ownership": "unsafe",
            "status": "succeeded",
            "failure": None,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "state_checkpoint": {
                "ownership": {"0": "safe", "1": "unsafe"},
                "pending_windows": [],
            },
        }
    ]
    policy = {"accept": True, "reason": "repair", "writeback_span": [1], "score": 0.9}
    decision, continuation = decision_writeback_runner(
        candidates, policy, tmp_path / "out"
    )
    assert decision.accept_reject_reason == "repair"
    assert decision.writeback_span == [1]
    assert continuation.before_state["ownership"]["0"] == "safe"
    assert continuation.after_state["ownership"]["0"] == "safe"
    assert continuation.after_state["ownership"]["1"] == "safe"
    assert continuation.committed_provenance["accepted_candidate_ids"] == [
        "cand-prop-R-A-0"
    ]

    rejected = [dict(candidates[0], id="cand-rej")]
    policy_rej = {"accept": False, "reason": "low-quality", "writeback_span": [1]}
    decision_rej, continuation_rej = decision_writeback_runner(
        rejected, policy_rej, tmp_path / "out2"
    )
    assert decision_rej.accept_reject_reason == "low-quality"
    assert decision_rej.writeback_span is None
    assert continuation_rej.after_state["ownership"]["1"] == "unsafe"


def test_evaluator_does_not_mutate_control_artifact(tmp_path):
    cand = Candidate(
        id="cand-prop-R-A-0",
        proposal_id="prop-R-A-0",
        forward_identity="digest",
        raw_output_path="raw.json",
        raw_output_sha256="expected-sha",
        ownership="unsafe",
        status="succeeded",
        failure=None,
    )
    candidates = [cand.to_dict()]
    before = copy.deepcopy(candidates)
    result = evaluator(candidates, {"expected_sha": "expected-sha"}, tmp_path / "out")
    assert candidates == before
    assert result.labeled == 1
    assert result.unlabeled == 0
    assert result.gt_binding_hash
