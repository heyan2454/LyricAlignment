"""Phase 1 验收：resume 不重复 forward、cache key 层级正确、轨迹可复现。

对应 07_REVIEWED_IMPLEMENTATION_PLAN.md §9 最低行为测试的
"actual forward/audio seconds 与调用记录一致；resume 不重复成功 item"。
"""

import json

import numpy as np
import pytest

from lyricalign.research_transition_recovery_detector.contracts import (
    TRANSITION_T1_DIRECT,
    TRANSITION_T2_CORE,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.identity import (
    forward_cache_key,
    trajectory_cache_key,
)
from lyricalign.research_transition_recovery_detector.runner import (
    FakeAlignerBackend,
    TransitionRunner,
    build_query_ids,
)
from lyricalign.research_transition_recovery_detector.session_state import SessionState
from lyricalign.research_transition_recovery_detector.transitions import first_divergence

SR = 16000


def make_config(session_root):
    return {
        "unit_density_sec": 1.2,
        "lookback_units": 8,
        "audio_sha": "resume-test-v1",
        "model_identity": {"kind": "fake", "checkpoint": "none"},
        "env_identity": "cpu-test",
        "config_hash": "resume-test-v1",
        "sample_rate": SR,
        "audio_profile_provider": lambda a: None,
    }


def make_audio(duration_sec=180.0):
    return np.random.default_rng(1).standard_normal(int(duration_sec * SR)).astype(np.float32) * 0.05


def make_plan(duration_sec, audio):
    from scripts.demo.align_qwen_fa_serial_demo import build_vocal_activity_profile
    from lyricalign.demo.window_planning import build_silence_aware_window_plan

    profile = build_vocal_activity_profile(audio, sample_rate=SR)
    return build_silence_aware_window_plan(
        duration_sec, profile, target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
    )


def make_document():
    from lyricalign.demo.karaoke import parse_lyrics_text

    return parse_lyrics_text("\n".join(["啊" * 50 for _ in range(5)]), language="Chinese")


def test_resume_reuses_forward_cache(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config = make_config(tmp_path)

    first = FakeAlignerBackend(unit_density_sec=1.2)
    runner1 = TransitionRunner(config, session_root=tmp_path, backend=first)
    records1 = runner1.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
    )
    assert first.forward_calls > 0

    second = FakeAlignerBackend(unit_density_sec=1.2)
    runner2 = TransitionRunner(config, session_root=tmp_path, backend=second)
    records2 = runner2.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
    )
    assert second.forward_calls == 0  # 全部命中 forward cache，不重复真实 forward
    assert len(records1) == len(records2)
    for r1, r2 in zip(records1, records2, strict=True):
        assert r1["state_after"] == r2["state_after"]
        assert r1["request"] == r2["request"]


def test_config_change_invalidates_forward_cache(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config = make_config(tmp_path)

    backend = FakeAlignerBackend(unit_density_sec=1.2)
    TransitionRunner(config, session_root=tmp_path, backend=backend).run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
    )
    changed = dict(config)
    changed["unit_density_sec"] = 0.9
    backend2 = FakeAlignerBackend(unit_density_sec=0.9)
    runner2 = TransitionRunner(changed, session_root=tmp_path, backend=backend2)
    runner2.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
    )
    assert backend2.forward_calls > 0  # 配置变化 → key 不同 → 必须重新 forward


def test_cache_key_sensitive_and_deterministic():
    base = WindowRequest(
        request_id="r1", parent_state_hash="p", audio_identity="a",
        original_bounds=(0.0, 10.0, 70.0, 80.0), model_bounds=(0.0, 10.0, 70.0, 80.0),
        query_canonical_ids=(0, 1, 2, 3), slot_canonical_ids=(), transition=TRANSITION_T1_DIRECT,
    )
    model = {"kind": "lora", "revision": "r2", "checkpoint_sha": "abc"}
    key1 = forward_cache_key(base, config_hash="c1", model_identity=model, env_identity="e1")
    assert key1 == forward_cache_key(base, config_hash="c1", model_identity=model, env_identity="e1")
    for field, change in [
        ("audio_identity", "a2"),
        ("config_hash", "c2"),
        ("env_identity", "e2"),
        ("model_identity", {"kind": "raw"}),
    ]:
        if field == "audio_identity":
            other = WindowRequest(**{**base.__dict__, "audio_identity": change})
            assert forward_cache_key(other, config_hash="c1", model_identity=model, env_identity="e1") != key1
        elif field == "config_hash":
            assert forward_cache_key(base, config_hash=change, model_identity=model, env_identity="e1") != key1
        elif field == "env_identity":
            assert forward_cache_key(base, config_hash="c1", model_identity=model, env_identity=change) != key1
        else:
            assert forward_cache_key(base, config_hash="c1", model_identity=change, env_identity="e1") != key1
    tk = trajectory_cache_key("state-hash", "policy-v2", key1)
    assert tk != trajectory_cache_key("state-hash", "policy-v3", key1)


def test_query_ids_t0_requires_gt():
    state = None  # T0 不读 state
    bounds = (0.0, 10.0, 70.0, 80.0)
    ids = build_query_ids(
        transition="T0_oracle_independent", state=None, model_bounds=bounds,
        unit_density_sec=1.2, gt_timeline={0: {"start_sec": 9.0}, 5: {"start_sec": 50.0},
                                           9: {"start_sec": 71.0}},
        lookback_units=8,
    )
    assert ids == (5,)
    assert build_query_ids(
        transition="T0_oracle_independent", state=None, model_bounds=bounds,
        unit_density_sec=1.2, gt_timeline=None, lookback_units=8,
    ) is None


def test_session_state_gpu_accounting(tmp_path):
    state = SessionState(tmp_path / "ss")
    state.begin_phase("phase_1")
    state.update_gpu_seconds(0.7)
    state.update_gpu_seconds(0.3)
    assert state.phase_status("phase_1") == "in_progress"
    reopened = SessionState(tmp_path / "ss")
    assert reopened.data["gpu_seconds_used"] == pytest.approx(1.0)
    state.complete_phase("phase_1", "complete")
    assert SessionState(tmp_path / "ss").phase_status("phase_1") == "complete"
