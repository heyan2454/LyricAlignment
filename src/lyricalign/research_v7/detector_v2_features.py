"""Detector V2 feature extraction (Phase2-1, 18 §7 / 20 §3).

只消费 detector_v2_evidence.EvidenceRow（H/R/O/V 契约），绝不消费 GT/mutation/family。
unit_feature_row 在提取前必须通过 assert_no_label_leak 泄漏断言（含邻居行与 cross_view）。

特征分组（feature_schema() 与 19 §6 FEATURE_SCHEMA.json 交付物对齐）：
  R  — raw/posterior：entropy、margin、top1-top2 margin、top-k span/variance、
       raw duration、零时长、逆序（end<=start）、gap/overlap（与邻域比）。
  O  — official/repair：official duration、raw→official shift、repair shift、
       has_repair、repair 连续长度（邻域）。
  H  — hidden：available=False 时全部 None（不伪造零，18 §7/19 G1：H blocked 时 R/O 继续）；
       available=True 时 start/end norm、variance、start-end cosine/L2（start/end dict
       有 vector 字段时计算 cosine/L2）。
  neighborhood — 一/二阶差（duration/start/end 相邻差）与局部突变（与邻域 median 偏差），
       raw 与 official 各一套。
  cross_view — 同 unit 跨视图 onset/offset 差与 posterior 距离（cross_view dict 提供时）。

neighbors 契约（build_neighbors 生成或调用方构造）：
  {"prev": EvidenceRow|None, "next": EvidenceRow|None, "repair_run_length": int|None}

缺失值一律 None（不伪造 0）；仅真实计算的零值才输出 0.0。
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Sequence

from lyricalign.research_v7.detector_v2_evidence import (
    FORBIDDEN_FEATURE_FIELDS,
    EvidenceRow,
    assert_no_label_leak,
)

R_FEATURE_KEYS = (
    "raw_start_entropy",
    "raw_end_entropy",
    "raw_start_margin",
    "raw_end_margin",
    "raw_top1_top2_margin",
    "raw_topk_span",
    "raw_topk_variance",
    "raw_duration_sec",
    "raw_zero_duration",
    "raw_inverted",
    "raw_gap_to_prev_sec",
    "raw_gap_to_next_sec",
)

O_FEATURE_KEYS = (
    "official_duration_sec",
    "ro_start_shift_sec",
    "ro_end_shift_sec",
    "repair_start_shift_sec",
    "repair_end_shift_sec",
    "has_repair",
    "repair_run_length",
)

H_FEATURE_KEYS = (
    "hidden_start_norm",
    "hidden_end_norm",
    "hidden_start_variance",
    "hidden_end_variance",
    "hidden_start_end_cosine",
    "hidden_start_end_l2",
)

NEIGHBORHOOD_FEATURE_KEYS = (
    "raw_dur_diff_prev",
    "raw_dur_diff_next",
    "raw_dur_diff2",
    "raw_start_diff_prev",
    "raw_start_diff_next",
    "raw_start_diff2",
    "raw_end_diff_prev",
    "raw_end_diff_next",
    "raw_end_diff2",
    "official_dur_diff_prev",
    "official_dur_diff_next",
    "official_dur_diff2",
    "official_start_diff_prev",
    "official_start_diff_next",
    "official_start_diff2",
    "official_end_diff_prev",
    "official_end_diff_next",
    "official_end_diff2",
    "raw_dur_median_dev",
    "raw_start_median_dev",
    "raw_end_median_dev",
    "official_dur_median_dev",
    "official_start_median_dev",
    "official_end_median_dev",
)

CROSS_VIEW_FEATURE_KEYS = (
    "cv_n_views",
    "cv_start_diff_sec",
    "cv_end_diff_sec",
    "cv_posterior_distance",
)

FEATURE_GROUPS = {
    "R": R_FEATURE_KEYS,
    "O": O_FEATURE_KEYS,
    "H": H_FEATURE_KEYS,
    "neighborhood": NEIGHBORHOOD_FEATURE_KEYS,
    "cross_view": CROSS_VIEW_FEATURE_KEYS,
}

_EPS = 1e-9


def feature_schema() -> dict[str, list[str]]:
    """FEATURE_SCHEMA.json 契约：每组的特征键清单（键名与实际输出完全一致）。"""
    return {group: list(keys) for group, keys in FEATURE_GROUPS.items()}


def all_feature_keys() -> list[str]:
    return [key for keys in FEATURE_GROUPS.values() for key in keys]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _f(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _flat_keys(mapping: Mapping) -> set[str]:
    """递归展开 dict 的叶子键，取末段（跨视图子键也能命中 forbidden 名单）。"""
    out: set[str] = set()

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                out.add(key)
                walk(v, key)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, prefix)

    walk(mapping, "")
    return {k.split(".")[-1] for k in out}


def _assert_no_leak(*payloads: Mapping) -> None:
    """提取前泄漏断言：row/neighbors/cross_view 的任何 forbidden 键都拒绝。"""
    leaf_keys: set[str] = set()
    for payload in payloads:
        if payload:
            leaf_keys |= _flat_keys(payload)
    forbidden = sorted(leaf_keys & FORBIDDEN_FEATURE_FIELDS)
    if forbidden:
        raise ValueError(f"feature row leaks forbidden label fields: {forbidden}")
    assert_no_label_leak(dict.fromkeys(leaf_keys, 1))


def _topk_probs(topk: Sequence) -> list[float] | None:
    """topk 概率列表：接受纯概率列表或 (class, prob) 对列表；非法条目返回 None。"""
    out: list[float] = []
    for item in topk or ():
        if isinstance(item, (int, float)):
            out.append(float(item))
            continue
        try:
            pair = tuple(item)
            if len(pair) >= 2:
                out.append(float(pair[-1]))
                continue
        except (TypeError, ValueError):
            pass
        return None
    return out


def is_repaired(row: EvidenceRow) -> bool:
    """repair shift 任一非零（有实际 repair move）即视为 repaired。"""
    rs = row.official.repair_start_shift_sec
    re = row.official.repair_end_shift_sec
    return bool(
        (rs is not None and abs(float(rs)) > _EPS)
        or (re is not None and abs(float(re)) > _EPS)
    )


def repair_run_lengths(rows: Sequence[EvidenceRow]) -> list[int]:
    """每个 unit 所在连续 repair 段的长度（单跑长度 1；需完整序列）。"""
    flags = [is_repaired(row) for row in rows]
    out: list[int] = []
    n = len(rows)
    for i, flag in enumerate(flags):
        if not flag:
            out.append(0)
            continue
        length = 1
        j = i - 1
        while j >= 0 and flags[j]:
            length += 1
            j -= 1
        j = i + 1
        while j < n and flags[j]:
            length += 1
            j += 1
        out.append(length)
    return out


def build_neighbors(rows: Sequence[EvidenceRow], index: int) -> dict:
    """从完整序列构造 unit_feature_row 的 neighbors dict（含精确 repair_run_length）。"""
    prev_row = rows[index - 1] if index - 1 >= 0 else None
    next_row = rows[index + 1] if index + 1 < len(rows) else None
    runs = repair_run_lengths(rows)
    return {"prev": prev_row, "next": next_row, "repair_run_length": runs[index]}


# ---------------------------------------------------------------------------
# R 类：raw/posterior
# ---------------------------------------------------------------------------

def _raw_features(row: EvidenceRow, neighbors: Mapping | None) -> dict[str, float | None]:
    f: dict[str, float | None] = {key: None for key in R_FEATURE_KEYS}
    raw = row.raw
    f["raw_start_entropy"] = _f(raw.start_entropy)
    f["raw_end_entropy"] = _f(raw.end_entropy)
    f["raw_start_margin"] = _f(raw.start_margin)
    f["raw_end_margin"] = _f(raw.end_margin)

    probs = _topk_probs(raw.topk)
    if probs is not None and len(probs) >= 2:
        f["raw_top1_top2_margin"] = _f(probs[0] - probs[1])
        f["raw_topk_span"] = _f(probs[0] - probs[-1])
        f["raw_topk_variance"] = _f(statistics.pvariance(probs))

    start = _f(raw.start_sec)
    end = _f(raw.end_sec)
    if start is not None and end is not None:
        f["raw_duration_sec"] = _f(max(0.0, end - start))
        f["raw_zero_duration"] = float(abs(end - start) < _EPS)
        f["raw_inverted"] = float(end <= start)

    if neighbors:
        prev = neighbors.get("prev")
        next_ = neighbors.get("next")
        if prev is not None and start is not None:
            prev_end = _f(prev.raw.end_sec)
            if prev_end is not None:
                f["raw_gap_to_prev_sec"] = _f(start - prev_end)
        if next_ is not None and end is not None:
            next_start = _f(next_.raw.start_sec)
            if next_start is not None:
                f["raw_gap_to_next_sec"] = _f(next_start - end)
    return f


# ---------------------------------------------------------------------------
# O 类：official/repair
# ---------------------------------------------------------------------------

def _official_features(row: EvidenceRow, neighbors: Mapping | None) -> dict[str, float | None]:
    f: dict[str, float | None] = {key: None for key in O_FEATURE_KEYS}
    off = row.official
    raw = row.raw
    o_start = _f(off.start_sec)
    o_end = _f(off.end_sec)
    if o_start is not None and o_end is not None:
        f["official_duration_sec"] = _f(max(0.0, o_end - o_start))
    r_start = _f(raw.start_sec)
    r_end = _f(raw.end_sec)
    if o_start is not None and r_start is not None:
        f["ro_start_shift_sec"] = _f(o_start - r_start)
    if o_end is not None and r_end is not None:
        f["ro_end_shift_sec"] = _f(o_end - r_end)
    f["repair_start_shift_sec"] = _f(off.repair_start_shift_sec)
    f["repair_end_shift_sec"] = _f(off.repair_end_shift_sec)
    f["has_repair"] = float(is_repaired(row))
    if neighbors:
        f["repair_run_length"] = neighbors.get("repair_run_length")
    return f


# ---------------------------------------------------------------------------
# H 类：hidden（blocked → 全 None）
# ---------------------------------------------------------------------------

def _hidden_features(row: EvidenceRow) -> dict[str, float | None]:
    f: dict[str, float | None] = {key: None for key in H_FEATURE_KEYS}
    hidden = row.hidden
    if not hidden.available:
        return f
    start = hidden.start or {}
    end = hidden.end or {}
    f["hidden_start_norm"] = _f(start.get("norm"))
    f["hidden_end_norm"] = _f(end.get("norm"))
    f["hidden_start_variance"] = _f(start.get("variance"))
    f["hidden_end_variance"] = _f(end.get("variance"))
    s_vec = start.get("vector")
    e_vec = end.get("vector")
    if isinstance(s_vec, (list, tuple)) and isinstance(e_vec, (list, tuple)) \
            and len(s_vec) == len(e_vec) and len(s_vec) > 0:
        try:
            s = [float(x) for x in s_vec]
            e = [float(x) for x in e_vec]
        except (TypeError, ValueError):
            s = e = []
        if s:
            dot = sum(a * b for a, b in zip(s, e))
            norm_s = math.sqrt(sum(a * a for a in s))
            norm_e = math.sqrt(sum(b * b for b in e))
            if norm_s > _EPS and norm_e > _EPS:
                f["hidden_start_end_cosine"] = _f(dot / (norm_s * norm_e))
            f["hidden_start_end_l2"] = _f(
                math.sqrt(sum((a - b) ** 2 for a, b in zip(s, e))))
    return f


# ---------------------------------------------------------------------------
# 邻域特征：一/二阶差 + 局部突变（median 偏差）
# ---------------------------------------------------------------------------

def _pair_median(a: float, b: float, c: float | None = None) -> float:
    if c is None:
        return statistics.median([a, b])
    return statistics.median([a, b, c])


def _neighborhood_features(
    row: EvidenceRow, neighbors: Mapping | None,
) -> dict[str, float | None]:
    f: dict[str, float | None] = {key: None for key in NEIGHBORHOOD_FEATURE_KEYS}
    if not neighbors:
        return f
    prev = neighbors.get("prev")
    next_ = neighbors.get("next")

    def _raw_dur(r: EvidenceRow) -> float | None:
        s, e = _f(r.raw.start_sec), _f(r.raw.end_sec)
        return _f(max(0.0, e - s)) if s is not None and e is not None else None

    def _official_dur(r: EvidenceRow) -> float | None:
        s, e = _f(r.official.start_sec), _f(r.official.end_sec)
        return _f(max(0.0, e - s)) if s is not None and e is not None else None

    def _view_vals(r: EvidenceRow, kind: str) -> tuple:
        if kind == "raw":
            return (_f(r.raw.start_sec), _f(r.raw.end_sec), _raw_dur(r))
        return (_f(r.official.start_sec), _f(r.official.end_sec), _official_dur(r))

    for kind, dkey in (("raw", "raw"), ("official", "official")):
        self_start, self_end, self_dur = _view_vals(row, kind)
        prev_start, prev_end, prev_dur = (_view_vals(prev, kind) if prev is not None
                                          else (None, None, None))
        next_start, next_end, next_dur = (_view_vals(next_, kind) if next_ is not None
                                          else (None, None, None))
        for name, self_v, prev_v, next_v in (
            ("dur", self_dur, prev_dur, next_dur),
            ("start", self_start, prev_start, next_start),
            ("end", self_end, prev_end, next_end),
        ):
            if self_v is not None:
                if prev_v is not None:
                    f[f"{kind}_{name}_diff_prev"] = _f(self_v - prev_v)
                if next_v is not None:
                    f[f"{kind}_{name}_diff_next"] = _f(next_v - self_v)
                if prev_v is not None and next_v is not None:
                    f[f"{kind}_{name}_diff2"] = _f(next_v - 2 * self_v + prev_v)
                median = None
                if prev_v is not None and next_v is not None:
                    median = _pair_median(prev_v, self_v, next_v)
                elif prev_v is not None:
                    median = _pair_median(prev_v, self_v)
                elif next_v is not None:
                    median = _pair_median(self_v, next_v)
                if median is not None:
                    f[f"{kind}_{name}_median_dev"] = _f(self_v - median)
    return f


# ---------------------------------------------------------------------------
# 跨视图特征
# ---------------------------------------------------------------------------

def _cross_view_features(cross_view: Mapping | None) -> dict[str, float | None]:
    f: dict[str, float | None] = {key: None for key in CROSS_VIEW_FEATURE_KEYS}
    if not cross_view:
        return f
    f["cv_n_views"] = cross_view.get("n_views")
    f["cv_start_diff_sec"] = _f(cross_view.get("start_diff_sec", cross_view.get("onset_diff_sec")))
    f["cv_end_diff_sec"] = _f(cross_view.get("end_diff_sec", cross_view.get("offset_diff_sec")))
    posterior_distance = cross_view.get("posterior_distance")
    if posterior_distance is None:
        vectors = cross_view.get("posterior_vectors")
        if isinstance(vectors, (list, tuple)) and len(vectors) >= 2:
            try:
                cleaned = [[float(x) for x in v] for v in vectors]
            except (TypeError, ValueError):
                cleaned = []
            if all(len(v) > 0 and len(v) == len(cleaned[0]) for v in cleaned):
                distances = [
                    math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))
                    for i, v1 in enumerate(cleaned)
                    for v2 in cleaned[i + 1:]
                ]
                if distances:
                    posterior_distance = statistics.mean(distances)
    f["cv_posterior_distance"] = _f(posterior_distance)
    return f


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def unit_feature_row(
    row: EvidenceRow,
    neighbors: Mapping | None = None,
    cross_view: Mapping | None = None,
) -> dict[str, float | None]:
    """单 unit 特征行：R/O/H/neighborhood/cross_view 全部键。

    泄漏 assert 前置：row（含 cross_view 内嵌）、邻居行、cross_view 参数中任何
    forbidden 字段（GT/mutation/family 等）都会 ValueError。
    cross_view 参数缺省时回退 row.cross_view。
    """
    if cross_view is None:
        cross_view = row.cross_view
    row_dict = row.to_dict()
    neighbor_rows = {}
    if neighbors:
        for name, value in neighbors.items():
            if isinstance(value, EvidenceRow):
                neighbor_rows[name] = value.to_dict()
    _assert_no_leak(row_dict, neighbor_rows, dict(cross_view) if cross_view else None)

    out: dict[str, float | None] = {}
    out.update(_raw_features(row, neighbors))
    out.update(_official_features(row, neighbors))
    out.update(_hidden_features(row))
    out.update(_neighborhood_features(row, neighbors))
    out.update(_cross_view_features(cross_view))
    return out
