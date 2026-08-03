"""research_v7 align_behavior — 生产型不合法输入行为研究（最小可运行集）。

对应 docs/research_v7_align_behavior/00_EXECUTION_PLAN.md 的 Request/Attempt/Evidence 契约
与 mutation/behavior 入口。本包只实现契约、mutation 目录生成与可穿行的单 case 行为流水线骨架；
真实模型推理由 scripts/research_v7 在 controlled pilot 阶段接入（不在此处硬编码路径/模型）。
"""
from __future__ import annotations

from .attempt import AlignmentAttempt, EvidencePack
from .mutations import (
    MutationCatalog,
    build_mutation,
    DonorSpec,
    extra_ratio,
    missing_ratio,
    replace_ratio,
)
from .requests import AlignmentRequest

__all__ = [
    "AlignmentRequest",
    "AlignmentAttempt",
    "EvidencePack",
    "MutationCatalog",
    "build_mutation",
    "DonorSpec",
    "extra_ratio",
    "missing_ratio",
    "replace_ratio",
]
