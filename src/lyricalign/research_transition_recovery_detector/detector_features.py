"""Phase 6：Detector 信号族特征提取（纯函数，无模型/音频）。

覆盖 09 §3 P4 必做信号族：R（raw 几何）、O（official 几何）、RO（raw×official
交互）、V（跨窗一致）、P（posterior 竞争）、S（trajectory）、H（hidden）、
PR（propagation-risk）。约束：
- 不读 GT / future trajectory / mutation family 字段：row 中任何 gt_*/future_*/
  mutation_* 字段不参与特征计算；
- PR 只提供决策时 evidence 特征，label 由外部提供（本模块不读 label）；
- H 族当前 row 无 hidden 字段时特征全部 None 且 status=not_available，不伪造。
"""

from __future__ import annotations

from statistics import pstdev
from typing import Any

LEGACY_FEATURE_NAMES = (
    "raw_start_entropy",
    "raw_end_entropy",
    "raw_start_margin",
    "raw_end_margin",
    "raw_start_top1_probability",
    "raw_end_top1_probability",
    "raw_official_start_diff_sec",
    "start_top2_gap_sec",
)

_R_NAMES = (
    "raw_start_entropy",
    "raw_end_entropy",
    "raw_start_margin",
    "raw_end_margin",
    "raw_start_top1_probability",
    "raw_end_top1_probability",
    "raw_start_interval_gap_sec",
    "raw_end_interval_gap_sec",
)
_O_NAMES = (
    "official_start_sec",
    "official_end_sec",
    "repair_shift_sec",
    "repair_shift_abs_sec",
    "repair_shift_run_len",
    "repair_shift_delta_sec",
)
_RO_NAMES = (
    "raw_official_start_diff_sec",
    "raw_official_end_diff_sec",
    "raw_official_start_diff_bucket",
    "raw_official_start_diff_sign",
)
_P_NAMES = (
    "start_top2_gap_sec",
    "start_second_peak_ratio",
    "start_second_peak_adjacent",
    "end_top2_gap_sec",
    "end_second_peak_ratio",
)
_S_NAMES = (
    "raw_zero_duration_flag",
    "start_velocity_sec",
    "start_acceleration_sec",
    "gap_overlap_sec",
    "compression_run_len",
    "zero_duration_run_len",
)
_V_NAMES = (
    "v_n_observations",
    "v_start_displacement_sec",
    "v_start_std_sec",
    "v_start_top1_std",
)
_H_NAMES = (
    "h_hidden_available",
    "h_last_layer_l2_norm",
    "h_early_layer_l2_norm",
)
_PR_NAMES = (
    "pr_entropy_max",
    "pr_shift_abs_sec",
    "pr_temporal_instability_sec",
)

SIGNAL_GROUPS: dict[str, tuple[str, ...]] = {
    "R": _R_NAMES,
    "O": _O_NAMES,
    "RO": _RO_NAMES,
    "V": _V_NAMES,
    "P": _P_NAMES,
    "S": _S_NAMES,
    "H": _H_NAMES,
    "PR": _PR_NAMES,
}

FEATURE_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        list(LEGACY_FEATURE_NAMES) + [name for group in SIGNAL_GROUPS.values() for name in group]
    )
)

_COMPRESSION_SEC = 0.25


