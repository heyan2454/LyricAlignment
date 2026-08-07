"""Route planning（唯一决策点）：DetectorOutput -> build_route_plan -> RoutePlan -> execute_route_plan。

本模块只做纯函数决策，不执行任何 forward；真实执行见 route_executor.RouteExecutor。
决策语义（07_REVIEWED_IMPLEMENTATION_PLAN.md 第 3 节）：
- W（ROUTE_WHOLE）：window 内存在 REJECT 即整窗 REJECT —— commit_ids=()、unresolved_gap=None、
  retry_request 指向 retry_anchor。UNCERTAIN 不触发整窗 REJECT，仅在 L 语义下成为 gap 起点。
- L（ROUTE_LOCAL）：提交从 cursor 起连续 ACCEPT prefix；第一个 REJECT/UNCERTAIN 起为
  unresolved_gap（gap_start=该 canonical id，gap_end=连续非 ACCEPT 段尾之后的第一个 id；若非 ACCEPT
  段延伸到窗尾，则 gap_end=窗内最后一个 id+1，即窗尾 exclusive）；gap 之后的 ACCEPT 一律不提交。
- shadow：与 L 相同决策（REJECT 不触发整窗 REJECT），但 route=ROUTE_SHADOW（调用方不写回）。
- 全 ACCEPT：route=ROUTE_NONE，无 retry。
"""

from __future__ import annotations

from .contracts import (
    ROUTE_LOCAL,
    ROUTE_NONE,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    RetryRequest,
    RoutePlan,
)

ACCEPT = "ACCEPT"
REJECT = "REJECT"
UNCERTAIN = "UNCERTAIN"
THREE_STATE = (ACCEPT, REJECT, UNCERTAIN)

ROUTE_MODES = ("L", "W", "shadow")

REASON_ACCEPT_ALL = "ACCEPT_ALL"
REASON_REJECT_WHOLE = "REJECT_WHOLE"
REASON_GAP_REJECT = "GAP_REJECT"
REASON_GAP_UNCERTAIN = "GAP_UNCERTAIN"


def _retry_request(window_id: str, transition_state_hash: str, retry_count: int, reason_code: str) -> RetryRequest:
    return RetryRequest(
        request_id=f"{window_id}::retry::{retry_count + 1}",
        retry_anchor_state_hash=transition_state_hash,
        retry_count=retry_count + 1,
        reason_code=reason_code,
    )


def build_route_plan(
    *,
    window_id: str,
    unit_states: list[tuple[int, str]],
    current_cursor: int = 0,
    transition_state_hash: str = "",
    retry_count: int = 0,
    route_mode: str = "L",
) -> RoutePlan:
    """唯一 route 决策：DetectorOutput -> build_route_plan -> RoutePlan -> execute_route_plan。

    unit_states 为从 current_cursor 起的有序 (canonical_id, ACCEPT|REJECT|UNCERTAIN) 列表。
    """
    if route_mode not in ROUTE_MODES:
        raise ValueError(f"unknown route_mode: {route_mode!r}")
    for _cid, st in unit_states:
        if st not in THREE_STATE:
            raise ValueError(f"unknown unit state: {st!r}")
    shadow = route_mode == "shadow"

    first_bad = next((i for i, (_cid, st) in enumerate(unit_states) if st != ACCEPT), None)

    if first_bad is None:
        commit_ids = tuple(cid for cid, _st in unit_states)
        return RoutePlan(
            route=ROUTE_SHADOW if shadow else ROUTE_NONE,
            window_id=window_id,
            commit_ids=commit_ids,
            next_input_cursor=commit_ids[-1] + 1 if commit_ids else current_cursor,
            reason_codes=(REASON_ACCEPT_ALL,),
        )

    has_reject = any(st == REJECT for _cid, st in unit_states)

    if has_reject and route_mode == "W":
        return RoutePlan(
            route=ROUTE_SHADOW if shadow else ROUTE_WHOLE,
            window_id=window_id,
            commit_ids=(),
            retry_request=_retry_request(window_id, transition_state_hash, retry_count, REASON_REJECT_WHOLE),
            next_input_cursor=current_cursor,
            reason_codes=(REASON_REJECT_WHOLE,),
        )

    gap_start_id = unit_states[first_bad][0]
    run_end = first_bad
    while run_end < len(unit_states) and unit_states[run_end][1] != ACCEPT:
        run_end += 1
    gap_end_id = unit_states[run_end][0] if run_end < len(unit_states) else unit_states[-1][0] + 1
    unresolved_gap = (gap_start_id, gap_end_id)

    commit_ids = tuple(cid for cid, _st in unit_states[:first_bad])
    reason = REASON_GAP_UNCERTAIN if unit_states[first_bad][1] == UNCERTAIN else REASON_GAP_REJECT
    return RoutePlan(
        route=ROUTE_SHADOW if shadow else ROUTE_LOCAL,
        window_id=window_id,
        commit_ids=commit_ids,
        unresolved_gap=unresolved_gap,
        retry_request=_retry_request(window_id, transition_state_hash, retry_count, reason),
        next_input_cursor=commit_ids[-1] + 1 if commit_ids else gap_start_id,
        reason_codes=(reason,),
    )
