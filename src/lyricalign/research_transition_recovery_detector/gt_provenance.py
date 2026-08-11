"""Synthetic-GT provenance payloads for historical LONG_TIMELINE_MANIFEST experiments.

`LONG_TIMELINE_MANIFEST.canonical_units[*].start_sec` 是 synthetic uniform
concatenation timeline（由 build_long_timeline_manifest 拼接生成），不是人工 GT。
凡以它作 correctness reference、或作 O0/O1/O2 oracle / query routing 输入的
session 输出，都不得解读为 real-GT/no-GT 能力结论。本模块提供集中 provenance
载荷工厂与 stderr 警告，受影响的脚本在写 JSON 输出时附加 `provenance` 字段。
"""

from __future__ import annotations

import sys

GT_KIND = "synthetic_uniform_timeline"
VALID_FOR_REALGT_CORRECTNESS = False
RESULT_STATUS = "historical_synthetic_gt_diagnostic"

WARNING_TEXT = (
    "WARNING: historical synthetic-GT oracle diagnostic, not real-GT/no-GT capability "
    "(timing reference is LONG_TIMELINE_MANIFEST.canonical_units.start_sec, a synthetic "
    "uniform concatenation timeline; do not cite these numbers as real-GT correctness)."
)


def synthetic_uniform_timeline_provenance(
    *,
    gt_used_for_routing: bool = False,
    mode: str | None = None,
) -> dict:
    """Provenance payload factory for results scored against synthetic uniform GT.

    Base payload (always present):
      gt_kind / valid_for_realgt_correctness / result_status

    Oracle modes additionally set:
      gt_used_for_routing=True  (GT also fed O0/O1/O2 query/head construction)
      mode="O0" | "O1" | "O2"   (precise oracle mode)
    """
    payload = {
        "gt_kind": GT_KIND,
        "valid_for_realgt_correctness": VALID_FOR_REALGT_CORRECTNESS,
        "result_status": RESULT_STATUS,
    }
    if gt_used_for_routing:
        payload["gt_used_for_routing"] = True
    if mode is not None:
        payload["mode"] = mode
    return payload


def warn_synthetic_gt(*, stream=None) -> None:
    """Print the synthetic-GT warning to stderr (call once per script run)."""
    (stream if stream is not None else sys.stderr).write(WARNING_TEXT + "\n")
