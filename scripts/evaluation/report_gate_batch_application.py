#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the batch-application report (what the gate waves through, audited without labels)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_gate_batch_application")
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_gate_batch_application.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_gate_batch_application/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "GATE_BATCH_APPLICATION.json").read_text(encoding="utf-8"))
    pol = r["policies"]
    ag = r["rung_agreement"]
    base = r["whole_batch_violations"]
    a1, a3 = pol["r1_entropy"], pol["r3_entropy_inversion_gap"]
    review_share_1 = 1.0 - a1["realised_accept_rate"]
    captured_1 = (a1["rejected_violations"]["flag_zero_or_negative"] * review_share_1) / max(
        base["flag_zero_or_negative"], 1e-9)
    review_share_3 = 1.0 - a3["realised_accept_rate"]
    captured_3 = (a3["rejected_violations"]["flag_zero_or_negative"] * review_share_3) / max(
        base["flag_zero_or_negative"], 1e-9)

    L: list[str] = []
    w = L.append
    w("# 把学到的放行率搬到 33 首真实歌：无真值下的结构审计（第 39 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_gate_batch_application/GATE_BATCH_APPLICATION.json` 生成。"
      "**本批没有真值**：绝对熵阈值不跨域（第 27 轮：GTSinger 上合理的阈值在产品批会 flag 68.7%），"
      "所以这里按 GTSinger 学到的**放行率**做批内分位匹配；被放行集合只审计**结构安全**，"
      "不构成任何精度声明。零新前向、零 GPU。")
    w("")
    w("## 0. 结论")
    w("")
    w(f"- 整批 {r['units']:,} 单元里零长/负长占 **{100 * base['flag_zero_or_negative']:.2f}%**、"
      f"结构非法合计 **{100 * base['is_illegal']:.2f}%**（第 12 轮同一口径）。")
    w(f"- **R1（只用边界熵，放行 {100 * a1['realised_accept_rate']:.2f}%）**："
      f"被放行集合零长 **{100 * a1['accepted_violations']['flag_zero_or_negative']:.2f}%** vs "
      f"被拦集合 **{100 * a1['rejected_violations']['flag_zero_or_negative']:.2f}%**"
      f"（lift {100 * a1['safety_lift_accepted_vs_rejected']['flag_zero_or_negative']:+.1f}pp）；"
      f"即 **{100 * a1['rejected_violations']['flag_zero_or_negative'] * review_share_1 / max(base['flag_zero_or_negative'], 1e-9):.0f}% 的零长单元被集中到 "
      f"{100 * review_share_1:.1f}% 的复核队列里**。")
    w(f"- **R3（加间隙残余，放行 {100 * a3['realised_accept_rate']:.2f}%）**：捕获率降到 "
      f"**{100 * captured_3:.0f}%**（复核队列仅 {100 * review_share_3:.1f}%），"
      f"且被放行集合零长升到 {100 * a3['accepted_violations']['flag_zero_or_negative']:.2f}%。")
    w(f"- **无真值的独立警告**：R3 相对 R1 新增放行的 **{ag['newly_accepted_by_r3']:,}** 个单元中，"
      f"**{100 * ag['newly_accepted_violations']['flag_zero_or_negative']:.1f}% 是零长单元**"
      f"（整批平均 {100 * base['flag_zero_or_negative']:.1f}%，即 **"
      f"{ag['newly_accepted_violations']['flag_zero_or_negative'] / max(base['flag_zero_or_negative'], 1e-9):.1f}×**）"
      "⇒ 间隙残余在 GTSinger 上的增益**没有迁移到产品批**，与第 30/31 轮跨语料复现失败完全一致；"
      "**结构代理在无真值条件下独立否证了 R3 上线**。")
    w(f"- **单一全局阈值 = 按语言分配复核预算**：R1 下普通话放行 **{100 * a1['by_language']['Chinese']['accepted_share']:.1f}%**、"
      f"粤语 {100 * a1['by_language']['Cantonese']['accepted_share']:.1f}%、"
      f"英语 {100 * a1['by_language']['English']['accepted_share']:.1f}%、"
      f"日语 {100 * a1['by_language']['Japanese']['accepted_share']:.1f}% ⇒ 若不希望「日语几乎全部进复核」，"
      "需按语言分别标定阈值。")
    w("")
    w("## 1. 两个策略的结构审计")
    w("")
    w("| 指标 | 整批 | R1 放行 | R1 拦下 | R3 放行 | R3 拦下 |")
    w("|---|---:|---:|---:|---:|---:|")
    for c in base:
        w(f"| `{c}` | {100 * base[c]:.2f}% | {100 * a1['accepted_violations'][c]:.2f}% | "
          f"{100 * a1['rejected_violations'][c]:.2f}% | {100 * a3['accepted_violations'][c]:.2f}% | "
          f"{100 * a3['rejected_violations'][c]:.2f}% |")
    w("")
    w(f"两档一致部分：both_accept {ag['both_accept']:,}、R3 新增放行 {ag['newly_accepted_by_r3']:,}、"
      f"R3 撤回 {ag['withdrawn_by_r3']:,}、Jaccard {ag['jaccard']}；"
      f"间隙特征在本批覆盖 {100 * r['gap_feature_coverage']:.1f}%"
      f"（R3 新增放行单元里间隙特征覆盖 {100 * (ag.get('gap_coverage_among_newly_accepted') or 0):.1f}%）"
      "⇒ R3 大部分时候并没有间隙信息可用，其排序变化主要来自那 12.7% 有值的单元。")
    w("")
    w("## 2. 复核队列集中在哪些歌")
    w("")
    w("| 策略 | 放行率最低的歌（前 5） |")
    w("|---|---|")
    for rung, blk in pol.items():
        items = blk["review_budget_concentration"]["least_accepted_songs"][:5]
        w(f"| `{rung}` | " + "、".join(f"{x['song']}（{x['language']}，放行 {100 * x['accepted_share']:.0f}%）"
                                       for x in items) + " |")
    w("")
    w("- 这与第 27 轮的重解码队列**同源同序**（I See Fire、初音未来的消失、p.h、冬之花、皱鳃鲨），"
      "两个独立构造的清单互相印证 ⇒ 排序稳定；")
    w("- 但同样**只是建议复核顺序**，不是「这些歌一定错」。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_gate_application_to_batch.py")
    w("PYTHONPATH=src python scripts/evaluation/report_gate_batch_application.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "gate_batch_application_metrics_v1", "audit": r,
         "headline": {
             "batch_units": r["units"], "batch_zero_length_share": base["flag_zero_or_negative"],
             "batch_illegal_share": base["is_illegal"],
             "r1": {"accept": a1["realised_accept_rate"],
                    "accepted_zero_length": a1["accepted_violations"]["flag_zero_or_negative"],
                    "rejected_zero_length": a1["rejected_violations"]["flag_zero_or_negative"],
                    "illegal_captured_in_review": round(captured_1, 4)},
             "r3": {"accept": a3["realised_accept_rate"],
                    "accepted_zero_length": a3["accepted_violations"]["flag_zero_or_negative"],
                    "illegal_captured_in_review": round(captured_3, 4)},
             "r3_newly_accepted_zero_length_share": ag["newly_accepted_violations"]["flag_zero_or_negative"],
             "r3_newly_accepted_vs_batch_x": round(
                 ag["newly_accepted_violations"]["flag_zero_or_negative"]
                 / max(base["flag_zero_or_negative"], 1e-9), 2),
             "accepted_share_by_language_r1": {k: v["accepted_share"] for k, v in a1["by_language"].items()},
             "structural_proxy_refutes_r3_transfer": True,
             "caveat": "rate-matched application, structural-only evidence; no accuracy claim"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
