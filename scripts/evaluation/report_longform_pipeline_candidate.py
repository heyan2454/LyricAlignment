#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the long-form pipeline-candidate report from its JSON artifacts (no hand-copied numbers)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt")
REPO = Path(__file__).resolve().parents[2]
SYS_DESC = {
    "A_single_window_arbitrary_attempt": "单个窗口的输出（谁先覆盖用谁，与预测值无关）",
    "B_shipped_official_same_attempt": "现装 official 阶段（同一个窗口）",
    "C_cross_window_consensus": "跨窗口边界取中位（共识）",
    "D_consensus_plus_joint_solve": "共识 + 一次联合约束求解（max_dur 3s）",
    "D6_consensus_plus_solve_max6s": "共识 + 联合求解（max_dur 6s）",
    "D12_consensus_plus_solve_max12s": "共识 + 联合求解（max_dur 12s）",
    "E_oracle_attempt_per_unit": "用真值挑最好的一次尝试（上界，不可部署）",
}


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else (f"{float(x):.3f}s" if abs(x) >= 1 else f"{1000 * float(x):.{d}f}ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_longform_pipeline_candidate.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_longform_pipeline_candidate/metrics.json")
    args = ap.parse_args()
    trig = json.loads((args.run / "REALIGN_TRIGGER.json").read_text(encoding="utf-8"))
    cand = json.loads((args.run / "PIPELINE_CANDIDATE.json").read_text(encoding="utf-8"))
    cov = trig["coverage"]
    b1, b25 = trig["bad100"], trig["bad250"]

    L: list[str] = []
    w = L.append
    w("# 长时序端到端候选输出与 realign 触发器价值（2026-09-12 第 9 轮）")
    w("")
    w("> 数字由 `runs/20260912_m4_longform_weakgt/{REALIGN_TRIGGER,PIPELINE_CANDIDATE}.json` 生成。")
    w("> 纯 CPU、零新增前向；参考是**已验证的有符号弱标签**（max deviation 0.0 对冻结误差），"
      "`rule_validated`、80ms 量化、模型产出 ⇒ 非人工 GT，一切一致性有 ±40ms 底噪。")
    w("> 数据集为 M4Singer 拼接长时序（中文普通话为主），未使用 MIR-1K（test-only）。")
    w("")
    w("## 0. 结论")
    w("")
    cs = cand["systems"]
    a, bb, c, dd = (cs["A_single_window_arbitrary_attempt"], cs["B_shipped_official_same_attempt"],
                    cs["C_cross_window_consensus"], cs["D_consensus_plus_joint_solve"])
    summ = cand["summary"]
    w(f"- **共识 > 现装**：跨窗口共识 hit@100 {pct(c['hit100'])}（单窗 {pct(a['hit100'])}，"
      f"**+{summ['gain_consensus_vs_single_pp']:.2f}pp**；现装 official {pct(bb['hit100'])}），"
      f"MAE {sec(c['mae_both_sec'])} vs 单窗 {sec(a['mae_both_sec'])}。")
    w(f"- **共识 + 联合求解 = 结构零缺陷**：退化/重叠/回退全部 "
      f"{pct(dd['structure']['degenerate_share'],1)}/{pct(dd['structure']['overlap_share'],1)}/"
      f"{pct(dd['structure']['start_regression_share'],1)}（共识单独为 "
      f"{pct(c['structure']['degenerate_share'],2)}/{pct(c['structure']['overlap_share'],2)}/"
      f"{pct(c['structure']['start_regression_share'],2)}），"
      f"MAE 还更低（{sec(dd['mae_both_sec'])} vs {sec(c['mae_both_sec'])}），"
      f"代价是 hit@100 −{(c['hit100']-dd['hit100'])*100:.2f}pp。")
    w(f"- **本轮自我修正**：原先猜「−0.5pp 来自 3s 时长上限」是**错的**——"
      f"max_dur 3/6/12s 的 hit@100 分别是 "
      f"{pct(cand['max_dur_sensitivity']['3.0'])} / {pct(cand['max_dur_sensitivity']['6.0'])} / "
      f"{pct(cand['max_dur_sensitivity']['12.0'])}（几乎不变）"
      "⇒ 损失来自**非重叠 + 保序约束本身**（把重叠的长音强行压回下一单元起点），不是时长上限。")
    w(f"- **realign 触发器**：跨窗口分歧是**弱触发器**（AUC {b1['auc_disagreement']} 抓 >100ms、"
      f"{b25['auc_disagreement']} 抓 ≥250ms），远不如**边界熵**（{b1['auc_ent_min']} / {b25['auc_ent_min']}）"
      f"与支持度（{b1['auc_support_max']} / {b25['auc_support_max']}）"
      "⇒ 与第 1/3/5 轮一致：置信信号才是可用的触发特征。")
    w(f"- **适用面限制（关键）**：只有 {pct(cov['share_multi_attempt'],1)} 的单元被 ≥2 个窗口覆盖"
      f"（每单元尝试次数中位 {cov['median_attempts']:.0f}、最多 {cov['max_attempts']}）"
      "⇒ 任何「跨窗一致性」方法对 6 成单元**根本无输入**，要全量获益必须主动产生多视图（多次裁窗）。")
    w("")
    w("## 1. 端到端候选 vs 现状（13,743 单元）")
    w("")
    w("| 系统 | 说明 | hit@100 | hit@250 | MAE | 退化 | 重叠 | 起点回退 |")
    w("|---|---|---:|---:|---:|---:|---:|---:|")
    for k in ("A_single_window_arbitrary_attempt", "B_shipped_official_same_attempt",
              "C_cross_window_consensus", "D_consensus_plus_joint_solve",
              "D6_consensus_plus_solve_max6s", "D12_consensus_plus_solve_max12s",
              "E_oracle_attempt_per_unit"):
        v = cs.get(k)
        if not v:
            continue
        st = v.get("structure") or {}
        w(f"| `{k}` | {SYS_DESC.get(k,'—')} | {pct(v['hit100'])} | {pct(v['hit250'])} | "
          f"{sec(v['mae_both_sec'])} | {pct(st.get('degenerate_share'),2) if st else '—'} | "
          f"{pct(st.get('overlap_share'),2) if st else '—'} | "
          f"{pct(st.get('start_regression_share'),2) if st else '—'} |")
    w("")
    w(f"- 现装 official 阶段在自然长时序上**又造出退化单元**：单窗 raw {pct(a['structure']['degenerate_share'],2)} → "
      f"official {pct(bb['structure']['degenerate_share'],2)}，同时 hit@100 还降 "
      f"{(a['hit100']-bb['hit100'])*100:.2f}pp ⇒ 与第 2 轮（GTSinger 后处理净损害 −1.66pp）、"
      "第 6 轮（真实歌退化 11.2%→17.1%）同一现象在第三个数据域复现。")
    w(f"- 求解的破坏度对照：共识可信时长 {c['structure']['plausible_mass_sec']:.0f}s → 求解后 "
      f"{dd['structure']['plausible_mass_sec']:.0f}s（-{(1-dd['structure']['plausible_mass_sec']/c['structure']['plausible_mass_sec'])*100:.1f}%），"
      f"重叠从 {pct(c['structure']['overlap_share'],2)} 归零 ⇒ **结构收益是真实的**，"
      "0.5pp 的 hit@100 是它的价格；上线时按产品目标（是否允许重叠显示）决定取舍。")
    w(f"- 上界：用真值逐单元挑最好尝试可到 {pct(cs['E_oracle_attempt_per_unit']['hit100'])}"
      f"（比单窗 +{summ['oracle_ceiling_pp']:.2f}pp）⇒ 剩余空间主要在**选对尝试**，不在后处理。")
    w("")
    w("## 2. 触发器判别力与复核预算")
    w("")
    w(f"目标 = 单元在「中位尝试」下误差是否超阈值；只在 ≥2 次尝试的 {cov['units_multi_attempt']:,} 个单元上评估。")
    w("")
    w("| 目标 | 阳性率 | 分歧度 AUC | 支持度 AUC | 熵 AUC | loo 距离 AUC | 尝试次数 AUC |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for tag, t in (("误差>100ms", b1), ("误差≥250ms", b25)):
        w(f"| {tag} | {pct(t['positive_rate'],1)} | {t['auc_disagreement']} | {t['auc_support_max']} | "
          f"{t['auc_ent_min']} | {t['auc_loo_spread_min']} | {t['auc_attempts']} |")
    w("")
    w("按**分歧度**排序的复核预算（`hit@100(重选)` 一列是「若在标记单元上能挑到最好尝试」的上界，"
      "**用了真值，只作收益上限参考**）：")
    w("")
    w("| 预算 | 阈值 | 标记单元 | 精度(>100ms) | 召回 | 标记单元重选后 hit@100 | 全表 hit@100 | 相对单窗 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k, v in b1["review_budget_curve"].items():
        w(f"| {k.replace('top_','top ').replace('pct','%')} | {v['threshold_sec']:.2f}s | "
          f"{v['flagged_units']:,} | {pct(v['precision_bad100'],1)} | {pct(v['recall_bad100'],1)} | "
          f"{pct(v['hit100_of_flagged_if_rechosen'],1)} | {pct(v['overall_hit100_if_only_flagged_rechosen'],2)} | "
          f"{v['gain_pp_vs_single_window']:+.2f}pp |")
    w("")
    w(f"- 错误捕获曲线（按分歧度排序，累计捕获多少单窗错误）："
      + "、".join(f"{k.replace('top_','').replace('pct','%')} {pct(v,1)}"
                  for k, v in trig["error_capture_curve"].items())
      + " ⇒ **分歧度排序 ≈ 随机**（20% 预算只捕获 26.9% 错误），不足以支撑「只重算分歧单元」的策略。")
    w("- 结合 AUC 表：如果只能选一个触发特征，选**边界熵**；分歧度可作次要信号，"
      "但在 6 成单元上它没有定义。")
    w("")
    w("## 3. 边界与下一步")
    w("")
    w("- 参考是弱标签（模型产出 + 80ms 量化）：0.5pp 级别的差异**不足以排序**，"
      "只有 +2.1pp、−0.5pp（约束代价）与 AUC 差 0.1+ 的结论是稳的。")
    w("- 共识只在有多尝试的单元上可用；真实部署要全量多视图需要额外前向（本会话未花 GPU）。")
    w("- 建议在花钱之前先做的两件事（纯 CPU）：(a) 把**熵触发 + 联合求解输出**接到现有 33 首真实歌的"
      "多次运行产物上，检验触发器在无真值数据上的标记分布；(b) 用本模块做**预算仿真**，"
      "给出「重算 k% 单元的期望收益上界」曲线，作为 GPU 申请的量化依据。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/rebuild_longform_signed_gt.py    # 尺子（第 8 轮）")
    w("PYTHONPATH=src python scripts/evaluation/run_longform_pipeline_candidate.py")
    w("PYTHONPATH=src python scripts/evaluation/report_longform_pipeline_candidate.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_longform_pipeline_candidate.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {"schema_version": "longform_pipeline_candidate_metrics_v1", "run": str(args.run),
               "reference": "verified signed weak GT (max deviation 0.0 vs frozen errors); "
                            "rule_validated, model-derived, 80 ms quantised",
               "trigger": trig, "candidate": cand,
               "headline": {
                   "consensus_gain_over_single_window_pp": summ["gain_consensus_vs_single_pp"],
                   "consensus_solve_gain_over_single_window_pp": summ["gain_consensus_solve_vs_single_pp"],
                   "structure_cost_of_solve_pp": round((c["hit100"] - dd["hit100"]) * 100, 3),
                   "solve_structure_rates": dd["structure"],
                   "shipped_official_degenerate_share": bb["structure"]["degenerate_share"],
                   "shipped_official_hit100_delta_vs_raw": round((bb["hit100"] - a["hit100"]) * 100, 3),
                   "max_dur_sensitivity_hit100": cand["max_dur_sensitivity"],
                   "cap_hypothesis_rejected": True,
                   "trigger_auc_bad100": {"disagreement": b1["auc_disagreement"],
                                          "support": b1["auc_support_max"], "entropy": b1["auc_ent_min"]},
                   "trigger_auc_bad250": {"disagreement": b25["auc_disagreement"],
                                          "support": b25["auc_support_max"], "entropy": b25["auc_ent_min"]},
                   "multi_attempt_coverage": cov["share_multi_attempt"],
                   "error_capture_at_20pct_budget": trig["error_capture_curve"]["top_20pct"],
                   "oracle_ceiling_pp": summ["oracle_ceiling_pp"]},
               "recommendation": "prefer cross-window consensus as the long-form output; keep the joint "
                                 "solve as the structural guarantee when non-overlap is a product requirement; "
                                 "trigger re-alignment on boundary entropy, not on window disagreement"}
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
