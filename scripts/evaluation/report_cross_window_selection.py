#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the cross-window selection report (signed-GT reconstruction + label-free selectors)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt")
REPO = Path(__file__).resolve().parents[2]
DESC = {
    "A_first_attempt": "任意单一窗口（现状：谁覆盖就用谁）",
    "C_closest_to_consensus": "离其余尝试的中位最近",
    "D_max_support": "与其余尝试 50ms 内一致度最高",
    "E_min_entropy": "边界熵最低",
    "F_max_margin": "边界 margin 最大",
    "G_most_central_in_request": "该单元在其请求窗口内最居中",
    "H_gated_then_confident": "先要求与共识 ≤100ms，再取熵最低",
    "median_of_attempts": "跨窗误差中位（参考线）",
    "consensus_median_boundaries": "跨窗边界取中位（共识输出）",
}


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else (f"{float(x):.3f}s" if abs(x) >= 1 else f"{1000 * float(x):.{d}f}ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_cross_window_selection.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_cross_window_selection/metrics.json")
    args = ap.parse_args()
    sel = json.loads((args.run / "CROSS_WINDOW_SELECTION.json").read_text(encoding="utf-8"))
    sgt = json.loads((args.run / "SIGNED_GT_STATS.json").read_text(encoding="utf-8"))
    pane, res, ver = sel["panel"], sel, sgt["verification"]
    head = res["reference_headroom"]
    gap = res["gap_closed_vs_oracle"]

    L: list[str] = []
    w = L.append
    w("# 长时序跨窗口选择：无真值能吃到多少 headroom（2026-09-12 第 8 轮）")
    w("")
    w("> 数字由 `runs/20260912_m4_longform_weakgt/{CROSS_WINDOW_SELECTION,SIGNED_GT_STATS}.json` 生成。")
    w("> 纯 CPU：全部复用已落盘的逐次尝试证据，零新增前向。")
    w("")
    w("## 0. 先修好尺子：重建**有符号**逐字真值并验证")
    w("")
    w("面板里 `label_*_err_sec` 是**无符号**绝对误差，`raw − err` 反推真值带 ± 号歧义；"
      "面板自带的 `gt_*` 列又落在第 3 轮证明的伪造均匀轴上。"
      "本轮按 labeler 的公式重建：段局部 `timestamp_class_ids × 0.08s` + `segment_offsets.global_start_sec`。")
    w("")
    r = ver["raw"]
    o = ver["official"]
    f = ver["fabricated_axis_contrast"]
    w(f"- 验证：重建后 `|raw − gt|` 与冻结误差偏差 **max {r['max_deviation_sec']}s**"
      f"（start/end 命中率 {pct(r['start_within_tol_share'],1)}/{pct(r['end_within_tol_share'],1)}，"
      f"相关系数 {r['correlation_start']}）；official 阶段同样 {o['max_deviation_sec']}s。"
      "⇒ 重建与项目 labeler 用的是同一份参考，逐字不差。")
    w(f"- 交叉对照：与 `raw` 距离在 100ms 内的比例，面板 `gt_*`（伪造轴）只有 "
      f"{pct(f['share_within_100ms_panel_gt'],1)}，重建参考为 {pct(f['share_within_100ms_rebuilt'],1)}；"
      f"中位距离 {sec(f['median_distance_panel_gt_sec'])} vs {sec(f['median_distance_rebuilt_sec'])}"
      "⇒ 第 3 轮的伪造轴结论现在有了定量版本。")
    w(f"- 跨尝试自洽：同一单元多次尝试推出的重建真值极差中位 "
      f"{ver['cross_attempt_reference_spread']['median_spread_sec']}s、"
      f"≤5ms 占比 {pct(ver['cross_attempt_reference_spread']['share_within_5ms'],1)}"
      f"（{ver['cross_attempt_reference_spread']['multi_attempt_units']:,} 个多尝试单元）"
      "⇒ 之前看到的「24% 单元跨尝试分歧 >100ms」是 ± 号假象，不是模型不稳。")
    w(f"- 参考性质（必须随结论一起说）：`{sgt['stats']['reference']['validation_basis']}`，"
      f"量化步长 {sgt['stats']['reference']['quantisation_sec']}s ⇒ 任何一致性指标都有 ±40ms 底噪；"
      "这不是人工 GT。")
    w("")
    w(f"面板：{pane['rows']:,} 次尝试 / {pane['units']:,} 个唯一单元；"
      f"每单元尝试次数中位 {pane['attempts_per_unit']['median']}、p90 {pane['attempts_per_unit']['p90']:.0f}、"
      f"最多 {pane['attempts_per_unit']['max']}；{pane['attempts_per_unit']['units_with_ge2']:,} 个单元被 ≥2 个窗口覆盖。")
    w("")
    w("## 1. 结论：窗口选择本身值 2.1pp；无真值选择器能再拿 0.6pp")
    w("")
    w("| 方法 | 说明 | hit@100 | hit@250 | MAE | Δ vs 跨窗中位 | 吃掉 oracle 差距 |")
    w("|---|---|---:|---:|---:|---:|---:|")
    agg = res["aggregates"]
    rows = [("A_first_attempt", res["selectors"]["A_first_attempt"]),
            ("median_of_attempts", agg["unit_median_of_attempts"]),
            ("consensus_median_boundaries", agg["B_consensus_median_boundaries"])]
    rows += [(k, res["selectors"][k]) for k in sorted(res["selectors"])
             if k.startswith(("C_", "D_", "E_", "F_", "G_", "H_"))]
    rows.append(("unit_best_of_attempts_oracle", agg["unit_best_of_attempts_oracle"]))
    for key, src in rows:
        label = DESC.get(key, "用真值挑最好的一次尝试（上界）")
        gg = gap.get(key, {})
        w(f"| `{key}` | {label} | {pct(src.get('hit100'), 2)} | {pct(src.get('hit250'), 2)} | "
          f"{sec(src.get('mae_both_sec'))} | {gg.get('delta_pp_vs_median_attempt', 0):+.2f}pp | "
          f"{pct(gg.get('share_of_oracle_gap_closed'), 1) if gg.get('share_of_oracle_gap_closed') is not None else '—'} |")
    w("")
    w(f"- **单窗代价**：随便取一个覆盖该单元的窗口，hit@100 只有 "
      f"{pct(res['selectors']['A_first_attempt']['hit100'],2)}（MAE {sec(res['selectors']['A_first_attempt']['mae_both_sec'])}），"
      f"比跨窗中位低 **{abs(gap['A_first_attempt']['delta_pp_vs_median_attempt']):.2f}pp**"
      f"，最差尝试更是 {pct(res['aggregates']['unit_worst_of_attempts']['hit100'],1)}"
      f"（MAE {sec(res['aggregates']['unit_worst_of_attempts']['mae_both_sec'])}）"
      "⇒ 长时序的真实风险来自**窗口选择**，不是解码器平均质量。")
    w(f"- **可部署最优：`D_max_support`**（与其余尝试 50ms 内一致度最高）hit@100 "
      f"{pct(res['selectors']['D_max_support']['hit100'],2)}（+{gap['D_max_support']['delta_pp_vs_median_attempt']:.2f}pp），"
      f"吃掉 oracle 差距的 {pct(gap['D_max_support']['share_of_oracle_gap_closed'],0)}；"
      f"`H_gated_then_confident` MAE 最低（{sec(res['selectors']['H_gated_then_confident']['mae_both_sec'])}）。")
    w(f"- **熵/margin 几乎不能选窗**：{pct(res['selectors']['E_min_entropy']['hit100'],2)} / "
      f"{pct(res['selectors']['F_max_margin']['hit100'],2)}（+0.09/+0.16pp）"
      "⇒ 第 1/3/5 轮的「置信信号」在这里只能抓 gross 错误，不足以在多个合格尝试中挑出最好的。")
    w(f"- **反直觉负结果：`G_most_central_in_request` 比中位差 "
      f"{abs(gap['G_most_central_in_request']['delta_pp_vs_median_attempt']):.2f}pp**"
      "（85.80%）⇒ 「把单元放在窗口中央就更可靠」在长时序上**不成立**，"
      "这直接削弱了「靠重新裁窗把困难单元居中」这类 realign 设计的理论依据。")
    w(f"- 共识输出（取中位边界）与「最接近共识的那一次」几乎等价"
      f"（{pct(res['aggregates']['B_consensus_median_boundaries']['hit100'],2)} vs "
      f"{pct(res['selectors']['C_closest_to_consensus']['hit100'],2)}）"
      "⇒ 中位本身就是某个尝试，工程上可以直接输出中位而无需回选尝试。")
    w("")
    w("## 2. 与前几轮的关系（为什么这次不同）")
    w("")
    w("- 第 5 轮：同一音频同一歌词的**不同 checkpoint** 之间，共识只值 +0.34pp（oracle 4.57pp，吃 7.4%）。"
      f"本轮：同一单元的**不同音频切片**之间，oracle {head['headroom_pp']:.2f}pp，"
      f"可部署支持度选择器拿到 {gap['D_max_support']['share_of_oracle_gap_closed']*100:.0f}%。"
      "⇒ **视图多样性才是关键变量**：多视图值得做，但必须是不同裁窗，不是同裁窗换模型。")
    w("- 第 1/3 轮的聚簇/接缝结论在本轮得到加强而非削弱：困难不在「接缝附近的单元」，"
      "而在「同一个单元被不同窗口给出不同答案」，且这个差异可以被一致性度量预测。")
    w("")
    w("## 3. 边界")
    w("")
    w(f"- 只有 {pane['attempts_per_unit']['units_with_ge2']:,}/{pane['units']:,} 个单元有多窗口尝试"
      "（每单元中位 1 次），所以选择器的收益只作用于这部分；对单尝试单元无任何改善。")
    w(f"- 参考是 {sgt['stats']['reference']['validation_basis'].split(' ')[0]} 弱标签、"
      f"{sgt['stats']['reference']['quantisation_sec']}s 量化 ⇒ hit@100 有 ±40ms 底噪，"
      "选择器之间 0.1-0.2pp 的差异不足以定序（只有 +0.6pp 与 −1.15pp 是显著的）。")
    w("- 真实歌曲（无人工/弱 GT）上无法验证，只能验证「一致性度量本身」是否可用；"
      "MIR-1K 仍是 test-only，本轮未使用。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("# 1) 重建并验证有符号真值  2) 跑跨窗选择实验  3) 生成本报告")
    w("PYTHONPATH=src python scripts/evaluation/rebuild_longform_signed_gt.py")
    w("PYTHONPATH=src python scripts/evaluation/run_cross_window_selection.py")
    w("PYTHONPATH=src python scripts/evaluation/report_cross_window_selection.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_cross_window_selection.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {"schema_version": "cross_window_selection_metrics_v1", "run": str(args.run),
               "signed_gt_verification": ver, "signed_gt_stats": sgt["stats"],
               "panel": pane, "results": res,
               "headline": {
                   "single_window_penalty_pp": round(abs(gap["A_first_attempt"]["delta_pp_vs_median_attempt"]), 2),
                   "best_deployable_selector": "D_max_support",
                   "best_deployable_gain_pp": gap["D_max_support"]["delta_pp_vs_median_attempt"],
                   "oracle_headroom_pp": head["headroom_pp"],
                   "gap_closed_by_support_selector": gap["D_max_support"]["share_of_oracle_gap_closed"],
                   "entropy_selector_gain_pp": gap["E_min_entropy"]["delta_pp_vs_median_attempt"],
                   "central_position_selector_gain_pp": gap["G_most_central_in_request"]["delta_pp_vs_median_attempt"],
                   "worst_attempt_hit100": res["aggregates"]["unit_worst_of_attempts"]["hit100"],
               },
               "claim": "long-form risk is window choice, not decoder average quality; "
                        "view diversity (different crops) is the variable worth paying for"}
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
