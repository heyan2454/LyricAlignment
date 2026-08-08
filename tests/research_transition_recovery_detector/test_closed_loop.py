"""P5 closed loop 全链测试（无 GPU）：FakeAlignerBackend + 注入 p_bad。

覆盖（09 §3 P5）：
- W REJECT 整窗 REJECT 零提交、retry 重跑整窗；
- L 不越 gap（只提交 ACCEPT 前缀）、retry 只覆盖 gap 区间；
- writeback 改变后续 request/state（Gate C pass）；shadow 不写回 → Gate C 失败；
- executor 不读分数（p_bad 只在 build_route_plan 前经 detector_predict 注入，
  executor/backend 均不可见）；
- L/W 的 audio/query/prefix/writeback 行为在 fixture 中不同；
- 执行阶段 GT 不泄漏进 backend（仅最终评估消费 GT）。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from research_transition_recovery_detector.run_closed_loop import (  # noqa: E402
    RecordingAlignerBackend,
    evaluate_song_gt,
    run_closed_loop_song,
)
from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    ROUTE_LOCAL,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    TRANSITION_T2_CORE,
)
from lyricalign.research_transition_recovery_detector.query_estimator import (  # noqa: E402
    QueryEstimator,
)
from lyricalign.research_transition_recovery_detector.route_executor import (  # noqa: E402
    RouteExecutor,
)
from lyricalign.research_transition_recovery_detector.runner import (  # noqa: E402
    FakeAlignerBackend,
)

N_UNITS = 13
DURATION = 130.0
SR = 16000
SEC_PER_UNIT = 1.2
FROZEN_WP = {"t_accept": 0.5, "t_reject": 0.9}
ALL_ACCEPT = 0.1
BAD = 0.95


class _Doc:
    characters = [f"c{i}" for i in range(N_UNITS)]


def _make_gt() -> dict:
    return {
        i: {"canonical_unit_id": i, "text": f"c{i}", "start_sec": float(i * SEC_PER_UNIT)}
        for i in range(N_UNITS)
    }


def _make_window_plan() -> dict:
    return {"windows": [
        {"window_index": 0, "core_start_sec": 0.0, "core_end_sec": 60.0,
         "input_start_sec": 0.0, "input_end_sec": 70.0},
        {"window_index": 1, "core_start_sec": 60.0, "core_end_sec": 130.0,
         "input_start_sec": 50.0, "input_end_sec": 130.0},
    ]}


def _make_estimator() -> QueryEstimator:
    return QueryEstimator(n_units=N_UNITS, effective_audio_sec=DURATION)


def _run(*, route_mode: str, p_bad_stream: list[list[float]], backend=None):
    it = iter(p_bad_stream)
    backend = backend or RecordingAlignerBackend(FakeAlignerBackend(sec_per_unit=SEC_PER_UNIT))
    out = run_closed_loop_song(
        song_id="song-a",
        audio=np.zeros(int(DURATION * SR), dtype=np.float32),
        document=_Doc(),
        gt=_make_gt(),
        window_plan=_make_window_plan(),
        estimator=_make_estimator(),
        backend=backend,
        transition=TRANSITION_T2_CORE,
        frozen_wp=FROZEN_WP,
        route_mode=route_mode,
        detector_predict=lambda rows: list(next(it)),
    )
    return out, backend


def test_w_reject_zero_commit_and_retry_whole_window():
    out, backend = _run(route_mode="W", p_bad_stream=[
        [ALL_ACCEPT, BAD, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT],
        [ALL_ACCEPT] * N_UNITS,
    ])
    w0 = out["windows"][0]
    assert w0["plan"]["route"] == ROUTE_WHOLE
    assert w0["plan"]["commit_ids"] == []
    assert w0["committed_this_window"] == []
    assert w0["retry"]["executed_forward_count"] == 1
    assert w0["retry"]["query_ids"] == list(range(7))  # W 重跑整窗 query
    assert w0["writeback"]["actual_writeback"] == 1
    assert w0["writeback"]["gate_c_ok"] is True
    assert w0["writeback"]["next_request_unchanged"] is False
    assert out["windows"][1]["plan"]["route"] == "none"
    assert len(out["windows"][1]["plan"]["commit_ids"]) == N_UNITS
    assert out["evaluation"]["committed"] == N_UNITS
    assert out["evaluation"]["unsafe_commit"] == 0
    assert out["gate_c"]["passed"] is True
    assert backend.last_gt_seen is None  # 执行阶段 GT 不泄漏


def test_l_never_commits_past_gap():
    out, backend = _run(route_mode="L", p_bad_stream=[
        [ALL_ACCEPT, BAD, BAD, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT],
        [ALL_ACCEPT] * N_UNITS,
    ])
    w0 = out["windows"][0]
    assert w0["plan"]["route"] == ROUTE_LOCAL
    assert w0["plan"]["commit_ids"] == [0]  # 不越 gap（id2 是 ACCEPT 也不提交）
    assert w0["plan"]["unresolved_gap"] == [1, 3]
    assert w0["retry"]["executed_forward_count"] == 1
    assert w0["retry"]["query_ids"] == [0, 1, 2]  # 左回看 1 + gap 区间
    assert w0["retry"]["slot_ids"] == [1, 2]
    assert w0["writeback"]["state_hash_before"] != w0["writeback"]["state_hash_after"]
    assert w0["writeback"]["gate_c_ok"] is True
    w1 = out["windows"][1]
    assert w1["plan"]["unresolved_gap"] is None
    assert len(w1["plan"]["commit_ids"]) == N_UNITS - 1  # 1..12 全部补提交
    assert out["evaluation"]["committed"] == N_UNITS
    assert out["evaluation"]["correct_committed"] == N_UNITS
    assert out["evaluation"]["correct_committed_rate"] == 1.0
    assert out["gate_c"]["passed"] is True


def test_l_and_w_behavior_distinct():
    stream = [
        [ALL_ACCEPT, BAD, BAD, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT],
        [ALL_ACCEPT] * N_UNITS,
    ]
    out_l, _ = _run(route_mode="L", p_bad_stream=[list(s) for s in stream])
    out_w, _ = _run(route_mode="W", p_bad_stream=[list(s) for s in stream])
    w0_l = out_l["windows"][0]
    w0_w = out_w["windows"][0]
    assert w0_l["plan"]["route"] == ROUTE_LOCAL and w0_w["plan"]["route"] == ROUTE_WHOLE
    assert w0_l["plan"]["commit_ids"] != w0_w["plan"]["commit_ids"]  # [0] vs []
    assert w0_l["retry"]["query_ids"] != w0_w["retry"]["query_ids"]  # gap vs 整窗
    assert w0_l["retry"]["slot_ids"] != w0_w["retry"]["slot_ids"]
    assert w0_l["writeback"]["state_hash_after"] != w0_w["writeback"]["state_hash_after"]
    assert w0_l["writeback"]["state_hash_after"] != w0_l["writeback"]["state_hash_before"]
    # 下一窗 prefix（query 起点）不同：L 从 committed_end=1 出发，W 从 0 出发
    assert out_l["windows"][1]["query_ids"][0] <= out_w["windows"][1]["query_ids"][0]


def test_gate_c_fails_when_writeback_does_not_change_next_request():
    out, _ = _run(route_mode="shadow", p_bad_stream=[
        [ALL_ACCEPT, BAD, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT],
        [ALL_ACCEPT] * N_UNITS,
    ])
    w0 = out["windows"][0]
    assert w0["plan"]["route"] == ROUTE_SHADOW
    assert w0["writeback"]["actual_writeback"] == 0
    assert w0["writeback"]["state_hash_before"] == w0["writeback"]["state_hash_after"]
    assert w0["writeback"]["gate_c_ok"] is False
    assert out["gate_c"]["passed"] is False
    assert len(out["gate_c"]["failures"]) >= 1
    assert out["gate_c"]["failures"][0]["window_index"] == 0


def test_executor_never_reads_scores_and_p_bad_only_pre_plan():
    class RecordingFake(FakeAlignerBackend):
        def __init__(self):
            super().__init__(sec_per_unit=SEC_PER_UNIT)
            self.requests = []

        def forward(self, request, audio=None, document=None, **kwargs):
            self.requests.append(request)
            return super().forward(request, audio, document, **kwargs)

    calls = {"n": 0}
    stream = [
        [ALL_ACCEPT, BAD, BAD, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT, ALL_ACCEPT],
        [ALL_ACCEPT] * N_UNITS,
    ]
    it = iter(stream)

    def detector_predict(rows):
        calls["n"] += 1
        return list(next(it))

    inner = RecordingFake()
    backend = RecordingAlignerBackend(inner)
    out = run_closed_loop_song(
        song_id="song-a",
        audio=np.zeros(int(DURATION * SR), dtype=np.float32),
        document=_Doc(),
        gt=_make_gt(),
        window_plan=_make_window_plan(),
        estimator=_make_estimator(),
        backend=backend,
        transition=TRANSITION_T2_CORE,
        frozen_wp=FROZEN_WP,
        route_mode="L",
        detector_predict=detector_predict,
    )
    assert calls["n"] == 2  # 每窗一次，p_bad 只用于 build_route_plan 前
    assert len(inner.requests) == 2 + 1  # 2 串行 + 1 retry
    assert not hasattr(RouteExecutor, "detector_predict")
    executor = RouteExecutor(transition_runner=None, backend=backend)
    assert not hasattr(executor, "detector_predict")
    assert not hasattr(executor, "p_bad")
    for request in inner.requests:
        payload = request.__dict__
        assert "p_bad" not in payload
        assert "scores" not in payload
    assert out["windows"][0]["plan"]["route"] == ROUTE_LOCAL
    assert out["gate_c"]["passed"] is True


def test_gt_used_only_in_evaluation():
    eval_ = evaluate_song_gt(
        song_id="song-a",
        n_units=4,
        committed_ids=(0, 1, 2, 3),
        committed_times={0: 0.0, 1: 1.2, 2: 20.0, 3: 3.6},
        gt=_make_gt(),
        tolerance_sec=0.25,
        unsafe_tolerance_sec=1.0,
    )
    assert eval_["correct_committed"] == 3  # id2 偏差 18.8s
    assert eval_["unsafe_commit"] == 1
    assert eval_["committed_coverage"] == 1.0
    assert eval_["unresolved_units"] == 0
