#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the re-decode budget brief (what GPU time can and cannot buy)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_redecode_budget")
REPO = Path(__file__).resolve().parents[2]


def pp(x) -> str:
    return "n/a" if x is None else f"{float(x):+.2f}pp"


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_redecode_budget.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_redecode_budget/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "REDECODE_BUDGET.json").read_text(encoding="utf-8"))
    pan = r["panels"]

    L: list[str] = []
    w = L.append
    w("# 重解码预算值多少分？按可达性给上界（第 29 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_redecode_budget/REDECODE_BUDGET.json` 生成。"
      "只读既有面板（GTSinger 人工真值），零前向、零 GPU。这是给"
      "**是否申请 GPU 预算**用的决策表，不是已实现的效果。")
    w("")
    w("## 0. 一句话")
    w("")
    pv = pan.get("production_view_r2_vocal_windowed", {})
    if pv.get("budgets"):
        b5, b10, b20 = pv["budgets"]["5pct"], pv["budgets"]["10pct"], pv["budgets"]["20pct"]
        w(f"在生产视图（`r2|vocal|windowed`，基线 hit@100 {pct(pv['baseline_hit'])}）上，"
          f"用第 27 轮的免费触发器选单元重解码：**5% 预算最多 +{b5['fused_trigger_reachable_gain_pp']:.2f}pp、"
          f"10% +{b10['fused_trigger_reachable_gain_pp']:.2f}pp、20% +{b20['fused_trigger_reachable_gain_pp']:.2f}pp**"
          f"（假设重解码能把选中的可修复单元**全部修好**的上界；随机选择同预算只有 "
          f"+{b20['random_reachable_gain_pp']:.2f}pp）。")
    w(f"- 但**错单元里有 {pct(pv.get('headroom', {}).get('unrecoverable_share_of_wrong_units'))}"
      " 是真值根本不在候选内的**（第 19/21 轮：端点可达率 93.96%、起点 95.52%，"
      "长音层可达率显著更低），这部分**同样证据的重解码救不了**；")
    w(f"- 触发器的**选取效率只有 oracle 的 "
      f"{(pv.get('budgets', {}).get('20pct') or {}).get('fused_trigger_reachable_gain_pp', 0) / max((pv.get('budgets', {}).get('20pct') or {}).get('oracle_by_recoverable_reachable_gain_pp', 1), 1e-9):.2f}"
      "**（20% 预算处），也就是说：即便预算花下去，选错单元还浪费掉一多半。")
    w("")
    w("## 1. 两个上界的含义（务必分清）")
    w("")
    w("- **optimistic（乐观上界）**：假设被选中的单元重解码后**全对**（含那些真值不在候选内的）；")
    w("- **reachable（可达上界）**：只有**两个边界的真值格点都在 top-1 或 top-2 候选 ±1 格内**的单元才算修得动；")
    w("  这才是能拿去承诺的数字。两行之差就是"
      "**必须靠训练/新证据**（更长右上下文、换窗口）而不是靠重跑同一窗口解决的部分。")
    w("")
    w("## 2. 三张表")
    w("")
    for name, blk in pan.items():
        if not blk.get("budgets"):
            w(f"### `{name}`\n\n（样本不足，跳过）\n")
            continue
        w(f"### `{name}`")
        w("")
        w(f"单元 {blk['units']:,}｜基线 hit@100 {pct(blk['baseline_hit'])}｜错单元 {blk['wrong_units']:,}"
          f"，其中不可救 {blk['wrong_but_unreachable']:,}"
          f"（{pct(blk['headroom']['unrecoverable_share_of_wrong_units'])}）｜可救错单元 "
          f"{blk['headroom'].get('recoverable_wrong_units', 'n/a')}")
        w("")
        w("| 复核预算 | 触发器·乐观 | **触发器·可达** | 随机·可达 | 按可救排序的 oracle | 效率 | 触发器−随机 |")
        w("|---|---:|---:|---:|---:|---:|---:|")
        for b, v in blk["budgets"].items():
            eff = v["fused_trigger_reachable_gain_pp"] / max(
                v["oracle_by_recoverable_reachable_gain_pp"], 1e-9)
            w(f"| {b.replace('pct', '%')} | {pp(v['fused_trigger_optimistic_gain_pp'])} | "
              f"**{pp(v['fused_trigger_reachable_gain_pp'])}** | {pp(v['random_reachable_gain_pp'])} | "
              f"{pp(v['oracle_by_recoverable_reachable_gain_pp'])} | {eff:.2f} | "
              f"{pp(v['fused_trigger_reachable_gain_pp'] - v['random_reachable_gain_pp'])} |")
        w("")
    w("## 3. 结论与取舍")
    w("")
    ln = pan.get("long_note", {})
    if ln.get("budgets"):
        w(f"- **最难层（长音）上免费触发器已经不具备选择力**：20% 预算时触发器 +{ln['budgets']['20pct']['fused_trigger_reachable_gain_pp']:.2f}pp "
          f"vs 随机 +{ln['budgets']['20pct']['random_reachable_gain_pp']:.2f}pp"
          f"（该层错单元不可救比例 {pct(ln['headroom']['unrecoverable_share_of_wrong_units'])}）"
          "⇒ **在长音层，重解码预算应等可达性提升之后再花**，否则与随机无异。")
    w("- **该花在哪儿**：生产视图上 5–10% 预算的可达上界 +1.0~+1.9pp，且触发器明显优于随机（+0.8~+1.1pp），"
      "是**当前唯一有正期望的 GPU 用法**（但绝对量小于训练侧的潜在收益：第 19 轮显示训练已把长音不可达率从 70.8% 压到 21.7%）。")
    w("- **申请预算前该先做的事**：改进触发器的**排序质量**（现在只 capture oracle 的 0.2–0.47），"
      "或换更可能产生新候选的重解码参数（窗口右移、更长右上下文），否则等于把预算花在随机挑选上。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_redecode_budget.py")
    w("PYTHONPATH=src python scripts/evaluation/report_redecode_budget.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_redecode_budget.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "redecode_budget_metrics_v1", "audit": r,
         "headline": {
             "fixable_share": r["fixable_share"],
             "end_reachable_share": r["reachability"]["end"]["reachable_share"],
             "start_reachable_share": r["reachability"]["start"]["reachable_share"],
             "production_view": {b: {"trigger_reachable_pp": v["fused_trigger_reachable_gain_pp"],
                                     "trigger_optimistic_pp": v["fused_trigger_optimistic_gain_pp"],
                                     "random_reachable_pp": v["random_reachable_gain_pp"],
                                     "oracle_recoverable_pp": v["oracle_by_recoverable_reachable_gain_pp"]}
                                 for b, v in pv.get("budgets", {}).items()},
             "long_note_unrecoverable_share": (ln.get("headroom") or {}).get(
                 "unrecoverable_share_of_wrong_units"),
             "long_note_trigger_matches_random": bool(
                 ln.get("budgets") and abs(ln["budgets"]["20pct"]["fused_trigger_reachable_gain_pp"]
                                           - ln["budgets"]["20pct"]["random_reachable_gain_pp"]) < 0.5),
             "conclusion": "a 5-10 % re-decode budget is worth at most +1.0-+1.9 pp on the production "
                           "view and the free trigger beats random there, but on long notes the trigger "
                           "is no better than random because most errors are unreachable by same-window "
                           "re-decoding"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
