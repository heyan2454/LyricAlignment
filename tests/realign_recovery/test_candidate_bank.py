"""D1 candidate bank tests: E5/E1 grouping, region reverse-lookup, gate, resume."""
from __future__ import annotations

import hashlib
import json
import os

from lyricalign.realign_recovery.candidate_bank import (
    build_candidate_bank,
    _parse_region,
    _region_covering_episode,
)
from lyricalign.realign_recovery.run_objects import Candidate, file_sha256


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_evidence(ev_dir: str, request_id: str, content: str | None = None) -> str:
    os.makedirs(ev_dir, exist_ok=True)
    payload = {
        "content_identity": "sha256:" + _sha(f"req:{request_id}"),
        "audio_content_sha256": _sha(f"audio:{request_id}"),
        "attempt": {
            "request": {"request_id": request_id},
            "status": "ok",
            "error": None,
        },
    }
    if content is not None:
        payload["attempt"]["content"] = content
    name = f"sha256:{_sha(f'file:{request_id}')}.json"
    path = os.path.join(ev_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _episode(ep_id, song, window_units, target_units, family="natural", kind="natural"):
    return {
        "id": ep_id,
        "song_id": song,
        "family": family,
        "kind": kind,
        "source_window": {"text_unit_ids": list(window_units), "window_index": 0},
        "target_unit_ids": list(target_units),
        "schema_version": "realign_recovery_run_objects_v1",
    }


def _e5_request(request_id, ep_id, variant, method="original"):
    return {
        "request_id": request_id,
        "input_variant": variant,
        "mutation_parameters": {"episode_id": ep_id, "proposal_method": method},
        "provenance": {"episode_id": ep_id, "proposal_method": method},
    }


def _e1_request(request_id, region_id, variant="oracle_O1"):
    return {
        "request_id": request_id,
        "input_variant": variant,
        "mutation_parameters": {"mode": "O1", "region_id": region_id},
        "provenance": {"mode": "O1", "region_id": region_id, "unit_ids": []},
    }


def _setup(tmp_path):
    ep_dir = tmp_path / "episodes.jsonl"
    ep_dir.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [
        _episode("ep-nat-songA:w0", "songA", [0, 1, 2, 3, 4], [0, 1, 2, 3, 4]),
        _episode("ep-nat-songB:w0", "songB", [10, 11, 12], [11]),
    ]) + "\n", encoding="utf-8")

    plan_path = tmp_path / "PROPOSAL_PLAN.json"
    plan_path.write_text(json.dumps([
        {"request_id": "e5-A-1", "episode_id": "ep-nat-songA:w0", "variant": "original_full"},
        {"request_id": "e5-B-1", "episode_id": "ep-nat-songB:w0", "variant": "oracle_O1"},
    ], ensure_ascii=False) + "\n", encoding="utf-8")

    e5_req = tmp_path / "e5.jsonl"
    e5_req.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        _e5_request("e5-A-1", "ep-nat-songA:w0", "original_full"),
        _e5_request("e5-B-1", "ep-nat-songB:w0", "oracle_O1"),
    ]) + "\n", encoding="utf-8")

    e1_req = tmp_path / "e1.jsonl"
    e1_req.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        _e1_request("oracle-A-1", "songA:1-2"),
        _e1_request("oracle-A-2", "songA:7-8"),
        _e1_request("oracle-B-1", "songB:10-12"),
    ]) + "\n", encoding="utf-8")

    e5_ev = tmp_path / "e5_ev"
    e1_ev = tmp_path / "e1_ev"
    ev5 = _write_evidence(str(e5_ev), "e5-A-1")
    _write_evidence(str(e5_ev), "e5-B-1")
    ev1 = _write_evidence(str(e1_ev), "oracle-A-1")
    ev1b = _write_evidence(str(e1_ev), "oracle-B-1")
    # oracle-A-2 has no evidence file

    manifest = tmp_path / "timeline.jsonl"
    manifest.write_text(json.dumps({
        "song_id": "songA",
        "canonical_units": [{"canonical_unit_id": i, "start_sec": float(i), "end_sec": float(i + 1)} for i in range(10)],
        "concat_audio_path": "/tmp/a.wav",
        "duration_sec": 10.0,
    }) + "\n", encoding="utf-8")

    out = tmp_path / "bank.jsonl"
    return ep_dir, plan_path, e5_req, e1_req, e5_ev, e1_ev, manifest, out


