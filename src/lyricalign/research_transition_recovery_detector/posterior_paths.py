"""P 信号：posterior competing coherent path（11 计划 D5）。

从完整 boundary posterior 做单一冻结算法：exact k-best monotonic DP
（无固定宽度 beam）。对同一 request 的 boundary slots（每个 unit 的
start/end 各一 slot），在单调约束（path class 序列非递减）下求 top-k 路径，
再按 min_changed_slots（默认 1）选取真正 distinct 的 second path，输出：
best/second path score、normalized gap、displacement、differing-slot fraction、
longest alternate run、continuity、global-shift indicator 等 request-level
特征与 unit-level 局部特征。n_P_rows == n_R_rows（每 unit 一行，用其
start slot 的 path 状态）。

状态分类：ok（存在满足 min_changed_slots 的 distinct second path）/
unique_posterior（全请求只有唯一一条单调路径，无任何 distinct second）/
no_distinct_path_under_constraints（存在多条路径但均不满足约束）/
no_monotone_path（输入合法但不存在任何单调时间路径，后验时间戳错乱/回退）/
invalid_input / algorithm_failure。

设计要点：
- 每 slot 每 class 保存 top-k 前驱 backpointer；对固定 (slot, class) 前缀，
  续接增量只依赖末 class，故非 top-k 前缀不可能属于全局 top-k 完整路径，
  逐状态保留 top-k 即全局 k-best 精确（经典 k-best Viterbi）。
- 零概率 class 不进路径（与旧 beam 行为一致）。
- 50% diversity 不再是硬 gate：second 只需 >= min_changed_slots 个 slot 与
  best 不同；differing_slot_fraction 作为分析字段保留。
"""
from __future__ import annotations

import heapq
import math
import statistics
from collections import Counter

import numpy as np


def _kbest_paths(probs, *, k: int = 2, top_n: int = 32) -> list[dict]:
    """probs: (n_slots, n_classes) 每 slot 的 softmax。

    单调约束：path class 序列非递减（跨 slot timestep 单调不减）。
    exact k-best monotonic DP：每 slot 每 class 保存 top-k 前驱 backpointer，
    不用固定宽度 beam。返回至多 k 条 path（score 降序），每条
    {classes, score}。零概率 class 不可进入路径。

    top_n：每 slot 只考虑概率 top-N 的 class（显著后验）；top-N 之外的 class
    概率极低，无法进入全局 top-k 路径。默认 32 覆盖真实 posterior 的显著
    class（中位 ~47，但 top-32 通常已含 >99.9% 概率质量）。
    """
    n_slots, n_classes = probs.shape
    if n_slots <= 0 or n_classes <= 0:
        return []
    k = max(int(k), 1)
    top_n = max(int(top_n), 1)

    # 每 slot 的显著 class 列表（top-N，按概率降序；仅保留 >0）
    candidates: list[list[tuple[int, float]]] = []
    for slot in range(n_slots):
        row = probs[slot]
        idx = np.argsort(row)[::-1][:top_n]
        pairs = [(int(i), float(row[i])) for i in idx if float(row[i]) > 0.0]
        candidates.append(pairs)

    # dp[c] = 当前 slot 以 class c 结尾的 top-k (score, path tuple)
    dp: list[list[tuple[float, tuple[int, ...]]]] = [[] for _ in range(n_classes)]
    for c, p in candidates[0]:
        dp[c].append((math.log(p), (c,)))
    for slot in range(1, n_slots):
        ndp: list[list[tuple[float, tuple[int, ...]]]] = [[] for _ in range(n_classes)]
        for c, p in candidates[slot]:
            inc = math.log(p)
            cands: list[tuple[float, tuple[int, ...]]] = []
            for pc in range(c + 1):  # 单调：前驱 class <= 当前 class
                for score, path in dp[pc]:
                    cands.append((score + inc, path + (c,)))
            if cands:
                ndp[c] = heapq.nlargest(k, cands, key=lambda x: x[0])
        dp = ndp
    final: list[tuple[float, tuple[int, ...]]] = []
    for lst in dp:
        final.extend(lst)
    final = heapq.nlargest(k, final, key=lambda x: x[0])
    return [{"classes": list(cls), "score": float(score)} for score, cls in final]


