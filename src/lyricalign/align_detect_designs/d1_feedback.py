"""D1 — Detector 先行-反馈最小闭环（贴近现状 E8）。

设计（09 文档 D1/D2）：align 与 detect 经标准 request/EvidencePack 连接；
detect 产出风险后派生新 request 交由 align 重跑（feedback），直至无新风险或达上限。
只读复用 research_v6 纯模块：inspect_alignment / decode_rows / AlignmentRequest。

注意：这是一个契约演示/骨架，不是生产编排器——它不调用 SERIAL 串行提交，
因此“续跑/写入 committed prefix”等强耦合部分刻意留白（shadow-only 语义）。
"""
from __future__ import annotations

from typing import Iterable, Sequence

from ..research_v6.decoders import DecoderConfig, decode_rows
from ..research_v6.detector import DetectorConfig, inspect_alignment
from ..research_v6.requests import AlignmentRequest

from .contracts import (
    DetectionReport,
    EvidencePack,
    GeneratorResult,
    RiskRecord,
    pack_rows,
)


def _project_candidate_rows(rows: Sequence[dict[str, Any]], decoder_name: str) -> tuple[dict[str, Any], ...]:
    """对一行候选应用指定 decoder，产出对齐行（Generator 的最小实现）。"""
    cfg = DecoderConfig(name=decoder_name)
    return pack_rows(decode_rows(rows, cfg))


def detect_evidence(
    evidence: EvidencePack,
    *,
    item_id: str,
    config: DetectorConfig = DetectorConfig(),
    decoder_for_candidates: str = "official",
    max_feedback_rounds: int = 2,
) -> tuple[DetectionReport, list[AlignmentRequest]]:
    """detect 先行-反馈闭环骨架。

    返回 (最终 DetectionReport, 本轮派生出的待执行 request 列表)。
    每轮：
     1) 用 inspect_alignment（detect）从 EvidencePack 产出 DetectionReport；
     2) 从 risk_spans 派生对齐请求（RiskRecord.to_request）；
     3) 用 decoder_for_candidates 对局部行做一次 align（Generator 骨架）；
     4) 把新行回写成 EvidencePack，进入下一轮 detect（feedback）。
    """
    current = evidence
    report: DetectionReport | None = None
    pending_requests: list[AlignmentRequest] = []
    for _ in range(max_feedback_rounds):
        raw_report = inspect_alignment(
            current.aligned_rows,
            config=config,
            input_candidates=current.input_candidates,
            window_candidates=current.window_candidates,
            audio_support_by_index=current.audio_support_by_index,
            cursor_disagreement_by_index=current.cursor_disagreement_by_index,
        )
        risks = [
            RiskRecord(
                character_start=int(r["character_start"]),
                character_end=int(r["character_end"]),
                span=(float(current.aligned_rows[0]["start_sec"]), float(current.aligned_rows[-1]["end_sec"])) if current.aligned_rows else (0.0, 0.0),
                score=float(r.get("span_score", 0.0)),
                detail=dict(r),
            )
            for r in raw_report.get("risk_spans", [])
        ]
        report = DetectionReport(
            risk_spans=risks,
            safe_boundaries=[int(x) for x in raw_report.get("safe_boundaries", [])],
            feature_rows=raw_report.get("features", []),
            selected_detector=raw_report.get("selected_detector"),
            active_score_key=raw_report.get("active_score_key"),
            active_risk_threshold=raw_report.get("active_risk_threshold"),
            active_safe_threshold=raw_report.get("active_safe_threshold"),
            raw=raw_report,
        )
        derived = [risk.to_request(item_id) for risk in report.risk_spans]
        pending_requests.extend(derived)
        if not derived:
            break  # 无新风险，收敛
        # Generator 骨架：对每个派生 request 局部重解码，换成新证据进入下一轮 detect
        new_rows = list(current.aligned_rows)
        for req in derived:
            local = [r for r in new_rows if req.text_start <= int(r["global_character_index"]) < req.text_end]
            if local:
                decoded = _project_candidate_rows(local, decoder_for_candidates)
                idx = {int(r["global_character_index"]) for r in decoded}
                new_rows = [r for r in new_rows if int(r["global_character_index"]) not in idx] + list(decoded)
        current = current.with_rows(pack_rows(new_rows))
    assert report is not None
    return report, pending_requests


def generator_result(
    request: AlignmentRequest,
    rows: Iterable[dict[str, Any]],
    decoder_name: str,
) -> GeneratorResult:
    """构造一次 GeneratorResult（骨架，满足 AlignmentGenerator protocol 的形态）。"""
    aligned = decode_rows(rows, DecoderConfig(name=decoder_name))
    return GeneratorResult(
        rows=pack_rows(aligned),
        decoder_name=decoder_name,
        evidence=EvidencePack(aligned_rows=pack_rows(aligned), context={"request": request.to_dict()}),
    )