def _load_rows(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def test_region_parse_and_covering():
    assert _parse_region("songA:1-2") == ("songA", 1, 2)
    assert _parse_region("bad") is None
    assert _parse_region("s:2-1") is None
    index, order = {}, []
    # covered partially -> None
    assert _region_covering_episode("songA:7-8", {}, {}) is None


def test_build_e5_grouping_and_fields(tmp_path):
    ep_dir, plan_path, e5_req, e1_req, e5_ev, e1_ev, manifest, out = _setup(tmp_path)
    summary = build_candidate_bank(e5_req, e5_ev, e1_req, e1_ev, ep_dir, plan_path,
                                   str(manifest), out)
    rows = _load_rows(out)
    cands = [Candidate.from_dict(r) for r in rows]
    # E5: 2 rows grouped by provenance.episode_id; E1: 2 covered regions with evidence
    assert summary["n_candidates"] == 4
    e5_ids = {c.id for c in cands if c.ownership == "e5_proposal"}
    assert len(e5_ids) == 2
    for c in cands:
        assert c.proposal_id.startswith(c.id.split(":", 1)[0])
        assert c.raw_output_sha256 == file_sha256(c.raw_output_path)
        assert c.forward_identity.startswith("sha256:")
        assert c.status == "succeeded"
        assert c.failure is None
        assert c.schema_version == "realign_recovery_run_objects_v1"
    e5_orig = [c for c in cands if c.ownership == "e5_proposal" and c.id.endswith("original_full:")]
    # both E5 candidates: proposal_id = {episode_id}:{input_variant}
    assert {c.proposal_id for c in cands if c.ownership == "e5_proposal"} == {
        "ep-nat-songA:w0:original_full", "ep-nat-songB:w0:oracle_O1"}
    # E1 ownership + episode mapping
    e1_c = [c for c in cands if c.ownership == "e1_oracle"]
    assert len(e1_c) == 2
    assert {c.proposal_id for c in e1_c} == {"ep-nat-songA:w0:oracle_O1", "ep-nat-songB:w0:oracle_O1"}


def test_unmapped_and_gate(tmp_path):
    ep_dir, plan_path, e5_req, e1_req, e5_ev, e1_ev, manifest, out = _setup(tmp_path)
    summary = build_candidate_bank(e5_req, e5_ev, e1_req, e1_ev, ep_dir, plan_path,
                                   str(manifest), out)
    # songA:7-8 is not covered by ep-nat-songA:w0 ([0..4]) and no evidence -> unmapped
    assert [u for u in summary["unmapped_regions"] if u["region_id"] == "songA:7-8"]
    assert summary["ownership"] == {"e1_oracle": 2, "e5_proposal": 2}
    # per-episode counts: ep-nat-songA:w0=2 (1 E5 + 1 E1), ep-nat-songB:w0=2
    assert summary["per_episode"] == {"ep-nat-songA:w0": 2, "ep-nat-songB:w0": 2}
    # both under gate min -> gate_violations recorded
    assert {v["episode_id"] for v in summary["gate_violations"]} == {"ep-nat-songA:w0", "ep-nat-songB:w0"}
    assert all(v["reason"] == "too_few" for v in summary["gate_violations"])


def test_limit_truncation(tmp_path):
    ep_dir, plan_path, e5_req, e1_req, e5_ev, e1_ev, manifest, out = _setup(tmp_path)
    summary = build_candidate_bank(e5_req, e5_ev, e1_req, e1_ev, ep_dir, plan_path,
                                   str(manifest), out, limit=1)
    rows = _load_rows(out)
    assert len(rows) == 2
    assert all("songB" not in r["proposal_id"] for r in rows)
    assert summary["n_skipped_out_of_limit"] == 2
    assert "ep-nat-songB:w0" not in summary["per_episode"]


def test_resume_idempotent(tmp_path):
    ep_dir, plan_path, e5_req, e1_req, e5_ev, e1_ev, manifest, out = _setup(tmp_path)
    build_candidate_bank(e5_req, e5_ev, e1_req, e1_ev, ep_dir, plan_path, str(manifest), out)
    n_first = len(_load_rows(out))
    build_candidate_bank(e5_req, e5_ev, e1_req, e1_ev, ep_dir, plan_path, str(manifest), out,
                         resume=True)
    rows = _load_rows(out)
    assert len(rows) == n_first
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids)