def _select_second(paths: list[dict], *, min_changed_slots: int = 1) -> dict | None:
    """从按 score 降序的路径列表中选第一条与 best 差异 >= min_changed_slots 的路径。"""
    if len(paths) < 2:
        return None
    best = paths[0]
    b = list(best["classes"])
    n = len(b)
    for cand in paths[1:]:
        d = sum(1 for i in range(n) if cand["classes"][i] != b[i])
        if d >= min_changed_slots:
            return cand
    return None


def competing_path_features(probs, *, k: int = 2, min_changed_slots: int = 1,
                            top_n: int = 32) -> dict:
    """对单 request 的完整 posterior 计算 P 特征。

    probs: (n_slots, n_classes) float32。返回 dict 含 status、best/second path
    score、normalized_score_gap、has_distinct_second_path、differing_slot_fraction、
    max/median_time_displacement、longest_alternate_run、global_shift_like，
    以及向后兼容的旧字段（second_path_diverse、mean_time_shift_classes、
    second_path_continuity、global_shift、dominant_shift_classes、
    occurrence_mode_separation、local_ambiguity）。
    """
    try:
        arr = np.asarray(probs, dtype=np.float32)
        n_slots, n_classes = arr.shape
        if arr.ndim != 2 or n_slots <= 0 or n_classes <= 0:
            return {"status": "invalid_input", "n_slots": n_slots, "n_classes": n_classes}
        if not np.all(np.isfinite(arr)) or np.any(arr < 0) or np.any(arr.sum(axis=1) <= 0):
            return {"status": "invalid_input", "n_slots": n_slots, "n_classes": n_classes}
    except Exception:
        return {"status": "invalid_input"}
    try:
        paths = _kbest_paths(arr, k=max(int(k) * 4, 8), top_n=top_n)
    except Exception:
        return {"status": "algorithm_failure", "n_slots": n_slots, "n_classes": n_classes}
    if not paths:
        # 输入合法但不存在任何单调（时间非递减）路径：后验时间戳剧烈错乱/回退
        return {"status": "no_monotone_path", "n_slots": n_slots, "n_classes": n_classes,
                "has_distinct_second_path": False}

    best = paths[0]
    b = list(best["classes"])
    n = len(b)
    second = _select_second(paths, min_changed_slots=min_changed_slots)

    base = {
        "status": "ok",
        "n_slots": n_slots,
        "n_classes": n_classes,
        "best_path_score": round(best["score"], 4),
        "best_path_classes": b,
        "min_changed_slots": min_changed_slots,
    }
    if second is None:
        if len(paths) == 1:
            status = "unique_posterior"
        else:
            status = "no_distinct_path_under_constraints"
        return {
            **base, "status": status,
            "has_distinct_second_path": False,
            "second_path_score": None,
            "second_path_classes": None,
            "normalized_score_gap": None,
            "differing_slot_fraction": 0.0,
            "max_time_displacement": 0,
            "median_time_displacement": 0,
            "longest_alternate_run": 0,
            "global_shift_like": False,
            "second_path_diverse": False,
            "mean_time_shift_classes": 0.0,
            "second_path_continuity": 1.0,
            "global_shift": False,
            "dominant_shift_classes": 0,
            "occurrence_mode_separation": False,
            "local_ambiguity": 0.0,
        }

    s = list(second["classes"])
    diff_slots = sum(1 for i in range(n) if b[i] != s[i])
    diffs = [s[i] - b[i] for i in range(n)]
    abs_diffs = [abs(d) for d in diffs]
    longest_run = cur = 0
    for i in range(n):
        if b[i] != s[i]:
            cur += 1
            longest_run = max(longest_run, cur)
        else:
            cur = 0
    shift_counter = Counter(diffs)
    dominant_shift, dominant_count = shift_counter.most_common(1)[0] if diffs else (0, 0)
    global_shift = bool(dominant_count >= 0.8 * n) and abs(dominant_shift) > 0
    mean_shift = sum(diffs) / max(n, 1)
    normalized_gap = (best["score"] - second["score"]) / max(abs(best["score"]), 1e-9)
    second_continuity = 1.0 - longest_run / max(n, 1)
    return {
        **base, "status": "ok",
        "has_distinct_second_path": True,
        "second_path_score": round(second["score"], 4),
        "second_path_classes": s,
        "normalized_score_gap": round(normalized_gap, 4),
        "differing_slot_fraction": round(diff_slots / max(n, 1), 4),
        "max_time_displacement": int(max(abs_diffs)) if abs_diffs else 0,
        "median_time_displacement": round(float(statistics.median(abs_diffs)), 3),
        "longest_alternate_run": longest_run,
        "global_shift_like": bool(global_shift),
        "second_path_diverse": True,
        "mean_time_shift_classes": round(mean_shift, 3),
        "second_path_continuity": round(second_continuity, 4),
        "global_shift": bool(global_shift),
        "dominant_shift_classes": int(dominant_shift),
        "occurrence_mode_separation": bool(global_shift and abs(dominant_shift) >= n * 0.5),
        "local_ambiguity": round(diff_slots / max(n, 1), 4),
    }


