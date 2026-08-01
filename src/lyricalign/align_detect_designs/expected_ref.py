"""期望参照维度（主线：统一论断的结构补强）—— 补探针5 的‘整段放慢无感’盲区。

统一论断：detector 只测内部一致性，缺“对照外部期望参照”的维度。
其中“期望节奏”是一个**无需新增输入、由 request 即得先验**可用量：
   期望速率 = total_units / duration_sec   （字符/秒）
本文实现一个纯函数：对一行/一组特征，用实测节奏相对期望节奏的偏差给出“偏慢/偏快/正常”
信号，作为 detector 可融合的新参照特征。纯 CPU、无模型、不触碰 research_v6。

探针5 复现点：整段放慢×2 时，实测速率折半，期望速率不变 → 本信号应明显指“偏慢”，
从而把原先“无感”的盲区补上；对局部正常变体不应误报。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ExpectedTempoConfig:
    """期望节奏参照的判据阈值。"""

    # 偏慢/偏快：实测/期望 速率比在 (1-slow, 1+fast) 内视为“正常”
    slow_ratio_min: float = 0.85   # 期望/实测 超过此→偏慢
    fast_ratio_max: float = 0.85   # 实测/期望 超过此→偏快
    win_units: int = 5

    def expected_rate(self, total_units: int, duration_sec: float) -> float:
        return total_units / duration_sec if duration_sec > 0 else 0.0


@dataclass(frozen=True)
class TempoRefReport:
    """期望节奏评估结果（item 级 + 每段）。"""

    expected_rate: float
    measured_rate: float
    ratio: float          # measured / expected
    flag: str             # slow / fast / normal / no_data

    def to_feature(self, *, prefix: str = "tempo") -> dict[str, float]:
        return {
            f"{prefix}_expected_rate": round(float(self.expected_rate), 6),
            f"{prefix}_measured_ratio": round(float(self.ratio), 6),
            f"{prefix}_slow": float(self.flag == "slow"),
            f"{prefix}_fast": float(self.flag == "fast"),
        }


def _start(row: Mapping) -> float | None:
    v = row.get("start_sec")
    return None if v is None else float(v)


def measure_rate(rows: Sequence[Mapping]) -> float | None:
    """实测节奏：用首尾字符的 selected start 跨度与字符跨度估算（字符/秒）。"""
    starts = [(int(r["global_character_index"]), _start(r)) for r in rows]
    starts = [(i, s) for i, s in starts if s is not None]
    if len(starts) < 2:
        return None
    i0, s0 = starts[0]
    i1, s1 = starts[-1]
    span = s1 - s0
    units = i1 - i0
    if span <= 0:
        return None
    return units / span


def tempo_ref_score(
    rows: Sequence[Mapping],
    *,
    total_units: int,
    duration_sec: float,
    config: ExpectedTempoConfig = ExpectedTempoConfig(),
) -> TempoRefReport:
    """期望节奏参照评估（纯函数，无 GT）。

    用 request 已知的 total_units/duration_sec 得期望速率，与实测速率比出偏慢/偏快。
    - ratio 明显 < 1（实测远慢于期望，乘性慢）→ slow
    - ratio 明显 > 1（实测远快）→ fast
    对“整段放慢（探针5）”能直接给出 slow，从而补盲区。
    """
    expected = config.expected_rate(total_units, duration_sec)
    measured = measure_rate(rows)
    if expected <= 0 or measured is None or measured <= 0:
        return TempoRefReport(expected, measured or 0.0, 0.0, "no_data")
    ratio = measured / expected
    # 期望/实测：这句量纲是“期望速率/实测速率”，比值>1.0 表示实测更慢
    inverse = expected / measured
    if inverse >= 1.0 / config.slow_ratio_min:
        flag = "slow"
    elif ratio >= 1.0 / config.fast_ratio_max:
        flag = "fast"
    else:
        flag = "normal"
    return TempoRefReport(expected, measured, round(ratio, 6), flag)


def extend_with_tempo_ref(
    feature_rows: Sequence[Mapping],
    rows: Sequence[Mapping],
    *,
    total_units: int,
    duration_sec: float,
    prefix: str = "tempo",
    config: ExpectedTempoConfig = ExpectedTempoConfig(),
) -> list[dict]:
    """把期望节奏参照 broadcast 到每字符 feature row（与方向A的 broadcast 一致）。"""
    rep = tempo_ref_score(rows, total_units=total_units, duration_sec=duration_sec, config=config)
    feats = rep.to_feature(prefix=prefix)
    out = []
    for frow in feature_rows:
        row = dict(frow)
        row.update(feats)
        row[f"{prefix}_report"] = {"expected_rate": rep.expected_rate,
                                   "measured_rate": rep.measured_rate,
                                   "flag": rep.flag}
        out.append(row)
    return out
