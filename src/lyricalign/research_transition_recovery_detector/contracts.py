"""Transition–Recovery–Detector 冻结合同：共享 state/request/route 数据类与硬断言。

对应 docs/research_transition_recovery_detector_20260807/07_REVIEWED_IMPLEMENTATION_PLAN.md
第 3 节（修正后的正式行为合同）。本文件只含纯数据与校验，不加载模型/音频。
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRANSITION_T0_ORACLE = "T0_oracle_independent"
TRANSITION_T1_DIRECT = "T1_direct_serial"
TRANSITION_T2_CORE = "T2_core_boundary_serial"
TRANSITION_T3_STABLE = "T3_stable_boundary_serial"

TRANSITIONS: tuple[str, ...] = (
    TRANSITION_T0_ORACLE,
    TRANSITION_T1_DIRECT,
    TRANSITION_T2_CORE,
    TRANSITION_T3_STABLE,
)

ROUTE_NONE = "none"
ROUTE_SHADOW = "shadow"
ROUTE_LOCAL = "L"
ROUTE_WHOLE = "W"

ROUTES: tuple[str, ...] = (ROUTE_NONE, ROUTE_SHADOW, ROUTE_LOCAL, ROUTE_WHOLE)

RECOVERY_ANCHOR = "recovery_anchor"
RECOVERY_RETRY = "retry"


@dataclass(frozen=True)
class RetryRequest:
    request_id: str
    retry_anchor_state_hash: str
    retry_count: int
    reason_code: str


@dataclass(frozen=True)
class TransitionState:
    """不可变串行推进状态。

    - committed_ids 是从 0 开始的连续 canonical prefix（committed_ids[i] == i），
      无重复、无倒退；committed_end_exclusive == len(committed_ids)。
    - next_input_cursor <= committed_end_exclusive 只允许用于左声学上下文回看
      （query 可回看已提交歌词），不能跳过未提交歌词。
    - provisional 与 committed 不重叠。
    - unresolved_gap 存在时不得提交 gap 右侧。
    - 时间字段（previous_committed_end_model_sec）使用 model/compressed clock；
      写盘诊断时另存 original-clock 映射。
    """

    song_id: str
    transition: str
    window_index: int
    next_input_cursor: int
    committed_end_exclusive: int
    committed_ids: tuple[int, ...] = ()
    provisional_ids: tuple[int, ...] = ()
    unresolved_gap: tuple[int, int] | None = None
    occurrence_by_id: tuple[tuple[int, str], ...] = ()
    previous_committed_end_model_sec: float = 0.0
    retry_count: int = 0

    def validate(self) -> None:
        if self.transition not in TRANSITIONS:
            raise ValueError(f"unknown transition: {self.transition}")
        if self.window_index < 0:
            raise ValueError("window_index must be non-negative")
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        if not 0 <= self.next_input_cursor <= self.committed_end_exclusive:
            raise ValueError(
                "next_input_cursor must be in [0, committed_end_exclusive] "
                f"(got {self.next_input_cursor} vs {self.committed_end_exclusive})"
            )
        if self.committed_end_exclusive != len(self.committed_ids):
            raise ValueError(
                "committed_end_exclusive must equal len(committed_ids) "
                f"(got {self.committed_end_exclusive} vs {len(self.committed_ids)})"
            )
        for i, cid in enumerate(self.committed_ids):
            if cid != i:
                raise ValueError(f"committed_ids must be a continuous prefix 0..n; got {cid} at {i}")
        overlap = set(self.committed_ids) & set(self.provisional_ids)
        if overlap:
            raise ValueError(f"provisional overlaps committed: {sorted(overlap)}")
        if self.unresolved_gap is not None:
            gap_start, gap_end = self.unresolved_gap
            if not 0 <= gap_start < gap_end:
                raise ValueError(f"invalid unresolved_gap: {self.unresolved_gap}")
            if self.committed_end_exclusive > gap_start:
                raise ValueError(
                    "cannot commit past an unresolved gap: committed_end_exclusive "
                    f"{self.committed_end_exclusive} > gap_start {gap_start}"
                )
        seen: dict[int, str] = {}
        for cid, occ in self.occurrence_by_id:
            if cid in seen:
                raise ValueError(f"duplicate occurrence entry for id {cid}")
            seen[cid] = occ
        if self.previous_committed_end_model_sec < 0:
            raise ValueError("previous_committed_end_model_sec must be non-negative")

    def derive(self, **changes) -> "TransitionState":
        values = {
            "song_id": self.song_id,
            "transition": self.transition,
            "window_index": self.window_index,
            "next_input_cursor": self.next_input_cursor,
            "committed_end_exclusive": self.committed_end_exclusive,
            "committed_ids": self.committed_ids,
            "provisional_ids": self.provisional_ids,
            "unresolved_gap": self.unresolved_gap,
            "occurrence_by_id": self.occurrence_by_id,
            "previous_committed_end_model_sec": self.previous_committed_end_model_sec,
            "retry_count": self.retry_count,
        }
        values.update(changes)
        return TransitionState(**values)


@dataclass(frozen=True)
class WindowRequest:
    """一次真实 forward 的完整身份。

    original_bounds / model_bounds 字段顺序：
    (input_start, core_start, core_end, input_end)，model 时钟为压缩后时钟。
    所有对外 timestamp 输出统一回到 original clock。
    """

    request_id: str
    parent_state_hash: str
    audio_identity: str
    original_bounds: tuple[float, float, float, float]
    model_bounds: tuple[float, float, float, float]
    query_canonical_ids: tuple[int, ...]
    slot_canonical_ids: tuple[int, ...]
    decoder_evidence: tuple[str, ...] = ()
    transition: str = TRANSITION_T1_DIRECT

    def validate(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must not be empty")
        if not self.audio_identity:
            raise ValueError("audio_identity must not be empty")
        if self.transition not in TRANSITIONS:
            raise ValueError(f"unknown transition: {self.transition}")
        for bounds in (self.original_bounds, self.model_bounds):
            if len(bounds) != 4:
                raise ValueError(f"bounds must have 4 fields, got {bounds}")
            a, b, c, d = bounds
            if not (a <= b <= c <= d):
                raise ValueError(f"bounds must be monotonically non-decreasing: {bounds}")
        if not self.query_canonical_ids:
            raise ValueError("query_canonical_ids must not be empty")
        for i in range(len(self.query_canonical_ids) - 1):
            if self.query_canonical_ids[i] >= self.query_canonical_ids[i + 1]:
                raise ValueError(f"query_canonical_ids must be strictly increasing: {self.query_canonical_ids}")


@dataclass(frozen=True)
class RoutePlan:
    """唯一 recovery/route 决策。executor 只验证并执行，不得读取分数改决策。"""

    route: str
    window_id: str
    commit_ids: tuple[int, ...] = ()
    provisional_ids: tuple[int, ...] = ()
    unresolved_gap: tuple[int, int] | None = None
    retry_request: RetryRequest | None = None
    next_input_cursor: int = 0
    reason_codes: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.route not in ROUTES:
            raise ValueError(f"unknown route: {self.route}")
        if not self.window_id:
            raise ValueError("window_id must not be empty")
        if self.route == ROUTE_WHOLE and self.commit_ids:
            raise ValueError("W REJECT plan must have empty commit_ids")
        if self.unresolved_gap is not None:
            gap_start, gap_end = self.unresolved_gap
            if not 0 <= gap_start < gap_end:
                raise ValueError(f"invalid unresolved_gap: {self.unresolved_gap}")
            if self.commit_ids and max(self.commit_ids) >= gap_start:
                raise ValueError("L route cannot commit past the unresolved gap")
        if self.retry_request is not None and self.retry_request.retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        seen: set[int] = set()
        for cid in self.commit_ids:
            if cid in seen:
                raise ValueError(f"duplicate commit id {cid}")
            seen.add(cid)
        if self.commit_ids and not self.commit_ids == tuple(range(self.commit_ids[0], self.commit_ids[0] + len(self.commit_ids))):
            raise ValueError("commit_ids must be a contiguous increasing range")
