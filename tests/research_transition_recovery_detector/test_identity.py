from __future__ import annotations

import pytest

from lyricalign.research_transition_recovery_detector.contracts import (
    TransitionState,
    WindowRequest,
    TRANSITION_T1_DIRECT,
)
from lyricalign.research_transition_recovery_detector.identity import (
    forward_cache_key,
    request_id_for,
    state_hash,
    trajectory_cache_key,
)

MODEL_IDENTITY = {"kind": "qwen2_5_fa", "path": "/models/fa", "revision": "c07281df", "checkpoint_sha": "abc123"}
ENV_IDENTITY = "py310-cuda128"


def make_state(**over) -> TransitionState:
    base = dict(
        song_id="song_a",
        transition=TRANSITION_T1_DIRECT,
        window_index=3,
        next_input_cursor=12,
        committed_end_exclusive=12,
        committed_ids=tuple(range(12)),
        provisional_ids=(),
        unresolved_gap=None,
        occurrence_by_id=(),
        previous_committed_end_model_sec=120.5,
        retry_count=0,
    )
    base.update(over)
    return TransitionState(**base)


def make_request(**over) -> WindowRequest:
    base = dict(
        request_id="req",
        parent_state_hash="st",
        audio_identity="sha256:audio_a",
        original_bounds=(0.0, 10.0, 20.0, 30.0),
        model_bounds=(0.0, 10.0, 20.0, 30.0),
        query_canonical_ids=(0, 1, 2),
        slot_canonical_ids=(0, 1, 2),
        decoder_evidence=(),
        transition=TRANSITION_T1_DIRECT,
    )
    base.update(over)
    return WindowRequest(**base)


def fk(request: WindowRequest, **over) -> str:
    kw = dict(config_hash="cfg1", model_identity=MODEL_IDENTITY, env_identity=ENV_IDENTITY, hidden_schema="v3")
    kw.update(over)
    return forward_cache_key(request, **kw)


def test_forward_cache_key_identical_input_is_deterministic():
    r = make_request()
    assert fk(r) == fk(make_request())
    assert len(fk(r)) == 64


@pytest.mark.parametrize(
    "over",
    [
        {"audio_identity": "sha256:audio_b"},
        {"original_bounds": (0.0, 10.0, 20.0, 31.0)},
        {"model_bounds": (0.0, 11.0, 20.0, 30.0)},
        {"query_canonical_ids": (0, 1, 3)},
        {"slot_canonical_ids": (0, 1, 3)},
        {"request_id": "req2"},
        {"parent_state_hash": "st2"},
        {"transition": "T2_core_boundary_serial"},
    ],
)
def test_forward_cache_key_sensitive_to_each_request_field(over):
    base_key = fk(make_request())
    assert fk(make_request(**over)) != base_key


@pytest.mark.parametrize(
    "over",
    [
        {"config_hash": "cfg2"},
        {"model_identity": dict(MODEL_IDENTITY, revision="deadbeef")},
        {"env_identity": "py311-cuda129"},
        {"hidden_schema": "v4"},
    ],
)
def test_forward_cache_key_sensitive_to_identity_inputs(over):
    base_key = fk(make_request())
    assert fk(make_request(), **over) != base_key


def test_forward_cache_key_hidden_schema_none_distinct_from_string():
    assert fk(make_request(), hidden_schema=None) != fk(make_request(), hidden_schema="v3")


def test_state_hash_sensitive_to_committed_changes():
    base = make_state()
    assert state_hash(base) == state_hash(make_state())
    assert state_hash(make_state(committed_ids=tuple(range(13)), committed_end_exclusive=13)) != state_hash(base)
    assert state_hash(make_state(window_index=4)) != state_hash(base)
    assert state_hash(make_state(retry_count=1)) != state_hash(base)


def test_trajectory_cache_key_sensitive_to_policy_and_forward():
    k1 = trajectory_cache_key("s1", "policy_a", "f1")
    assert k1 == trajectory_cache_key("s1", "policy_a", "f1")
    assert k1 != trajectory_cache_key("s1", "policy_b", "f1")
    assert k1 != trajectory_cache_key("s2", "policy_a", "f1")
    assert k1 != trajectory_cache_key("s1", "policy_a", "f2")


def test_request_id_for_deterministic_and_sensitive():
    state = make_state()
    request = make_request()
    assert request_id_for(state, request) == request_id_for(make_state(), make_request())
    assert request_id_for(make_state(window_index=4), request) != request_id_for(state, request)
    assert request_id_for(state, make_request(query_canonical_ids=(0, 1, 3))) != request_id_for(state, request)
