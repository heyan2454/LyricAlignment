"""全局一致性维度（方向 A）：无 GT 的「整体漂移/一致性」纯函数。

背景（探针1/2，见 docs/research_v6/10_EXPLORATION_LOG_STRUCTURAL_PROBES.md）：
当前 detector 特征全是局部“曲率/边际”，对“全局一致平移”免疫（risk=0）。
本模块把探针2 的 raw↔selected 一致漂移判定提炼为可复用、可并入特征层的纯函数，
属 align_detect_designs 的“全局维度”扩展；纯 CPU、无模型、不触碰 production。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .contracts import pack_rows


@dataclass(frozen=True)
class GlobalShiftConfig:
    """全局一致性评分的阈值与口径。"""

    # “整体一致”判定：均值幅度阈值、离散度阈值、同向占比阈值
    magnitude_sec: float = 0.4
    max_spread_sec: float = 0.15
    min_right_ratio: float = 0.9
    # 参考口径：selected（最终输出）或 previous-position 递推（用上/下邻差异）
    ref: str = "selected"


def _boundary(row: Mapping, field_name: str) -> float | None:
    value = row.get(field_name)
    return None if value is None else float(value)


def raw_minus_ref_deltas(
    rows: Sequence[Mapping],
    *,
    config: GlobalShiftConfig = GlobalShiftConfig(),
) -> list[tuple[int, float]]:
    """逐字符计算 raw_start 相对参考的差向量（无 GT）。

    ref='selected'：raw_start − selected(start)；差值整体同向 → 疑似整体漂移。
    （探针2 证明该信号可区分“输出整体漂移”与基线/局部异常。）
    """
    ref = config.ref
    deltas: list[tuple[int, float]] = []
    for row in rows:
        index = int(row["global_character_index"])
        raw = _boundary(row, "raw_global_start_sec") or _boundary(row, "raw_start_sec")
        if ref == "selected":
            base = _boundary(row, "start_sec")
            if base is None:
                base = _boundary(row, "selected_start_sec")
        elif ref == "official":
            base = _boundary(row, "official_fixed_global_start_sec") or _boundary(row, "official_start_sec")
        else:
            base = None
        if raw is None or base is None:
            continue
        deltas.append((index, float(raw - base)))
    return deltas


@dataclass(frozen=True)
class GlobalShiftReport:
    """一次全局一致性评估的结果。"""

    mean_sec: float
    spread_sec: float
    right_ratio: float  # 同向(正)占比
    n: int
    flag: str  # global_consistent_shift / ambiguous / no_data

    def to_feature(self, *, prefix: str = "global") -> dict[str, float]:
        """转成一个可并入 extract_features 的扁平 feature 子集。"""
        return {
            f"{prefix}_shift_mean_sec": round(float(self.mean_sec), 6),
            f"{prefix}_shift_spread_sec": round(float(self.spread_sec), 6),
            f"{prefix}_consistent_shift": float(self.flag == "global_consistent_shift"),
        }


def global_shift_score(
    rows: Sequence[Mapping],
    *,
    config: GlobalShiftConfig = GlobalShiftConfig(),
) -> GlobalShiftReport:
    """对行集合做一次全局在移一致性评分（纯函数，无 GT）。

    判据：|mean|>=magnitude 且 spread<=max_spread 且 同向占比>=min_right_ratio
    → flag='global_consistent_shift'，否则 'ambiguous'；空→'no_data'。
    """
    deltas = raw_minus_ref_deltas(rows, config=config)
    if not deltas:
        return GlobalShiftReport(0.0, 0.0, 0.0, 0, "no_data")
    vals = [d for _, d in deltas]
    mean = statistics.fmean(vals)
    spread = statistics.median(abs(v - mean) for v in vals)
    right = sum(1 for v in vals if v > 0)
    ratio = max(right, len(vals) - right) / len(vals)
    flag = (
        "global_consistent_shift"
        if (abs(mean) >= config.magnitude_sec
            and spread <= config.max_spread_sec
            and ratio >= config.min_right_ratio)
        else "ambiguous"
    )
    return GlobalShiftReport(round(mean, 6), round(spread, 6), round(ratio, 6), len(vals), flag)


def extend_features_with_global(
    feature_rows: Sequence[Mapping],
    rows: Sequence[Mapping],
    *,
    prefix: str = "global",
    config: GlobalShiftConfig = GlobalShiftConfig(),
) -> list[dict]:
    """把一条全局一致性评分并入既有 per-char feature_rows（同一值广播到每行）。

    设计：全局维度是 item 级信号，叠加到每字符行，供后续 detector 训练/评分使用，
    不改变原始局部特征。返回新 feature_rows 列表。
    """
    report = global_shift_score(rows, config=config)
    feats = report.to_feature(prefix=prefix)
    out: list[dict] = []
    for frow in feature_rows:
        row = dict(frow)
        row.update(feats)
        # 附带原始几何供图/调试
        row[f"{prefix}_report"] = {
            "mean_sec": report.mean_sec,
            "spread_sec": report.spread_sec,
            "flag": report.flag,
        }
        out.append(row)
    return out


@dataclass(frozen=True)
class SegmentGlobalReport:
    """按段计算全局一致性：每段一份 GlobalShiftReport + 映射到字符。"""

    per_segment: tuple[tuple[str, GlobalShiftReport], ...]  # (segment_key, report)
    char_to_segment: tuple[tuple[int, str], ...]  # (global_index, segment_key)

    def flag_for_index(self, index: int) -> str:
        key = dict(self.char_to_segment).get(int(index))
        for k, r in self.per_segment:
            if k == key:
                return r.flag
        return "no_data"


def global_shift_score_by_segments(
    rows: Sequence[Mapping],
    *,
    key_fn,
    config: GlobalShiftConfig = GlobalShiftConfig(),
) -> SegmentGlobalReport:
    """按段/窗口计算全局一致性（探针3：粒度应是 per-window 而非整首）。

    key_fn: 把每行 dict 映射为 segment key 的纯函数（如按 global index / window 边界 /
          时间分段）。行按 key 分组后各算一次 global_shift_score，避免整首信号被
          分段差异漂移抵消（探针3 证明整首会漏检）。
    """
    groups: dict[str, list] = {}
    char_map: list[tuple[int, str]] = []
    for row in rows:
        key = str(key_fn(row))
        groups.setdefault(key, []).append(row)
        char_map.append((int(row["global_character_index"]), key))
    per: list[tuple[str, GlobalShiftReport]] = []
    for key in sorted(groups):
        report = global_shift_score(pack_rows(groups[key]), config=config)
        per.append((key, report))
    return SegmentGlobalReport(tuple(per), tuple(char_map))
