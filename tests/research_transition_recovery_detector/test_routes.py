"""build_route_plan 唯一决策语义测试（routes.py 纯函数）。"""

from lyricalign.research_transition_recovery_detector.contracts import (
    ROUTE_LOCAL,
    ROUTE_NONE,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
)
from lyricalign.research_transition_recovery_detector.routes import (
    REASON_GAP_REJECT,

    ACCEPT,
    REASON_GAP_UNCERTAIN,
    REASON_REJECT_WHOLE,
    REJECT,
    UNCERTAIN,
    build_route_plan,
)


def test_w_reject_whole_window_empty_commits():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, ACCEPT), (2, REJECT), (3, ACCEPT)],
        current_cursor=0, transition_state_hash="h1", retry_count=2, route_mode="W",
    )
    assert plan.route == ROUTE_WHOLE
    assert plan.commit_ids == ()
    assert plan.unresolved_gap is None
    assert plan.retry_request is not None
    assert plan.retry_request.retry_count == 3
    assert plan.retry_request.retry_anchor_state_hash == "h1"
    assert plan.retry_request.reason_code == REASON_REJECT_WHOLE
    assert plan.next_input_cursor == 0
    plan.validate()


def test_w_without_reject_uncertain_is_local_gap_not_whole():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, UNCERTAIN)],
        route_mode="W",
    )
    assert plan.route == ROUTE_LOCAL
    assert plan.unresolved_gap == (1, 2)
    assert plan.commit_ids == (0,)
    plan.validate()


def test_l_commits_accept_prefix_does_not_cross_gap():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, ACCEPT), (2, REJECT), (3, ACCEPT)],
        current_cursor=0,
    )
    assert plan.route == ROUTE_LOCAL
    assert plan.commit_ids == (0, 1)
    assert plan.unresolved_gap == (2, 3)
    assert plan.retry_request is not None
    assert plan.retry_request.retry_count == 1
    assert plan.next_input_cursor == 2
    plan.validate()


def test_l_gap_ends_at_next_accept_after_non_accept_run():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, UNCERTAIN), (2, REJECT), (3, ACCEPT)],
        current_cursor=0,
    )
    assert plan.route == ROUTE_LOCAL
    assert plan.commit_ids == (0,)
    assert plan.unresolved_gap == (1, 3)
    assert plan.retry_request.reason_code == REASON_GAP_UNCERTAIN
    plan.validate()


def test_l_gap_open_ended_when_run_reaches_window_end():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, REJECT), (2, REJECT)],
        current_cursor=0,
    )
    assert plan.route == ROUTE_LOCAL
    assert plan.commit_ids == (0,)
    assert plan.unresolved_gap == (1, 3)
    plan.validate()


def test_l_gap_after_accept_not_committed():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, REJECT), (2, ACCEPT), (3, ACCEPT)],
        current_cursor=0,
    )
    assert plan.commit_ids == (0,)
    assert plan.unresolved_gap == (1, 2)
    assert 2 not in plan.commit_ids
    assert 3 not in plan.commit_ids
    plan.validate()


def test_shadow_mirrors_l_decision_with_shadow_route():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, ACCEPT), (2, REJECT), (3, ACCEPT)],
        current_cursor=0, transition_state_hash="h2", retry_count=5, route_mode="shadow",
    )
    assert plan.route == ROUTE_SHADOW
    assert plan.commit_ids == (0, 1)
    assert plan.unresolved_gap == (2, 3)
    assert plan.retry_request.retry_count == 6
    plan.validate()


def test_shadow_with_reject_mirrors_l_decision_not_whole():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, REJECT)],
        route_mode="shadow",
    )
    assert plan.route == ROUTE_SHADOW
    assert plan.commit_ids == (0,)
    assert plan.unresolved_gap == (1, 2)
    assert plan.retry_request.reason_code == REASON_GAP_REJECT
    plan.validate()


def test_all_accept_none_route_no_retry():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, ACCEPT), (2, ACCEPT)],
        current_cursor=0, retry_count=3,
    )
    assert plan.route == ROUTE_NONE
    assert plan.commit_ids == (0, 1, 2)
    assert plan.retry_request is None
    assert plan.next_input_cursor == 3
    plan.validate()


def test_all_accept_shadow_none_route():
    plan = build_route_plan(
        window_id="w0", unit_states=[(0, ACCEPT), (1, ACCEPT)],
        route_mode="shadow",
    )
    assert plan.route == ROUTE_SHADOW
    assert plan.retry_request is None
    plan.validate()
