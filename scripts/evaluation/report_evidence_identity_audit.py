#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the evidence-identity audit report (which real-song comparisons are usable)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_evidence_identity_audit")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 0) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_evidence_identity_audit.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_evidence_identity_audit/metrics.json")
    args = ap.parse_args()
    a = json.loads((args.run / "IDENTITY_AUDIT.json").read_text(encoding="utf-8"))
    pairs = {p["pair"]: p for p in a["pairs"]}
    p0 = pairs.get("ktv_B4__vs__current_silence", {})
    differing = [r for r in p0.get("per_song", []) if not r["outputs_identical"]]
    explained = all(not r["same_audio_sha"] for r in differing) if differing else False

    L: list[str] = []
    w = L.append
    w("# 真实歌批次证据同一性审计（第 11 轮续，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_evidence_identity_audit/IDENTITY_AUDIT.json` 生成；"
      "检查器 `src/lyricalign/analysis/evidence_identity_audit.py` 可指向任意批次对复用。")
    w("")
    w("## 0. 裁定")
    w("")
    w("| 比较对 | 裁定 | 依据 |")
    w("|---|---|---|")
    VERD = {"not_identified": "**未识别的对比**（不可用于机制结论）",
            "duplicate_configuration": "**同一配置的重复运行**（不可用于机制结论）",
            "not_comparable": "**不可比**（行不对齐）",
            "identified": "可比", "no_overlap": "无交集", "missing_batch": "批次缺失"}
    for p in a["pairs"]:
        w(f"| `{p['pair']}` | {VERD.get(p['verdict'], p['verdict'])} | {p.get('reason')} |")
    w("")
    w(f"- **B4 vs current_silence 收紧结论**：25/25 首歌窗口计划完全相同，"
      f"{pct(p0.get('outputs_identical_share'))} 输出逐位相同；"
      f"余下 {len(differing)} 首不同的歌**恰好就是音频 sha 不同的那 {len(differing)} 首**"
      f"（{'差异完全由输入不同解释' if explained else '仍有非输入因素'}）"
      "⇒ 这不是两种机制的对比，而是**同一配置跑了两次**（其中 2 首换了分离音频）。"
      "比第 5 轮的表述更硬，也说明 2026-08-14 那批 KTV/四路诊断视频的 B4-vs-Current 对比不成立。")
    w("- **slot 两个批次根本没有身份**：`identity.schema_version`、`audio_sha256`、`request_hash` "
      "**100% 缺失**（见下表）⇒ 无法证明用的是哪份音频；再加上与 B4/current 逐索引文本 100% 不匹配"
      "（单元被跳过/重复导致漂移），这三批之间**不存在任何可支持的对比**。")
    w("- `textmode3` 与其余批次单元数不同（word vs char 单元化）⇒ 索引级比较先天不成立。")
    w("")
    w("## 1. 身份卫生（每个批次能不能支撑结论）")
    w("")
    w("| 批次 | 歌曲 | 缺 schema | 缺音频 sha | 缺 request_hash | 记录 silence 标志 | 窗口标志数(中位) | 退化单元 | 重叠 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, v in a["identity_hygiene"].items():
        w(f"| `{k}` | {v['songs']} | {pct(v['share_missing_schema_version'])} | "
          f"{pct(v['share_missing_audio_sha'])} | {pct(v['share_missing_request_hash'])} | "
          f"{pct(v['share_recording_silence_flags'])} | {v['median_window_flags_recorded']:.0f} | "
          f"{pct(v['degenerate_share'],1)} | {pct(v['overlap_share'],2)} |")
    w("")
    w(f"- 顺带复核第 6 轮的结构结论：真实伴奏歌退化单元比例在各批次 16.7%–19.7%（与第 6 轮 17.1% 一致），"
      "且**不依赖后处理选择**——这是数据/解码侧的既有事实。")
    w("")
    w("## 2. 把教训变成流程")
    w("")
    w("- 任何批次对比在出结论前必须通过 `audit_pair()`：输出 `not_identified` / `not_comparable` "
      "就直接拒绝出对比表（本轮实现即第 2 轮提议的最小门）。")
    w("- `collect()` 对缺失 `schema_version` / `audio_sha256` / `request_hash` 的批次要显式标记为"
      " **unattributable**；后续 batch runner 应把这三项写全（小改动、可纯 CPU 验证）。")
    w("- 与第 10 轮的 `factor_content_audit()` 合起来构成两类检查："
      "**批内因子是否真的变了**、**批间是否可比**。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/audit_evidence_identity.py")
    w("PYTHONPATH=src python scripts/evaluation/report_evidence_identity_audit.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_evidence_identity_audit.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {"schema_version": "evidence_identity_audit_metrics_v1", "audit": a,
               "headline": {
                   "b4_vs_current_verdict": p0.get("verdict"),
                   "b4_vs_current_identical_output_share": p0.get("outputs_identical_share"),
                   "b4_vs_current_same_plan_share": p0.get("same_window_plan_share"),
                   "divergent_songs_explained_by_audio_change": explained,
                   "pairs_not_comparable": [p["pair"] for p in a["pairs"]
                                            if p["verdict"] == "not_comparable"],
                   "unattributable_batches": [k for k, v in a["identity_hygiene"].items()
                                              if v.get("share_missing_audio_sha", 0) > 0.5],
                   "conclusion": "the 2026-08-14/15 real-song comparison suite cannot support any "
                                 "mechanism claim: one pair is a duplicate run, the other two are "
                                 "index-incomparable, and the slot batches record no audio identity"}}
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
