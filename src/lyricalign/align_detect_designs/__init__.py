"""align/detect 抽象设计库（探索性、可复用、不触碰 research_v6/suite）。

对应用户多设计草案：docs/research_v6/09_ALIGN_DETECT_ABSTRACTION_DESIGNS.md
当前实现：
- contracts.py  : D8 contract-first 基座（protocol + 证据/决策 record）
- d1_feedback.py: D1 Detector 先行-反馈最小闭环
- d5_posthoc.py : D5 detector 后置（post-hoc 诊断）
设计采用“只读复用 research_v6 纯模块（requests/detector/decoders）”，不依赖
SERIAL/demo/suite，可在 CPU 上做接口自洽检查。
"""

from .contracts import (
    AlignmentGenerator,
    Detector,
    DetectionReport,
    EvidencePack,
    GeneratorResult,
    RiskRecord,
)
from .global_dims import (
    GlobalShiftConfig,
    GlobalShiftReport,
    SegmentGlobalReport,
    extend_features_with_global,
    global_shift_score,
    global_shift_score_by_segments,
)
from .expected_ref import (
    ExpectedTempoConfig,
    TempoRefReport,
    extend_with_tempo_ref,
    tempo_ref_score,
)

__all__ = [
    "AlignmentGenerator",
    "Detector",
    "DetectionReport",
    "EvidencePack",
    "GeneratorResult",
    "RiskRecord",
    "GlobalShiftConfig",
    "GlobalShiftReport",
    "SegmentGlobalReport",
    "extend_features_with_global",
    "global_shift_score",
    "global_shift_score_by_segments",
    "ExpectedTempoConfig",
    "TempoRefReport",
    "extend_with_tempo_ref",
    "tempo_ref_score",
]
