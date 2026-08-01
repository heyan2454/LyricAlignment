"""D5 — detector 后置（post-hoc 诊断）。

设计：先只跑官方 align 全程，detect 在完成对齐后**独立**评估并标示风险，不做实时干预。
最符合 "detector 未验证前不改正式输出"（03:47 / 05:5）。只读复用 inspect_alignment。
"""
from __future__ import annotations

from typing import Sequence

from ..research_v6.detector import DetectorConfig, inspect_alignment
from ..research_v6.requests import AlignmentRequest

from .contracts import DetectionReport, EvidencePack, RiskRecord


def posthoc_diagnose(
    evidence: EvidencePack,
    *,
    item_id: str,
    config: DetectorConfig = DetectorConfig(),
) -> DetectionReport:
    """对给定的已完成对齐证据做一次后置检测，返回风险报告（不产生任何派生 request）。

    接口可组合性：任意 Generator 产出的 EvidencePack 都可被本函数独立评估，
    满足 D3/D8 的“detect 不依赖 align 内部，只依赖不可变证据”约束。
    """
    raw_report = inspect_alignment(
        evidence.aligned_rows,
        config=config,
        input_candidates=evidence.input_candidates,
        window_candidates=evidence.window_candidates,
        audio_support_by_index=evidence.audio_support_by_index,
        cursor_disagreement_by_index=evidence.cursor_disagreement_by_index,
    )
    rows = evidence.aligned_rows
    span_est = (
        (float(rows[0]["start_sec"]), float(rows[-1]["end_sec"])) if rows else (0.0, 0.0)
    )
    risks = [
        RiskRecord(
            character_start=int(r["character_start"]),
            character_end=int(r["character_end"]),
            span=span_est,
            score=float(r.get("span_score", 0.0)),
            detail=dict(r),
        )
        for r in raw_report.get("risk_spans", [])
    ]
    return DetectionReport(
        risk_spans=risks,
        safe_boundaries=[int(x) for x in raw_report.get("safe_boundaries", [])],
        feature_rows=raw_report.get("features", []),
        selected_detector=raw_report.get("selected_detector"),
        active_score_key=raw_report.get("active_score_key"),
        active_risk_threshold=raw_report.get("active_risk_threshold"),
        active_safe_threshold=raw_report.get("active_safe_threshold"),
        raw=raw_report,
    )


def risks_to_requests(report: DetectionReport, item_id: str) -> list[AlignmentRequest]:
    """把 post-hoc 报告转成“后续人工/编排决定”的候选请求（默认不自动执行）。"""
    return [r.to_request(item_id, owner="posthoc") for r in report.risk_spans]
