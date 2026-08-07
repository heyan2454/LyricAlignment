"""Phase 6：Detector unit 级特征提取（纯函数，无模型/音频）。

特征来自 infer_slice 的 row 字段（raw 熵/边际/topk/official 对照）。
label 只由外部 gt 参数决定（no label leak）：row 内任何字段不参与标签判定。
"""

from __future__ import annotations

from typing import Any

FEATURE_NAMES = (
    "raw_start_entropy",
    "raw_end_entropy",
    "raw_start_margin",
    "raw_end_margin",
    "raw_start_top1_probability",
    "raw_end_top1_probability",
    "raw_official_start_diff_sec",
    "start_top2_gap_sec",
)


def extract_unit_features(row: dict) -> dict[str, float | None]:
    """从 infer_slice row 提取 unit 级特征；缺失字段填 None。"""
    feats: dict[str, float | None] = {}
    feats["raw_start_entropy"] = _num(row.get("raw_start_entropy"))
    feats["raw_end_entropy"] = _num(row.get("raw_end_entropy"))
    feats["raw_start_margin"] = _num(row.get("raw_start_margin"))
    feats["raw_end_margin"] = _num(row.get("raw_end_margin"))
    feats["raw_start_top1_probability"] = _num(row.get("raw_start_top1_probability"))
    feats["raw_end_top1_probability"] = _num(row.get("raw_end_top1_probability"))
    pred_start = _num(row.get("fixed_global_start_sec"))
    official_start = _num(row.get("official_fixed_global_start_sec"))
    feats["raw_official_start_diff_sec"] = (
        abs(pred_start - official_start) if pred_start is not None and official_start is not None else None
    )
    topk_probs = row.get("raw_start_topk_probabilities")
    if isinstance(topk_probs, (list, tuple)) and len(topk_probs) >= 2:
        feats["start_top2_gap_sec"] = float(topk_probs[0]) - float(topk_probs[1])
    else:
        feats["start_top2_gap_sec"] = None
    return feats


def rows_to_matrix(
    rows: list[dict],
    gt: dict[int, dict] | None,
    *,
    tolerance_sec: float = 0.32,
) -> tuple[list[dict[str, float | None]], list[float | None]]:
    """rows -> (特征 dict 列表, label 列表)。

    label：None=无 GT 不评估；1=unsafe（|pred_start - gt_start| > tolerance）；
    0=safe。label 只由 gt 参数与 row 的 fixed_global_start_sec 决定（GT 判定，
    不读 row 中任何其他字段，保证 no label leak）。
    """
    features: list[dict[str, float | None]] = []
    labels: list[float | None] = []
    for row in rows:
        features.append(extract_unit_features(row))
        if gt is None:
            labels.append(None)
            continue
        cid = int(row["global_character_index"])
        g = gt.get(cid)
        pred = _num(row.get("fixed_global_start_sec"))
        if g is None or pred is None:
            labels.append(None)
            continue
        labels.append(1.0 if abs(pred - float(g["start_sec"])) > tolerance_sec else 0.0)
    return features, labels


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
