"""Route executor：只验证并执行 RoutePlan，不得读取 detector 分数改决策。

执行语义：
- ROUTE_NONE / ROUTE_SHADOW：只应用 plan 的状态推进（forward 过渡），不触发真实 backend
  forward；ROUTE_SHADOW 标记 actual_writeback=0，调用方不写回。
- ROUTE_LOCAL：对 unresolved_gap 区间构造 retry request（gap 内真实 forward 一次，
  retry_count 取 plan.retry_request 值），提交仍只取 plan.commit_ids（从 cursor 连续）。
- ROUTE_WHOLE：从 retry_anchor 重跑整窗（原始 request 内容不变，真实 forward 一次）。

anchor 语义：plan.retry_request.retry_anchor_state_hash 标识冻结的 retry 点（state hash）；
本实现中 executor 在 self._retry_anchors 记录 anchor_hash -> 冻结的 TransitionState。

依赖注入：
- transition_runner：可选；若存在 advance(state, plan) -> TransitionState 则调用，否则
  executor 内部按 plan 直接 derive 新状态。
- backend：真实 forward；backend.forward(request, *, audio, document, state, gt_timeline=None)
  返回 dict（至少含 forward_seconds / audio_seconds 成本字段）。executor 只计数与记录，不读分数。
"""

from __future__ import annotations

from dataclasses import replace

from .contracts import (
    ROUTE_LOCAL,
    ROUTE_NONE,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    RoutePlan,
    TransitionState,
    WindowRequest,
)


class RouteExecutor:
    def __init__(self, transition_runner, backend):
        self._transition_runner = transition_runner
        self._backend = backend
        self._retry_anchors: dict[str, TransitionState] = {}

    @property
    def retry_anchors(self) -> dict[str, TransitionState]:
        return dict(self._retry_anchors)

    def execute(
        self,
        plan: RoutePlan,
        *,
        request: WindowRequest,
        audio,
        document,
        state: TransitionState,
        gt_timeline=None,
    ) -> dict:
        """验证并执行 plan。返回 {plan, executed_forward_count, actual_writeback, new_state, cost}。"""
        plan.validate()
        state.validate()
        request.validate()

        if plan.retry_request is not None and plan.route in (ROUTE_LOCAL, ROUTE_WHOLE):
            self._record_anchor(plan, state)

        executed_forward_count = 0
        forward_cost = {"forward_seconds": 0.0, "audio_seconds": 0.0}

        if plan.route in (ROUTE_LOCAL, ROUTE_WHOLE):
            if plan.retry_request is None:
                raise ValueError(f"route {plan.route} requires plan.retry_request")
            if plan.route == ROUTE_LOCAL and plan.unresolved_gap is None:
                raise ValueError("ROUTE_LOCAL requires plan.unresolved_gap")
            retry = self._build_retry_request(plan, request)
            outcome = self._backend.forward(
                retry, audio=audio, document=document, state=state, gt_timeline=gt_timeline
            )
            executed_forward_count = 1
            forward_cost = {
                k: float(outcome.get(k, 0.0)) for k in ("forward_seconds", "audio_seconds")
            }

        new_state = self._advance(state, plan)
        actual_writeback = 0 if plan.route == ROUTE_SHADOW else 1

        return {
            "plan": plan,
            "executed_forward_count": executed_forward_count,
            "actual_writeback": actual_writeback,
            "new_state": new_state,
            "cost": forward_cost,
        }

    def _record_anchor(self, plan: RoutePlan, state: TransitionState) -> None:
        rr = plan.retry_request
        if rr is not None and rr.retry_anchor_state_hash:
            self._retry_anchors[rr.retry_anchor_state_hash] = state

    def _build_retry_request(self, plan: RoutePlan, request: WindowRequest) -> WindowRequest:
        rr = plan.retry_request
        assert rr is not None
        base = {
            "request_id": rr.request_id,
            "parent_state_hash": rr.retry_anchor_state_hash,
        }
        if plan.route == ROUTE_WHOLE:
            retry = replace(request, **base)
        else:
            gap_start, gap_end = plan.unresolved_gap
            slot_ids = tuple(
                i
                for i in request.slot_canonical_ids
                if gap_start <= i < gap_end
            )
            if not slot_ids:
                raise ValueError("gap interval not covered by request.slot_canonical_ids")
            left_context = tuple(i for i in request.query_canonical_ids if i < gap_start)[-1:]
            query_ids = left_context + slot_ids
            retry = replace(request, query_canonical_ids=query_ids, slot_canonical_ids=slot_ids, **base)
        retry.validate()
        return retry

    def _advance(self, state: TransitionState, plan: RoutePlan) -> TransitionState:
        runner = self._transition_runner
        if runner is not None and hasattr(runner, "advance"):
            return runner.advance(state, plan)
        return self._apply_plan(state, plan)

    def _apply_plan(self, state: TransitionState, plan: RoutePlan) -> TransitionState:
        committed = state.committed_ids
        if plan.commit_ids:
            if plan.commit_ids[0] != state.committed_end_exclusive:
                raise ValueError(
                    "plan.commit_ids must continue from state.committed_end_exclusive "
                    f"(got {plan.commit_ids[0]} vs {state.committed_end_exclusive})"
                )
            committed = state.committed_ids + tuple(plan.commit_ids)
        next_cursor = committed[-1] + 1 if committed else state.next_input_cursor
        retry_count = plan.retry_request.retry_count if plan.retry_request is not None else state.retry_count
        provisional = tuple(plan.provisional_ids) if plan.provisional_ids else state.provisional_ids
        new_state = state.derive(
            committed_ids=committed,
            committed_end_exclusive=len(committed),
            next_input_cursor=next_cursor,
            provisional_ids=provisional,
            unresolved_gap=plan.unresolved_gap,
            retry_count=retry_count,
        )
        new_state.validate()
        return new_state
