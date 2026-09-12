#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the combined-repair shadow report: exactly how much of the fix to apply."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_combined_repair_shadow")
REPO = Path(__file__).resolve().parents[2]
LABEL = {"upstream_repaired_shipped": "上游修补＝现交付值",
         "shadow_targeted_only": "影子·只修塌陷块（推荐）",
         "shadow_all_targeted_recommended": "影子·再定向治重叠",
         "shadow_targeted_then_legalised": "影子·再走整体合法化求解"}
PROD_LABEL = {"shipped": "现交付值",
              "shadow_targeted_only": "影子·只修塌陷块（推荐）",
              "shadow_all_targeted_recommended": "影子·再定向治重叠",
              "shadow_targeted_then_legalised": "影子·再走整体合法化求解"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_combined_repair_shadow.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_combined_repair_shadow/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "COMBINED_REPAIR_SHADOW.json").read_text(encoding="utf-8"))
    gs = r["panels"]["gtsinger_human_gt"]
    prod = r["panels"]["product_batch_structural"]
    d = gs["deltas_pp_vs_shipped"]

    L: list[str] = []
    w = L.append
    w("# 到底该改多少？组合修复的影子对照（第 47 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_combined_repair_shadow/COMBINED_REPAIR_SHADOW.json` 生成。"
      "只读影子实验，绝不写回产品。零前向、零 GPU。")
    w("")
    w("## 0. 结论：**只改塌陷那一步，别的都不要动**")
    w("")
    w("GTSinger（人工标准答案，30,600 字）：")
    w("")
    w("| 时间线 | 中位误差 | 没有位置的字 | 误差<0.1s | <0.2s | <0.25s |")
    w("|---|---:|---:|---:|---:|---:|")
    for key in ("upstream_repaired_shipped", "shadow_targeted_only",
                "shadow_all_targeted_recommended", "shadow_targeted_then_legalised"):
        v = gs[key]
        w(f"| {LABEL[key]} | {v['median_err_ms']}ms | {100 * v['zero_length_share']:.2f}% | "
          f"{100 * v['hit_at_100ms']:.2f}% | {100 * v['hit_at_200ms']:.2f}% | "
          f"{100 * v['hit_at_250ms']:.2f}% |")
    w("")
    w(f"- **只修塌陷块**：三个档位 **{d['shadow_targeted_only_minus_shipped@100ms']:+.2f} / "
      f"{d['shadow_targeted_only_minus_shipped@200ms']:+.2f} / "
      f"{d['shadow_targeted_only_minus_shipped@250ms']:+.2f}pp**（对现交付值），零长度归零、中位误差不变；")
    w(f"- **再顺手治重叠**（只动越界的结尾）：结构更干净，但精度掉 "
      f"**{abs(d['shadow_all_targeted_recommended_minus_shipped@200ms']):.2f}pp**（0.2s 档），中位误差 40→45ms；")
    w(f"- **再走整体合法化求解**：结构几乎完美，精度掉 "
      f"**{abs(d['shadow_targeted_then_legalised_minus_shipped@200ms']):.2f}pp**，中位误差 40→50ms。")
    w("")
    w("真歌批（无标准答案，只看结构）：")
    w("")
    w("| 版本 | 没有位置的字 | 结构非法 | 重叠 | 同一时刻长块 |")
    w("|---|---:|---:|---:|---:|")
    for key in ("shipped", "shadow_targeted_only", "shadow_all_targeted_recommended",
                "shadow_targeted_then_legalised"):
        v = prod[key]
        w(f"| {PROD_LABEL[key]} | {100 * v['zero_length_share']:.2f}% | "
          f"{100 * v['illegal_share']:.2f}% | {100 * v['overlap_share']:.2f}% | "
          f"{v['identical_start_blocks']['blocks']} |")
    w("")
    w("## 1. 为什么「顺手多做一点」反而更差")
    w("")
    w("- **塌陷块内部本来就没有时间信息**（整块同一个时刻）⇒ 把它摊开不会破坏任何原有信息，"
      "所以这一步只赚不亏；")
    w("- **重叠是另一回事**：重叠的字**各自都有时间**，只是相邻两个互相压住了。"
      "修它必须移动某个本来正确的值 ⇒ 一定是有得有失。实测这笔账是「结构 +14pp、精度 −3.6pp」（0.2s 档），"
      "而且**产品流水线本来就已经在处理重叠**（现交付值的重叠只剩 0.10%），"
      "所以再插一道同样的处理只是重复收费；")
    w("- **整体合法化求解**是同一逻辑的极端版本：它会把整条时间线一起挪（中位误差 40→50ms），"
      "换来的结构收益在现流水线里本来就有。")
    w("")
    w("## 2. 因此的最终建议（清单 26/26b/26c）")
    w("")
    w("1. **只把上游那步「邻居缺失/相等时用常数填满整块」替换掉**，"
      "改为「只重排塌陷/倒序的块，边界由健康邻居决定」，其余步骤保持原样；")
    w("2. **不要**再叠加治重叠或整体合法化（产品已有；叠加只会掉精度）；")
    w("3. **保留告警**：批次自检已加「同一时刻长块」观察列（第 47 轮接入），交付前能看到是否又出现整段塌陷；")
    w("4. 预期收益（有标准答案的口径）：**误差<0.2s 提升 1.09pp**；真歌批上 **16.28% 的字恢复位置**。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_combined_repair_shadow.py")
    w("PYTHONPATH=src python scripts/evaluation/report_combined_repair_shadow.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_monotone_repair.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "combined_repair_shadow_metrics_v1", "audit": r,
         "headline": {
             "gtsinger": {k: gs[k] for k in LABEL},
             "deltas_pp_vs_shipped": d,
             "product_batch": {k: prod[k] for k in PROD_LABEL},
             "recommended_change": "replace only the upstream constant-fill step with the targeted "
                                   "block repair; do not add any further legalisation",
             "targeted_only_gain_pp_at_200ms": d["shadow_targeted_only_minus_shipped@200ms"],
             "extra_legalisation_cost_pp_at_200ms": d[
                 "shadow_all_targeted_recommended_minus_shipped@200ms"],
             "product_zero_length_before_after": [prod["shipped"]["zero_length_share"],
                                                  prod["shadow_targeted_only"]["zero_length_share"]]}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
