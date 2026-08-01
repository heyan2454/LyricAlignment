"""D8 contract-first 基座：align 与 detect 之间的稳定接口/数据契约。

只定义协议与不可变数据 record，不实现端到端编排。只读复用 research_v6 纯模块
（AlignmentRequest / inspect_alignment / decode_rows 等），不 import 任何 suite 模块。

设计要点（见 09_ALIGN_DETECT_ABSTRACTION_DESIGNS.md D8）：
- request 是唯一耦合面（对齐 AlignmentRequest，requests.py:8）。
- align 与 detect 通过 EvidencePack（不可变）通信，契约显式、可离线重算。
- 任何实现只要满足本模块的 protocol 即可被后续编排器选用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from ..research_v6.requests import AlignmentRequest  # 复用既有请求契约（只读）


# --------------------------------------------------------------------------- #
# 数据契约：align / detect 之间流通的不可变 record
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskRecord:
    """单个风险区间的标准化描述（detect 输出，供决策/重跑。）。"""

    character_start: int
    character_end: int  # exclusive
    span: tuple[float, float]  # (audio_start_sec, audio_end_sec)
    score: float
    kind: str = "risk"  # risk / safe_boundary / repairable
    detail: dict[str, Any] = field(default_factory=dict)

    def to_request(self, item_id: str, *, owner: str = "detect") -> AlignmentRequest:
        """把风险区间转成一次可执行的派生请求（复用 requests.py 的 derive 语义）。"""
        return AlignmentRequest(
            item_id=item_id,
            audio_start_sec=self.span[0],
            audio_end_sec=self.span[1],
            text_start=self.character_start,
            text_end=self.character_end,
            ownership_start_sec=self.span[0],
            ownership_end_sec=self.span[1],
            decoder_names=("raw", "official"),
            request_role=f"{owner}:{self.kind}",
            metadata={"kind": self.kind, "_design": "align_detect_designs"},
        )


@dataclass(frozen=True)
class DetectionReport:
    """detect 的标准化输出包（对齐 detector.py:350 inspect_alignment 的职责）。"""

    risk_spans: Sequence[RiskRecord]
    safe_boundaries: Sequence[int]
    feature_rows: Sequence[dict[str, Any]] = field(default_factory=list)
    selected_detector: str | None = None
    active_score_key: str | None = None
    active_risk_threshold: float | None = None
    active_safe_threshold: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # 保留底层报告，便于调试


@dataclass(frozen=True)
class EvidencePack:
    """align 与 detect 之间交换的不可变证据。

    设计原则（对 03:31 “EvidencePack 可离线重算 Detector/decoder”）：任何一方都
    只依赖本包，不依赖对方的内部可变状态。full 语义下证据已物化，detect 可离线重算。
    """

    aligned_rows: tuple[dict[str, Any], ...]
    input_candidates: tuple[tuple[dict[str, Any], ...], ...] = ()
    window_candidates: tuple[tuple[dict[str, Any], ...], ...] = ()
    audio_support_by_index: dict[int, dict[str, float]] = field(default_factory=dict)
    cursor_disagreement_by_index: dict[int, float] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def with_rows(self, rows: Sequence[dict[str, Any]]) -> "EvidencePack":
        """返回带新对齐行的不可变副本（用于 align 重跑后再次 detect 的闭环）。"""
        return EvidencePack(
            aligned_rows=tuple(rows),
            input_candidates=self.input_candidates,
            window_candidates=self.window_candidates,
            audio_support_by_index=self.audio_support_by_index,
            cursor_disagreement_by_index=self.cursor_disagreement_by_index,
            context=self.context,
        )


@dataclass(frozen=True)
class GeneratorResult:
    """align（Generator）的输出包（对齐 decoders.py:309 decode_rows 的职责）。"""

    rows: tuple[dict[str, Any], ...]
    decoder_name: str
    evidence: EvidencePack
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 协议：align 与 detect 的可替换抽象边界
# --------------------------------------------------------------------------- #


@runtime_checkable
class AlignmentGenerator(Protocol):
    """align 抽象：给定 request 与证据，产出对齐候选行 + 证据包。"""

    def __call__(self, request: AlignmentRequest, evidence: EvidencePack | None = None) -> GeneratorResult:
        ...


@runtime_checkable
class Detector(Protocol):
    """detect 抽象：给定证据包（含对齐行），产出风险/安全边界/候选 request 的报告。"""

    def __call__(self, evidence: EvidencePack) -> DetectionReport:
        ...


# --------------------------------------------------------------------------- #
# 便捷工具（纯函数，不依赖 suite）
# --------------------------------------------------------------------------- #


def pack_rows(rows: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """把行按 global_character_index 规范排序，形成稳定证据。"""
    return tuple(
        sorted((dict(r) for r in rows), key=lambda row: int(row["global_character_index"]))
    )
