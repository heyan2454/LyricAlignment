"""Query 预算估计器（09_CODEX_REVIEWED_IMPLEMENTATION_PLAN §2.1 Density contract）。

canonical 名称只允许 units_per_sec；sec_per_unit 只能是显式 reciprocal 字段。
禁止继续使用同时表示两种物理量的 `unit_density_sec` 名称（旧配置命中时 fail closed）。

units_per_sec = n_units / effective_audio_sec
expected_units(audio_span_sec) = audio_span_sec * units_per_sec
"""

from __future__ import annotations

from dataclasses import dataclass

QUERY_ESTIMATOR_VERSION = "units_per_sec_v2"


class DensityContractError(ValueError):
    """旧 `unit_density_sec` 语义（sec/unit）在 estimator 上下文中出现时 fail closed。"""


@dataclass(frozen=True)
class QueryEstimator:
    n_units: int
    effective_audio_sec: float
    version: str = QUERY_ESTIMATOR_VERSION

    def __post_init__(self) -> None:
        if self.n_units <= 0:
            raise ValueError(f"n_units must be positive, got {self.n_units}")
        if self.effective_audio_sec <= 0:
            raise ValueError(f"effective_audio_sec must be positive, got {self.effective_audio_sec}")

    @property
    def units_per_sec(self) -> float:
        """canonical 单位：units / second。"""
        return self.n_units / self.effective_audio_sec

    @property
    def sec_per_unit(self) -> float:
        """reciprocal 字段：seconds / unit，明确标注，不得与 units_per_sec 混用。"""
        return self.effective_audio_sec / self.n_units

    def expected_units(self, audio_span_sec: float) -> float:
        """span 内期望歌词行数 = span * units_per_sec。"""
        return audio_span_sec * self.units_per_sec

    def query_end_id_exclusive(self, audio_span_sec: float, start_id: int = 0) -> int:
        """从 start_id 起覆盖 span 所需的 end id（exclusive）。"""
        return max(start_id + 1, start_id + int(round(self.expected_units(audio_span_sec))))

    def to_dict(self) -> dict:
        return {
            "n_units": self.n_units,
            "effective_audio_sec": round(self.effective_audio_sec, 6),
            "units_per_sec": round(self.units_per_sec, 6),
            "sec_per_unit": round(self.sec_per_unit, 6),
            "query_estimator_version": self.version,
        }


def build_estimator(n_units: int, effective_audio_sec: float) -> QueryEstimator:
    """推荐入口：按行数与实际（模型时钟）音频时长构造估计器。"""
    return QueryEstimator(n_units=n_units, effective_audio_sec=effective_audio_sec)


def migrate_legacy_sec_per_unit(value: float, *, n_units: int) -> QueryEstimator:
    """显式迁移路径：旧配置若表达 sec/unit（1.2 = 每单位 1.2 秒），

    转成 units_per_sec 语义。调用方必须确认旧值确为 sec/unit；
    无法确认时抛 DensityContractError，不得静默解释。
    """
    if value <= 0:
        raise DensityContractError(f"invalid legacy sec_per_unit: {value}")
    return QueryEstimator(n_units=n_units, effective_audio_sec=value * n_units)
