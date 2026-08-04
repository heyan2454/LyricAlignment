"""review6-2：evaluation-role 硬隔离 —— 非 lyrics_aligned 记录不得进训练/阈值冻结/正式分母。

runner 产出的 RUN_MANIFEST.requests_identity 每项带 evaluation_role
(acoustic_probe | demo_challenge | lyrics_aligned)。feature/train/evaluate 入口必须先调用
本模块过滤：任何 evaluation_role != lyrics_aligned 的记录不得进入 CDS 权重、阈值冻结、
准确率分母；缺失 role 视为 probe（拒绝），不静默放行。
纯函数、可单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

ALLOWED_FOR_TRAIN_EVAL = {"lyrics_aligned"}


@dataclass(frozen=True)
class EvaluationGuard:
    reject_reason: str | None = None

    @property
    def allowed(self) -> bool:
        return self.reject_reason is None


def guard_role(role: str | None) -> EvaluationGuard:
    """判定单条记录能否进入训练/阈值/正式评价。

    缺失/未知 -> 视为 probe 并拒绝（不静默放行）；仅 lyrics_aligned 放行。
    """
    if role is None or role == "" or role == "unknown":
        return EvaluationGuard("missing evaluation_role (treated as probe)")
    if role == "acoustic_probe":
        return EvaluationGuard("acoustic_probe must not enter alignment/train/eval")
    if role == "demo_challenge":
        return EvaluationGuard("demo_challenge (no GT) must not enter train/threshold/formal denominator")
    if role == "lyrics_aligned":
        return EvaluationGuard(None)
    return EvaluationGuard(f"unknown evaluation_role={role!r}")


def partition_by_role(records: Sequence[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (allowed_for_train_eval, rejected_text_or_probe, rejected_other)。

    allowed：evaluation_role==lyrics_aligned **且** text_window_aligned 为真（文本须与所选窗对齐）；
    probe：acoustic_probe/demo_challenge 或 text_window_aligned=False；other：unknown role。
    """
    allowed: list[dict] = []
    probe: list[dict] = []
    other: list[dict] = []
    for r in records:
        role = r.get("evaluation_role")
        g = guard_role(role)
        # review7-3：缺 text_window_aligned 标记默认视为未对齐（拒绝），而非默认对齐
        window_aligned = r.get("text_window_aligned") is True
        if g.allowed and window_aligned:
            allowed.append(r)
        elif role in ("acoustic_probe", "demo_challenge") or not window_aligned:
            probe.append(r)
        else:
            other.append(r)
    return allowed, probe, other


def require_trainable(records: Sequence[dict]) -> dict:
    """train/evaluate 入口的硬过滤：只放行 lyrics_aligned（且 text_window_aligned=True）。

    review8-7：返回 allowed 身份清单 + rejected 完整身份记录（含 role/alignment/原因），
    供消费入口保存清单与确切分母；被拒项一律不入训练/阈值/正式评价。
    """
    allowed, probe, other = partition_by_role(records)
    rejected = []
    for r in probe + other:
        role = r.get("evaluation_role")
        reason = ("role_not_lyrics_aligned" if not guard_role(role).allowed
                  else "text_window_not_aligned")
        rejected.append({
            "item_id": r.get("item_id"), "request_id": r.get("request_id"),
            "request_identity": r.get("request_identity"),
            "evaluation_role": role,
            "text_window_aligned": r.get("text_window_aligned"),
            "reason": reason,
        })
    return {
        "trainable": allowed,
        "trainable_count": len(allowed),
        "rejected": rejected,
        "rejected_count": len(rejected),
    }
