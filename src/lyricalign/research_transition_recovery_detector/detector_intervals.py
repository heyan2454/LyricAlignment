"""Detector intervalization（09 §3 P4 必做）。

将 per-unit 三态（ACCEPT/REJECT/UNCERTAIN）折叠为整段无 gap/overlap 的 interval，
报告 interval @75/@100、longest unsafe ACCEPT run、correct-unit false reject/uncertain。
纯函数，无模型/GT 泄漏（标签由外部传入）。
"""

from __future__ import annotations

from .thresholds import STATE_ACCEPT, STATE_REJECT, STATE_UNCERTAIN


def build_intervals(unit_states: list[tuple[int, str]]) -> list[dict]:
    """连续相同三态区间（无 gap/overlap）。unit_states = [(canonical_id, state)]，需升序。"""
    intervals: list[dict] = []
    for cid, state in sorted(unit_states, key=lambda x: x[0]):
        if intervals and intervals[-1]["state"] == state and cid == intervals[-1]["end_id"] + 1:
            intervals[-1]["end_id"] = cid
            intervals[-1]["n_units"] += 1
        else:
            intervals.append({"state": state, "start_id": cid, "end_id": cid, "n_units": 1})
    return intervals


def interval_metrics(
    unit_states: list[tuple[int, str]],
    gt_labels: dict[int, int],
) -> dict:
    """interval 级指标。

    - unsafe_reject_interval_75/100：连续 unsafe 且被 REJECT 的 interval 中，
      覆盖（interval 内 unsafe 行 / 该 interval unsafe 总数）>=75%/100% 的 interval 数
    - longest_unsafe_accept_run：连续 unsafe 且被 ACCEPT 的最长区间行数（危险：误放行）
    - correct_unit_false_reject：correct（gt=0）但被 REJECT 的行数
    - correct_unit_false_uncertain：correct 但 UNCERTAIN 的行数
    """
    intervals = build_intervals(unit_states)
    unsafe_accept_runs: list[int] = []
    unsafe_reject_ok_75 = 0
    unsafe_reject_ok_100 = 0
    false_reject = 0
    false_uncertain = 0
    for iv in intervals:
        ids = [cid for cid in range(iv["start_id"], iv["end_id"] + 1) if cid in gt_labels]
        if not ids:
            continue
        unsafe = [cid for cid in ids if gt_labels[cid] == 1]
        n_unsafe = len(unsafe)
        if iv["state"] == STATE_ACCEPT and n_unsafe:
            unsafe_accept_runs.append(n_unsafe)
        elif iv["state"] == STATE_REJECT:
            if n_unsafe and n_unsafe / max(len(ids), 1) >= 0.75:
                unsafe_reject_ok_75 += 1
            if n_unsafe and n_unsafe == len(ids):
                unsafe_reject_ok_100 += 1
            false_reject += sum(1 for cid in ids if gt_labels[cid] == 0)
        elif iv["state"] == STATE_UNCERTAIN:
            false_uncertain += sum(1 for cid in ids if gt_labels[cid] == 0)
    return {
        "n_intervals": len(intervals),
        "interval_states": {
            STATE_ACCEPT: sum(1 for iv in intervals if iv["state"] == STATE_ACCEPT),
            STATE_REJECT: sum(1 for iv in intervals if iv["state"] == STATE_REJECT),
            STATE_UNCERTAIN: sum(1 for iv in intervals if iv["state"] == STATE_UNCERTAIN),
        },
        "unsafe_reject_interval_75": unsafe_reject_ok_75,
        "unsafe_reject_interval_100": unsafe_reject_ok_100,
        "longest_unsafe_accept_run": max(unsafe_accept_runs) if unsafe_accept_runs else 0,
        "correct_unit_false_reject": false_reject,
        "correct_unit_false_uncertain": false_uncertain,
    }
