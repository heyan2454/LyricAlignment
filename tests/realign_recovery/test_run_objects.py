"""B1 run objects contract tests: round-trip, strict validation, atomic IO."""

from __future__ import annotations

import json
import os

import pytest

from lyricalign.realign_recovery.run_objects import (
    MANIFEST_SCHEMA_VERSION,
    Candidate,
    Continuation,
    Decision,
    Episode,
    Evaluation,
    Proposal,
    append_failure,
    append_jsonl,
    atomic_write_text,
    stage_completed,
    write_jsonl,
)


def _episode(**over):
    d = {
        "id": "ep_1",
        "song_id": "demo_001",
        "source_role": "primary",
        "kind": "natural",
        "source_window": {"start": 0.0, "end": 60.0},
        "state_checkpoint": {"step": 3},
        "target_unit_ids": [0, 1, 2],
        "family": "fam_a",
        "attempt_status": "pending",
        "effective_status": "pending",
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    d.update(over)
    return d


def _proposal(**over):
    d = {
        "id": "pr_1",
        "method": "R-A",
        "audio_span": [0.0, 60.0],
        "text_span": [0, 10],
        "anchors": {"seed": "anchor_0"},
        "context": {"language": "zh"},
        "no_gt_inputs": {"audio_span": [0.0, 60.0], "text_span": [0, 10]},
        "identity": "pr_1_identity",
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    d.update(over)
    return d


def _candidate(**over):
    d = {
        "id": "cd_1",
        "proposal_id": "pr_1",
        "forward_identity": "fwd_abc",
        "raw_output_path": "runs/demo_001/raw/cd_1.json",
        "raw_output_sha256": "a" * 64,
        "ownership": "shared_model_forward",
        "status": "pending",
        "failure": None,
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    d.update(over)
    return d


def _decision(**over):
    d = {
        "id": "dc_1",
        "trigger": "score_drop",
        "old_no_gt_scores": {"s": 0.7},
        "new_no_gt_scores": {"s": 0.9},
        "rank": 1,
        "accept_reject_reason": "new_better",
        "writeback_span": [0, 10],
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    d.update(over)
    return d


def _continuation(**over):
    d = {
        "id": "ct_1",
        "before_state": {"step": 3},
        "after_state": {"step": 4},
        "committed_provenance": {"proposal": "pr_1"},
        "next_windows": [{"start": 60.0, "end": 120.0}],
        "cost": {"seconds": 12.5},
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    d.update(over)
    return d


def _evaluation(**over):
    d = {
        "id": "ev_1",
        "gt_binding_hash": "b" * 64,
        "labeled": 10,
        "unlabeled": 5,
        "metrics": {"acc": 0.9},
        "stage_labels": ["b1"],
        "schema_version": MANIFEST_SCHEMA_VERSION,
    }
    d.update(over)
    return d


OBJECTS = [
    (Episode, _episode()),
    (Proposal, _proposal()),
    (Candidate, _candidate()),
    (Decision, _decision()),
    (Continuation, _continuation()),
    (Evaluation, _evaluation()),
]


def test_all_objects_default_schema_version():
    assert Episode(id="e", song_id="s", source_role="r", kind="natural",
                   source_window={}, state_checkpoint={}, target_unit_ids=[1],
                   family="f", attempt_status="pending", effective_status="pending"
                   ).schema_version == MANIFEST_SCHEMA_VERSION


@pytest.mark.parametrize("cls,data", OBJECTS)
def test_round_trip(cls, data):
    obj = cls.from_dict(data)
    assert obj.to_dict() == data
    assert cls.from_dict(obj.to_dict()).to_dict() == data
    assert obj == cls.from_dict(data)


@pytest.mark.parametrize("cls,data", OBJECTS)
def test_missing_field_raises_value_error(cls, data):
    for key in data:
        missing = {k: v for k, v in data.items() if k != key}
        with pytest.raises(ValueError):
            cls.from_dict(missing)


@pytest.mark.parametrize("cls,data", OBJECTS)
def test_wrong_schema_raises_value_error(cls, data):
    bad = dict(data)
    bad["schema_version"] = "some_other_v99"
    with pytest.raises(ValueError):
        cls.from_dict(bad)


def test_empty_id_raises_value_error():
    with pytest.raises(ValueError):
        Episode.from_dict(_episode(id="  "))
    with pytest.raises(ValueError):
        Proposal.from_dict(_proposal(id=""))


def test_illegal_kind_raises_value_error():
    with pytest.raises(ValueError):
        Episode.from_dict(_episode(kind="synthetic"))
    Episode.from_dict(_episode(kind="propagated"))


def test_illegal_method_raises_value_error():
    with pytest.raises(ValueError):
        Proposal.from_dict(_proposal(method="R-D"))
    Proposal.from_dict(_proposal(method="R-B"))


def test_non_monotonic_target_unit_ids_raises_value_error():
    with pytest.raises(ValueError):
        Episode.from_dict(_episode(target_unit_ids=[2, 1]))
    with pytest.raises(ValueError):
        Episode.from_dict(_episode(target_unit_ids=[1, "a"]))
    Episode.from_dict(_episode(target_unit_ids=[1, 1, 2]))


def test_illegal_status_raises_value_error():
    with pytest.raises(ValueError):
        Episode.from_dict(_episode(effective_status="done"))
    with pytest.raises(ValueError):
        Candidate.from_dict(_candidate(status="ok"))


def test_atomic_write_text_no_partial_leftover(tmp_path):
    target = str(tmp_path / "out.json")
    atomic_write_text(target, '{"a": 1}')
    assert not os.path.exists(target + ".partial")
    assert json.load(open(target)) == {"a": 1}
    atomic_write_text(target, '{"a": 2}')
    assert not os.path.exists(target + ".partial")
    assert json.load(open(target)) == {"a": 2}


def test_stage_completed_and_append_failure(tmp_path):
    out = str(tmp_path / "run")
    p = stage_completed(out, "b1_episodes", {"count": 3})
    assert p == os.path.join(out, "b1_episodes.COMPLETED.json")
    payload = json.load(open(p))
    assert payload["status"] == "completed"
    assert payload["stage"] == "b1_episodes"
    assert payload["summary"] == {"count": 3}

    f = append_failure(out, "b1_episodes", {"id": "ep_9", "error": "boom"})
    assert f == os.path.join(out, "b1_episodes.FAILURES.jsonl")
    f2 = append_failure(out, "b1_episodes", {"id": "ep_10", "error": "boom2"})
    lines = [json.loads(x) for x in open(f2).read().splitlines()]
    assert lines == [{"id": "ep_9", "error": "boom"}, {"id": "ep_10", "error": "boom2"}]


def test_write_jsonl_round_trip_and_row_count(tmp_path):
    path = str(tmp_path / "rows.jsonl")
    rows = [_episode(), _proposal(), _candidate()]
    write_jsonl(path, rows)
    got = [json.loads(x) for x in open(path).read().splitlines()]
    assert got == rows
    assert len(got) == len(rows)
    append_jsonl(path, _decision())
    got2 = [json.loads(x) for x in open(path).read().splitlines()]
    assert got2 == rows + [_decision()]
    assert not os.path.exists(path + ".partial")


def test_atomic_write_no_partial_for_jsonl(tmp_path):
    path = str(tmp_path / "rows.jsonl")
    write_jsonl(path, [_episode()])
    write_jsonl(path, [_proposal()])
    assert not os.path.exists(path + ".partial")
    lines = [json.loads(x) for x in open(path).read().splitlines()]
    assert lines == [_proposal()]
