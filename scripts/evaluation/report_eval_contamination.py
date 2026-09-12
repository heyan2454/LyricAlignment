#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the eval-set contamination report (how much of a hit rate is the collapse).

NOTE for future editors: inside Chinese prose use 「」, never ASCII double quotes — mixing them has
broken this session's generators repeatedly, and automated fixers made it worse.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_eval_contamination")
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_eval_contamination.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_eval_contamination/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "EVAL_CONTAMINATION.json").read_text(encoding="utf-8"))

    L: list[str] = []
    w = L.append
    w("# 评测集里有多少误差其实是「没有位置的字」（第 50 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_eval_contamination/EVAL_CONTAMINATION.json` 生成；两个评测集都有人工真值，"
      "零前向、零 GPU。容差用 0.20s（第 31/32 轮已证 0.10s 档受 0.08s 格点污染，不可靠）。")
    w("")
    w("## 0. 结论")
    w("")
    w("- **两个评测集都被同一缺陷污染，量级不同**：")
    w("  - MIR-1K 的**基础模型**（未适配）最严重：20.15% 的字没有位置，去掉这些字后"
      "「误差<0.2s」从 **38.72% → 46.52%**；")
    w("  - 训练后的检查点轻得多，但并非无关：MIR-1K 上 0.25–0.59%、GTSinger 上 3.53–5.69%；")
    w("- **「去掉退化单元后的值」就是修复能给该指标带来的上限**（若那些字恢复到健康字的水准，"
      "整体指标至多等于健康子集的指标）。于是：")
    w("  - MIR-1K · r2_full：97.99% → **98.47%**（上限 +0.48pp）；r2_seed：98.23% → 98.62%；")
    w("  - GTSinger · r2：94.27% → **96.50%**（上限 **+2.23pp**）；r1：91.96% → 94.68%（+2.72pp）；"
      "r0：75.41% → 77.88%（+2.47pp）；")
    w("- **失败里有多少是这个缺陷**：GTSinger r2 的失败中 **41.1%**、r1 **36.6%**、r0 15.2%；"
      "MIR-1K 各检查点 7.1%–24.4%（r2_full 24.4%）。也就是说："
      "**我们过去报的精度里，有一部分其实在测量流水线的塌陷，而不是模型的时间判断能力。**")
    w("")
    for panel_name, zh in (("mir1k_human_gt", "MIR-1K（人工逐字真值）"),
                           ("gtsinger_human_gt", "GTSinger（人工词级真值）")):
        blk = r["panels"][panel_name]
        idx = "1" if "mir" in panel_name else "2"
        w(f"## {idx}. {zh}（{blk['units']:,} 单元）")
        w("")
        w("| 预测器 | 没有位置的字 | 误差<0.2s | 去掉这些字后（＝修复上限） | 这些字占失败的比例 | 最长连续块 |")
        w("|---|---:|---:|---:|---:|---:|")
        for name, v in blk["predictors"].items():
            w(f"| `{name}` | {100 * (v['degenerate_share'] or 0):.2f}% | "
              f"{100 * (v['hit_at_200ms'] or 0):.2f}% | "
              f"**{100 * (v['hit_at_200ms_excluding_degenerate'] or 0):.2f}%** | "
              f"{100 * (v['degenerate_share_of_misses_at_200ms'] or 0):.1f}% | "
              f"{v['identical_start_blocks']['longest_run']} |")
        w("")
    w("## 3. 这对结论与流程的含义")
    w("")
    w("1. **不能再把「现在的 hit@0.2s」直接当作模型能力**：至少 GTSinger r1/r2 的失败里有三分之一以上、"
      "MIR-1K 训练后检查点有四分之一左右来自这个结构缺陷；引用时应同时给「去掉退化单元」的并列值"
      "（这正是第 31 轮定的纪律，现在有了具体数字）；")
    w("2. **修复后的复测要同比**：修复会把这些字重新变成有位置的字，届时 hit@0.2s 会向上限靠拢——"
      "**不得**把这部分涨幅当成训练或模型的进步；")
    w("3. **基础模型的 20% 与 38.72% 解释了它的低分**：未适配模型的时间判断本来就弱，"
      "再叠加 20% 的结构塌陷，指标被压到 38.72%；去掉后 46.52% 仍不高，"
      "说明「适配」与「修塌陷」是两件独立且都需要做的事。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_eval_contamination.py")
    w("PYTHONPATH=src python scripts/evaluation/report_eval_contamination.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_label_noise_ceiling.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "eval_contamination_metrics_v1", "audit": r,
         "headline": {
             "mir1k": {k: {"degenerate_share": v["degenerate_share"],
                           "hit200": v["hit_at_200ms"],
                           "hit200_excl_degenerate": v["hit_at_200ms_excluding_degenerate"],
                           "degenerate_share_of_misses": v["degenerate_share_of_misses_at_200ms"]}
                       for k, v in r["panels"]["mir1k_human_gt"]["predictors"].items()},
             "gtsinger": {k: {"degenerate_share": v["degenerate_share"],
                              "hit200": v["hit_at_200ms"],
                              "hit200_excl_degenerate": v["hit_at_200ms_excluding_degenerate"],
                              "degenerate_share_of_misses": v["degenerate_share_of_misses_at_200ms"]}
                          for k, v in r["panels"]["gtsinger_human_gt"]["predictors"].items()},
             "ceiling_interpretation": "the excluding-degenerate value is the upper bound of what "
                                       "fixing the collapse can buy on that metric",
             "conclusion": "both human-GT evaluation sets are contaminated by the upstream collapse: "
                           "the untuned base model loses 7.80 pp at 0.2 s, tuned checkpoints 0.3-2.7 pp, "
                           "and degenerate units make up 7-41 % of their misses"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
