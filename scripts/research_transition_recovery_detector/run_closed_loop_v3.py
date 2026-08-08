#!/usr/bin/env python3
"""10_FOLLOWUP Task B：retry 驱动的 closed-loop writeback（v3）。

数据流（10_FOLLOWUP_IMPLEMENTATION_PLAN.md §2 Task B）：
    serial forward -> detector -> initial RoutePlan -> executor retry
      -> retry rows -> detector(retry rows) -> retry writeback plan
      -> apply writeback rows/state/timestamps -> next serial request

与 v2（run_closed_loop.py）的区别：
- v2 的 retry 只把 retry rows 并入 observations，retry 输出不参与写回决策；
- v3 的编排层（本模块）是唯一可对 retry rows 再调 detector 并构造 retry writeback plan
  的位置；RouteExecutor 只执行传入 plan 并返回 retry rows/audit/cost（不修改
  src/lyricalign/research_transition_recovery_detector/ 与 route_executor）。

写回语义：
- L（ROUTE_LOCAL）：原 serial ACCEPT prefix 照常写回；retry plan 只从 gap 起
  依 retry rows 的 detector 三态连续提交，不跨未解决 gap（gap 内部首个非 ACCEPT
  起保持 unresolved）。
- W（ROUTE_WHOLE）：retry 重跑整窗后依 retry detector 结果重新决定可提交 prefix /
  未解决状态；原 whole rejection 不被当作 recovery 成功。
- 写回的 committed timestamps 来自实际写回的 serial/retry row，并记录 row provenance
  （source: serial|retry, window, request_id）。

Gate C（v3 强化，双条件）：
    ① 写回改变后续 state/request；
    ② 写回含至少一个实际 retry-derived row（retry 执行过时；未执行则 vacuous pass）。

输出 <session>/10_followup/closed_loop_v3/CLOSED_LOOP_V3_SUMMARY.json：
baseline serial（retry_enabled=False）与 selected closed-loop（retry_enabled=True）
对同一 GT/n_units 的同分母 delta：cost/coverage/Safe/Grey/Unsafe/unresolved/retry provenance。

GT 只在完整执行结束后的 evaluation 使用（执行阶段恒传 gt_timeline=None）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lyricalign.research_transition_recovery_detector.contracts import (  # noqa: E402
    ROUTE_LOCAL,
    ROUTE_SHADOW,
    ROUTE_WHOLE,
    TRANSITION_T2_CORE,
    TransitionState,
    WindowRequest,
)
from lyricalign.research_transition_recovery_detector.identity import state_hash  # noqa: E402
from lyricalign.research_transition_recovery_detector.query_estimator import (  # noqa: E402
    QueryEstimator,
)
from lyricalign.research_transition_recovery_detector.route_executor import (  # noqa: E402
    RouteExecutor,
)
from lyricalign.research_transition_recovery_detector.routes import build_route_plan  # noqa: E402
from lyricalign.research_transition_recovery_detector.thresholds import (  # noqa: E402
    tristate_labels,
)
from scripts.research_transition_recovery_detector.run_closed_loop import (  # noqa: E402
    DETECTOR_PKL_DEFAULT,
    HEAD_STRATEGY,
    LOOKBACK_UNITS,
    SAMPLE_RATE,
    CORRECT_TOLERANCE_SEC,
    UNSAFE_TOLERANCE_SEC,
    RecordingAlignerBackend,
    _normalize_rows,
    _request_for,
    _request_identity,
    _unit_states_from_rows,
    evaluate_song_gt,
)

SAFE_TOLERANCE_SEC = 0.100  # 冻结正式标签：error <= 100ms -> Safe
GREY_TOLERANCE_SEC = CORRECT_TOLERANCE_SEC  # 100ms < error <= 250ms -> Grey


def _apply_plan_state(state: TransitionState, plan) -> TransitionState:
    """serial-only 状态推进（baseline 无 retry 时复用，等价 executor._apply_plan）。"""
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
    new_state = state.derive(
        committed_ids=committed,
        committed_end_exclusive=len(committed),
        next_input_cursor=next_cursor,
        provisional_ids=tuple(plan.provisional_ids) if plan.provisional_ids else state.provisional_ids,
        unresolved_gap=plan.unresolved_gap,
        retry_count=retry_count,
    )
    new_state.validate()
    return new_state


def build_retry_writeback_plan(
    *,
    plan,
    retry_rows: list[dict],
    retry_p_bad: list[float],
    frozen_wp: dict,
    base_cursor: int,
) -> tuple[tuple[int, ...], tuple[int, int] | None, bool]:
    """编排层唯一的 retry writeback 决策：retry rows 的 detector 三态 -> (commit_ids, new_gap, evidence)。

    - 只从 base_cursor（L 的 gap_start / W 的 window cursor）起连续提交 ACCEPT；
    - 首个非 ACCEPT（含缺失 id，保守 UNCERTAIN）起为 unresolved gap 起点，
      gap 终点为该非 ACCEPT 连续段尾后的第一个 id（或 retry 覆盖末端+1）；
    - gap 之后的 ACCEPT 一律不提交（不跨未解决 gap）；
    - evidence=False 表示 retry rows 未覆盖 base_cursor 起的任何 id（调用方保留原 gap）。
    """
    if len(retry_p_bad) != len(retry_rows):
        raise ValueError(
            f"detector_predict must return one p_bad per retry row "
            f"(got {len(retry_p_bad)} for {len(retry_rows)} rows)"
        )
    by_id: dict[int, str] = {}
    for row, p in zip(retry_rows, retry_p_bad, strict=True):
        cid = int(row["global_character_index"])
        by_id[cid] = tristate_labels(
            float(p), float(frozen_wp["t_accept"]), float(frozen_wp["t_reject"])
        )
    covered = sorted(cid for cid in by_id if cid >= base_cursor)
    if not covered:
        return (), None, False
    max_covered = covered[-1]

    commit: list[int] = []
    gap_start: int | None = None
    for cid in range(base_cursor, max_covered + 1):
        st = by_id.get(cid, "UNCERTAIN")
        if st == "ACCEPT":
            if gap_start is None:
                commit.append(cid)
        elif gap_start is None:
            gap_start = cid
    if gap_start is None:
        return tuple(commit), None, True
    run_end = gap_start
    while run_end <= max_covered and by_id.get(run_end, "UNCERTAIN") != "ACCEPT":
        run_end += 1
    return tuple(commit), (gap_start, run_end), True


def _query_audio_span_sec(query_ids, estimator: QueryEstimator) -> tuple[float, float]:
    """retry query 覆盖的音频区间（uniform 估计，仅供 audit，不参与 alignment）。"""
    if not query_ids:
        return (0.0, 0.0)
    spu = estimator.sec_per_unit
    return (min(query_ids) * spu, (max(query_ids) + 1) * spu)


def evaluate_song_gt_v3(
    *,
    song_id: str,
    n_units: int,
    committed_ids: tuple[int, ...],
    committed_times: dict[int, float],
    gt: dict[int, dict],
    tolerance_sec: float,
    unsafe_tolerance_sec: float,
) -> dict:
    """v3 评估：复用 v2 核心指标 + 冻结标签 Safe/Grey/Unsafe 计数（100/250ms 边界）。"""
    eval_ = evaluate_song_gt(
        song_id=song_id,
        n_units=n_units,
        committed_ids=committed_ids,
        committed_times=committed_times,
        gt=gt,
        tolerance_sec=tolerance_sec,
        unsafe_tolerance_sec=unsafe_tolerance_sec,
    )
    safe = grey = unsafe = 0
    for cid in committed_ids:
        g = gt.get(cid)
        if g is None:
            continue
        diff = abs(committed_times.get(cid, float("inf")) - float(g["start_sec"]))
        if diff <= SAFE_TOLERANCE_SEC:
            safe += 1
        elif diff <= GREY_TOLERANCE_SEC:
            grey += 1
        else:
            unsafe += 1
    eval_["classification"] = {
        "safe_100ms": safe,
        "grey_250ms": grey,
        "unsafe_250ms": unsafe,
    }
    return eval_


def run_closed_loop_v3_song(
    *,
    song_id: str,
    audio,
    document,
    gt: dict[int, dict],
    window_plan: dict,
    estimator: QueryEstimator,
    backend,
    transition: str = TRANSITION_T2_CORE,
    frozen_wp: dict,
    route_mode: str = "L",
    detector_predict=None,
    retry_enabled: bool = True,
    lookback_units: int = LOOKBACK_UNITS,
    head_strategy: str = HEAD_STRATEGY,
    tolerance_sec: float = CORRECT_TOLERANCE_SEC,
    unsafe_tolerance_sec: float = UNSAFE_TOLERANCE_SEC,
) -> dict:
    """Task B 闭环：retry rows 再入 detector -> retry writeback plan -> 实际写回。

    detector_predict(rows) -> list[float] 是唯一 p_bad 注入点；它对 serial rows 与
    retry rows 各调用一次（编排层是唯一可对 retry rows 调 detector 的位置）。
    retry_enabled=False 时退化为 baseline serial（无 retry forward/写回决策）。
    """
    if detector_predict is None:
        raise ValueError("detector_predict must be provided (main 注入真实 detector，测试注入 p_bad 列表)")

    executor = RouteExecutor(transition_runner=None, backend=backend)
    state = TransitionState(
        song_id=song_id, transition=transition, window_index=0,
        next_input_cursor=0, committed_end_exclusive=0,
    )
    observations: dict[int, dict] = {}
    windows = list(window_plan["windows"])
    records: list[dict] = []
    totals = {"forward_seconds": 0.0, "audio_seconds": 0.0, "wall_seconds": 0.0,
              "extra_forward_count": 0, "extra_audio_seconds": 0.0,
              "extra_wall_seconds": 0.0}
    gate_c_failures: list[dict] = []
    first_gap_window: int | None = None
    last_gap_window: int | None = None
    committed_times: dict[int, float] = {}
    provenance: dict[int, dict] = {}
    retry_request_ids: list[str] = []
    n_retry_derived_commits = 0

    for win in windows:
        k = int(win["window_index"])
        state = state.derive(window_index=k)
        state_before = state
        request = _request_for(
            song_id=song_id, transition=transition, state=state, win=win,
            estimator=estimator, observations=observations, window_index=k,
            lookback_units=lookback_units, head_strategy=head_strategy,
        )
        wall0 = time.monotonic()
        rows, audit = backend.forward(request, audio=audio, document=document)
        rows = _normalize_rows(rows)
        serial_cost = {
            "forward_seconds": float(audit.get("forward_seconds", 0.0)),
            "audio_seconds": float(audit.get("audio_seconds", 0.0)),
        }
        wall = time.monotonic() - wall0

        # ---- serial rows -> detector -> initial RoutePlan（唯一初始决策点） ----
        p_bad = list(detector_predict(rows))
        unit_states = _unit_states_from_rows(
            rows=rows, p_bad_per_row=p_bad, frozen_wp=frozen_wp,
            start_id=state.committed_end_exclusive,
        )
        plan = build_route_plan(
            window_id=f"w{k:03d}",
            unit_states=unit_states,
            current_cursor=state.committed_end_exclusive,
            transition_state_hash=state_hash(state),
            retry_count=state.retry_count,
            route_mode=route_mode,
        )

        if retry_enabled:
            outcome = executor.execute(
                plan, request=request, audio=audio, document=document,
                state=state, gt_timeline=None,  # 执行阶段不读 GT
            )
        elif plan.route in (ROUTE_LOCAL, ROUTE_WHOLE):
            # baseline serial：不触发 retry forward，只应用 serial 决策（含 gap 保持）
            outcome = {
                "executed_forward_count": 0,
                "actual_writeback": 0 if plan.route == ROUTE_SHADOW else 1,
                "new_state": _apply_plan_state(state, plan),
                "cost": {"forward_seconds": 0.0, "audio_seconds": 0.0},
            }
        else:
            outcome = executor.execute(
                plan, request=request, audio=audio, document=document,
                state=state, gt_timeline=None,
            )

        retry_rows: list[dict] = []
        retry_info = {"executed_forward_count": 0, "request_id": None, "n_rows": 0,
                      "query_ids": [], "slot_ids": [], "audio_seconds": 0.0,
                      "query_audio_span_sec": [0.0, 0.0]}
        if outcome["executed_forward_count"] > 0:
            retry_rows = _normalize_rows(list(backend.last_rows or []))
            retry_req = backend.last_request
            retry_info = {
                "executed_forward_count": outcome["executed_forward_count"],
                "request_id": retry_req.request_id if retry_req else None,
                "n_rows": len(retry_rows),
                "query_ids": list(retry_req.query_canonical_ids) if retry_req else [],
                "slot_ids": list(retry_req.slot_canonical_ids) if retry_req else [],
                "audio_seconds": float(outcome["cost"].get("audio_seconds", 0.0)),
                "query_audio_span_sec": list(
                    _query_audio_span_sec(
                        retry_req.query_canonical_ids, estimator) if retry_req else (0.0, 0.0)
                ),
            }

        # ---- retry writeback plan：编排层唯一可对 retry rows 调 detector 的位置 ----
        plan_state = outcome["new_state"]
        retry_commits: tuple[int, ...] = ()
        retry_gap: tuple[int, int] | None = None
        retry_evidence = False
        if retry_enabled and retry_rows:
            retry_p_bad = list(detector_predict(retry_rows))
            base_cursor = plan_state.committed_end_exclusive
            retry_commits, retry_gap, retry_evidence = build_retry_writeback_plan(
                plan=plan, retry_rows=retry_rows, retry_p_bad=retry_p_bad,
                frozen_wp=frozen_wp, base_cursor=base_cursor,
            )
            if retry_evidence:
                plan_state = plan_state.derive(
                    committed_ids=plan_state.committed_ids + tuple(retry_commits),
                    committed_end_exclusive=plan_state.committed_end_exclusive + len(retry_commits),
                    unresolved_gap=retry_gap,
                )
                plan_state.validate()

        writeback_commits = tuple(plan.commit_ids) + tuple(retry_commits)
        if retry_commits:
            n_retry_derived_commits += len(retry_commits)
        if retry_info["executed_forward_count"] > 0 and retry_info["request_id"]:
            retry_request_ids.append(retry_info["request_id"])

        # ---- 实际写回的 rows -> committed timestamps + row provenance ----
        serial_by_id = {int(r["global_character_index"]): r for r in rows}
        retry_by_id = {int(r["global_character_index"]): r for r in retry_rows}
        for cid in plan.commit_ids:
            row = serial_by_id.get(cid)
            if row is None:
                raise RuntimeError(f"serial writeback row missing for id {cid} (window {k})")
            committed_times[cid] = float(row["start_sec"])
            provenance[cid] = {
                "source": "serial", "window": k, "request_id": request.request_id,
            }
        for cid in retry_commits:
            row = retry_by_id.get(cid)
            if row is None:
                raise RuntimeError(f"retry writeback row missing for id {cid} (window {k})")
            committed_times[cid] = float(row["start_sec"])
            provenance[cid] = {
                "source": "retry", "window": k,
                "request_id": retry_info["request_id"],
            }

        # retry rows 优先进 observations（后续 query 用 retry 证据），serial rows 兜底。
        for r in retry_rows:
            observations[int(r["global_character_index"])] = {
                "global_character_index": int(r["global_character_index"]),
                "start_sec": float(r["start_sec"]), "end_sec": float(r["end_sec"]),
                "source": str(r.get("source", "raw")),
            }
        for r in rows:
            observations.setdefault(
                int(r["global_character_index"]),
                {"global_character_index": int(r["global_character_index"]),
                 "start_sec": float(r["start_sec"]), "end_sec": float(r["end_sec"]),
                 "source": str(r.get("source", "raw"))},
            )

        # ---- Gate C v3：① state/request 改变 且 ② 含至少一个 retry-derived row ----
        last_window = k == len(windows) - 1
        state_hash_before = state_hash(state_before)
        resumed_state = plan_state if outcome["actual_writeback"] else state_before
        state_hash_after = state_hash(resumed_state)
        state_changed = state_hash_before != state_hash_after
        next_request_changed: bool | None = None
        if not last_window:
            next_win = windows[k + 1]
            hypothetical = _request_for(
                song_id=song_id, transition=transition, state=state_before, win=next_win,
                estimator=estimator,
                observations={x: y for x, y in observations.items()
                              if x not in retry_by_id},
                window_index=k + 1,
                lookback_units=lookback_units, head_strategy=head_strategy,
            )
            actual_next = _request_for(
                song_id=song_id, transition=transition, state=resumed_state, win=next_win,
                estimator=estimator, observations=observations, window_index=k + 1,
                lookback_units=lookback_units, head_strategy=head_strategy,
            )
            next_request_changed = _request_identity(hypothetical) != _request_identity(actual_next)
        cond1_ok = state_changed or bool(next_request_changed)
        retry_executed = outcome["executed_forward_count"] > 0
        retry_derived_required = retry_executed
        retry_derived_ok = (not retry_derived_required) or len(retry_commits) >= 1
        gate_c_ok = cond1_ok and retry_derived_ok
        if not gate_c_ok:
            gate_c_failures.append({
                "window_index": k,
                "state_changed": state_changed,
                "next_request_changed": next_request_changed,
                "cond1_state_or_request_changed": cond1_ok,
                "retry_derived_required": retry_derived_required,
                "retry_derived_ok": retry_derived_ok,
            })

        if plan_state.unresolved_gap is not None:
            if first_gap_window is None:
                first_gap_window = k
            last_gap_window = k

        if outcome["actual_writeback"]:
            state = plan_state
        else:
            state = state_before

        retry_cost = dict(outcome["cost"])
        window_cost = {
            "forward_seconds": serial_cost["forward_seconds"] + retry_cost["forward_seconds"],
            "audio_seconds": serial_cost["audio_seconds"] + retry_cost["audio_seconds"],
            "wall_seconds": wall + float(retry_cost.get("forward_seconds", 0.0)),
        }
        totals["forward_seconds"] += window_cost["forward_seconds"]
        totals["audio_seconds"] += window_cost["audio_seconds"]
        totals["wall_seconds"] += window_cost["wall_seconds"]
        totals["extra_forward_count"] += retry_info["executed_forward_count"]
        totals["extra_audio_seconds"] += retry_cost["audio_seconds"]
        totals["extra_wall_seconds"] += retry_cost["forward_seconds"]

        records.append({
            "window_index": k,
            "request_id": request.request_id,
            "model_bounds": list(request.model_bounds),
            "query_ids": list(request.query_canonical_ids),
            "n_query_units": len(request.query_canonical_ids),
            "plan": {
                "route": plan.route,
                "commit_ids": list(plan.commit_ids),
                "provisional_ids": list(plan.provisional_ids),
                "unresolved_gap": list(plan.unresolved_gap) if plan.unresolved_gap else None,
                "retry_count": plan.retry_request.retry_count if plan.retry_request else None,
                "reason_codes": list(plan.reason_codes),
                "next_input_cursor": plan.next_input_cursor,
            },
            "retry": retry_info,
            "retry_writeback": {
                "evidence": retry_evidence,
                "commit_ids": list(retry_commits),
                "unresolved_gap_after": list(retry_gap) if retry_gap else None,
                "n_retry_derived": len(retry_commits),
            },
            "writeback": {
                "actual_writeback": outcome["actual_writeback"],
                "committed_this_window": list(writeback_commits),
                "n_serial_derived": len(plan.commit_ids),
                "n_retry_derived": len(retry_commits),
                "state_hash_before": state_hash_before,
                "state_hash_after": state_hash_after,
                "gate_c": {
                    "ok": gate_c_ok,
                    "state_changed": state_changed,
                    "next_request_changed": next_request_changed,
                    "retry_derived_required": retry_derived_required,
                    "retry_derived_ok": retry_derived_ok,
                },
            },
            "committed_this_window": list(writeback_commits),
            "cost": window_cost,
            "window_state": {
                "committed_end_exclusive": state.committed_end_exclusive,
                "unresolved_gap": state.unresolved_gap,
            },
        })

    # ---- 最终评估（GT 只在这里进入） ----
    eval_ = evaluate_song_gt_v3(
        song_id=song_id,
        n_units=len(gt),
        committed_ids=state.committed_ids,
        committed_times=committed_times,
        gt=gt,
        tolerance_sec=tolerance_sec,
        unsafe_tolerance_sec=unsafe_tolerance_sec,
    )
    recovery_delay_windows = None
    if first_gap_window is not None:
        recovery_delay_windows = (
            (last_gap_window - first_gap_window + 1) if last_gap_window is not None else 1
        )

    return {
        "schema_version": "closed_loop_v3_retry_writeback",
        "song_id": song_id,
        "transition": transition,
        "route_mode": route_mode,
        "retry_enabled": retry_enabled,
        "n_windows": len(records),
        "n_units_total": len(gt),
        "windows": records,
        "totals": totals,
        "evaluation": eval_,
        "committed_times": {str(cid): t for cid, t in sorted(committed_times.items())},
        "committed_provenance": {str(cid): p for cid, p in sorted(provenance.items())},
        "retry_provenance": {
            "n_retry_derived_commits": n_retry_derived_commits,
            "n_windows_with_retry": len(retry_request_ids),
            "retry_request_ids": retry_request_ids,
        },
        "recovery_delay_windows": recovery_delay_windows,
        "gate_c": {
            "passed": not gate_c_failures,
            "n_windows": len(records),
            "n_passed": len(records) - len(gate_c_failures),
            "failures": gate_c_failures,
        },
    }


def _num_delta(a: float, b: float) -> float:
    return round(float(b) - float(a), 6)


def _song_delta(baseline: dict, selected: dict) -> dict:
    """同分母（同一 song 的同一 GT/n_units）的 baseline vs selected delta。"""
    b, s = baseline, selected
    clf_keys = ("safe_100ms", "grey_250ms", "unsafe_250ms")
    return {
        "song_id": s["song_id"],
        "route_mode": s["route_mode"],
        "denominator_n_units": s["n_units_total"],
        "cost": {
            "baseline": b["totals"], "closed_loop": s["totals"],
            "delta": {
                "forward_seconds": _num_delta(b["totals"]["forward_seconds"], s["totals"]["forward_seconds"]),
                "audio_seconds": _num_delta(b["totals"]["audio_seconds"], s["totals"]["audio_seconds"]),
                "wall_seconds": _num_delta(b["totals"]["wall_seconds"], s["totals"]["wall_seconds"]),
                "extra_forward_count": int(s["totals"]["extra_forward_count"]) - int(b["totals"]["extra_forward_count"]),
                "extra_audio_seconds": _num_delta(b["totals"]["extra_audio_seconds"], s["totals"]["extra_audio_seconds"]),
            },
        },
        "coverage": {
            "baseline": {k: b["evaluation"][k] for k in
                         ("committed_coverage", "correct_committed_coverage", "correct_committed_rate")},
            "closed_loop": {k: s["evaluation"][k] for k in
                            ("committed_coverage", "correct_committed_coverage", "correct_committed_rate")},
            "delta": {k: _num_delta(b["evaluation"][k], s["evaluation"][k]) for k in
                      ("committed_coverage", "correct_committed_coverage", "correct_committed_rate")},
        },
        "classification": {
            "baseline": {k: b["evaluation"]["classification"][k] for k in clf_keys},
            "closed_loop": {k: s["evaluation"]["classification"][k] for k in clf_keys},
            "delta": {k: int(s["evaluation"]["classification"][k]) - int(b["evaluation"]["classification"][k])
                      for k in clf_keys},
        },
        "unresolved": {
            "baseline": {"unresolved_units": b["evaluation"]["unresolved_units"],
                         "unresolved_rate": b["evaluation"]["unresolved_rate"]},
            "closed_loop": {"unresolved_units": s["evaluation"]["unresolved_units"],
                            "unresolved_rate": s["evaluation"]["unresolved_rate"]},
            "delta": {"unresolved_units": int(s["evaluation"]["unresolved_units"]) - int(b["evaluation"]["unresolved_units"]),
                      "unresolved_rate": _num_delta(b["evaluation"]["unresolved_rate"], s["evaluation"]["unresolved_rate"])},
        },
        "retry_provenance": {
            "n_retry_derived_commits": s["retry_provenance"]["n_retry_derived_commits"],
            "n_windows_with_retry": s["retry_provenance"]["n_windows_with_retry"],
            "retry_request_ids": s["retry_provenance"]["retry_request_ids"],
        },
    }


def _pooled_delta(song_deltas: list[dict]) -> dict:
    if not song_deltas:
        return {}
    denom = sum(d["denominator_n_units"] for d in song_deltas)
    pooled = {
        "denominator_n_units": denom,
        "cost": {"baseline": {"forward_seconds": 0.0, "audio_seconds": 0.0, "wall_seconds": 0.0,
                              "extra_forward_count": 0, "extra_audio_seconds": 0.0, "extra_wall_seconds": 0.0},
                 "closed_loop": {k: 0.0 for k in ("forward_seconds", "audio_seconds", "wall_seconds")},
                 "delta": {}},
        "coverage": {"baseline": {}, "closed_loop": {}, "delta": {}},
        "classification": {"baseline": {"safe_100ms": 0, "grey_250ms": 0, "unsafe_250ms": 0},
                           "closed_loop": {"safe_100ms": 0, "grey_250ms": 0, "unsafe_250ms": 0},
                           "delta": {}},
        "unresolved": {"baseline": {"unresolved_units": 0}, "closed_loop": {"unresolved_units": 0}},
        "retry_provenance": {"n_retry_derived_commits": 0, "n_windows_with_retry": 0, "retry_request_ids": []},
    }
    for d in song_deltas:
        for side in ("baseline", "closed_loop"):
            for k, v in d["cost"][side].items():
                pooled["cost"][side][k] = pooled["cost"][side].get(k, 0.0) + v
            for k, v in d["classification"][side].items():
                pooled["classification"][side][k] += v
            for k, v in d["coverage"][side].items():
                pooled["coverage"][side][k] = pooled["coverage"][side].get(k, 0.0) + v * d["denominator_n_units"]
            pooled["unresolved"][side]["unresolved_units"] += d["unresolved"][side]["unresolved_units"]
        pooled["retry_provenance"]["n_retry_derived_commits"] += d["retry_provenance"]["n_retry_derived_commits"]
        pooled["retry_provenance"]["n_windows_with_retry"] += d["retry_provenance"]["n_windows_with_retry"]
        pooled["retry_provenance"]["retry_request_ids"] += d["retry_provenance"]["retry_request_ids"]
    for side in ("baseline", "closed_loop"):
        for k in ("committed_coverage", "correct_committed_coverage", "correct_committed_rate"):
            pooled["coverage"][side][k] = round(pooled["coverage"][side].get(k, 0.0) / max(denom, 1), 6)
        pooled["unresolved"][side]["unresolved_rate"] = round(
            pooled["unresolved"][side]["unresolved_units"] / max(denom, 1), 6)
    for k in ("committed_coverage", "correct_committed_coverage", "correct_committed_rate"):
        pooled["coverage"]["delta"][k] = round(
            pooled["coverage"]["closed_loop"][k] - pooled["coverage"]["baseline"][k], 6)
    pooled["unresolved"]["delta"] = {
        "unresolved_units": pooled["unresolved"]["closed_loop"]["unresolved_units"]
        - pooled["unresolved"]["baseline"]["unresolved_units"],
        "unresolved_rate": round(pooled["unresolved"]["closed_loop"]["unresolved_rate"]
                                 - pooled["unresolved"]["baseline"]["unresolved_rate"], 6),
    }
    for k in ("safe_100ms", "grey_250ms", "unsafe_250ms"):
        pooled["classification"]["delta"][k] = (
            pooled["classification"]["closed_loop"][k] - pooled["classification"]["baseline"][k])
    pooled["cost"]["delta"] = {
        k: round(pooled["cost"]["closed_loop"].get(k, 0.0) - pooled["cost"]["baseline"].get(k, 0.0), 6)
        for k in ("forward_seconds", "audio_seconds", "wall_seconds", "extra_audio_seconds")
    }
    pooled["cost"]["delta"]["extra_forward_count"] = int(
        pooled["cost"]["closed_loop"].get("extra_forward_count", 0.0)
        - pooled["cost"]["baseline"].get("extra_forward_count", 0.0))
    return pooled


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-root", required=True)
    p.add_argument("--timeline-manifest", required=True)
    p.add_argument("--role", default="model_selection")
    p.add_argument("--transition", default=TRANSITION_T2_CORE)
    p.add_argument("--detector-pkl", default=DETECTOR_PKL_DEFAULT)
    p.add_argument("--working-point", default="SA60")
    p.add_argument("--route-mode", default="L", choices=["L", "W"])
    p.add_argument("--song-ids", default="")
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()

    import pickle

    import numpy as np
    import soundfile as sf
    from scripts.demo.align_qwen_fa_serial_demo import (  # noqa: E402
        build_vocal_activity_profile,
        load_model,
    )
    from scripts.research_transition_recovery_detector.train_detector_helpers import (  # noqa: E402
        predict_p_bad,
    )
    from lyricalign.demo.karaoke import parse_lyrics_text  # noqa: E402
    from lyricalign.demo.window_planning import build_silence_aware_window_plan  # noqa: E402
    from lyricalign.research_transition_recovery_detector.detector_features import (  # noqa: E402
        FEATURE_NAMES,
        extract_signal_features,
    )
    from lyricalign.research_transition_recovery_detector.runner import RealAlignerBackend  # noqa: E402

    session_root = Path(args.session_root)
    split = json.loads((session_root / "00_meta" / "DATASET_SPLIT.json").read_text(encoding="utf-8"))
    song_ids = split["roles"][args.role]
    if args.song_ids:
        song_ids = [s for s in song_ids if s in {x.strip() for x in args.song_ids.split(",")}]
    by_song = {
        json.loads(line)["song_id"]: json.loads(line)
        for line in Path(args.timeline_manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    v2_path = session_root / "10_followup" / "detector_v2" / "FROZEN_WORKING_POINTS_v2.json"
    frozen = json.loads(v2_path.read_text(encoding="utf-8")).get("working_points_v3_format", {})
    if args.working_point not in frozen:
        raise ValueError(f"working point {args.working_point!r} not in FROZEN_WORKING_POINTS_v2.json (v3 format)")
    wp = frozen[args.working_point]
    if "t_accept" not in wp or "t_reject" not in wp:
        raise ValueError(f"working point {args.working_point!r} not frozen/feasible (v3 format)")
    with open(args.detector_pkl, "rb") as f:
        artifact = pickle.load(f)

    model_args = argparse.Namespace(
        model="Qwen/Qwen3-ForcedAligner-0.6B-hf",
        revision="c07281df297b9905d24a508279258cccf987a064",
        cache_dir="/home/hyan/Data/lyricalign/models/hf_cache",
        local_files_only=True,
        device=args.device,
    )
    processor, model = load_model(model_args, "raw", None)
    infer_args = argparse.Namespace(
        timestamp_segment_sec=0.08, decoder_kind="raw", decoder_top_k=8, decoder_beam_size=96,
        research_infer_cache_root=str(session_root / "cache" / "closed_loop"),
        research_model_identity={"kind": "raw"}, device=args.device,
    )

    detector_feature_names = tuple(artifact.get("feature_names") or FEATURE_NAMES)

    def detector_predict(rows):
        feats = extract_signal_features(rows)
        return predict_p_bad(artifact, feats, detector_feature_names)

    per_song = []
    song_deltas = []
    backends = []
    for song_id in song_ids:
        row = by_song[song_id]
        audio, sr = sf.read(row["concat_audio_path"], dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        duration = float(len(audio) / SAMPLE_RATE)
        document = parse_lyrics_text(
            "".join(u["text"] for u in row["canonical_units"]), language="Chinese")
        gt = {int(u["canonical_unit_id"]): u for u in row["canonical_units"]}
        window_plan = build_silence_aware_window_plan(
            duration, build_vocal_activity_profile(audio, sample_rate=SAMPLE_RATE),
            target_core_sec=60.0, left_context_sec=10.0, right_context_sec=10.0,
        )
        estimator = QueryEstimator(
            n_units=len(document.characters), effective_audio_sec=duration,
        )

        def make_backend():
            return RecordingAlignerBackend(
                RealAlignerBackend(processor=processor, model=model, args=infer_args,
                                   sample_rate=SAMPLE_RATE))

        base_backend = make_backend()
        baseline = run_closed_loop_v3_song(
            song_id=song_id, audio=audio, document=document, gt=gt,
            window_plan=window_plan, estimator=estimator, backend=base_backend,
            transition=args.transition, frozen_wp=wp, route_mode=args.route_mode,
            detector_predict=detector_predict, retry_enabled=False,
        )
        sel_backend = make_backend()
        selected = run_closed_loop_v3_song(
            song_id=song_id, audio=audio, document=document, gt=gt,
            window_plan=window_plan, estimator=estimator, backend=sel_backend,
            transition=args.transition, frozen_wp=wp, route_mode=args.route_mode,
            detector_predict=detector_predict, retry_enabled=True,
        )
        backends.extend([base_backend, sel_backend])
        per_song.append(selected)
        song_deltas.append(_song_delta(baseline, selected))
        print(json.dumps({
            "song_id": song_id,
            "windows": selected["n_windows"],
            "committed_coverage": round(selected["evaluation"]["committed_coverage"], 4),
            "correct_coverage": round(selected["evaluation"]["correct_committed_coverage"], 4),
            "unsafe_commit": selected["evaluation"]["unsafe_commit"],
            "extra_forward": selected["totals"]["extra_forward_count"],
            "n_retry_derived": selected["retry_provenance"]["n_retry_derived_commits"],
            "gate_c_passed": selected["gate_c"]["passed"],
        }))
    if any(b.last_gt_seen is not None for b in backends):
        raise RuntimeError("GT leaked into backend execution")

    all_gate_c = [s["gate_c"]["passed"] for s in per_song]
    out_dir = session_root / "10_followup" / "closed_loop_v3"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "closed_loop_v3_retry_writeback",
        "correction_plan_version": "20260808_correction_v1",
        "task": "B_retry_writeback",
        "clock": "original",
        "scope": "no_gt_execution",
        "transition": args.transition,
        "route_mode": args.route_mode,
        "working_point": args.working_point,
        "detector_pkl": args.detector_pkl,
        "retry_semantics": {
            "L": "serial ACCEPT prefix writeback + retry commits from gap, no crossing unresolved gap",
            "W": "retry whole-window rows re-decide commit prefix via retry detector; "
                 "original whole rejection is not recovery success",
            "provenance": "committed timestamps from actually written-back serial/retry rows "
                          "(source: serial|retry, window, request_id)",
            "gate_c_v3": "① writeback changes subsequent state/request AND "
                         "② writeback contains >=1 retry-derived row (when retry executed)",
        },
        "per_song": per_song,
        "baseline_vs_closed_loop_delta": {
            "per_song": song_deltas,
            "pooled": _pooled_delta(song_deltas),
            "same_denominator_note": "baseline serial and selected closed-loop evaluate the same GT "
                                     "with the same n_units per song (denominator_n_units)",
        },
        "gate_c": {
            "passed": bool(per_song) and all(all_gate_c),
            "n_songs": len(per_song),
            "n_songs_passed": sum(1 for ok in all_gate_c if ok),
            "n_songs_failed": sum(1 for ok in all_gate_c if not ok),
        },
    }
    (out_dir / "CLOSED_LOOP_V3_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"gate_c": summary["gate_c"],
                      "out": str(out_dir / "CLOSED_LOOP_V3_SUMMARY.json")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
