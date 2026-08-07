"""RouteExecutor 执行语义测试（只执行、不改决策、真实 forward 计数）。"""

from lyricalign.research_transition_recovery_detector.contracts import (
    TRANSITION_T1_DIRECT,
    ROUTE_LOCAL,
    ROUTE_NONE,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    RetryRequest,
    RoutePlan,
    TransitionState,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.route_executor import RouteExecutor


class FakeAlignerBackend:
    def __init__(self):
        self.calls = []

    def forward(self, request, *, audio, document, state, gt_timeline=None):
        self.calls.append(request)
        return {"forward_seconds": 3.5, "audio_seconds": 60.0, "aligned": ["fake"]}


class FakeTransitionRunner:
    def __init__(self):
        self.seen = []

    def advance(self, state, plan):
        self.seen.append((state, plan))
        return RouteExecutor(None, None)._apply_plan(state, plan)


def make_state(committed: tuple[int, ...] = (), retry_count: int = 0) -> TransitionState:
    return TransitionState(
        song_id="song-a",
        transition=TRANSITION_T1_DIRECT,
        window_index=0,
        next_input_cursor=len(committed),
        committed_end_exclusive=len(committed),
        committed_ids=committed,
        retry_count=retry_count,
    )


def make_request(cursor: int = 0) -> WindowRequest:
    ids = tuple(range(cursor, cursor + 4))
    return WindowRequest(
        request_id="req-0",
        parent_state_hash="parent-0",
        audio_identity="audio-a",
        original_bounds=(0.0, 5.0, 60.0, 65.0),
        model_bounds=(0.0, 5.0, 60.0, 65.0),
        query_canonical_ids=ids,
        slot_canonical_ids=ids,
        transition=TRANSITION_T1_DIRECT,
    )


def retry_for(plan_retry_count: int, reason: str = "REJECT_WHOLE") -> RetryRequest:
    return RetryRequest(
        request_id=f"retry-{plan_retry_count}",
        retry_anchor_state_hash="anchor-hash",
        retry_count=plan_retry_count,
        reason_code=reason,
    )


def test_w_whole_reruns_whole_window_once():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_WHOLE, window_id="w0", commit_ids=(),
        retry_request=retry_for(3),
    )
    state = make_state(committed=(0, 1), retry_count=2)
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=state)

    assert result["executed_forward_count"] == 1
    assert len(backend.calls) == 1
    forwarded = backend.calls[0]
    assert forwarded.request_id == "retry-3"
    assert forwarded.parent_state_hash == "anchor-hash"
    assert forwarded.slot_canonical_ids == (0, 1, 2, 3)
    assert result["actual_writeback"] == 1
    assert result["new_state"].committed_ids == (0, 1)
    assert result["new_state"].retry_count == 3
    assert result["cost"] == {"forward_seconds": 3.5, "audio_seconds": 60.0}
    result["new_state"].validate()


def test_l_reruns_gap_interval_once():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_LOCAL, window_id="w0", commit_ids=(0,),
        unresolved_gap=(1, 3),
        retry_request=retry_for(2, reason="GAP_REJECT"),
        next_input_cursor=1,
    )
    state = make_state(retry_count=1)
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=state)

    assert result["executed_forward_count"] == 1
    assert len(backend.calls) == 1
    forwarded = backend.calls[0]
    assert forwarded.slot_canonical_ids == (1, 2)
    assert forwarded.query_canonical_ids == (0, 1, 2)
    assert result["actual_writeback"] == 1
    new_state = result["new_state"]
    assert new_state.committed_ids == (0,)
    assert new_state.committed_end_exclusive == 1
    assert new_state.unresolved_gap == (1, 3)
    assert new_state.next_input_cursor == 1
    assert new_state.retry_count == 2
    new_state.validate()


def test_l_open_ended_gap_slots_to_window_end():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_LOCAL, window_id="w0", commit_ids=(0,),
        unresolved_gap=(1, 4), retry_request=retry_for(1, reason="GAP_REJECT"),
    )
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=make_state())
    assert backend.calls[0].slot_canonical_ids == (1, 2, 3)
    assert result["executed_forward_count"] == 1
    assert result["new_state"].unresolved_gap == (1, 4)
    result["new_state"].validate()


def test_none_route_no_forward_commits_accepts():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_NONE, window_id="w0", commit_ids=(0, 1, 2), next_input_cursor=3,
    )
    state = make_state(retry_count=1)
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=state)

    assert result["executed_forward_count"] == 0
    assert backend.calls == []
    assert result["actual_writeback"] == 1
    assert result["new_state"].committed_ids == (0, 1, 2)
    assert result["new_state"].retry_count == 1
    assert result["cost"] == {"forward_seconds": 0.0, "audio_seconds": 0.0}
    result["new_state"].validate()


def test_shadow_route_no_forward_no_writeback():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_SHADOW, window_id="w0", commit_ids=(0,),
        unresolved_gap=(1, 4),
        retry_request=retry_for(1, reason="GAP_REJECT"),
        next_input_cursor=1,
    )
    state = make_state()
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=state)

    assert result["executed_forward_count"] == 0
    assert backend.calls == []
    assert result["actual_writeback"] == 0
    assert result["new_state"].committed_ids == (0,)
    assert result["new_state"].unresolved_gap == (1, 4)
    result["new_state"].validate()


def test_executor_records_retry_anchor():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_WHOLE, window_id="w0", commit_ids=(),
        retry_request=retry_for(1),
    )
    state = make_state(committed=(0,))
    executor.execute(plan, request=make_request(), audio="a", document="d", state=state)
    assert executor.retry_anchors == {"anchor-hash": state}


def test_executor_does_not_mutate_plan():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(
        route=ROUTE_LOCAL, window_id="w0", commit_ids=(0,),
        unresolved_gap=(1, 4), retry_request=retry_for(1, reason="GAP_REJECT"),
    )
    before = (plan.route, plan.commit_ids, plan.unresolved_gap, plan.retry_request, plan.next_input_cursor)
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=make_state())
    after = (plan.route, plan.commit_ids, plan.unresolved_gap, plan.retry_request, plan.next_input_cursor)
    assert before == after
    assert result["plan"] is plan


def test_executor_uses_transition_runner_advance_when_present():
    backend = FakeAlignerBackend()
    runner = FakeTransitionRunner()
    executor = RouteExecutor(runner, backend)
    plan = RoutePlan(
        route=ROUTE_NONE, window_id="w0", commit_ids=(0,), next_input_cursor=1,
    )
    state = make_state()
    result = executor.execute(plan, request=make_request(), audio="a", document="d", state=state)
    assert len(runner.seen) == 1
    assert runner.seen[0][1] is plan
    assert result["new_state"].committed_ids == (0,)


def test_executor_rejects_invalid_plan():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    invalid = RoutePlan(route=ROUTE_WHOLE, window_id="w0", commit_ids=(0,))
    try:
        executor.execute(invalid, request=make_request(), audio="a", document="d", state=make_state())
    except ValueError:
        pass
    else:
        raise AssertionError("invalid W plan with commit_ids must raise")


def test_local_without_retry_request_raises():
    backend = FakeAlignerBackend()
    executor = RouteExecutor(None, backend)
    plan = RoutePlan(route=ROUTE_LOCAL, window_id="w0", commit_ids=(), unresolved_gap=(1, 3))
    try:
        executor.execute(plan, request=make_request(), audio="a", document="d", state=make_state())
    except ValueError:
        pass
    else:
        raise AssertionError("ROUTE_LOCAL without retry_request must raise")
