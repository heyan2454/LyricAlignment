"""Phase 6：确定性 Detector 工作点（SA60/SA80/R95，07 §5）。

阈值函数全部纯函数；候选阈值来自唯一 p_bad 值 + 0/1 边界，
要求 0 <= T_accept < T_reject <= 1。
"""

from __future__ import annotations

from typing import Iterable

STATE_ACCEPT = "ACCEPT"
STATE_REJECT = "REJECT"
STATE_UNCERTAIN = "UNCERTAIN"


def candidate_thresholds(p_bad: Iterable[float], *, max_unique: int = 200) -> list[tuple[float, float]]:
    """唯一 p_bad 值（分位数抽样，上限 max_unique）+ 0/1 边界，去重并保证 0 <= T_accept < T_reject <= 1。

    07 §5 要求候选阈值来自唯一 p_bad 值；p_bad 值过多时（>max_unique）按分位数均匀抽样，
    保持阈值覆盖分布，避免候选网格爆炸（记录在 FROZEN_WORKING_POINTS 的分位近似说明）。
    """
    values = sorted({round(float(v), 10) for v in p_bad})
    values = [v for v in values if 0.0 < v < 1.0]
    if len(values) > max_unique:
        import math

        step = len(values) / max_unique
        values = [values[min(len(values) - 1, int(math.floor(i * step)))] for i in range(max_unique)]
        values = sorted(set(values))
    candidates: list[tuple[float, float]] = []
    for ta in [0.0, *values]:
        for tr in [*values, 1.0]:
            if 0.0 <= ta < tr <= 1.0:
                candidates.append((round(ta, 10), round(tr, 10)))
    return sorted(set(candidates))


def tristate_labels(p_bad: float, t_accept: float, t_reject: float) -> str:
    """三态判定：ACCEPT if p_bad < t_accept；REJECT if p_bad >= t_reject；其余 UNCERTAIN。

    边界采用半开语义（REJECT 含等号），保证 p_bad 恰在候选阈值上时
    REJECT 仍可触发（否则 max p_bad 落在阈值上时 R95 永远不可达）。
    """
    if p_bad < t_accept:
        return STATE_ACCEPT
    if p_bad >= t_reject:
        return STATE_REJECT
    return STATE_UNCERTAIN


def working_point_metrics(labels_gt: list[tuple[str, int]]) -> dict:
    """labels_gt = [(tristate, gt)]；gt 1=unsafe 0=safe。UNCERTAIN 不计 REJECT。"""
    counts = {"safe_accept": 0, "safe_reject": 0, "unsafe_accept": 0, "unsafe_reject": 0,
              "uncertain": 0, "safe_total": 0, "unsafe_total": 0, "grey": 0}
    for state, gt in labels_gt:
        if state == STATE_UNCERTAIN:
            counts["uncertain"] += 1
            counts["grey"] += 1
            continue
        if gt is None:
            continue
        if state == STATE_ACCEPT:
            if gt == 0:
                counts["safe_accept"] += 1
                counts["safe_total"] += 1
            else:
                counts["unsafe_accept"] += 1
                counts["unsafe_total"] += 1
        else:  # REJECT
            if gt == 0:
                counts["safe_reject"] += 1
                counts["safe_total"] += 1
            else:
                counts["unsafe_reject"] += 1
                counts["unsafe_total"] += 1
    safe_den = max(counts["safe_total"], 1)
    unsafe_den = max(counts["unsafe_total"], 1)
    return {
        "safe_accept": counts["safe_accept"] / safe_den,
        "safe_reject": counts["safe_reject"] / safe_den,
        "unsafe_accept": counts["unsafe_accept"] / unsafe_den,
        "unsafe_reject": counts["unsafe_reject"] / unsafe_den,
        "uncertain_rate": counts["uncertain"] / max(counts["uncertain"] + counts["safe_total"] + counts["unsafe_total"], 1),
        "safe_denominator": counts["safe_total"],
        "unsafe_denominator": counts["unsafe_total"],
        "grey_denominator": counts["grey"],
    }


def _evaluate(p_bad: list[float], gt: list[int | None], t_accept: float, t_reject: float) -> dict:
    labels_gt = [
        (tristate_labels(float(p), t_accept, t_reject), g)
        for p, g in zip(p_bad, gt, strict=True)
    ]
    m = working_point_metrics(labels_gt)
    return {
        "t_accept": round(t_accept, 10),
        "t_reject": round(t_reject, 10),
        **{k: round(v, 6) for k, v in m.items() if isinstance(v, float)},
        "safe_denominator": m["safe_denominator"],
        "unsafe_denominator": m["unsafe_denominator"],
    }


def select_working_point(
    p_bad: list[float],
    gt: list[int | None],
    *,
    constraint: str,
    level: float,
) -> dict:
    """constraint: 'SA60'|'SA80'|'R95'。tie-break 按 07 §5。"""
    candidates = candidate_thresholds(p_bad)
    results = [_evaluate(p_bad, gt, ta, tr) for ta, tr in candidates]
    if constraint in ("SA60", "SA80"):
        target_sa = 0.60 if constraint == "SA60" else 0.80
        feasible = [r for r in results if r["safe_accept"] >= target_sa]
        feasible.sort(key=lambda r: (
            r["unsafe_accept"], -r["unsafe_reject"], r["safe_reject"], r["uncertain_rate"],
            (r["t_reject"] - r["t_accept"]), r["t_accept"], r["t_reject"],
        ))
    elif constraint == "R95":
        feasible = [r for r in results if r["unsafe_reject"] >= level]
        feasible.sort(key=lambda r: (
            -r["safe_accept"], r["unsafe_accept"], r["safe_reject"], r["uncertain_rate"],
            (r["t_reject"] - r["t_accept"]), r["t_accept"], r["t_reject"],
        ))
    else:
        raise ValueError(f"unknown constraint {constraint}")
    if not feasible:
        return {"constraint": constraint, "level": level, "feasible": False,
                "safe_denominator": results[0]["safe_denominator"] if results else 0,
                "unsafe_denominator": results[0]["unsafe_denominator"] if results else 0}
    best = feasible[0]
    return {"constraint": constraint, "level": level, "feasible": True, **best}


def joint_working_point(
    p_bad: list[float],
    gt: list[int | None],
    *,
    sa_level: float = 0.60,
    r95_level: float = 0.95,
) -> dict:
    """SA60+R95 联合；不可行输出 Pareto gap 摘要。"""
    candidates = candidate_thresholds(p_bad)
    results = [_evaluate(p_bad, gt, ta, tr) for ta, tr in candidates]
    joint = [
        r for r in results
        if r["safe_accept"] >= sa_level and r["unsafe_reject"] >= r95_level
    ]
    if joint:
        joint.sort(key=lambda r: (
            r["unsafe_accept"], r["safe_reject"], r["uncertain_rate"],
            (r["t_reject"] - r["t_accept"]), r["t_accept"], r["t_reject"],
        ))
        return {"feasible": True, **joint[0]}
    best_sa = max(results, key=lambda r: r["safe_accept"]) if results else None
    best_r95 = max(results, key=lambda r: r["unsafe_reject"]) if results else None
    return {
        "feasible": False,
        "pareto_gap": {
            "max_safe_accept": best_sa["safe_accept"] if best_sa else None,
            "at_that_unsafe_reject": best_sa["unsafe_reject"] if best_sa else None,
            "max_unsafe_reject": best_r95["unsafe_reject"] if best_r95 else None,
            "at_that_safe_accept": best_r95["safe_accept"] if best_r95 else None,
        },
    }
