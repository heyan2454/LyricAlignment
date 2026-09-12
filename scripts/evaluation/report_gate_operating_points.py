#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the gate operating-point report (what the SAFE edge really buys)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_gate_operating_points")
REPO = Path(__file__).resolve().parents[2]


def rows_of(blk: dict) -> list[str]:
    out = ["| SAFE 边 | 自动通过 | 其中稳健（±1 格仍成立） | 稳健占自动通过 | 落入待复核 | 一格摆幅 |",
           "|---|---:|---:|---:|---:|---:|"]
    for k, v in blk["by_safe_edge"].items():
        out.append(f"| ≤{k.replace('ms','ms')} | {100 * v['safe_share']:.2f}% | "
                   f"{100 * v['robust_safe_share']:.2f}% | {100 * v['safe_share_robustness']:.1f}% | "
                   f"{100 * v['grey_share']:.2f}% | {v['swing_pp_if_edge_moved_one_quantum']:.1f}pp |")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_gate_operating_points.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_gate_operating_points/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "GATE_OPERATING_POINTS.json").read_text(encoding="utf-8"))
    nb, po, ho = r["pooled_non_broken"], r["pooled"], r["held_out_test_slice"]

    L: list[str] = []
    w = L.append
    w("# 复核 gate 的 SAFE 边买到什么：格点视角下的工作点（第 35 轮，2026-09-12）")
    w("")
    w(f"> 数字由 `runs/{r['schema'] and '20260912_gate_operating_points'}/GATE_OPERATING_POINTS.json` 生成；"
      f"读冻结 detector_v2 的 {r['files']} 个 `LABELS.jsonl`（{r['pooled']['units']:,} 个已标单元），"
      "零前向、零 GPU。UNSAFE 边固定 ≥0.250s，格点 0.08s。")
    w("> **这是标签侧的天花板**（假设 gate 能完美预测真值误差），不是探测器实际达到的覆盖率；"
      "它回答的是「这个带边定义允许多少单元被自动放行」。")
    w("")
    w("## 0. 结论：把 SAFE 边从 100ms 推到 200ms，三个指标同时变好")
    w("")
    b100, b200 = nb["by_safe_edge"]["100ms"], nb["by_safe_edge"]["200ms"]
    w(f"- 产品口径（排除 {nb['excluded_files']} 两个 ~95% unsafe 的研究跑，"
      f"{nb['units']:,} 单元、真 unsafe {100 * nb['unsafe_share']:.2f}%）：")
    w("")
    L.extend(rows_of(nb))
    w("")
    w(f"- ⇒ SAFE ≤0.10s → ≤0.20s：**自动通过 {100 * b100['safe_share']:.2f}%→{100 * b200['safe_share']:.2f}%**"
      f"（+{(b200['safe_share'] - b100['safe_share']) * 100:.1f}pp），"
      f"**其中稳健 {100 * b100['robust_safe_share']:.2f}%→{100 * b200['robust_safe_share']:.2f}%**"
      f"（+{(b200['robust_safe_share'] - b100['robust_safe_share']) * 100:.1f}pp），"
      f"**待复核 {100 * b100['grey_share']:.2f}%→{100 * b200['grey_share']:.2f}%**；"
      "也就是说当前 100ms 边**既少放行、放行得又不确定**。")
    w(f"- 稳健性差异的根源：好系统里中位误差 40ms **小于** 80ms 格点，"
      f"≤100ms 放行的单元中有 {100 * (1 - b100['safe_share_robustness']):.1f}% 其实处在"
      f"「距带边不足一格」的刀尖区（带边移一格，占比摆 "
      f"{b100['swing_pp_if_edge_moved_one_quantum']:.1f}pp）。")
    w("")
    w("## 1. 对照口径")
    w("")
    w(f"### 全部 LABELS 合并（{po['units']:,} 单元，含两个坏研究跑，真 unsafe {100 * po['unsafe_share']:.2f}%）")
    w("")
    L.extend(rows_of(po))
    w("")
    w(f"### 留出 test 片（{ho['units']:,} 单元；探测器只在 train 上拟合过）")
    w("")
    L.extend(rows_of(ho))
    w("")
    w("- 三个口径的**形状完全一致**（100ms 稳健率 28.3–28.8%、200ms 95.2%），"
      "结论不是某个子集的巧合。")
    w("")
    w("## 2. 建议（供主线裁定，本会话未改生产 gate）")
    w("")
    w(f"1. **SAFE 边取 ≤0.200s（两格缓冲）**：自动通过 {100 * b200['safe_share']:.1f}%、"
      f"稳健率 {100 * b200['safe_share_robustness']:.0f}%、待复核 {100 * b200['grey_share']:.1f}%；"
      "比现状 ≤0.100s 在三个维度上都不更差；")
    w("2. **UNSAFE 保持 ≥0.250s**（第 33/34 轮已证该边格点稳定：刀尖 ≤3.1%、摆幅 ≤3.1pp）；"
      "于是 200–250ms 成为窄复核带，而 100ms 只作为**报告口径**保留；")
    w("3. 若担心 200ms 太松：可只对**产品链路真实伴奏普通话**放宽到 200ms，"
      "清唱/录音室仍用 100ms 报告 —— 但要注意第 21 轮的事实（伴奏域端点偏晚、清唱偏早），"
      "分域设边比单一全局边更合理；")
    w("4. gate 的**实际收益**仍取决于探测器预测质量（第 5 轮：SAFE 命中尚可、UNSAFE 仅 3–5% 召回），"
      "本轮只界定了「带边定义本身允许的上限」。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_gate_operating_points.py")
    w("PYTHONPATH=src python scripts/evaluation/report_gate_operating_points.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_label_noise_ceiling.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "gate_operating_points_metrics_v1", "audit": r,
         "headline": {
             "product_regime_units": nb["units"], "excluded_broken_runs": nb["excluded_files"],
             "true_unsafe_share": nb["unsafe_share"],
             "safe_100ms": {"auto_accept": b100["safe_share"], "robust": b100["robust_safe_share"],
                            "robustness": b100["safe_share_robustness"], "review": b100["grey_share"]},
             "safe_200ms": {"auto_accept": b200["safe_share"], "robust": b200["robust_safe_share"],
                            "robustness": b200["safe_share_robustness"], "review": b200["grey_share"]},
             "delta_auto_accept_pp": round(100 * (b200["safe_share"] - b100["safe_share"]), 2),
             "delta_robust_pp": round(100 * (b200["robust_safe_share"] - b100["robust_safe_share"]), 2),
             "delta_review_pp": round(100 * (b200["grey_share"] - b100["grey_share"]), 2),
             "recommendation": "SAFE <=0.200s with UNSAFE >=0.250s; keep 100ms as report-only",
             "caveat": "label-side ceiling; realised coverage depends on detector accuracy"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
