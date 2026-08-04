"""WP5：region_metrics —— 判别器结果评价（15 蓝图 §6.3）。

对每个 target/domain/mutation family 输出：unit recall、correct-retained-unit FPR、
gap event recall、gap omitted-unit weighted recall、wrong-output recall、replaced-GT
omission recall、interval recall（cover_frac 阈值由调用方给定）。
review17-minor：历史宣称的 interval 双阈值、全漏检率、扩张长度等输出项均未实现，
docstring 不再宣称这些输出。
按 source-song 独立 split 报告；demo 不参与训练/阈值。
纯函数、可单测。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence


def _safe_p(r, d):
    return r / d if d else 0.0


def unit_metrics(
    *,
    total_gt_units: int,
    unsafe_pred_units: list[int],   # 被判 unsafe 的 unit 索引
    truly_unsafe_indices: set,      # 真 unsafe（identity error/boundary>250ms）
    correct_retained_units: int,    # 正确保留(trusted)的 unit 数
    total_retained_gt: int,         # 应保留的总数
) -> dict[str, float]:
    """unit recall / FPR（FP 分母 = total_retained_gt）。

    调用约定（round01 GT eval）：
    - 两侧索引必须在同一 canonical 轴上（请求文本覆盖的 canonical ids 子集）；
    - 空集情形（truly_unsafe 与 unsafe_pred 均为空）本函数返回 0/0 -> 0.0；
      调用方如需“无真 unsafe 且未误报 = 完全正确”的真空约定，请自行在外部覆盖 recall=1.0，
      本函数签名与返回值保持不变。
    """
    hit = len([u for u in unsafe_pred_units if u in truly_unsafe_indices])
    fp = len([u for u in unsafe_pred_units if u not in truly_unsafe_indices])
    fn = len([u for u in truly_unsafe_indices if u not in set(unsafe_pred_units)])
    return {
        "unit_recall": round(_safe_p(hit, len(truly_unsafe_indices)), 4),
        "correct_unit_fpr": round(_safe_p(fp, total_retained_gt), 4),
        "n_hit": hit, "n_fp": fp, "n_fn": fn,
    }


def gap_metrics(
    *,
    gt_gaps: Sequence[int],                        # 真 gap id 集
    pred_gap_ids: Sequence[int],                   # 检出的 gap id
    gt_gap_omitted: Mapping[int, Sequence[int]] | None = None,  # gap_id -> omitted canonical units
) -> dict[str, float]:
    """P0-4：gap 指标按 omitted canonical units 加权（不使用未实现/死参数 pred_gap_omitted、weighted_deleted_gt）。"""
    gtg = set(gt_gaps); pgs = set(pred_gap_ids)
    tp = len(gtg & pgs); fp = len(pgs - gtg); fn = len(gtg - pgs)
    # omitted-units 加权
    gt_units = set()
    for g, ids in (gt_gap_omitted or {}).items():
        gt_units.update(ids)
    if gt_units:
        hit_units = set()
        for g in pgs & gtg:
            hit_units.update((gt_gap_omitted or {}).get(g, ()))
        w_recall = len(hit_units & gt_units) / len(gt_units)
    else:
        w_recall = 0.0
    return {
        "gap_event_recall": round(_safe_p(tp, len(gtg)), 4),
        "gap_omitted_unit_weighted_recall": round(w_recall, 4),
        "gap_fp": fp, "gap_fn": fn,
    }


def wrong_output_metrics(
    *,
    gt_replaced: int,                     # 应为 wrong-output 的 GT replaced 数
    wrong_output_hits: int,               # 判为 wrong-output 且命中 GT replaced 的 token 数
    replaced_omission_hits: int,          # 判为“被替换 GT 遗漏”且命中 omitted-original 的候选数
    replaced_omission_gt: int,            # GT 中“原词被替代省略”的总数
) -> dict[str, float]:
    """P0-4b：wrong-output 与 replaced-omission 两个方向用独立命中量，不复用一个数。

    wrong_output_recall = wrong_output 命中 / 应标记 wrong-output 的 GT。
    replaced_gt_omission_recall = omission(被替代 GT) 候选命中 / 应标记 omission 的 GT。
    """
    return {
        "wrong_output_recall": round(_safe_p(wrong_output_hits, gt_replaced), 4),
        "replaced_gt_omission_recall": round(_safe_p(replaced_omission_hits, replaced_omission_gt), 4),
    }


def interval_recall(gt_intervals_units: Sequence[set], pred_cover: set, cover_frac: float) -> float:
    hit = sum(1 for s in gt_intervals_units if len(s & pred_cover) >= cover_frac * len(s))
    return round(_safe_p(hit, len(gt_intervals_units)), 4)


def summarize_by_split(
    per_item: Sequence[dict],
    *,
    split_field: str = "split",
    domain_field: str = "domain",
    family_field: str = "mutation_family",
) -> dict:
    """按 (split, domain, family) 汇总。per_item 已含各指标。"""
    acc: dict = defaultdict(lambda: {"unit_recall": [], "fpr": [], "gap_recall": []})
    for it in per_item:
        key = (it.get(split_field), it.get(domain_field), it.get(family_field))
        if it.get("unit_recall") is not None:
            acc[key]["unit_recall"].append(it["unit_recall"])
        if it.get("correct_unit_fpr", it.get("fpr")) is not None:
            acc[key]["fpr"].append(it.get("correct_unit_fpr", it.get("fpr")))
        if it.get("gap_event_recall", it.get("gap_recall")) is not None:
            acc[key]["gap_recall"].append(it.get("gap_event_recall", it.get("gap_recall")))
    out = {}
    for (sp, dom, fam), v in sorted(acc.items()):
        out[f"{sp}|{dom}|{fam}"] = {
            "n_items": len(v.get("unit_recall", [])),
            "unit_recall_mean": round(sum(v["unit_recall"]) / len(v["unit_recall"]), 4) if v["unit_recall"] else None,
            "fpr_mean": round(sum(v["fpr"]) / len(v["fpr"]), 4) if v["fpr"] else None,
            "gap_recall_mean": round(sum(v["gap_recall"]) / len(v["gap_recall"]), 4) if v["gap_recall"] else None,
        }
    return out
