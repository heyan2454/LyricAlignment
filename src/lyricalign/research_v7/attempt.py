"""v7 AlignmentAttempt / Evidence — 一次尝试的不可变证据 + 行为流程骨架。

对应 00 §4：每次 attempt 保存 raw/official/topK/weighted、cursor before/after、posterior、
repair trace、lineage；EvidencePack 是单次 attempt 的不可变 cache，多个 pack 经 parent_request_id
构成 lineage。本模块是数据契约 + 可穿行的单 case 流程骨架；真实模型 exec 由 pilot 注入。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Sequence

from .requests import AlignmentRequest


@dataclass(frozen=True)
class AlignmentAttempt:
    request: AlignmentRequest
    attempt_id: str
    decoder_outputs: dict[str, Any]          # {decoder_name: rows/geometry}
    cursor_prev_end: float | None = None
    cursor_after: float | None = None
    committed: bool = False
    runtime_sec: float | None = None
    status: str = "ok"                        # ok / error / timeout / unresolved
    error: str | None = None
    fa_taxonomy: tuple[str, ...] = ()         # 参见 00 §12
    gt_eval: dict[str, Any] | None = None     # 仅 evaluation 用，不作为输入
    verdict: str | None = None                # 多解/正确/错段/...人工或自动分类

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidencePack:
    """单次 attempt 不可变证据；可通过 parent lineage 串联。"""

    attempt: AlignmentAttempt
    parent_request_id: str | None = None
    audio_hash: str | None = None
    text_hash: str | None = None
    slot_mask: tuple[int, ...] | None = None
    posterior: dict[str, Any] | None = None   # topK/entropy/margin/远距第二峰
    repair_trace: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 注入型模型执行器：request -> AlignmentAttempt（真推理在 pilot 接入；smoke 用 fake）
AttemptExecutor = Callable[[AlignmentRequest], AlignmentAttempt]


def run_request(
    request: AlignmentRequest,
    executor: AttemptExecutor,
    *,
    cursor_prev: float | None = None,
    fa_taxonomy: Sequence[str] = (),
) -> EvidencePack:
    """执行一次 request，产出 EvidencePack（骨架；执行器负责真实推理）。

    smoke 可传一个 fake executor 验证契约/数据流自洽而不触碰模型。
    """
    attempt = executor(request)
    # 骨架把 cursor 与 taxonomy 补进 attempt（frozen → 重建）
    attempt = AlignmentAttempt(
        request=attempt.request,
        attempt_id=attempt.attempt_id,
        decoder_outputs=attempt.decoder_outputs,
        cursor_prev_end=cursor_prev,
        cursor_after=attempt.cursor_after,
        committed=attempt.committed,
        runtime_sec=attempt.runtime_sec,
        status=attempt.status,
        error=attempt.error,
        fa_taxonomy=tuple(attempt.fa_taxonomy) + tuple(fa_taxonomy),
        gt_eval=attempt.gt_eval,
        verdict=attempt.verdict,
    )
    return EvidencePack(
        attempt=attempt,
        parent_request_id=request.parent_request_id,
        metadata={"request_id": request.request_id, "mutation": request.mutation_type},
    )
