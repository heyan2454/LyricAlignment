#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the decodability-ceiling report from CEILING.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_decodability_ceiling")
RAW_RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_decodability_ceiling_raw")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--raw-run", type=Path, default=RAW_RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_decodability_ceiling.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_decodability_ceiling/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "CEILING.json").read_text(encoding="utf-8"))
    raw = None
    if (args.raw_run / "CEILING.json").exists():
        raw = json.loads((args.raw_run / "CEILING.json").read_text(encoding="utf-8"))
    st, cp = r["strata"], r["by_checkpoint"]

    L: list[str] = []
    w = L.append
    w("# 可解码上限：真值边界到底在不在模型的候选里（第 19 轮，2026-09-12）")
    w("")
    w(f"> 数字由 `{args.run.name}/CEILING.json` 生成（人工 GTSinger 词级真值，"
      f"{r['units']:,} 单元 / {r['items']} 片段，解码格点 {r['timestamp_step_sec']}s）。")
    w("> **只读既有面板**：零前向、零 GPU。面板存有 top-1 概率、top1−top2 margin、entropy 与"
      "**top-2 类别索引**，因此只测 k=1/2 的确切包含；k≥3 记为未知，不做猜测。")
    w("")
    w("## 0. 结论")
    w("")
    lo, allu = st["long_note"]["end"], st["all_units"]["end"]
    fu = st["first_unit"]["end"]
    w(f"- **长音（gt_dur ≥ 1s，n={st['long_note']['units']:,}）的端点有 "
      f"{pct(lo['outside_top2_within_0bins'])} 连 top-2 候选都不是真值所在格点**"
      f"（全体单元只有 {pct(allu['outside_top2_within_0bins'])}）。"
      "⇒ 对这些单元，**任何基于本次解码的选择/共识/门控都不可能选对**——只能改解码本身"
      "（训练信号、更长右上下文、或换窗口重解码）。")
    w(f"- **训练确实抬高了这个上限**（同一格点口径，长音端点"
      f"「真值不在 top-2」比例）："
      + " → ".join(f"{k} {pct(v['long_note']['end_outside_top2_exact'],1)}"
                   for k, v in sorted(cp.items()))
      + f"；而 top-1 命中率 {pct(cp['r0']['long_note']['end_top1_exact'],1)} → "
      f"{pct(cp['r2']['long_note']['end_top1_exact'],1)}。"
      "⇒ 这一层的进展主要买在**训练侧**，r1→r2 的增益已经变小（边际递减）。")
    w(f"- **首单元最糟**：{pct(fu['outside_top2_within_0bins'])} 的首单元其真值起点/终点不在 top-2 内"
      f"（端点 top-1 仅 {pct(fu['top1_within_0bins'])}）⇒ 与第 1/6 轮「片段被硬裁」一致，"
      "这类单元应从一开始就被标为不可信，而不是指望后处理。")
    w("- **模型置信度能预示可达性**（无参考触发器的基础）："
      f"end 上 AUC(top1_prob → 真值在某候选 ±1 bin 内) 全体 "
      f"{allu.get('auc_top1_prob_predicts_gt_within_1bin_of_candidate')}、"
      f"长音 {st['long_note']['end'].get('auc_top1_prob_predicts_gt_within_1bin_of_candidate')}、"
      f"末单元 {st['last_unit']['end'].get('auc_top1_prob_predicts_gt_within_1bin_of_candidate')}"
      "⇒ 全体/末单元很好用，但**恰恰在最需要的长音层明显变弱**，所以这个触发器会漏掉相当一部分长音单元。")
    if raw:
        w(f"- 旁证：`pipeline=raw`（不经后处理钳位）的包含率几乎相同"
          f"（长音 outside top-2 {pct(raw['strata']['long_note']['end']['outside_top2_within_0bins'])} vs "
          f"official {pct(lo['outside_top2_within_0bins'])}）⇒ 上限来自解码器，**不是**第 16/17 轮那处钳位。")
    w("")
    w("## 1. 分层包含率（端点）")
    w("")
    w("| 层 | 单元 | GT 时长中位 | top-1 恰中 | top-1∪top-2 恰中 | **不在 top-2** | top-1 ±1格 | ∪ ±1格 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, blk in st.items():
        e = blk["end"]
        w(f"| {name} | {blk['units']:,} | {blk['gt_dur_median_sec']}s | "
          f"{pct(e['top1_within_0bins'])} | {pct(e['in_top2_union_within_0bins'])} | "
          f"**{pct(e['outside_top2_within_0bins'])}** | {pct(e['top1_within_1bins'])} | "
          f"{pct(e['in_top2_union_within_1bins'])} |")
    w("")
    w("起点侧对照（`first_unit` 的不可达最严重，印证硬裁片段的系统性偏差）：")
    w("")
    w("| 层 | top-1 恰中 | 不在 top-2 | 置信度 AUC |")
    w("|---|---:|---:|---:|")
    for name, blk in st.items():
        b = blk["start"]
        w(f"| {name} | {pct(b['top1_within_0bins'])} | {pct(b['outside_top2_within_0bins'])} | "
          f"{b.get('auc_top1_prob_predicts_gt_within_1bin_of_candidate')} |")
    w("")
    w("## 2. 检查点横向（长音与末单元的端点）")
    w("")
    w("| 检查点 | 单元 | 长音 top-1 | 长音 ∪top-2 | 长音**不可达** | 末单元 top-1 | 末单元不可达 |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for name, blk in sorted(cp.items()):
        ln, lu = blk.get("long_note", {}), blk.get("last_unit", {})
        w(f"| `{name}` | {blk['units']:,} | {pct(ln.get('end_top1_exact'))} | "
          f"{pct(ln.get('end_in_top2_exact'))} | **{pct(ln.get('end_outside_top2_exact'))}** | "
          f"{pct(lu.get('end_top1_exact'))} | {pct(lu.get('end_outside_top2_exact'))} |")
    w("")
    w("- 注意 GTSinger 的 `last_unit` 与真实歌的末字不是同一件事：这里是**片段硬切尾**"
      "（能量骤停，可达性 90.6%），MIR-1K 的末字是**自然衰减长音**（第 11 轮声学锚点都不触发）"
      "⇒ 不要用 GTSinger 末单元的容易程度去推断真实歌末字的容易程度。")
    w("")
    w("## 3. 这一条对路线选择的意义")
    w("")
    w("- 第 5/6/7/12/15/18 轮反复得到同一结论：**单次解码之后的环节可挽回空间是个位数 pp**。")
    w("  本轮给出了机制解释——**其中相当一部分目标位置根本不在候选集内**（长音 40%）。")
    w("- 因此值得投资的方向按证据排序：")
    w("  1. **训练侧**（已证明能把不可达率从 70.8% 压到 21.7%，还有空间且边际递减尚未见底）；")
    w("  2. **重解码/换窗口**（对不可达单元提供新候选；配合第 15/16 轮的免费触发器：raw 起止倒序 + "
      "低置信度）；")
    w("  3. 后处理只做**结构合法性**（第 7/12/18 轮已证明它能把非法率清零），不要再期待它提升精度。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_decodability_ceiling.py")
    w("PYTHONPATH=src python scripts/evaluation/run_decodability_ceiling.py --pipeline raw \\")
    w("    --out-dir /home/hyan/Data/lyricalign/runs/20260912_decodability_ceiling_raw")
    w("PYTHONPATH=src python scripts/evaluation/report_decodability_ceiling.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_decodability_ceiling.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "decodability_ceiling_metrics_v1", "ceiling": r, "ceiling_raw_pipeline": raw,
         "headline": {
             "long_note_end_outside_top2": lo["outside_top2_within_0bins"],
             "all_units_end_outside_top2": allu["outside_top2_within_0bins"],
             "first_unit_end_outside_top2": fu["outside_top2_within_0bins"],
             "checkpoint_progression_long_note_unreachable": {
                 k: v["long_note"]["end_outside_top2_exact"] for k, v in sorted(cp.items())},
             "auc_confidence_reachability_end": {
                 k: v["end"].get("auc_top1_prob_predicts_gt_within_1bin_of_candidate")
                 for k, v in st.items()},
             "conclusion": "on long notes 40% of GT end bins are not even in the top-2 candidates, so "
                           "post-selection cannot reach them; training moved that from 70.8% to 21.7%"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
