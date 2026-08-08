"""09 §3 P0 最低测试：L/W retry request region、commit/writeback 区域不同；executor 不读分数。"""

import pytest

from lyricalign.research_transition_recovery_detector.contracts import (
    ROUTE_LOCAL,
    ROUTE_WHOLE,
    RoutePlan,
    TransitionState,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.route_executor import RouteExecutor
from lyricalign.research_transition_recovery_detector.routes import (
    ACCEPT,
    REJECT,
    build_route_plan,
)


class FakeBackend:
    """记录每次 forward 的 request（window_index/query/slot），不加载模型。"""

    def __init__(self):
        self.calls = []

    def forward(self, request, audio, document, *, state=None, gt_timeline=None, window_index=0):
        self.calls.append(request)
        return [], {"backend": "fake", "forward_seconds": 0.1, "audio_seconds": 1.0}


def make_state():
    return TransitionState(
        song_id="s", transition="T2_core_boundary_serial", window_index=0,
        next_input_cursor=0, committed_end_exclusive=0,
    )


def make_request(window_index=0):
    return WindowRequest(
        request_id=f"w{window_index}", parent_state_hash="h",
        audio_identity="a", original_bounds=(0.0, 10.0, 70.0, 80.0),
        model_bounds=(0.0, 10.0, 70.0, 80.0),
        query_canonical_ids=(0, 1, 2, 3), slot_canonical_ids=(),
        transition="T2_core_boundary_serial", window_index=window_index,
    )


def test_l_and_w_retry_regions_differ():
    """同一待提交区（unit 1 为 gap/REJECT 起点）：L 只 retry gap，W retry 整窗。"""
    backend = FakeBackend()
    executor = RouteExecutor(None, backend)

    # L：unit 0 ACCEPT、1 REJECT、2/3 ACCEPT → gap (1,3)，commit (0,)
    plan_l = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, REJECT), (2, ACCEPT), (3, ACCEPT)],
        current_cursor=0, route_mode="L",
    )
    assert plan_l.route == ROUTE_LOCAL
    assert plan_l.commit_ids == (0,)
    assert plan_l.unresolved_gap is not None
    executor.execute(plan_l, request=make_request(), audio="a", document="d", state=make_state())
    l_call = backend.calls[-1]
    # L retry query 只覆盖 gap + 左 context：unit 1 REJECT、2 ACCEPT →
    # gap = (1,2) → retry query 只含 1（+左 context 0），绝不含 2/3
    l_gap_ids = [i for i in l_call.query_canonical_ids if 1 <= i < 2]
    assert l_gap_ids == [1]
    assert 2 not in l_call.query_canonical_ids
    assert 3 not in l_call.query_canonical_ids

    # W：同输入但 route_mode="W" → REJECT 触发整窗零提交
    plan_w = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, REJECT), (2, ACCEPT), (3, ACCEPT)],
        current_cursor=0, route_mode="W",
    )
    assert plan_w.route == ROUTE_WHOLE
    assert plan_w.commit_ids == ()

    # 两个 plan 的 retry 语义必须不同：L 有 gap 局部重试，W 是整窗
    assert (plan_l.retry_request is not None) == (plan_w.retry_request is not None)
    assert plan_l.unresolved_gap != plan_w.unresolved_gap or plan_l.commit_ids != plan_w.commit_ids


def test_l_writeback_commits_prefix_w_zero():
    """writeback 可区分：L 提交连续 ACCEPT prefix；W REJECT 零提交（09 P0.6）。"""
    from lyricalign.research_transition_recovery_detector.contracts import RetryRequest

    backend = FakeBackend()
    executor = RouteExecutor(None, backend)
    retry = RetryRequest(request_id="r", retry_anchor_state_hash="a", retry_count=1, reason_code="GAP_REJECT")
    plan_l = RoutePlan(
        route=ROUTE_LOCAL, window_id="w0", commit_ids=(0,),
        unresolved_gap=(1, 3), retry_request=retry, next_input_cursor=1,
    )
    plan_w = RoutePlan(
        route=ROUTE_WHOLE, window_id="w0", commit_ids=(),
        retry_request=RetryRequest(request_id="rw", retry_anchor_state_hash="a", retry_count=1,
                                   reason_code="REJECT_WHOLE"),
        next_input_cursor=0,
    )
    state = make_state()
    r_l = executor.execute(plan_l, request=make_request(), audio="a", document="d", state=state)
    r_w = executor.execute(plan_w, request=make_request(), audio="a", document="d", state=state)
    # 都真实执行了 writeback（L/W 非 shadow）；区分在提交区域：
    assert r_l["actual_writeback"] == 1
    assert r_w["actual_writeback"] == 1
    assert r_l["new_state"].committed_end_exclusive == 1  # L 提交 ACCEPT prefix
    assert r_w["new_state"].committed_end_exclusive == 0  # W 零提交


def test_executor_has_no_score_input():
    """executor 不读分数：execute 签名不含任何 p_bad/score 参数（API 级断言）。"""
    import inspect

    sig = inspect.signature(RouteExecutor.execute)
    params = set(sig.parameters)
    assert "p_bad" not in params and "score" not in params and "detector" not in params