def extract_unit_features(row: dict) -> dict[str, float | None]:
    """从单个 infer_slice row 提取 unit 级特征；缺失字段全部 None。

    只读 row 的证据字段（raw/official/topk）；任何 gt_*/future_*/mutation_* 字段
    不参与计算。序列级特征（差分/run/velocity）由 extract_context_features 补充。
    """
    feats: dict[str, float | None] = {}
    feats["raw_start_entropy"] = _num(row.get("raw_start_entropy"))
    feats["raw_end_entropy"] = _num(row.get("raw_end_entropy"))
    feats["raw_start_margin"] = _num(row.get("raw_start_margin"))
    feats["raw_end_margin"] = _num(row.get("raw_end_margin"))
    feats["raw_start_top1_probability"] = _num(row.get("raw_start_top1_probability"))
    feats["raw_end_top1_probability"] = _num(row.get("raw_end_top1_probability"))

    pred_start = _num(row.get("fixed_global_start_sec"))
    pred_end = _num(row.get("fixed_global_end_sec"))
    official_start = _num(row.get("official_fixed_global_start_sec"))
    official_end = _num(row.get("official_fixed_global_end_sec"))

    # O：official 几何 + repair shift（official - raw，带符号）
    feats["official_start_sec"] = official_start
    feats["official_end_sec"] = official_end
    if pred_start is not None and official_start is not None:
        shift = official_start - pred_start
        feats["repair_shift_sec"] = shift
        feats["repair_shift_abs_sec"] = abs(shift)
    else:
        feats["repair_shift_sec"] = None
        feats["repair_shift_abs_sec"] = None

    # RO：raw×official 交互
    start_diff = (
        abs(pred_start - official_start) if pred_start is not None and official_start is not None else None
    )
    feats["raw_official_start_diff_sec"] = start_diff
    feats["raw_official_end_diff_sec"] = (
        abs(pred_end - official_end) if pred_end is not None and official_end is not None else None
    )
    feats["raw_official_start_diff_bucket"] = _diff_bucket(start_diff)
    feats["raw_official_start_diff_sign"] = _diff_sign(pred_start, official_start)

    # P：top-2 峰间距 / 第二峰连续性（topk classes 相邻性）
    start_topk = row.get("raw_start_topk_probabilities")
    start_top2_gap, second_ratio = _topk_gap_and_ratio(start_topk)
    feats["start_top2_gap_sec"] = start_top2_gap
    feats["start_second_peak_ratio"] = second_ratio
    feats["start_second_peak_adjacent"] = _topk_second_adjacent(row.get("raw_start_topk_classes"))
    end_topk = row.get("raw_end_topk_probabilities")
    end_top2_gap, end_second_ratio = _topk_gap_and_ratio(end_topk)
    feats["end_top2_gap_sec"] = end_top2_gap
    feats["end_second_peak_ratio"] = end_second_ratio

    # S：单行可得的零时长标记（run 由序列层给出）
    feats["raw_zero_duration_flag"] = (
        1.0 if pred_start is not None and pred_end is not None and abs(pred_end - pred_start) <= 1e-6
        else (None if pred_start is None or pred_end is None else 0.0)
    )

    # H：row 无 hidden 字段时 None；不伪造
    hidden = {k: v for k, v in row.items() if k.startswith("hidden_")}
    feats["h_hidden_available"] = 1.0 if hidden else None
    feats["h_last_layer_l2_norm"] = _num(hidden.get("hidden_last_layer_l2_norm"))
    feats["h_early_layer_l2_norm"] = _num(hidden.get("hidden_early_layer_l2_norm"))

    # PR：只取决策时 evidence，不读 label
    entropy = [feats["raw_start_entropy"], feats["raw_end_entropy"]]
    entropy = [e for e in entropy if e is not None]
    feats["pr_entropy_max"] = max(entropy) if entropy else None
    feats["pr_shift_abs_sec"] = feats["repair_shift_abs_sec"]
    return feats


def extract_context_features(rows: list[dict]) -> list[dict[str, float | None]]:
    """序列级特征（R 差分、O repair-shift run/delta、S trajectory、PR 时域不稳定），与 rows 对齐。

    只依赖行序证据，不读 GT/未来行信息（除严格前缀行外无未来信息）。
    """
    out: list[dict[str, float | None]] = []
    prev_start: float | None = None
    prev_end: float | None = None
    prev_interval: float | None = None
    prev_shift: float | None = None
    prev_velocity: float | None = None
    prev_shift_sign: float | None = None
    shift_run = 0
    comp_run = 0
    zero_run = 0
    for row in rows:
        start = _num(row.get("fixed_global_start_sec"))
        end = _num(row.get("fixed_global_end_sec"))
        official = _num(row.get("official_fixed_global_start_sec"))
        unit = extract_unit_features(row)

        interval = start - prev_start if start is not None and prev_start is not None else None
        end_interval = end - prev_end if end is not None and prev_end is not None else None
        shift = official - start if official is not None and start is not None else None

        if interval is not None and interval < _COMPRESSION_SEC:
            comp_run += 1
        else:
            comp_run = 0
        if unit["raw_zero_duration_flag"] == 1.0:
            zero_run += 1
        else:
            zero_run = 0
        if shift is not None and shift != 0.0:
            sgn = 1.0 if shift > 0.0 else -1.0
            shift_run = shift_run + 1 if prev_shift_sign == sgn else 1
            prev_shift_sign = sgn
        else:
            shift_run = 0
            prev_shift_sign = 0.0 if shift == 0.0 else None

        velocity = interval - prev_interval if interval is not None and prev_interval is not None else None
        acceleration = (
            velocity - prev_velocity if velocity is not None and prev_velocity is not None else None
        )
        gap_overlap = prev_end - start if prev_end is not None and start is not None else None
        shift_delta = shift - prev_shift if shift is not None and prev_shift is not None else None

        out.append(
            {
                "raw_start_interval_gap_sec": interval,
                "raw_end_interval_gap_sec": end_interval,
                "repair_shift_run_len": float(shift_run),
                "repair_shift_delta_sec": shift_delta,
                "start_velocity_sec": velocity,
                "start_acceleration_sec": acceleration,
                "gap_overlap_sec": gap_overlap,
                "compression_run_len": float(comp_run),
                "zero_duration_run_len": float(zero_run),
                "pr_temporal_instability_sec": abs(shift_delta) if shift_delta is not None else None,
            }
        )
        prev_start, prev_end, prev_interval, prev_shift, prev_velocity = (
            start,
            end,
            interval,
            shift,
            velocity,
        )
    return out


