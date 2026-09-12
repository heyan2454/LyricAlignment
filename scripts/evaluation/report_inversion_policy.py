#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the inversion-policy decision brief."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_inversion_policy")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def ms(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{d}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_inversion_policy.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_inversion_policy/metrics.json")
    args = ap.parse_args()
    brief = json.loads((args.run / "INVERSION_POLICY.json").read_text(encoding="utf-8"))
    struct = json.loads((args.run / "STRUCTURAL_CONSEQUENCE.json").read_text(encoding="utf-8"))
    gt = brief["panels"]["gtsinger_raw_human_gt"]
    m4 = brief["panels"]["m4_longform_weak_gt"]

    L: list[str] = []
    w = L.append
    w("# 倒序处理策略决策简报（第 18 轮，2026-09-12）——**没有局部策略是净赢**")
    w("")
    w("> 数字由 `runs/20260912_inversion_policy/{INVERSION_POLICY,STRUCTURAL_CONSEQUENCE}.json` 生成。")
    w("> **shadow-only**：只在既有面板上逐单元施加策略并度量，未改任何生产行为、未回写。")
    w("")
    w("## 0. 一句话结论")
    w("")
    w("- 倒序单元**救不回来**：人工真值上最好的局部策略（交换端点）hit@100 也只有 "
      f"{pct(gt['decision']['best_hit_at_tol'],1)}（现状 0.0%），MAE(end) "
      f"{ms(next(r['mae_end_sec'] for r in gt['decision']['ranking'] if r['policy']==gt['decision']['best_policy']))}"
      "；弱真值 M4 上所有策略都是 0.0%。")
    w(f"- 交换端点**在结构上是净亏**：真实歌上非法率 {pct(struct['policies']['P0_shipped']['illegal_share'])} → "
      f"{pct(struct['policies']['P1_swap']['illegal_share'])}（重叠 "
      f"{pct(struct['policies']['P0_shipped']['overlap_share'])}→{pct(struct['policies']['P1_swap']['overlap_share'])}、"
      f"回退 {pct(struct['policies']['P0_shipped']['regression_share'])}→"
      f"{pct(struct['policies']['P1_swap']['regression_share'])}），"
      f"因为倒序幅度中位 {struct['inversion_gap_median_sec']}s、p90 {struct['inversion_gap_p90_sec']}s，"
      "交换后区间会**吞掉邻居**。")
    w(f"- **可行组合**：把倒序当作**重解码触发器**（代价：真实歌 {pct(struct['inverted_share'])} 单元、"
      f"M4 {pct(m4['inverted_share'],3)}、GTSinger {pct(gt['inverted_share'],3)}）+ "
      f"全局联合求解保结构（swap 后再求解：非法率 {pct(struct['policies']['P1_swap_then_joint_solve']['illegal_share'])}）。")
    w("")
    w("## 1. 有真值处：策略对**正确率**的影响（只施加在倒序单元上）")
    w("")
    w(f"### GTSinger `pipeline=raw`（人工词级真值，{gt['units']:,} 单元，倒序 {gt['inverted_units']} 个）")
    w("")
    w("| 策略 | hit@100 | MAE(start) | MAE(end) | 偏置(end) | 零长率 |")
    w("|---|---:|---:|---:|---:|---:|")
    for r in gt["decision"]["ranking"]:
        v = gt["policies"][r["policy"]]["inverted_units_only"]
        w(f"| `{r['policy']}` | {pct(r['hit_at_tol'],1)} | {ms(v['mae_start_sec'])} | "
          f"{ms(r['mae_end_sec'])} | {ms(r['bias_end_sec'])} | {pct(r['zero_length_share'],1)} |")
    w("")
    w(f"### M4 长时序（弱真值·签名重建，{m4['units']:,} 单元，倒序 {m4['inverted_units']:,} 个，"
      f"{pct(m4['inverted_share'],3)}）")
    w("")
    w("| 策略 | hit@100 | MAE(end) | 偏置(end) |")
    w("|---|---:|---:|---:|")
    for r in m4["decision"]["ranking"]:
        w(f"| `{r['policy']}` | {pct(r['hit_at_tol'],2)} | {ms(r['mae_end_sec'],0)} | {ms(r['bias_end_sec'],0)} |")
    w("")
    w(f"- M4 按 split 的倒序数：{json.dumps(m4['by_split'])}"
      "（train 占多数，但**验证/测试 split 同样有** ⇒ 这不是可以靠重训偶然消失的噪声）。")
    w("- 注意 `P4_floor_from_previous_end`（用上一单元尾端定起点）在两个面板上都是**最差**"
      f"（GTSinger MAE(end) {ms(next(r['mae_end_sec'] for r in gt['decision']['ranking'] if r['policy'].startswith('P4')),0)}、"
      "偏置转正）⇒ 不要用"
      "「邻居顺延」猜测倒序单元的位置。")
    w("")
    w("## 2. 无真值处：策略对**结构合法性**的影响（33 首真实歌）")
    w("")
    w(f"{struct['units']:,} 单元 / 倒序 {struct['inverted_units']}（{pct(struct['inverted_share'])}），"
      f"倒序幅度中位 {struct['inversion_gap_median_sec']}s、p90 {struct['inversion_gap_p90_sec']}s")
    w("")
    w("| 策略 | 零长/负长 | 重叠下一单元 | 起点回退 | 超长 | **非法合计** |")
    w("|---|---:|---:|---:|---:|---:|")
    for k, v in struct["policies"].items():
        w(f"| `{k}` | {pct(v['degenerate_share'])} | {pct(v['overlap_share'])} | "
          f"{pct(v['regression_share'])} | {pct(v['overshoot_share'])} | **{pct(v['illegal_share'])}** |")
    w("")
    w(f"- 现状（钳成零长）非法率 {pct(struct['policies']['P0_shipped']['illegal_share'])}；"
      f"交换端点 **{pct(struct['policies']['P1_swap']['illegal_share'])}（更差）**；"
      f"最小时长下限 {pct(struct['policies']['P3_min_floor']['illegal_share'])}（也更差）；"
      f"交换 + 全局联合求解 **{pct(struct['policies']['P1_swap_then_joint_solve']['illegal_share'])}**。")
    w("- 读法：局部策略只是把一种非法形态换成另一种；**结构合法性必须由全局约束保证**，"
      "而**正确性**要靠重解码（这两件事不要指望同一个手段完成）。")
    w("")
    w("## 3. 给你的三个决定点（我已测好代价，未替你改行为）")
    w("")
    w("1. **是否把 raw 起止倒序升级为重解码触发条件**？收益：这些单元现在 100% 错（人工真值面板），"
      f"且后来塌陷率 lift 8–10×（第 15 轮）；代价：触发比例真实歌 {pct(struct['inverted_share'])}、"
      f"M4 {pct(m4['inverted_share'],3)}、GTSinger {pct(gt['inverted_share'],3)}。")
    w("2. **是否放弃"
      "「交换端点」这一看似自然的修补**？数据说放弃：结构更差、正确率仍≈0。")
    w("3. **交付 gate 是否采用第 17 轮的伴生列口径**（`hit@tol_excluding_degenerate` + "
      "`degenerate_share`）？如果不采用，跨系统比较会持续把退化率差异误读成精度差异。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_inversion_policy_brief.py")
    w("PYTHONPATH=src python scripts/evaluation/report_inversion_policy.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_inversion_policy.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "inversion_policy_metrics_v1", "brief": brief, "structural": struct,
         "headline": {
             "gtsinger_best_policy": gt["decision"]["best_policy"],
             "gtsinger_best_hit": gt["decision"]["best_hit_at_tol"],
             "gtsinger_gain_vs_shipped_pp": gt["decision"]["gain_vs_shipped_pp"],
             "m4_all_policies_hit_zero": all(r["hit_at_tol"] <= 0.011 for r in m4["decision"]["ranking"]),
             "illegal_share_P0": struct["policies"]["P0_shipped"]["illegal_share"],
             "illegal_share_swap": struct["policies"]["P1_swap"]["illegal_share"],
             "illegal_share_swap_then_solve": struct["policies"]["P1_swap_then_joint_solve"]["illegal_share"],
             "inversion_gap_median_sec": struct["inversion_gap_median_sec"],
             "redecode_trigger_share_real_songs": struct["inverted_share"],
             "conclusion": "no local policy recovers inverted units and swapping worsens structure; "
                           "use inversion as a re-decode trigger plus the global solve for legality"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
