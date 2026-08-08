"""09 §3 P0：propagation 恢复语义。

- 从 clean 轨迹的 window k state_after 恢复 + 前序 observations → k 之后所有窗的
  request/query_canonical_ids/state 轨迹与 clean 完全一致，且只 forward k+1..n 的窗。
- 干预只改变声明字段（state_before.committed_end_exclusive）；no-op 干预无下游差异。
- continuation：starting_state.window_index == k+1 时不重放窗 0..k。
"""

import numpy as np
import pytest

from lyricalign.research_transition_recovery_detector.contracts import (
    TRANSITION_T1_DIRECT,
    TransitionState,
)
from lyricalign.research_transition_recovery_detector.runner import (
    FakeAlignerBackend,
    TransitionRunner,
)

SR = 16000


def make_config(session_root):
    # 注意：config 不得含 unit_density_sec（09 §2.1 fail closed），density 由
    # QueryEstimator 从 n_units/duration 动态推导。
    return {
        "lookback_units": 8,
        "audio_sha": "propagation-resume-v1",
        "model_identity": {"kind": "fake", "checkpoint": "none"},
        "env_identity": "cpu-test",
        "config_hash": "propagation-resume-v1",
        "sample_rate": SR,
        "audio_profile_provider": lambda a: None,
    }


def make_audio(duration_sec=180.0):
    return np.random.default_rng(2).standard_normal(int(duration_sec * SR)).astype(np.float32) * 0.05


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


def _run_clean(tmp_path, audio, plan, document):
    config = make_config(tmp_path)
    backend = FakeAlignerBackend(sec_per_unit=1.2)
    runner = TransitionRunner(config, session_root=tmp_path, backend=backend)
    records = runner.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
    )
    return config, backend, runner, records


def test_resume_from_clean_state_k_reproduces_trajectory(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config, backend1, runner1, records1 = _run_clean(tmp_path, audio, plan, document)

    n = len(records1)
    assert n >= 2
    k = 1
    starting_state = TransitionState(**records1[k]["state_after"])
    assert starting_state.window_index == k + 1  # continuation 起点

    # 独立 cache root（tmp_path/fresh）：恢复 run 必须真实 forward 且只 forward 窗 k+1..
    backend2 = FakeAlignerBackend(sec_per_unit=1.2)
    fresh_root = tmp_path / "fresh_cache"
    runner2 = TransitionRunner(config, session_root=fresh_root, backend=backend2)
    records2 = runner2.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
        starting_state=starting_state,
        observations=runner1.last_observations,
    )

    assert len(records2) == n - (k + 1)
    assert backend2.forward_calls == n - (k + 1)  # 不重放窗 0..k
    for j, r2 in enumerate(records2):
        i = k + 1 + j
        r1 = records1[i]
        assert r2["window_index"] == r1["window_index"]
        assert r2["request"]["request_id"] == r1["request"]["request_id"]
        assert r2["request"]["query_canonical_ids"] == r1["request"]["query_canonical_ids"]
        assert r2["request"]["parent_state_hash"] == r1["request"]["parent_state_hash"]
        assert r2["state_before"] == r1["state_before"]
        assert r2["state_after"] == r1["state_after"]
        assert r2["decision"] == r1["decision"]


def test_continuation_does_not_replay_windows_0_to_k(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config, backend1, runner1, records1 = _run_clean(tmp_path, audio, plan, document)

    n = len(records1)
    k = 1
    starting_state = TransitionState(**records1[k]["state_after"])
    backend2 = FakeAlignerBackend(sec_per_unit=1.2)
    fresh_root = tmp_path / "fresh_cache2"
    runner2 = TransitionRunner(config, session_root=fresh_root, backend=backend2)
    records2 = runner2.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
        starting_state=starting_state,
        observations=runner1.last_observations,
    )
    assert len(records2) == n - (k + 1)
    assert backend2.forward_calls == n - (k + 1)
    assert records2[0]["window_index"] == k + 1


def test_intervention_changes_declared_fields_only(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config, backend1, runner1, records1 = _run_clean(tmp_path, audio, plan, document)

    k = 1
    clean_after = TransitionState(**records1[k]["state_after"])
    # cursor 前移 20 units（人工干预）：committed prefix 延长，时间字段保持原样。
    intervened = clean_after.derive(
        committed_end_exclusive=clean_after.committed_end_exclusive + 20,
        committed_ids=tuple(range(clean_after.committed_end_exclusive + 20)),
    )
    backend2 = FakeAlignerBackend(sec_per_unit=1.2)
    runner2 = TransitionRunner(config, session_root=tmp_path, backend=backend2)
    records2 = runner2.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
        starting_state=intervened,
        observations=runner1.last_observations,
    )
    assert len(records2) == len(records1) - (k + 1)
    assert records2[0]["state_before"]["committed_end_exclusive"] == (
        records1[k + 1]["state_before"]["committed_end_exclusive"] + 20
    )
    # 后续窗 query 允许不同（声明字段变化 → 可能进入 query 范围），但必须完成不崩。
    for r in records2:
        assert r["request"]["query_canonical_ids"]


def test_noop_intervention_has_no_downstream_difference(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config, backend1, runner1, records1 = _run_clean(tmp_path, audio, plan, document)

    k = 1
    clean_after = TransitionState(**records1[k]["state_after"])
    # occurrence 相同值重写：字段内容逐位相同 → no-op。
    noop = clean_after.derive(
        occurrence_by_id=tuple(clean_after.occurrence_by_id),
        provisional_ids=tuple(clean_after.provisional_ids),
    )
    backend2 = FakeAlignerBackend(sec_per_unit=1.2)
    runner2 = TransitionRunner(config, session_root=tmp_path, backend=backend2)
    records2 = runner2.run_song(
        song_id="song-a", audio=audio, document=document, window_plan=plan,
        transition=TRANSITION_T1_DIRECT,
        starting_state=noop,
        observations=runner1.last_observations,
    )
    assert len(records2) == len(records1) - (k + 1)
    for j, r2 in enumerate(records2):
        i = k + 1 + j
        r1 = records1[i]
        assert r2["request"] == r1["request"]
        assert r2["state_before"] == r1["state_before"]
        assert r2["state_after"] == r1["state_after"]


def test_clean_run_assert_baseline(tmp_path):
    audio = make_audio()
    plan = make_plan(float(len(audio) / SR), audio)
    document = make_document()
    config, backend, runner, records = _run_clean(tmp_path, audio, plan, document)
    assert backend.forward_calls == len(records)
    assert len(runner.last_observations) > 0
    for r in records:
        assert r["request"]["query_canonical_ids"]
