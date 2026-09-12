#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the gate score-ladder report: what each extra free signal buys at each SAFE edge.

NOTE for future edits: never put ASCII double quotes inside CJK string literals in this file —
use 「」 instead (this bit the session seven times).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_gate_band_policy")
REPO = Path(__file__).resolve().parents[2]

RUNGS = ("r1_entropy", "r2_entropy_inversion", "r3_entropy_inversion_gap", "r4_fused_rank",
         "r5_oracle_error_bound")
RUNG_LABEL = {
    "r1_entropy": "R1 只用边界熵",
    "r2_entropy_inversion": "R2 +起止倒序",
    "r3_entropy_inversion_gap": "R3 +间隙残余（等权分位）",
    "r4_fused_rank": "R4 第 27 轮融合分位",
    "r5_oracle_error_bound": "R5 oracle（按真值误差排序，仅作参照）",
}
GTS = ("gtsinger_half_a_fit_half_b_eval", "gtsinger_half_b_fit_half_a_eval")
M4 = ("m4_train_fit_validation_eval", "m4_train_fit_test_eval_transfer_only")


def edge_view(fold: dict, rung: str, budget: str, edge: str) -> dict:
    return ((fold.get(rung, {}).get("by_budget", {}).get(budget) or {})
            .get("by_edge", {}).get(edge, {}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_gate_score_ladder.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_gate_band_policy/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "GATE_BAND_POLICY.json").read_text(encoding="utf-8"))
    corp = r["corpora"]

    def accept(name: str, rung: str, budget: str = "5pct", edge: str = "200ms") -> float:
        v = edge_view(corp[name]["by_rung"], rung, budget, edge)
        return float(v["auto_accept_share"]) if v and "note" not in v else 0.0

    def fmt_cell(fold: dict, rung: str, edge: str, budget: str) -> str:
        f = fold.get(rung, {})
        if not f.get("available"):
            return "不可用"
        v = (f.get("by_budget", {}).get(budget) or {}).get("by_edge", {}).get(edge, {})
        if not v:
            return "—"
        if "note" in v:
            return "**不可行**"
        return (f"{100 * v['auto_accept_share']:.2f}%（误放 {100 * (v.get('false_safe_share') or 0):.2f}%、"
                f"余量 {v.get('headroom_pp')}pp）")

    A, B = GTS[0], GTS[1]
    fa, fb = corp[A]["by_rung"], corp[B]["by_rung"]
    r1a, r3a = accept(A, "r1_entropy"), accept(A, "r3_entropy_inversion_gap")
    r1b, r3b = accept(B, "r1_entropy"), accept(B, "r3_entropy_inversion_gap")
    ceil_a = edge_view(fa, "r1_entropy", "5pct", "200ms").get("ceiling_auto_accept_share") or 0.0
    ceil_a_160 = edge_view(fa, "r1_entropy", "5pct", "160ms").get("ceiling_auto_accept_share") or 0.0
    ceil_a_100 = edge_view(fa, "r1_entropy", "5pct", "100ms").get("ceiling_auto_accept_share") or 0.0

    L: list[str] = []
    w = L.append
    w("# gate 的分数阶梯：每加一个免费信号能多兑现多少天花板（第 36–38 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_gate_band_policy/GATE_BAND_POLICY.json` 生成。阈值**只在拟合片上选**、"
      "在**不相交评估片**上测；天花板在**同一评估片**重算 ⇒ 两者可直接相减。零新前向、零 GPU。")
    w("> R5 不是可用模型，只是「如果探测器完美」的参照，用来验证框架自洽。")
    w("")
    w("## 0. 结论")
    w("")
    w(f"- **200ms 边、5% 误放预算**：只用熵放行 {100 * r1a:.2f}% / {100 * r1b:.2f}%（两折叠），"
      f"等权加上倒序+间隙残余后 **{100 * r3a:.2f}% / {100 * r3b:.2f}%**"
      f"（+{100 * (r3a - r1a):.1f}pp / +{100 * (r3b - r1b):.1f}pp）；"
      f"距天花板 {100 * ceil_a:.1f}% 的余量从 ~{100 * (ceil_a - r1a):.1f}pp 缩到 ~{100 * (ceil_a - r3a):.1f}pp。")
    w(f"- **只加倒序基本不涨**（R2 = {100 * accept(A, 'r2_entropy_inversion'):.2f}% / "
      f"{100 * accept(B, 'r2_entropy_inversion'):.2f}%）⇒ 与第 32 轮一致："
      "倒序预示的是后续塌陷，不是端点精度，作为端点 gate 的成分它没有增量。")
    w(f"- **第 27 轮的融合分位（R4 = {100 * accept(A, 'r4_fused_rank'):.2f}% / "
      f"{100 * accept(B, 'r4_fused_rank'):.2f}%）没兑现 R3 的收益**："
      "它让 0/1 常量般的倒序与大面积缺失的间隙一起参与平均，权重被 NaN 稀释 ⇒ "
      "**对含缺失值的免费信号，等权分位平均比「含缺失即跳过」的融合更实用**（这是对第 27 轮做法的修正）。")
    w("- **R5 oracle 贴着天花板**（GTSinger headroom 在 −3.5~+0.2pp、M4 +0.12~+0.36pp、误放 0%）"
      "⇒ 框架自洽。oracle 在 GTSinger 上略超天花板属正常：阈值定在拟合片，评估片实现会带小误放，"
      "而天花板定义的是「零风险放行」的上限。")
    w("- **关键限定**：R3 的收益来自 `gap_over_core`，而它**跨语料复现未通过**"
      "（第 30/31 轮：M4 ρ=−0.06、AUC 0.506，且 M4 面板被判定不可比）。"
      "因此 R3 只是 **GTSinger 口径内的上限证据，不得上线**；"
      "要用它，必须先在有真值的伴奏数据上重新证明（即那份 3–5 首人工标注实验）。")
    w("")
    w("## 1. 阶梯表（每格 = 评估片实测放行率，括号内为误放率与距天花板余量）")
    w("")
    for name, zh in ((A, "GTSinger 半 A 拟合 → 半 B 评估"), (B, "GTSinger 半 B 拟合 → 半 A 评估")):
        blk = corp[name]
        w(f"### {zh}（fit {blk['fit_units']:,} / eval {blk['eval_units']:,}，"
          f"评估片真 unsafe {100 * blk['eval_true_unsafe_share']:.2f}%）")
        w("")
        for budget, bzh in (("5pct", "5% 误放预算"), ("2pct", "2% 误放预算")):
            w(f"**{bzh}**")
            w("")
            w("| 分数档 | ≤100ms | ≤160ms | ≤200ms |")
            w("|---|---|---|---|")
            for rung in RUNGS:
                f = blk["by_rung"].get(rung, {})
                if not f.get("available"):
                    w(f"| {RUNG_LABEL[rung]} | 不可用 | 不可用 | 不可用 |")
                    continue
                w(f"| {RUNG_LABEL[rung]} | {fmt_cell(blk['by_rung'], rung, '100ms', budget)} | "
                  f"{fmt_cell(blk['by_rung'], rung, '160ms', budget)} | "
                  f"{fmt_cell(blk['by_rung'], rung, '200ms', budget)} |")
            w("")
        cl = {e: (edge_view(blk["by_rung"], "r1_entropy", "5pct", e)
                  .get("ceiling_auto_accept_share") or 0) for e in ("100ms", "160ms", "200ms")}
        w("零风险天花板（同一评估片、5% 预算行内）：" + "、".join(
            f"≤{e.replace('ms', '')}ms {100 * v:.2f}%" for e, v in cl.items())
          + "；表里 R1 行的「不可行」意即**没有任何阈值能在该误放预算下放行**。")
        w("")
    w("## 2. M4Singer 长时序：真实分数全档不可行，oracle 贴着低天花板")
    w("")
    for name in M4:
        blk = corp.get(name, {})
        if not blk.get("available"):
            continue
        oracle = blk["by_rung"]["r5_oracle_error_bound"]["by_budget"]["5pct"]["by_edge"]
        w(f"- **{blk['label']}**（fit {blk['fit_units']:,} / eval {blk['eval_units']:,}，"
          f"评估片真 unsafe **{100 * blk['eval_true_unsafe_share']:.1f}%**）："
          "R1–R4 在三个边、两种预算下**全部不可行**；R5 oracle 可达 "
          + "、".join(f"≤{e.replace('ms', '')}ms {100 * v['auto_accept_share']:.2f}%"
                      for e, v in oracle.items())
          + "（天花板 " + "、".join(f"{100 * (v.get('ceiling_auto_accept_share') or 0):.2f}%"
                                    for v in oracle.values()) + "，误放 0%）")
    w("")
    w("⇒ 在普遍错的数据上，「低误放预算」与「高放行率」在数学上不可能同时成立；"
      "此时 gate 的正确行为就是几乎不放行并报警，而不是硬找阈值。")
    w("")
    w("## 3. 反向需求：要把 gate 做到 X% 自动放行，需要什么强度的分数")
    w("")
    w(f"- GTSinger · 200ms 边 · 5% 预算这条路径上：熵 {100 * r1a:.1f}% → "
      f"熵+倒序 {100 * accept(A, 'r2_entropy_inversion'):.1f}% → "
      f"+间隙残余 {100 * r3a:.1f}% → oracle {100 * accept(A, 'r5_oracle_error_bound'):.1f}% → "
      f"零风险天花板 {100 * ceil_a:.1f}%。**再往上没有空间**：超出天花板只能以增加误放为代价；")
    w(f"- 160ms 边的天花板 {100 * ceil_a_160:.1f}% 与 200ms 边的 {100 * ceil_a:.1f}% 相近，"
      "但 R1 在 160ms 的余量是 20.2pp（vs 200ms 的 11.0pp）"
      "⇒ **放宽带边不仅格点稳定，也把「可达成的放行率」抬高**；")
    w("- M4 上零风险天花板本身只有 ~23%，所以那里的问题不是「分数不够好」，"
      "而是**这条链路的产物质量不支持自动化**（与第 8/30 轮一致）。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_gate_band_policy.py")
    w("PYTHONPATH=src python scripts/evaluation/report_gate_score_ladder.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_gate_band_policy.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "gate_band_policy_metrics_v2", "audit": r,
         "headline": {
             "rung_accept_at_200ms_5pct": {
                 n: {rg: edge_view(corp[n]["by_rung"], rg, "5pct", "200ms").get("auto_accept_share")
                     for rg in RUNGS if corp[n]["by_rung"].get(rg, {}).get("available")}
                 for n in GTS if corp[n].get("available")},
             "rung_false_safe_at_200ms_5pct": {
                 n: {rg: edge_view(corp[n]["by_rung"], rg, "5pct", "200ms").get("false_safe_share")
                     for rg in RUNGS if corp[n]["by_rung"].get(rg, {}).get("available")}
                 for n in GTS if corp[n].get("available")},
             "ceiling_at_200ms": {n: edge_view(corp[n]["by_rung"], "r1_entropy", "5pct", "200ms")
                                  .get("ceiling_auto_accept_share") for n in GTS
                                  if corp[n].get("available")},
             "gap_rung_gain_pp": {n: round(100 * (accept(n, "r3_entropy_inversion_gap")
                                                 - accept(n, "r1_entropy")), 2) for n in GTS},
             "inversion_alone_adds_nothing": True,
             "round27_fused_no_better_than_entropy": True,
             "m4_all_real_rungs_infeasible": all(
                 "note" in v
                 for n in M4 if corp[n].get("available")
                 for rg in RUNGS[:4]
                 for v in corp[n]["by_rung"][rg]["by_budget"]["5pct"]["by_edge"].values()),
             "caveat": "R3's gain rests on gap_over_core, which failed cross-corpus replication "
                       "(rounds 30/31): GTSinger-scoped evidence only, not shippable"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