def unit_p_features(probs, slot_to_unit: list[int], *, k: int = 2, top_n: int = 32) -> list[dict]:
    """每个 unit 一行：用该 unit 的 start slot 对应的 path 状态。

    slot_to_unit: 每 slot 归属的 unit index（同一 unit 的 start/end 两个 slot）。
    返回 list（长度 = max(unit index)+1），每项含 canonical_id / status /
    best_class / second_class / top2_gap，以及 unit 级局部 P 特征：
    local_second_path_gap（unit 本地 best/second path 的 normalized score gap）、
    local_boundary_disagreement（unit 的 start/end 两个边界 slot 的 best class
    是否不一致）、local_alternate_run_membership（start slot 是否落入 second
    path 与 best 的差异段）、local_displacement（start slot 上 second-best
    class 差，即 local boundary 的候选位移）。
    """
    arr = np.asarray(probs, dtype=np.float32)
    n_units = max(slot_to_unit) + 1 if slot_to_unit else 0
    n_slots, n_classes = arr.shape
    paths = _kbest_paths(arr, k=max(int(k) * 4, 8), top_n=top_n) if arr.size else []
    best = paths[0] if paths else None
    second = _select_second(paths, min_changed_slots=1)

    def _unit_local_gap(u: int, slots: list[int]) -> float | None:
        if best is None or second is None:
            return None
        b = list(best["classes"])
        s = list(second["classes"])
        b_loc = sum(math.log(float(arr[i, b[i]])) for i in slots
                    if i < len(b) and float(arr[i, b[i]]) > 0.0)
        s_loc = sum(math.log(float(arr[i, s[i]])) for i in slots
                    if i < len(s) and float(arr[i, s[i]]) > 0.0)
        denom = max(abs(b_loc), 1e-9)
        return round((b_loc - s_loc) / denom, 4)

    out = []
    for u in range(n_units):
        slots = [i for i, su in enumerate(slot_to_unit) if su == u]
        start_slot = slots[0] if slots else None
        if start_slot is None or start_slot >= n_slots:
            out.append({"canonical_id": u, "status": "missing_slot"})
            continue
        row = arr[start_slot]
        order = np.argsort(row)[::-1]
        best_c = int(order[0]) if order.size else None
        second_c = int(order[1]) if order.size > 1 else None
        row_best = float(row[best_c]) if best_c is not None else None
        row_second = float(row[second_c]) if second_c is not None else None
        top2_gap = (round(row_best - row_second, 4)
                    if row_best is not None and row_second is not None else None)
        end_slot = slots[-1] if len(slots) > 1 else None
        boundary_disagreement = False
        if best is not None and end_slot is not None and end_slot < n_slots:
            boundary_disagreement = bool(
                best["classes"][start_slot] != best["classes"][end_slot])
        alt_membership = False
        local_displacement = 0
        if best is not None and second is not None and start_slot < len(best["classes"]):
            alt_membership = bool(
                second["classes"][start_slot] != best["classes"][start_slot])
            local_displacement = int(
                second["classes"][start_slot] - best["classes"][start_slot])
        out.append({
            "canonical_id": u,
            "status": "ok",
            "best_class": best_c,
            "second_class": second_c,
            "top2_gap": top2_gap,
            "local_second_path_gap": _unit_local_gap(u, slots),
            "local_boundary_disagreement": boundary_disagreement,
            "local_alternate_run_membership": alt_membership,
            "local_displacement": local_displacement,
        })
    return out
