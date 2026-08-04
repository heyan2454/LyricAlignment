"""v7 AlignmentRequest — 只描述“这次模型收到什么”，并带行为研究元数据。

设计遵循 docs/research_v7_align_behavior/00_EXECUTION_PLAN.md §4 的最小数据契约：
request 只携带一次模型调用的全部输入踪迹；mutation 与 workflow 信息内嵌，
供 Evidence/行为分类与跨 attempt lineage 追踪。纯 CPU，可单测。

request_identity：内容寻址严格 identity（15 蓝图 WP1 §3）——对 canonic 序列化（键排序、
UTF-8、无空白）+ context（code/env/model/checkpoint/audio/text/slot/mutation/decoder/
mapping-schema）做 SHA-256；相同输入稳定，slot/crop/text/decoder/mapping 任一不同必变。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Sequence


@dataclass(frozen=True)
class AlignmentRequest:
    request_id: str
    item_id: str
    parent_request_id: str | None
    audio_source: str
    audio_start_sec: float
    audio_end_sec: float
    text_source: str
    text_start_index: int
    text_end_index: int  # exclusive
    text_units: tuple[str, ...]
    timestamp_slot_indices: tuple[int, ...] | None
    workflow_mode: str
    mutation_type: str
    mutation_parameters: dict[str, Any]
    model_id: str
    checkpoint_id: str
    input_variant: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def _canonical_payload(self, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """规范化可哈希负载：剔除 request_id 等非内容字段，键排序、tuple→list。"""
        d = asdict(self)
        d.pop("request_id", None)  # request_id 为人为 id，非输入内容，不进身份
        d.pop("metadata", None)
        if context:
            d["context"] = context
        return d

    def request_identity(self, *, context: dict[str, Any] | None = None) -> str:
        """内容寻址严格 identity：canonical JSON(键排序/无空白/UTF-8) 的 SHA-256。

        context 应含 code/model env、音频内容 hash、canonical-mapping schema 版本等；
        由调用方提供（保持本模块纯、不依赖磁盘/模型）。
        """
        d = self._canonical_payload(context=context)
        canonical = json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def validate(self, *, total_units: int | None = None, duration_sec: float | None = None) -> None:
        if self.audio_start_sec < 0 or self.audio_end_sec <= self.audio_start_sec:
            raise ValueError(f"invalid audio range: {self.audio_start_sec}, {self.audio_end_sec}")
        if self.text_start_index < 0 or self.text_end_index <= self.text_start_index:
            raise ValueError(
                f"invalid text range: {self.text_start_index}, {self.text_end_index}"
            )
        if self.text_end_index > len(self.text_units):
            raise ValueError(
                f"text_end {self.text_end_index} exceeds text_units len {len(self.text_units)}"
            )
        if total_units is not None and self.text_end_index > total_units:
            raise ValueError(f"text_end {self.text_end_index} exceeds total_units {total_units}")
        if duration_sec is not None and self.audio_end_sec > duration_sec + 1e-6:
            raise ValueError(f"audio_end {self.audio_end_sec} exceeds duration {duration_sec}")
        if self.timestamp_slot_indices is not None:
            if any(i < 0 or i >= len(self.text_units) for i in self.timestamp_slot_indices):
                raise ValueError("timestamp_slot_indices out of text_units range")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def derive(self, **changes: Any) -> "AlignmentRequest":
        metadata = dict(self.metadata)
        metadata.update(changes.pop("metadata", {}))
        return replace(self, metadata=metadata, **changes)


def _freeze_units(units: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(u) for u in units)
