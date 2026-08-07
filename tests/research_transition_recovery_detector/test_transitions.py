"""T1/T2/T3 纯状态机测试：可区分 commit、split 等价、stability 晋升、合同硬断言。

覆盖 07_REVIEWED_IMPLEMENTATION_PLAN.md §3.2 与 §9 最低行为测试中的 T1/T2/T3 部分。
"""

import pytest

from lyricalign.demo.karaoke import split_core_commit_prefix
from lyricalign.research_transition_recovery_detector.contracts import (
    TRANSITION_T1_DIRECT,
    TRANSITION_T2_CORE,
    TRANSITION_T3_STABLE,
    TransitionState,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.transitions import (
    STABILITY_TOLERANCE_SEC,
    apply_transition_policy,
    first_divergence,
    stable_when,
)

W1_BOUNDS = (0.0, 10.0, 60.0, 70.0)  # input_start, core_start, core_end, input_end


def make_rows(starts, *, index_offset=0, indices=None):
    rows = []
    for i, s in enumerate(starts):
        idx = indices[i] if indices is not None else i + index_offset
        rows.append(
            {
                "global_character_index": idx,
                "character": f"c{idx}",
                "start_sec": s,
                "end_sec": s + 2.5,
                "fixed_global_start_sec": s,
                "fixed_global_end_sec": s + 2.5,
                "occurrence": "1" if i % 5 == 0 else "",
            }
        )
    return rows


def make_request(transition, bounds=W1_BOUNDS, query_count=32):
    return WindowRequest(
        request_id="req-1",
        parent_state_hash="parent-hash",
        audio_identity="audio-sha",
        original_bounds=bounds,
        model_bounds=bounds,
        query_canonical_ids=tuple(range(query_count)),
        slot_canonical_ids=(),
        transition=transition,
    )


def initial_state(transition):
    return TransitionState(
        song_id="song-1",
        transition=transition,
        window_index=0,
        next_input_cursor=0,
        committed_end_exclusive=0,
    )


def test_t1_t2_t3_distinguishable_commit_behavior():
    # 窗 1：T1 提交 lookahead、T2/T3 只提交 core 内 prefix（T3 首窗 baseline 提交同 T2）
    starts = [i * 4.0 for i in range(18)]  # 0..68, all inside input [0,70)
    rows = make_rows(starts)
    t1 = apply_transition_policy(
        TRANSITION_T1_DIRECT, initial_state(TRANSITION_T1_DIRECT), rows,
        window_request=make_request(TRANSITION_T1_DIRECT),
    )
    t2 = apply_transition_policy(
        TRANSITION_T2_CORE, initial_state(TRANSITION_T2_CORE), rows,
        window_request=make_request(TRANSITION_T2_CORE),
    )
    t3 = apply_transition_policy(
        TRANSITION_T3_STABLE, initial_state(TRANSITION_T3_STABLE), rows,
        window_request=make_request(TRANSITION_T3_STABLE),
    )
    assert t1.committed_end_exclusive == 18   # commits right lookahead (starts 60..68)
    assert t2.committed_end_exclusive == 15   # stops at core_end=60 (start 60 -> lookahead)
    assert t3.committed_end_exclusive == 15   # first-window baseline commit == T2 prefix
    assert t3.provisional_ids == ()
    # 窗 2：T2 无条件提交新 core prefix；T3 只晋升跨窗 stable 前缀。
    # 构造窗 2 rows（id 15..29 起）并给窗 1 观察（无 drift），id 15..22 稳定、id 23 起漂移 0.4s。
    prev_obs = {
        i: {"global_character_index": i, "start_sec": i * 4.0, "end_sec": i * 4.0 + 2.5, "source": "official"}
        for i in range(18)  # 窗 1 观察覆盖 0..17
    }
    rows2 = make_rows(
        [i * 4.0 if i != 23 else i * 4.0 + 0.4 for i in range(15, 30)], index_offset=15,
    )
    t2b = apply_transition_policy(
        TRANSITION_T2_CORE, t2, rows2,
        window_request=make_request(TRANSITION_T2_CORE, bounds=(50.0, 60.0, 110.0, 120.0)),
    )
    t3b = apply_transition_policy(
        TRANSITION_T3_STABLE, t3, rows2,
        window_request=make_request(TRANSITION_T3_STABLE, bounds=(50.0, 60.0, 110.0, 120.0)),
        previous_observation=prev_obs,
    )
    assert t2b.committed_end_exclusive == 15 + 13          # 无条件提交 15..27
    assert t3b.committed_end_exclusive == 18               # 只晋升有跨窗观察且 stable 的 15..17
    assert t3b.provisional_ids == tuple(range(18, 28))     # 18.. 无窗1观察 -> 保留 provisional
    assert first_divergence(t1, t2b, t3b) == 1
    for st in (t1, t2b, t3b):
        st.validate()
        assert st.committed_ids == tuple(range(st.committed_end_exclusive))
        assert st.next_input_cursor == st.committed_end_exclusive


def test_t2_matches_split_core_commit_prefix_within_core():
    starts = [i * 4.0 for i in range(18)]
    rows = make_rows(starts)
    t2 = apply_transition_policy(
        TRANSITION_T2_CORE, initial_state(TRANSITION_T2_CORE), rows,
        window_request=make_request(TRANSITION_T2_CORE),
    )
    _, split_committed, _ = split_core_commit_prefix(
        rows,
        expected_input_character_start=0,
        committed_character_start=0,
        core_start_sec=10.0,
        core_end_sec=60.0,
        final_core=False,
    )
    assert t2.committed_ids == tuple(r["global_character_index"] for r in split_committed)

    t2b = apply_transition_policy(
        TRANSITION_T2_CORE, t2, make_rows([i * 4.0 for i in range(15, 30)], index_offset=15),
        window_request=make_request(TRANSITION_T2_CORE, bounds=(50.0, 60.0, 110.0, 120.0)),
    )
    rows_b = make_rows([i * 4.0 for i in range(15, 30)], index_offset=15)
    _, split_committed_b, _ = split_core_commit_prefix(
        rows_b,
        expected_input_character_start=15,
        committed_character_start=15,
        core_start_sec=60.0,
        core_end_sec=110.0,
        final_core=False,
    )
    assert t2b.committed_ids == tuple(range(15)) + tuple(
        r["global_character_index"] for r in split_committed_b
    )


def test_t3_promotes_provisional_on_second_observation():
    rows1 = make_rows([i * 4.0 for i in range(18)])
    t3_1 = apply_transition_policy(
        TRANSITION_T3_STABLE, initial_state(TRANSITION_T3_STABLE), rows1,
        window_request=make_request(TRANSITION_T3_STABLE),
    )
    assert t3_1.committed_end_exclusive == 15  # first-window baseline
    assert t3_1.provisional_ids == ()

    previous_observation = {
        i: {"global_character_index": i, "start_sec": i * 4.0, "end_sec": i * 4.0 + 2.5, "source": "official"}
        for i in range(15)
    }
    rows2 = make_rows([i * 4.0 + 0.1 if i < 15 else i * 4.0 for i in range(30)])
    t3_2 = apply_transition_policy(
        TRANSITION_T3_STABLE, t3_1, rows2,
        window_request=make_request(TRANSITION_T3_STABLE, bounds=(0.0, 60.0, 110.0, 120.0)),
        previous_observation=previous_observation,
    )
    # 前 15 行 diff=0.1 <= 0.32 stable -> 已提交；id 15.. 无观察但本窗新观察 -> provisional
    assert t3_2.committed_ids == tuple(range(15))
    assert t3_2.provisional_ids == tuple(range(15, 28))
    t3_2.validate()


def test_t3_does_not_jump_over_unstable_prefix():
    rows1 = make_rows([i * 4.0 for i in range(18)])
    t3_1 = apply_transition_policy(
        TRANSITION_T3_STABLE, initial_state(TRANSITION_T3_STABLE), rows1,
        window_request=make_request(TRANSITION_T3_STABLE),
    )
    # t3_1 首窗 baseline 已提交 0..14；窗 2 首行 id 15 与窗 1 观察差 1.0s -> unstable
    previous_observation = {
        i: {"global_character_index": i, "start_sec": i * 4.0, "end_sec": i * 4.0 + 2.5, "source": "official"}
        for i in range(18)
    }
    previous_observation[15] = {
        "global_character_index": 15, "start_sec": 60.0 + 1.0, "end_sec": 63.5, "source": "official",
    }
    rows2 = make_rows([i * 4.0 for i in range(30)])
    t3_2 = apply_transition_policy(
        TRANSITION_T3_STABLE, t3_1, rows2,
        window_request=make_request(TRANSITION_T3_STABLE, bounds=(0.0, 60.0, 110.0, 120.0)),
        previous_observation=previous_observation,
    )
    assert t3_2.committed_end_exclusive == 15           # no promotion: first candidate unstable
    assert 15 not in t3_2.committed_ids                 # unstable prefix not jumped over
    assert t3_2.provisional_ids == tuple(range(15, 28))
    t3_2.validate()


def test_committed_continuous_no_duplicates_and_validate():
    rows = make_rows([i * 4.0 for i in range(18)])
    t1 = apply_transition_policy(
        TRANSITION_T1_DIRECT, initial_state(TRANSITION_T1_DIRECT), rows,
        window_request=make_request(TRANSITION_T1_DIRECT),
    )
    assert t1.committed_ids == tuple(range(18))
    assert len(set(t1.committed_ids)) == len(t1.committed_ids)
    assert t1.occurrence_by_id == tuple((i, "1") for i in range(0, 18, 5))
    t1.validate()


def test_unresolved_gap_blocks_commit_past_gap():
    state = initial_state(TRANSITION_T1_DIRECT).derive(unresolved_gap=(5, 7))
    rows = make_rows([i * 4.0 for i in range(10)])
    t1 = apply_transition_policy(
        TRANSITION_T1_DIRECT, state, rows,
        window_request=make_request(TRANSITION_T1_DIRECT),
    )
    assert t1.committed_end_exclusive == 5
    assert t1.committed_ids == tuple(range(5))
    assert t1.unresolved_gap == (5, 7)
    t1.validate()


def test_t1_stops_on_out_of_bounds_and_out_of_order_rows():
    starts = [i * 4.0 for i in range(18)]
    starts[2] = 72.0  # beyond input_end=70 mid-prefix: must stop, no skipping
    t1 = apply_transition_policy(
        TRANSITION_T1_DIRECT, initial_state(TRANSITION_T1_DIRECT), make_rows(starts),
        window_request=make_request(TRANSITION_T1_DIRECT),
    )
    assert t1.committed_end_exclusive == 2

    missing = [0, 1, 3, 4]  # id 2 absent: non-contiguous, stop
    t1b = apply_transition_policy(
        TRANSITION_T1_DIRECT, initial_state(TRANSITION_T1_DIRECT),
        make_rows([i * 4.0 for i in missing], indices=missing),
        window_request=make_request(TRANSITION_T1_DIRECT),
    )
    assert t1b.committed_end_exclusive == 2


def test_stable_when_requires_two_cross_window_observations():
    obs1 = {"global_character_index": 3, "start_sec": 12.0, "end_sec": 14.5, "source": "official"}
    obs2 = {"global_character_index": 3, "start_sec": 12.1, "end_sec": 14.6, "source": "raw"}
    assert stable_when(obs1, obs2)
    assert stable_when(obs2, obs1, tolerance_sec=0.05) is False  # 0.1 > 0.05
    assert stable_when(obs1, {**obs2, "start_sec": 12.5}) is False
    assert stable_when(obs1, {**obs2, "global_character_index": 4}) is False
    assert stable_when(obs1, {**obs2, "pre_registered_equivalent": True})
    with pytest.raises(ValueError):
        stable_when(obs1, {**obs2, "source": "decoded"})


def test_first_divergence_no_divergence():
    t2a = apply_transition_policy(
        TRANSITION_T2_CORE, initial_state(TRANSITION_T2_CORE), make_rows([i * 4.0 for i in range(18)]),
        window_request=make_request(TRANSITION_T2_CORE),
    )
    t2b = apply_transition_policy(
        TRANSITION_T2_CORE, initial_state(TRANSITION_T2_CORE), make_rows([i * 4.0 for i in range(18)]),
        window_request=make_request(TRANSITION_T2_CORE),
    )
    assert first_divergence(t2a, t2b, t2b) == -1


def test_t0_and_state_mismatch_rejected():
    from lyricalign.research_transition_recovery_detector.contracts import TRANSITION_T0_ORACLE

    with pytest.raises(NotImplementedError):
        apply_transition_policy(
            TRANSITION_T0_ORACLE, initial_state(TRANSITION_T0_ORACLE), make_rows([0.0]),
            window_request=make_request(TRANSITION_T0_ORACLE),
        )
    with pytest.raises(ValueError):
        apply_transition_policy(
            TRANSITION_T1_DIRECT, initial_state(TRANSITION_T2_CORE), make_rows([0.0]),
            window_request=make_request(TRANSITION_T1_DIRECT),
        )