def extract_signal_features(rows: list[dict]) -> list[dict[str, float | None]]:
    """per-row + context 合并后的完整 unit 特征行（V 族除外，V 用 cross_window_features）。"""
    per_row = [extract_unit_features(r) for r in rows]
    context = extract_context_features(rows)
    return [dict(p, **c) for p, c in zip(per_row, context)]


def _pick(feats: dict, names) -> dict[str, float | None]:
    return {name: feats.get(name) for name in names}


def extract_raw_geometry(rows: list[dict]) -> list[dict[str, float | None]]:
    return [_pick(f, _R_NAMES) for f in extract_signal_features(rows)]


def extract_official_geometry(rows: list[dict]) -> list[dict[str, float | None]]:
    return [_pick(f, _O_NAMES) for f in extract_signal_features(rows)]


def extract_raw_official_interaction(rows: list[dict]) -> list[dict[str, float | None]]:
    return [_pick(f, _RO_NAMES) for f in extract_signal_features(rows)]


def extract_posterior_competition(rows: list[dict]) -> list[dict[str, float | None]]:
    return [_pick(f, _P_NAMES) for f in extract_signal_features(rows)]


def extract_trajectory(rows: list[dict]) -> list[dict[str, float | None]]:
    return [_pick(f, _S_NAMES) for f in extract_signal_features(rows)]


def extract_hidden_features(rows: list[dict]) -> list[dict[str, Any]]:
    """H 族：row 无 hidden_* 字段 → 特征全 None + status=not_available（不伪造）。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        hidden = {k: v for k, v in row.items() if k.startswith("hidden_")}
        if not hidden:
            out.append(
                {
                    "status": "not_available",
                    "reason": "row has no hidden_* fields (output_hidden_states not exported)",
                    "features": {n: None for n in _H_NAMES},
                }
            )
            continue
        out.append(
            {
                "status": "available",
                "reason": None,
                "features": {
                    "h_hidden_available": 1.0,
                    "h_last_layer_l2_norm": _num(hidden.get("hidden_last_layer_l2_norm")),
                    "h_early_layer_l2_norm": _num(hidden.get("hidden_early_layer_l2_norm")),
                },
            }
        )
    return out


def extract_propagation_risk(rows: list[dict]) -> list[dict[str, Any]]:
    """PR 族：只提供决策时 evidence 特征；label 由外部在 Gate P 后提供，本模块不读 label。"""
    full = extract_signal_features(rows)
    out: list[dict[str, Any]] = []
    for f in full:
        out.append(
            {
                "status": "gate_p_required",
                "reason": "PR label supplied externally after Gate P; module never reads a label",
                "features": _pick(f, _PR_NAMES),
            }
        )
    return out


def cross_window_features(observations_by_id: dict[int, list[dict]]) -> dict[int, dict[str, float | None]]:
    """V 族：同一 canonical unit 跨重叠窗观察 → timing/posterior 位移与方差。"""
    out: dict[int, dict[str, float | None]] = {}
    for cid, observations in observations_by_id.items():
        starts = [_num(o.get("fixed_global_start_sec")) for o in observations]
        starts = [s for s in starts if s is not None]
        top1s = [_num(o.get("raw_start_top1_probability")) for o in observations]
        top1s = [t for t in top1s if t is not None]
        feats: dict[str, float | None] = {"v_n_observations": float(len(observations))}
        if starts:
            feats["v_start_displacement_sec"] = max(starts) - min(starts)
            feats["v_start_std_sec"] = pstdev(starts) if len(starts) >= 2 else None
        else:
            feats["v_start_displacement_sec"] = None
            feats["v_start_std_sec"] = None
        feats["v_start_top1_std"] = pstdev(top1s) if len(top1s) >= 2 else None
        out[int(cid)] = feats
    return out


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


def _topk_gap_and_ratio(topk) -> tuple[float | None, float | None]:
    if not isinstance(topk, (list, tuple)) or len(topk) < 2:
        return None, None
    p0 = _num(topk[0])
    p1 = _num(topk[1])
    if p0 is None or p1 is None:
        return None, None
    return float(p0) - float(p1), (float(p1) / float(p0) if p0 > 0.0 else None)


def _topk_second_adjacent(classes) -> float | None:
    if not isinstance(classes, (list, tuple)) or len(classes) < 2:
        return None
    c0 = _num(classes[0])
    c1 = _num(classes[1])
    if c0 is None or c1 is None:
        return None
    return 1.0 if abs(c0 - c1) <= 1.0 else 0.0


def _diff_bucket(diff: float | None) -> float | None:
    if diff is None:
        return None
    if diff < 0.1:
        return 0.0
    if diff < 0.5:
        return 1.0
    return 2.0


def _diff_sign(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    delta = b - a
    if abs(delta) <= 1e-9:
        return 0.0
    return 1.0 if delta > 0 else -1.0


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
