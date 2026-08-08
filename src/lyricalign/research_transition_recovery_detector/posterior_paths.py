"""P 信号：posterior competing coherent path（11 计划 D5）。

从完整 boundary posterior 做单一冻结算法：k-best monotonic beam DP。
对同一 request 的 boundary slots（每个 unit 的 start/end 各一 slot），
找 best/second-best 连续单调路径（timestep class 单调不减），输出：
best/second path score、normalized gap、displacement、differing-slot fraction、
longest alternate run、continuity、global-shift indicator、occurrence-mode separation。
n_P_rows == n_R_rows（每 unit 一行，用其 start slot 的 path 状态）。
"""
from __future__ import annotations

import heapq


def _beam_paths(probs, *, k: int = 2) -> list[dict]:
    """probs: (n_slots, n_classes) 每 slot 的 softmax。

    单调约束：path class 序列非递减。k-best beam DP（经典 Viterbi 变体）。
    返回 k 条 path（score 降序），每条约 {classes, score, logits}。
    """
    import math

    n_slots, n_classes = probs.shape
    beam_width = max(k * 3, 6)
    beams: list[tuple[float, list[int], int]] = [(0.0, [], -1)]  # (logscore, classes, last_class)
    for slot in range(n_slots):
        new_beams: list[tuple[float, list[int], int]] = []
        for score, classes, last in beams:
            for c in range(n_classes):
                if c < last:
                    continue  # 单调约束
                logit = float(probs[slot, c])
                if logit <= 0:
                    continue
                heapq.heappush(new_beams, (score + math.log(logit), classes + [c], c))
        beams = heapq.nlargest(beam_width, new_beams, key=lambda x: x[0])
    seen: set[tuple[int, ...]] = set()
    out = []
    for score, classes, _ in sorted(beams, key=lambda x: -x[0]):
        key = tuple(classes)
        if key in seen:
            continue
        seen.add(key)
        out.append({"classes": classes, "score": float(score)})
        if len(out) >= k:
            break
    return out


def competing_path_features(probs, *, k: int = 2) -> dict:
    """对单 request 的完整 posterior 计算 P 特征（聚合到 unit 行用 start-slot 状态）。"""
    import math

    n_slots, n_classes = probs.shape
    paths = _beam_paths(probs, k=max(k * 4, 8))
    if not paths:
        return {"status": "insufficient_paths", "n_slots": n_slots, "n_classes": n_classes}
    best = paths[0]
    b = best["classes"]
    n = len(b)
    # diversity 过滤：second = 与 best Hamming 距离 >= ceil(n/2) 的最高分路径；
    # 不存在则说明 posterior 无真正 alternate path（P=无歧义，非缺失）。
    second = None
    for cand in paths[1:]:
        d = sum(1 for i in range(n) if cand["classes"][i] != b[i])
        if d >= (n + 1) // 2:
            second = cand
            break
    if second is None:
        return {"status": "ok", "n_slots": n_slots, "n_classes": n_classes,
                "best_path_score": round(best["score"], 4),
                "second_path_diverse": False, "differing_slot_fraction": 0.0,
                "longest_alternate_run": 0, "global_shift": False,
                "occurrence_mode_separation": False, "local_ambiguity": 0.0,
                "normalized_score_gap": None, "mean_time_shift_classes": 0.0}
    s = second["classes"]
    n = len(b)
    diff_slots = sum(1 for i in range(n) if b[i] != s[i])
    # longest contiguous alternate run（second path 连续不同的最长段）
    longest_run = cur = 0
    for i in range(n):
        if b[i] != s[i]:
            cur += 1
            longest_run = max(longest_run, cur)
        else:
            cur = 0
    # global shift：second path 是否近似整体平移（多数 slot 差 == 众数差）
    from collections import Counter

    diffs = [s[i] - b[i] for i in range(n)]
    shift_counter = Counter(diffs)
    dominant_shift, dominant_count = shift_counter.most_common(1)[0] if diffs else (0, 0)
    global_shift = bool(dominant_count >= 0.8 * n) and abs(dominant_shift) > 0
    # occurrence-mode separation：best/second 的边界时间差（以 class 差 × segment_sec 近似）
    # 用 mean class 差作为 time displacement 代理（segment_sec 由调用方解释）
    mean_shift = sum(diffs) / max(n, 1)
    normalized_gap = (best["score"] - second["score"]) / max(abs(best["score"]), 1e-9)
    second_continuity = 1.0 - longest_run / max(n, 1)
    return {
        "status": "ok",
        "second_path_diverse": True,
        "best_path_score": round(best["score"], 4),
        "second_path_score": round(second["score"], 4),
        "normalized_score_gap": round(normalized_gap, 4),
        "mean_time_shift_classes": round(mean_shift, 3),
        "differing_slot_fraction": round(diff_slots / max(n, 1), 4),
        "longest_alternate_run": longest_run,
        "second_path_continuity": round(second_continuity, 4),
        "global_shift": global_shift,
        "dominant_shift_classes": int(dominant_shift),
        "occurrence_mode_separation": bool(global_shift and abs(dominant_shift) >= n * 0.5),
        "local_ambiguity": round(min(
            (sum(1 for i in range(n) if abs(diffs[i]) > 0)) / max(n, 1), 1.0), 4),
    }


def unit_p_features(probs, slot_to_unit: list[int], *, k: int = 2) -> list[dict]:
    """每个 unit 一行：用该 unit 的 start slot 对应的 path 状态（best class、second class）。

    slot_to_unit: 每 slot 归属的 unit index（同一 unit 的 start/end 两个 slot）。
    返回 list（长度 = max(unit index)+1），每项含 best/second class 与占位 P 特征
    （跨 slot 的 path 特征由 competing_path_features 在 request 级聚合，
    此处提供 unit 级 ambiguity：start slot 的 top2 差距）。
    """
    n_units = max(slot_to_unit) + 1 if slot_to_unit else 0
    out = []
    for u in range(n_units):
        slots = [i for i, su in enumerate(slot_to_unit) if su == u]
        start_slot = slots[0] if slots else None
        if start_slot is None or start_slot >= probs.shape[0]:
            out.append({"canonical_id": u, "status": "missing_slot"})
            continue
        row = probs[start_slot]
        order = row.argsort().tolist()[::-1]
        best_c, second_c = int(order[0]), int(order[1])
        out.append({
            "canonical_id": u,
            "best_class": best_c,
            "second_class": second_c,
            "top2_gap": round(float(row[best_c] - row[second_c]), 4),
        })
    return out
