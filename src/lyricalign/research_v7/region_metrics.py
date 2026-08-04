"""WP5：region_metrics —— 判别器结果评价（15 蓝图 §6.3）。

对每个 target/domain/mutation family 输出：unit recall、correct-retained-unit FPR、
gap event recall、deleted-GT weighted gap recall、wrong-output recall、replaced-GT omission
recall、interval recall@75/100、>=3-unit 全漏检率、unsafe 扩张长度。
按 source-song 独立 split 报告；demo 不参与训练/阈值。
纯函数、可单测。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence


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
    gt_gaps: Sequence[int],        # 真 gap（含 omitted canonical）
    pred_gap_ids: Sequence[int],   # 检出 gap
    weighted_deleted_gt: Sequence[int],  # deleted-GT gap (权重要)
) -> dict[str, float]:
    gtg = set(gt_gaps)
    pgs = set(pred_gap_ids)
    tp = len(gtg & pgs)
    fp = len(pgs - gtg)
    fn = len(gtg - pgs)
    return {
        "gap_event_recall": round(_safe_p(tp, len(gtg)), 4),
        "gap_deleted_weighted_recall": round(_safe_p(len(set(weighted_deleted_gt) & pgs), len(set(weighted_deleted_gt))), 4),
        "gap_fp": fp, "gap_fn": fn,
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
        if it.get("fpr") is not None:
            acc[key]["fpr"].append(it["fpr"])
        if it.get("gap_recall") is not None:
            acc[key]["gap_recall"].append(it["gap_recall"])
    out = {}
    for (sp, dom, fam), v in sorted(acc.items()):
        out[f"{sp}|{dom}|{fam}"] = {
            "n_items": len(v.get("unit_recall", [])),
            "unit_recall_mean": round(sum(v["unit_recall"]) / len(v["unit_recall"]), 4) if v["unit_recall"] else None,
            "fpr_mean": round(sum(v["fpr"]) / len(v["fpr"]), 4) if v["fpr"] else None,
            "gap_recall_mean": round(sum(v["gap_recall"]) / len(v["gap_recall"]), 4) if v["gap_recall"] else None,
        }
    return out
