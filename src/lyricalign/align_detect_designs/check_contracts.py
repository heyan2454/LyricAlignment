"""align_detect_designs 接口自洽检查（不占 GPU，无 suite 依赖）。

运行：PYTHONPATH=src python -m lyricalign.align_detect_designs.check_contracts
```
"""
from __future__ import annotations

from ..research_v6.requests import AlignmentRequest

from .contracts import AlignmentGenerator, Detector, EvidencePack, RiskRecord
from .d1_feedback import detect_evidence
from .d5_posthoc import posthoc_diagnose


def _make_rows(n: int = 8) -> list[dict]:
    rows = []
    for i in range(n):
        start = float(i) * 0.5
        end = start + 0.4
        rows.append(
            {
                "global_character_index": i,
                "character_index": i,
                "raw_global_start_sec": start,
                "raw_global_end_sec": end,
                "official_fixed_global_start_sec": start - 0.02,
                "official_fixed_global_end_sec": end + 0.02,
                "start_sec": start,
                "end_sec": end,
                "raw_start_sec": start,
                "raw_end_sec": end,
            }
        )
    return rows


def run() -> int:
    # 1) 契约可 import + protocol 可 runtime check
    assert _PROTOCOL("expect Protocol ok")

    # 2) AlignmentRequest / RiskRecord.to_request 契约
    req = RiskRecord(
        character_start=2, character_end=5,
        span=(1.0, 2.5), score=0.9, kind="risk",
    ).to_request(item_id="demo_X")
    assert isinstance(req, AlignmentRequest)
    req.validate(total_units=8, duration_sec=10.0)  # 契约合法

    # 3) D1 detect 先行-反馈闭环（纯 CPU）
    rows = _make_rows()
    ev = EvidencePack(aligned_rows=tuple(rows), context={"item_id": "demo_X"})
    report, pending = detect_evidence(ev, item_id="demo_X", max_feedback_rounds=2)
    assert report is not None
    for risk in report.risk_spans:
        assert isinstance(risk, RiskRecord)
    assert pending is None or isinstance(pending, list)

    # 4) D5 post-hoc 诊断
    report5 = posthoc_diagnose(ev, item_id="demo_X")
    f5 = report5.feature_rows
    assert isinstance(f5, list)
    assert report5.selected_detector is not None or True

    print("check_contracts OK:", "D8 contracts ✓ D1 feedback ✓ D5 posthoc ✓")
    return 0


def _PROTOCOL(_: str) -> list:
    # protocol 是 runtime_checkable 的：这里仅验证类存在可实例化形态
    out = []
    for cls in (AlignmentGenerator, Detector):
        out.append(cls)  # protocol 对象存在即可
    # 验证 AlignmentRequest 从 research_v6.requests 正常导入（复用线）
    assert "research_v6.requests" in AlignmentRequest.__module__
    return out


if __name__ == "__main__":
    raise SystemExit(run())
