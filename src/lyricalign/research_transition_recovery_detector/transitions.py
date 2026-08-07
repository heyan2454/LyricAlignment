"""T1/T2/T3 纯状态机：一窗 decoded rows -> 新 TransitionState。

对应 docs/research_transition_recovery_detector_20260807/07_REVIEWED_IMPLEMENTATION_PLAN.md
§3.2 的 T1/T2/T3 精确定义。本模块是纯函数：不加载模型、不读音频、不做任何 forward。
时间字段约定：rows 的 start_sec/end_sec 与 window_request.model_bounds 均为
model/compressed clock；original clock 映射由上层写盘时另存。
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    TRANSITION_T0_ORACLE,
    TRANSITION_T1_DIRECT,
    TRANSITION_T2_CORE,
    TRANSITION_T3_STABLE,
    TransitionState,
    WindowRequest,
)

STABILITY_TOLERANCE_SEC = 0.32


def stable_when(obs1: dict, obs2: dict, *, tolerance_sec: float = 0.32) -> bool:
    """两次跨窗观察是否构成 stability 证据。

    - 两次观察的 global_character_index 必须相同；
    - 任一观察带 `pre_registered_equivalent: True` 时视为预注册等价证据，直接 stable；
    - 否则要求两次真实观察的 start_sec 差 <= tolerance_sec（默认 0.32 s）。

    obs 字典字段：global_character_index、start_sec、end_sec、source（'raw'|'official'）。

    注意：stable_when 的两个参数必须来自**不同窗**的真实观察。同一 forward 内
    raw/official 的一致性绝不构成 cross-window stability（07 §3.2 T3 明确禁止）。
    """
    if int(obs1["global_character_index"]) != int(obs2["global_character_index"]):
        return False
    if obs1.get("pre_registered_equivalent") or obs2.get("pre_registered_equivalent"):
        return True
    for obs in (obs1, obs2):
        if obs["source"] not in ("raw", "official"):
            raise ValueError(f"observation source must be 'raw' or 'official', got {obs['source']!r}")
    return abs(float(obs1["start_sec"]) - float(obs2["start_sec"])) <= tolerance_sec


def _sorted_rows(rows: list[dict]) -> list[dict]:
    return sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))


def _collect_prefix_rows(
    ordered: list[dict],
    state: TransitionState,
    *,
    bound_sec: float,
) -> list[dict]:
    """收集本窗可永久提交的最大合法连续 prefix。

    规则（T1/T2 共用，见 07 §3.2）：
    - 只考虑 index >= committed_end_exclusive 的 uncommitted 行；更小的行是
      左上下文已提交行，仅供上下文，绝不重复提交；
    - 永久提交必须从 committed_end_exclusive 起连续：下一行 index != 期望值时
      停止提交（越界/倒序/缺失行都停止），不能跳过后继续；
    - start_sec < bound_sec 才属于本窗 ownership（T1: input_end；T2: core_end）；
      越界行停止提交，其后行即使再入界也不提交；
    - unresolved_gap 存在时不得提交 gap_start 及右侧行。
    """
    next_index = state.committed_end_exclusive
    gap = state.unresolved_gap
    prefix: list[dict] = []
    for row in ordered:
        row_index = int(row["global_character_index"])
        if row_index < next_index:
            continue
        if row_index != next_index:
            break
        if gap is not None and row_index >= gap[0]:
            break
        if float(row["start_sec"]) >= bound_sec:
            break
        prefix.append(row)
        next_index += 1
    return prefix


def _build_state(
    state: TransitionState,
    *,
    committed_rows: list[dict],
    provisional_ids: tuple[int, ...],
) -> TransitionState:
    committed_ids = state.committed_ids + tuple(int(r["global_character_index"]) for r in committed_rows)
    occurrence = list(state.occurrence_by_id)
    for row in committed_rows:
        occ = row.get("occurrence")
        if occ:
            occurrence.append((int(row["global_character_index"]), str(occ)))
    previous_end = (
        max(float(r["end_sec"]) for r in committed_rows)
        if committed_rows
        else state.previous_committed_end_model_sec
    )
    return state.derive(
        window_index=state.window_index + 1,
        next_input_cursor=len(committed_ids),
        committed_end_exclusive=len(committed_ids),
        committed_ids=committed_ids,
        provisional_ids=provisional_ids,
        occurrence_by_id=tuple(occurrence),
        previous_committed_end_model_sec=previous_end,
    )


def _apply_t1(state: TransitionState, ordered: list[dict], *, input_end_sec: float) -> TransitionState:
    committed = _collect_prefix_rows(ordered, state, bound_sec=input_end_sec)
    return _build_state(state, committed_rows=committed, provisional_ids=())


def _apply_t2(state: TransitionState, ordered: list[dict], *, core_end_sec: float) -> TransitionState:
    committed = _collect_prefix_rows(ordered, state, bound_sec=core_end_sec)
    return _build_state(state, committed_rows=committed, provisional_ids=())


def _apply_t3(
    state: TransitionState,
    ordered: list[dict],
    *,
    core_end_sec: float,
    previous_observation: dict[int, dict] | None,
) -> TransitionState:
    """在 T2 可提交 prefix 内仅永久提交 stable 连续前缀，其余保留 provisional。"""
    t2_prefix = _collect_prefix_rows(ordered, state, bound_sec=core_end_sec)
    previous_observation = previous_observation or {}
    stable: list[dict] = []
    deferred: list[dict] = []
    for row in t2_prefix:
        obs2 = {
            "global_character_index": int(row["global_character_index"]),
            "start_sec": float(row["start_sec"]),
            "end_sec": float(row["end_sec"]),
            "source": str(row.get("source", "official")),
        }
        obs1 = previous_observation.get(int(row["global_character_index"]))
        if obs1 is not None and stable_when(obs1, obs2):
            stable.append(row)
        else:
            deferred.append(row)
            break
    provisional = tuple(int(r["global_character_index"]) for r in (deferred + t2_prefix[len(stable) + len(deferred):]))
    return _build_state(state, committed_rows=stable, provisional_ids=provisional)


def apply_transition_policy(
    transition: str,
    state: TransitionState,
    rows: list[dict],
    *,
    window_request: WindowRequest,
    previous_observation: dict[int, dict] | None = None,
) -> TransitionState:
    """纯函数：上一窗 state + 本窗 decoded rows -> 新 state。

    rows 每行至少含 global_character_index、start_sec、end_sec（model clock）；
    可选：character、occurrence、source、fixed_global_start_sec 等（多余字段忽略）。
    ownership 边界取自 window_request.model_bounds = (input_start, core_start,
    core_end, input_end)。

    与 karaoke.split_core_commit_prefix（src/lyricalign/demo/karaoke.py:435）的
    等价关系（T2）：
    - split 的 committed = 按 global_character_index 连续（从
      expected_input_character_start 起校验）且 index >= committed_character_start、
      start（fixed_global_start_sec）< core_end_sec 的行；本实现 T2 在
      expected_input_character_start == state.next_input_cursor、
      committed_character_start == state.committed_end_exclusive、行序列连续且
      start_sec == fixed_global_start_sec 时给出完全相同的 committed 集合。
    - 差异：split 对非连续序列 raise RuntimeError；transition 合同要求“停止提交
      而不是报错”，故本实现以 break 停止（07 §3.2 T1 越界/倒序行停止提交）。
    - final_core（core_end >= input_end）时 split 提交全部 uncommitted，等价于本
      实现 bound=core_end 且所有可观察行 start < input_end <= core_end 的情形。
    """
    if transition not in (TRANSITION_T1_DIRECT, TRANSITION_T2_CORE, TRANSITION_T3_STABLE):
        raise NotImplementedError(
            f"apply_transition_policy only implements T1/T2/T3, got {transition!r}; "
            f"{TRANSITION_T0_ORACLE} requires oracle GT binding (Phase 1 runner scope)"
        )
    state.validate()
    window_request.validate()
    if state.transition != transition:
        raise ValueError(f"state.transition {state.transition!r} != policy {transition!r}")
    ordered = _sorted_rows(rows)
    input_start, _core_start, core_end, input_end = window_request.model_bounds
    if transition == TRANSITION_T1_DIRECT:
        return _apply_t1(state, ordered, input_end_sec=input_end)
    if transition == TRANSITION_T2_CORE:
        return _apply_t2(state, ordered, core_end_sec=core_end)
    return _apply_t3(state, ordered, core_end_sec=core_end, previous_observation=previous_observation)


def first_divergence(
    t1_state: TransitionState,
    t2_state: TransitionState,
    t3_state: TransitionState,
) -> int:
    """Phase 1 验收：返回首个三者 committed_end 分叉的 window_index。

    三个 state 应为同一初始 state 各自走 policy 后的快照。若三者 committed_end
    全部相等返回 -1（未分叉）；否则返回各快照的 window_index 最小值（三者应一致）。
    """
    ends = (t1_state.committed_end_exclusive, t2_state.committed_end_exclusive, t3_state.committed_end_exclusive)
    if len(set(ends)) == 1:
        return -1
    return min(t1_state.window_index, t2_state.window_index, t3_state.window_index)
