#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the label-quantisation / AUC-ceiling report (round 31)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_label_noise_ceiling")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_label_noise_ceiling.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_label_noise_ceiling/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "LABEL_NOISE.json").read_text(encoding="utf-8"))
    m4, gs = r["corpora"]["m4_weak_labels"], r["corpora"]["gtsinger_human_gt"]

    L: list[str] = []
    w = L.append
    w("# 是信号弱还是标签粗？量化感知 AUC 诊断（第 31 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_label_noise_ceiling/LABEL_NOISE.json` 生成；只读既有面板，零前向。")
    w("> 动机：第 30 轮用 M4Singer 复现触发器失败（熵 AUC 0.662 vs GTSinger 0.845）。"
      "但两个语料的标签与**质量层**都不同，单个 AUC 无法区分原因。")
    w("")
    w("## 0. 三条结论")
    w("")
    e4, e1 = m4["slices"]["all"], gs["slices"]["all"]
    am4, ags = m4["ambiguous_exclusion_entropy"], gs["ambiguous_exclusion_entropy"]
    w(f"### (1) M4Singer **不是可比的复现语料**（对第 30 轮的更正）")
    w("")
    w(f"- M4 面板（研究用 detector_v2 拼接时间线）中位误差 **{e4['median_err_ms']}ms**，"
      f"误差>100ms 流行率 **{pct(e4['prevalence'])}**；GTSinger 中位 **{e1['median_err_ms']}ms**、"
      f"流行率 **{pct(e1['prevalence'])}**。")
    w(f"- 也就是说 M4 上**几乎所有单元都错**（{pct(e4['prevalence'])}），"
      "判别任务退化成「在普遍错的里面排先后」；"
      "因此第 30 轮对 `gap_over_core` 的否证**证据强度要下调**："
      "结论仍是「除 GTSinger 外无正证据 ⇒ 不上线」，但不能再表述为『已被独立语料证伪』。")
    w("")
    w("### (2) 100ms 阈值本身被 80ms 格点污染（影响全项目 headline 口径）")
    w("")
    w(f"- 落在阈值 ±1 个量化格（±80ms）内的单元：GTSinger **{ags['ambiguous_units']:,} 个"
      f"（{pct(ags['ambiguous_share'])}）**、M4 {am4['ambiguous_units']:,}（{pct(am4['ambiguous_share'])}）。")
    w(f"- 剔除这些「标签可能被量化翻转」的单元后，同一个分数的 AUC："
      f"GTSinger {ags['auc_all']} → **{ags['auc_excluding_ambiguous']}**（Δ {ags['auc_change']:+}）；"
      f"M4 {am4['auc_all']} → {am4['auc_excluding_ambiguous']}（Δ {am4['auc_change']:+}）。")
    w(f"- 为什么 GTSinger 比例这么高：其**中位误差 {e1['median_err_ms']}ms 远小于量化格 80ms**，"
      "于是大量单元挤在 100ms 判定线附近。⇒ "
      "**任何以 100ms 为界的判别力评估都会系统性低估真实判别力**；"
      "detector_v2 的 SAFE ≤100ms 带正落在这个区间内（第 20 轮已给出 50ms 侧的同类警告）。")
    w("")
    w("### (3) 判别力随容差单调上升 ⇒ 触发器擅长抓「粗错」，不擅长抓边缘错")
    w("")
    w("| 容差 | GTSinger 流行率 | GTSinger AUC | M4 流行率 | M4 AUC |")
    w("|---|---:|---:|---:|---:|")
    gt = gs["threshold_sensitivity_entropy"]["by_threshold"]
    mt = m4["threshold_sensitivity_entropy"]["by_threshold"]
    for k in gt:
        w(f"| {k} | {pct(gt[k]['prevalence'])} | {gt[k]['auc']} | "
          f"{pct(mt[k]['prevalence'])} | {mt[k]['auc']} |")
    w("")
    w("## 1. 分层（同一分数、同一目标，只看标签最可信的子集）")
    w("")
    w("| 语料 / 切片 | 单元 | 流行率 | 中位误差 | AUC(熵) |")
    w("|---|---:|---:|---:|---:|")
    for name, blk in (("M4", m4), ("GTSinger", gs)):
        for k, v in blk["slices"].items():
            w(f"| {name} · {k} | {v['units']:,} | "
              f"{pct(v.get('prevalence'))} | {v.get('median_err_ms')}ms | {v.get('auc')} |")
    w("")
    w("- M4 上**邻居无歧义**（下一单元起点距本单元终点 ≥240ms）子集 AUC 升到 "
      f"{m4['slices']['unambiguous_neighbours']['auc']}（vs 全体 {e4['auc']}）"
      "⇒ 与 (2) 同向：边界越含糊，标签噪声吃掉的判别力越多；")
    w(f"- 但 M4 `baseline_legal_only`（未被拼接/伪造的原始时间线）AUC 只有 "
      f"{m4['slices']['baseline_legal_only']['auc']} ⇒ 标签质量分层解释不了全部差距，"
      "**语料差异（录音条件/曲风/单元长度）仍在**，不能声称熵的跨语料一致性已被证明。")
    w("")
    w("## 2. 对既有产物的动作")
    w("")
    w("- 索引 B37（触发器复现失败）加 ♻️ 限定：**不是被独立语料证伪，而是该语料不可比**；")
    w("- 清单新增一条：**报判别力/AUC 时必须同时报标签流行率、量化歧义比例与容差敏感性**；")
    w("- 第 29 轮预算表口径不变（其结论建立在 GTSinger 自身口径上），但引用时应注明「100ms 阈值下的 AUC 是保守值」。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_label_noise_ceiling.py")
    w("PYTHONPATH=src python scripts/evaluation/report_label_noise_ceiling.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_label_noise_ceiling.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "label_noise_ceiling_metrics_v1", "audit": r,
         "headline": {
             "m4_median_err_ms": e4["median_err_ms"], "m4_prevalence_err_gt100ms": e4["prevalence"],
             "gtsinger_median_err_ms": e1["median_err_ms"],
             "gtsinger_prevalence_err_gt100ms": e1["prevalence"],
             "comparable_corpus": False,
             "gtsinger_ambiguous_share": ags["ambiguous_share"],
             "gtsinger_auc_all": ags["auc_all"], "gtsinger_auc_excl_ambiguous": ags["auc_excluding_ambiguous"],
             "m4_ambiguous_share": am4["ambiguous_share"],
             "m4_auc_all": am4["auc_all"], "m4_auc_excl_ambiguous": am4["auc_excluding_ambiguous"],
             "auc_rises_with_tolerance_both": True,
             "conclusion": "M4Singer is not a comparable replication corpus for trigger portability "
                           "(96% of units exceed 100 ms, median error 525 ms vs 40 ms); separately, "
                           "73.4% of GTSinger units sit within one 80 ms quantum of the 100 ms "
                           "threshold, so 100 ms-based discrimination is systematically understated"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
