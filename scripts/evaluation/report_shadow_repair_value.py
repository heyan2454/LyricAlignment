#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the shadow-repair value report: does removing the collapse cost accuracy?"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_shadow_repair_value")
REPO = Path(__file__).resolve().parents[2]
LABEL = {"raw_argmax": "原始 argmax（不修补）",
         "upstream_repaired_shipped": "上游修补＝现交付值",
         "shadow_min_duration": "影子·全时间线重排",
         "shadow_targeted_blocks": "影子·只修塌陷块"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_shadow_repair_value.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_shadow_repair_value/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "SHADOW_REPAIR_VALUE.json").read_text(encoding="utf-8"))
    gs = r["panels"]["gtsinger_human_gt"]
    prod = r["panels"]["product_batch_structural"]
    d = gs["paired_deltas_pp"]

    L: list[str] = []
    w = L.append
    w("# 修掉零长度塌陷要付多少代价？影子修复的三方对照（第 46 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_shadow_repair_value/SHADOW_REPAIR_VALUE.json` 生成。"
      "**只读实验**：影子修复从不写回产品；GTSinger 有人工词级真值，真歌批只做结构审计。零前向、零 GPU。")
    w("")
    w("## 0. 结论：**一刀切修不好，定向修几乎免费**")
    w("")
    w("在 GTSinger（人工真值，30,600 单元）上比较四种时间线：")
    w("")
    w("| 时间线 | 中位误差 | 零长度 | hit@100ms | hit@200ms | hit@250ms |")
    w("|---|---:|---:|---:|---:|---:|")
    for key in ("raw_argmax", "upstream_repaired_shipped", "shadow_min_duration",
                "shadow_targeted_blocks"):
        v = gs["variants"][key]
        w(f"| {LABEL[key]} | {v['median_err_ms']}ms | {100 * v['zero_length_share']:.2f}% | "
          f"{100 * v['hit_at_100ms']:.2f}% | {100 * v['hit_at_200ms']:.2f}% | "
          f"{100 * v['hit_at_250ms']:.2f}% |")
    w("")
    w(f"- **一刀切（把整条时间线按最小时长重排）是错的**：零长度确实变 0%，但中位误差从 40ms 涨到 46ms，"
      f"hit@200ms 掉到 {100 * gs['variants']['shadow_min_duration']['hit_at_200ms']:.2f}%"
      f"（比现交付值低 {abs(d['shadow_min_duration_minus_upstream_repaired_shipped@200ms']):.2f}pp）"
      "——它把本来正确的字也重新排了，属于**用精度换结构**；")
    w(f"- **定向修复（只重排塌陷/倒序的块）几乎免费**：零长度 **0%**，中位误差仍是 **40ms**，"
      f"hit@200ms **{100 * gs['variants']['shadow_targeted_blocks']['hit_at_200ms']:.2f}%**"
      f"（比现交付值 **+{d['shadow_targeted_blocks_minus_upstream_repaired_shipped@200ms']:.2f}pp**，"
      f"比不修补的原始 argmax {d['shadow_targeted_blocks_minus_raw_argmax@200ms']:+.2f}pp）；"
      f"100ms 与 250ms 上同样是 **+{d['shadow_targeted_blocks_minus_upstream_repaired_shipped@100ms']:.2f}pp** 与 "
      f"**+{d['shadow_targeted_blocks_minus_upstream_repaired_shipped@250ms']:.2f}pp**。")
    w(f"- 道理很直白：塌陷块内部**本来就没有可用时间信息**（整块同一时刻），把它在两个健康邻居之间"
      "重新摊开，不会破坏任何原本存在的信息；而全时间线重排会动到不需要动的部分。")
    w("")
    w("## 1. 真歌批（无真值，只看结构）")
    w("")
    w("| 变体 | 零长度占比 | 结构非法占比 | 同一起点块（≥5） | 最大块 |")
    w("|---|---:|---:|---|---:|")
    for key, lbl in (("shipped", "现交付值"), ("shadow_from_raw", "影子·全时间线重排"),
                     ("shadow_targeted", "影子·只修塌陷块")):
        v = prod[key]
        b = v["identical_start_blocks"]
        w(f"| {lbl} | {100 * v['zero_length_share']:.2f}% | {100 * v['illegal_share']:.2f}% | "
          f"{b['blocks']} 块 / {b['units']} 字 | {b['largest']} |")
    w("")
    w("- 定向修复把零长度 **16.28% → 0.00%**、同一起点块 **16 → 0**（最大 199 字 → 0）；")
    w("- 残余非法率（13.62%）**全部是继承自原始阶段的重叠/起点回退**（原始阶段：重叠 11.36%、"
      "起点回退 6.57%、非法合计 24.35%；定向修复后：重叠 9.44%、起点回退 4.16%）——"
      "**定向修复没有新增任何一类违规**；")
    w("- 对照：把现交付值交给既有的联合合法化求解（`structural_compliance.repair`）后，"
      "非法率能降到 0，但**零长度仍是 16.28%** ⇒ **两处修复互补**，正确顺序是"
      "**先定向修复塌陷 → 再走既有的联合合法化**。")
    w("")
    w("## 2. 对修法建议的更新（清单第 26 条）")
    w("")
    w("1. **不要**把上游修补替换成「全时间线最小时长重排」——实测掉 ~4pp；")
    w("2. **要**只在检测到「同一起点连续 ≥2 字」或「结束不晚于开始」的块上重排，块边界由健康邻居决定；")
    w("3. 顺序：定向修复 → 既有联合合法化（治重叠/起点回退）→ 交付前结构自检告警；")
    w("4. 预期收益（有人工真值的口径）：hit@200ms **+1.09pp**、hit@250ms **+1.01pp**，"
      "同时在真歌批上消除 16.28% 的「没有位置的字」。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_shadow_repair_value.py")
    w("PYTHONPATH=src python scripts/evaluation/report_shadow_repair_value.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_monotone_repair.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "shadow_repair_value_metrics_v1", "audit": r,
         "headline": {
             "gtsinger_variants": gs["variants"],
             "paired_deltas_pp": gs["paired_deltas_pp"],
             "product_shipped_zero_share": prod["shipped"]["zero_length_share"],
             "product_targeted_zero_share": prod["shadow_targeted"]["zero_length_share"],
             "product_shipped_identical_blocks": prod["shipped"]["identical_start_blocks"],
             "product_targeted_identical_blocks": prod["shadow_targeted"]["identical_start_blocks"],
             "blanket_repair_costs_accuracy_pp": d[
                 "shadow_min_duration_minus_upstream_repaired_shipped@200ms"],
             "targeted_repair_gain_vs_shipped_pp": {
                 "hit100": d["shadow_targeted_blocks_minus_upstream_repaired_shipped@100ms"],
                 "hit200": d["shadow_targeted_blocks_minus_upstream_repaired_shipped@200ms"],
                 "hit250": d["shadow_targeted_blocks_minus_upstream_repaired_shipped@250ms"]},
             "conclusion": "a blanket minimum-duration re-space removes zero-length but costs ~4pp at "
                           "200 ms; a TARGETED repair restricted to collapsed/inverted blocks removes "
                           "100 % of zero-length at no measurable accuracy cost and beats the shipped "
                           "upstream output by ~1pp at every sound tolerance"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
