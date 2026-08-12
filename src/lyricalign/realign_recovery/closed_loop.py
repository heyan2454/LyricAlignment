"""E9 closed-loop 核心纯函数（raw-triggered realign/recovery）。

本模块只包含 side-effect free 的纯函数：不导入 GPU / 模型 / I/O 依赖，
可在纯 CPU 合成数据上单测。

模块约定
--------
- 字段名规避 FORBIDDEN_FEATURE_FIELDS 单字面（safe/unsafe/grey/family/label/
  error_magnitude 等），只使用连词形式的聚合键（如 ``repair_success``、
  ``safe_damage``），避免污染特征字段命名空间。
- ``schema_version`` 固定为 ``closed_loop_route_plan.v1``。
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "closed_loop_route_plan.v1"

# 每类 route 的固定规格：baseline 级 needs_forward 与 selective-writeback 策略。
# C2/C3 的 needs_forward 是否为 True 还需按 episode 是否含 continuation 窗口判定
# （见 ``build_route_plan``），因此这里只是 baseline。
ROUTE_SPECS: dict[str, dict[str, Any]] = {
    "C0": {"needs_forward": False, "writeback_strategy": "none"},
    "C0S": {"needs_forward": False, "writeback_strategy": "none"},
    "C1": {"needs_forward": False, "writeback_strategy": "none"},
    "C2": {"needs_forward": True, "writeback_strategy": "full"},
    "C3": {"needs_forward": True, "writeback_strategy": "improved_only"},
}

TRIGGER_STATES = ("accept", "uncertain", "reject")


def _serial_is_error(marker: str) -> bool:
    """把每窗口标记归一化为布尔错误标记；``unsafe`` 与 ``error`` 等价。"""
    if marker == "clean":
        return False
    if marker in ("error", "unsafe"):
        return True
    raise ValueError(f"unknown serial state marker: {marker!r}")


def classify_serial_recovery(window_states: list[str]) -> str:
    """对每窗口错误标记序列做五分类恢复形态判定。

    输入
    ----
    window_states : 每窗口二元/三态错误标记序列。合法元素为
        ``"clean"``（干净）与 ``"error"``（错误）；也接受 ``"unsafe"``，
        其与 ``"error"`` 等价。空序列与全 ``"clean"`` 不报错。

    判定规则（按优先级从高到低，命中即返回）
    --------
    1. ``"no_error"``：序列为空或全部窗口为 clean。
    2. ``"occurrence_jump"``：error 位置不连续（存在至少一个 clean 窗口
       严格夹在两个 error 窗口之间）。
    3. ``"amplifying"``：error 构成连续块且延伸到序列末尾（最后一个窗口
       为 error），且错误块长度 >= 2 —— 即错误数量随窗口单调不降地增长到
       结尾（cumulative error count 无下降、末窗口为 error）。
    4. ``"persistent"``：error 构成连续块、延伸到序列末尾，但错误块只有
       单窗口（错误从某个窗口起持续到最后一个窗口，未进一步加剧）。
    5. ``"slow_recover"``：error 连续块结束后仍有 clean 窗口收尾（最后
       一个 error 之后至少 1 个 clean），且错误块长度 >= 2。
    6. ``"self_recover"``：error 连续块结束后仍有 clean 收尾，且错误块
       只有单窗口（首个 error 之后所有窗口均 clean，不再 error）。

    返回 ``no_error`` 之外的类别为五分类：``self_recover`` /
    ``slow_recover`` / ``persistent`` / ``amplifying`` / ``occurrence_jump``。
    """
    flags = [_serial_is_error(m) for m in window_states]
    error_pos = [i for i, is_err in enumerate(flags) if is_err]
    if not error_pos:
        return "no_error"
    if error_pos != list(range(error_pos[0], error_pos[-1] + 1)):
        return "occurrence_jump"
    block_start, block_end = error_pos[0], error_pos[-1]
    block_len = block_end - block_start + 1
    last_index = len(window_states) - 1
    if block_end == last_index:
        return "amplifying" if block_len >= 2 else "persistent"
    return "slow_recover" if block_len >= 2 else "self_recover"


def _episode_id_of(row: dict) -> Any:
    """取 episode 标识：优先顶层 ``episode_id``，回退 ``provenance.episode_id``。"""
    episode_id = row.get("episode_id")
    if episode_id is None:
        provenance = row.get("provenance")
        if isinstance(provenance, dict):
            episode_id = provenance.get("episode_id")
    return episode_id


def _episode_has_continuation(episode_requests: list[dict]) -> bool:
    """episode 是否含 continuation 窗口（需要 forward 一次以上）。

    判定：同一 episode 有 >=2 条 REQUESTS 行，或任一 request 的
    ``input_variant`` 含 ``cont`` / ``forward`` 字样（大小写不敏感）。
    """
    if len(episode_requests) >= 2:
        return True
    for req in episode_requests:
        variant = str(req.get("input_variant", "")).lower()
        if "cont" in variant or "forward" in variant:
            return True
    return False


def build_route_plan(bank_rows: list[dict], requests: list[dict]) -> dict:
    """为每个 episode 构建五条 route（C0/C0S/C1/C2/C3）的运行计划。

    输入
    ----
    bank_rows : E5 candidate bank 行，字段含 ``ownership``（仅
        ``"e5_proposal"`` 计入 candidate evidence）、``raw_output_path``、
        ``status``、``episode_id``（缺省回退 ``provenance.episode_id``）。
    requests  : REQUESTS 行，字段含 ``provenance.episode_id``、
        ``input_variant``。

    输出结构
    --------
    ``{"schema_version", "routes", "per_episode", "n_episodes", "n_routes"}``

    - ``routes``：五条 route 的固定规格，``{"id", "needs_forward", "writeback_strategy"}``。
    - ``per_episode[episode_id][route]``：每 episode 每 route 的实例化结果，
      含 ``needs_forward``（C0/C0S/C1 恒为 False，复用 baseline evidence；
      C2/C3 仅当该 episode 有 continuation 窗口时 True）、
      ``writeback_strategy``（selective writeback 策略）、candidate 统计。
    - ``n_episodes``：bank/requests 中 episode 并集数量。
    - ``n_routes``：生成的 route 实例总数，恒为 ``5 * n_episodes``。
    """
    e5_rows = [r for r in bank_rows if r.get("ownership") == "e5_proposal"]
    by_ep_bank: dict[Any, list[dict]] = {}
    for row in e5_rows:
        by_ep_bank.setdefault(_episode_id_of(row), []).append(row)
    by_ep_req: dict[Any, list[dict]] = {}
    for req in requests:
        by_ep_req.setdefault(_episode_id_of(req), []).append(req)

    episode_ids = sorted({ep for ep in by_ep_bank if ep is not None} | {ep for ep in by_ep_req if ep is not None})

    routes = {
        rid: {"id": rid, "needs_forward": spec["needs_forward"], "writeback_strategy": spec["writeback_strategy"]}
        for rid, spec in ROUTE_SPECS.items()
    }

    per_episode: dict[Any, dict[str, dict[str, Any]]] = {}
    for ep in episode_ids:
        ep_reqs = by_ep_req.get(ep, [])
        ep_bank = by_ep_bank.get(ep, [])
        continuation = _episode_has_continuation(ep_reqs)
        per_episode[ep] = {}
        for rid, spec in ROUTE_SPECS.items():
            per_episode[ep][rid] = {
                "route": rid,
                "needs_forward": bool(spec["needs_forward"] and continuation),
                "writeback_strategy": spec["writeback_strategy"],
                "n_candidates": len(ep_bank),
                "candidate_paths": [b.get("raw_output_path") for b in ep_bank if b.get("raw_output_path")],
                "n_requests": len(ep_reqs),
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "routes": routes,
        "per_episode": per_episode,
        "n_episodes": len(episode_ids),
        "n_routes": 5 * len(episode_ids),
    }


def route_decision(
    route: str,
    trigger_state: str,
    score_delta: float | None,
    *,
    safe_threshold_sec: float = 1.0,
) -> dict:
    """单窗口的 route 决策纯函数。

    输入
    ----
    route          : ``C0`` / ``C0S`` / ``C1`` / ``C2`` / ``C3``。
    trigger_state  : frozen tristate，``accept | uncertain | reject``。
    score_delta    : detector p_bad 改善信号（正 = 候选更好）；可为 None。
    safe_threshold_sec : 保留参数，供后续窗口边界安全边际使用；本版
        C0–C3 决策逻辑不消费该值。

    决策（C0–C3）
    --------
    - C0 ：``{"action": "none", "writeback": False}``（无 detector 效果）。
    - C0S：``{"action": "shadow_only", "trigger": trigger_state != "accept",
      "writeback": False}``（只记录不写回）。
    - C1 ：trigger（``trigger_state != "accept"``）时 hold（不写回坏 commit），
      否则 ``commit_original``；均不写回。
    - C2 ：无条件写回（危险对照）。
    - C3 ：quality gate + selective，仅当 ``score_delta > 0`` 时
      ``selective_writeback``，否则 hold。

    非法 route 抛 ``ValueError``。
    """
    if trigger_state not in TRIGGER_STATES:
        raise ValueError(f"unknown trigger state: {trigger_state!r}")
    triggered = trigger_state != "accept"

    if route == "C0":
        return {"action": "none", "writeback": False}
    if route == "C0S":
        return {"action": "shadow_only", "trigger": triggered, "writeback": False}
    if route == "C1":
        if triggered:
            return {"action": "hold", "trigger": True, "writeback": False}
        return {"action": "commit_original", "trigger": False, "writeback": False}
    if route == "C2":
        return {"action": "unconditional_writeback", "writeback": True}
    if route == "C3":
        improved = score_delta is not None and score_delta > 0
        return {"action": "selective_writeback" if improved else "hold", "writeback": improved}
    raise ValueError(f"unknown route: {route!r}")


def aggregate_route_cost(rows: list[dict]) -> dict:
    """route 运行成本聚合。

    ``rows`` 每项含 ``{"extra_forwards": int, "processed_audio_sec": float,
    "retry_count": int, "cache_hit": bool}``。

    ``mean_wall_multiplier`` 由 ``total_audio_sec`` 比例估算：等效计算量
    为 ``processed_audio_sec * (1 + extra_forwards)``，以 ``total_audio_sec``
    为基准求加权平均；无基准（``total_audio_sec == 0``）时返回 None。
    """
    n = len(rows)
    total_extra_forwards = sum(int(r.get("extra_forwards", 0)) for r in rows)
    total_audio_sec = sum(float(r.get("processed_audio_sec", 0.0)) for r in rows)
    total_retries = sum(int(r.get("retry_count", 0)) for r in rows)
    cache_hits = sum(1 for r in rows if r.get("cache_hit"))
    if total_audio_sec > 0:
        effective = sum(
            float(r.get("processed_audio_sec", 0.0)) * (1 + int(r.get("extra_forwards", 0))) for r in rows
        )
        mean_wall_multiplier = effective / total_audio_sec
    else:
        mean_wall_multiplier = None
    return {
        "total_extra_forwards": total_extra_forwards,
        "total_audio_sec": total_audio_sec,
        "mean_wall_multiplier": mean_wall_multiplier,
        "total_retries": total_retries,
        "cache_hit_rate": (cache_hits / n) if n else 0.0,
        "n": n,
    }


def aggregate_repair_metrics(rows: list[dict]) -> dict:
    """repair 区域指标聚合。

    ``rows`` 每项含 ``{"repair_success": bool, "safe_damage": bool,
    "harmful_writeback": bool}``；返回各指标比例与样本数。
    """
    n = len(rows)

    def rate(key: str) -> float:
        return (sum(1 for r in rows if r.get(key)) / n) if n else 0.0

    return {
        "n": n,
        "repair_success_rate": rate("repair_success"),
        "safe_damage_rate": rate("safe_damage"),
        "harmful_writeback_rate": rate("harmful_writeback"),
    }


def build_shrink_candidates(fail_rows: list[dict], *, max_retries: int = 2) -> dict:
    """生成 E10/C4 缩窗候选。

    ``fail_rows`` 每项含 ``{"episode_id", "window_index"}``。按 episode
    分组；每个失败窗口生成至多 ``max_retries`` 个候选（``retry_index``
    从 0 递增），每个候选均缩半窗，且奇数 retry_index 启用 alternate
    anchor（``alternate_anchor = retry_index % 2 == 1``）。

    返回 ``{"n_episodes", "n_retries_total", "candidates"}``。
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")
    grouped: dict[Any, list[dict]] = {}
    for row in fail_rows:
        grouped.setdefault(row["episode_id"], []).append(row)

    candidates: list[dict[str, Any]] = []
    for ep in sorted(grouped):
        for row in grouped[ep]:
            for retry_index in range(max_retries):
                candidates.append(
                    {
                        "episode_id": row["episode_id"],
                        "window_index": row["window_index"],
                        "retry_index": retry_index,
                        "shrink": {"half_window": True, "alternate_anchor": (retry_index % 2 == 1)},
                    }
                )

    return {
        "n_episodes": len(grouped),
        "n_retries_total": len(candidates),
        "candidates": candidates,
    }
