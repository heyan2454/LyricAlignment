"""WP5：features —— unit/gap 特征提取（R/O/H，纯 CPU）。

对应 15 蓝图 §6.3：unit 特征分 raw(R)/official(O)/hidden(H) 三类，gap 特征用它左右 unit 的
同类特征 + 时间跳变/跨视图差。特征提取必须**拒绝 GT/mutation 字段**（feature extractor 不得
消费 canonical_mapping 中出现的 label 字段）。纯函数、可单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RowFeatureBag:
    features: dict[str, float]

    def to_dict(self) -> dict:
        return dict(self.features)


def row_raw_features(row: Mapping) -> dict[str, float]:
    """R 类：raw 边界/曲率/uncertainty。"""
    f = {}
    try:
        start = float(row.get("raw_start_sec") or row.get("raw_global_start_sec", 0.0))
        end = float(row.get("raw_end_sec") or row.get("raw_global_end_sec", 0.0))
        dur = max(0.0, end - start)
        f["raw_duration_sec"] = round(dur, 6)
        f["raw_inverted"] = float((end - start) < 0)
        f["raw_zero"] = float(abs(end - start) < 1e-9)
    except (TypeError, ValueError):
        f["raw_duration_sec"] = 0.0
    for k in ("raw_start_margin", "raw_end_margin", "raw_start_entropy", "raw_end_entropy"):
        try:
            f[k] = round(float(row.get(k, 0.0)), 6)
        except (TypeError, ValueError):
            f[k] = 0.0
    return f


def row_official_features(row: Mapping) -> dict[str, float]:
    """O 类：official/候选对齐的几何。

    P0-4 review：支持 real executor 行（fixed_global_start_sec/end），并校验不退回默认 start_sec。
    """
    f = {}
    start_key = next((k for k in ("official_fixed_global_start_sec", "official_global_start_sec",
                                  "official_start_sec", "fixed_global_start_sec")
                      if row.get(k) is not None), None)
    end_key = next((k for k in ("official_fixed_global_end_sec", "official_global_end_sec",
                                "official_end_sec", "fixed_global_end_sec")
                    if row.get(k) is not None), None)
    if start_key is None or end_key is None:
        # 无任何 official 几何 → 置 None 而非悄悄退回 start_sec（review：不允许默认倒退）
        f["official_duration_sec"] = None
        f["official_geometry_source"] = None
        f["official_missing_geometry"] = 1.0
    else:
        os_ = float(row[start_key]); oe_ = float(row[end_key])
        f["official_duration_sec"] = round(max(0.0, oe_ - os_), 6)
        f["official_geometry_source"] = f"{start_key}|{end_key}"
        f["official_missing_geometry"] = 0.0
    # 跨 R/O 视图差
    r = row_raw_features(row)
    if f.get("official_duration_sec") is not None:
        f["ro_official_minus_raw_sec"] = round(f["official_duration_sec"] - r["raw_duration_sec"], 6)
    else:
        f["ro_official_minus_raw_sec"] = None
    f["has_repair"] = float(bool(row.get("repair") or row.get("seam_repaired") or row.get("repair_run")))
    return f


def row_hidden_features(row: Mapping) -> dict[str, float]:
    """H 类：hidden vector 统计（若存在；无则 0——hidden 抽取需 via audit）。"""
    f = {}
    h = row.get("hidden")
    if isinstance(h, dict) and h.get("available"):
        for k in ("start_norm", "end_norm", "start_end_cosine"):
            f[f"hidden_{k}"] = round(float(h.get(k, 0.0)), 6)
    else:
        for k in ("start_norm", "end_norm", "start_end_cosine"):
            f[f"hidden_{k}"] = 0.0
    return f


def unit_features(row: Mapping, *, include_hidden: bool = False) -> dict[str, float]:
    out = {}
    out.update(row_raw_features(row))
    out.update(row_official_features(row))
    if include_hidden:
        out.update(row_hidden_features(row))
    return out


def gap_features(
    left: Mapping | None, right: Mapping | None,
    *,
    include_hidden: bool = False,
    time_jump_sec: float | None = None,
) -> dict[str, float]:
    """gap 特征：左右 unit 同类特征 + 时间跳变 + 跨视图差。不含 deleted count/mutation。"""
    lf = unit_features(left, include_hidden=include_hidden) if left else {}
    rf = unit_features(right, include_hidden=include_hidden) if right else {}
    out = {}
    for k, v in lf.items():
        out[f"left_{k}"] = v
    for k, v in rf.items():
        out[f"right_{k}"] = v
    if time_jump_sec is not None:
        out["time_jump_sec"] = round(float(time_jump_sec), 6)
    # 左右 raw 边界跨视图差
    lr = left.get("raw_global_start_sec") if left else None
    if left and right:
        try:
            out["raw_start_jump_sec"] = round(
                float(right.get("raw_global_start_sec", 0) or 0) - float(left.get("raw_global_end_sec", 0) or 0), 6)
        except (TypeError, ValueError):
            out["raw_start_jump_sec"] = 0.0
    return out


BLOCKED_GAP_FIELDS = {"omitted_canonical_unit_ids", "positive", "removed_canonical_unit_ids",
                      "replaced_canonical_unit_ids", "mutation_family", "deleted_count"}


def feature_extractor_blocked(features: Mapping) -> dict:
    """审计：确认特征不泄漏 GT/mutation（应返回未泄漏）。"""
    leak = [k for k in BLOCKED_GAP_FIELDS if k in features]
    return {"leak": leak, "ok": not leak}
