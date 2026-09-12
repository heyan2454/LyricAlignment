#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the metric-stability report: which pp differences this project can actually trust."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_label_noise_ceiling")
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_metric_stability.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_metric_stability/metrics.json")
    args = ap.parse_args()
    stab = json.loads((args.run / "STABILITY.json").read_text(encoding="utf-8"))
    gap = json.loads((args.run / "GAP_ARTIFACT.json").read_text(encoding="utf-8"))
    L: list[str] = []
    w = L.append
    w("# 指标能分辨多小的差？格点余量与差值可归因性（第 32 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_label_noise_ceiling/{STABILITY,GAP_ARTIFACT}.json` 生成；"
      "只读既有面板，零前向。量子 = 本项目统一的 **0.08s** 边界格点。")
    w("")
    w("## 0. 结论")
    w("")
    res = gap["results"]
    def get(k):
        return res.get(k, {})
    a100 = get("r2_vs_r1@100ms")
    r10 = get("r1_vs_r0@100ms")
    w(f"- **projector 适配的增益是真的**：r1 vs r0 在 100ms 上差 {r10['gap_pp']:+.2f}pp，"
      f"而格点舍入最多只能造 {r10['max_spurious_gap_pp']:.2f}pp ⇒ 超出界"
      f"（扎实差异单元 {r10['solid_disagreement_units']:,}）。")
    w(f"- **LoRA r1→r2 的增益处在可归因边界上**：GTSinger 100ms 差 "
      f"{a100['gap_pp']:+.2f}pp vs 界 {a100['max_spurious_gap_pp']:.2f}pp（勉强超出）；"
      f"但 **50ms 上差 {get('r2_vs_r1@50ms')['gap_pp']:+.2f}pp vs 界 "
      f"{get('r2_vs_r1@50ms')['max_spurious_gap_pp']:.2f}pp ⇒ 不可归因**。")
    m1 = get("mir1k r2_full_2_vs_r1_full_2@100ms")
    m2 = get("mir1k r2_full_2_vs_r2_ood_20@100ms")
    if m1.get("available"):
        w(f"- **MIR-1K 上更明确**：r2_full vs r1_full 100ms 差 {m1['gap_pp']:+.2f}pp，"
          f"界 {m1['max_spurious_gap_pp']:.2f}pp ⇒ **不可归因**；"
          f"r2_full vs r2_ood 差 {m2['gap_pp']:+.2f}pp，界 {m2['max_spurious_gap_pp']:.2f}pp ⇒ "
          "**这两个 checkpoint 谁更好，现有指标无法判定**（扎实差异仅 "
          f"{m2['solid_disagreement_units']} 单元）。")
    s50 = stab["panels"]["gtsinger_all"]["by_tolerance"]["50ms"]
    s100 = stab["panels"]["gtsinger_all"]["by_tolerance"]["100ms"]
    w(f"- **命中率本身在 50/100ms 处极不稳定**（§1 的「一个格点系统偏移」列）："
      f"hit@50 可被一个格点的同向偏移推动 ±{s50['systematic_shift_bound_pp'] / 2:.1f}pp"
      f"（总跨度 {s50['systematic_shift_bound_pp']:.1f}pp），"
      f"hit@100 ±{s100['systematic_shift_bound_pp'] / 2:.1f}pp；"
      f"刀尖判定占比分别是 {100 * s50['knife_edge_share']:.1f}% 与 {100 * s100['knife_edge_share']:.1f}%"
      "——因为中位误差 40ms 小于 80ms 格点，误差密度正好压在判定线上。")
    w("")
    w("- **因此本轮给出一条硬规则（已写入清单第 18 条）**：比较两个系统在同一标签上的 hit@tol 差值时，"
      "必须同时报 `max_spurious_gap_pp`（落后方差距不足一个格点的单元数换算成 pp）；"
      "小于该界的差值一律记为 **不可归因**，不得写进结论或用于选型。")
    w("")
    w("## 1. 单系统稳定性（同一量子下判定有多脆）")
    w("")
    w("| 面板 | 单元 | 容差 | hit | 一个格点系统偏移可移 | 刀尖判定占比 |")
    w("|---|---:|---|---:|---:|---:|")
    for name, blk in stab["panels"].items():
        for tol, v in blk["by_tolerance"].items():
            w(f"| `{name}` | {blk['units']:,} | {tol} | {100*v['hit_share']:.2f}% | "
              f"±{v['systematic_shift_bound_pp']/2:.2f}pp | {100*v['knife_edge_share']:.1f}% |")
    w("")
    w("## 2. 两两差值可归因性")
    w("")
    w("### GTSinger（人工词级真值，80ms 格点）")
    w("")
    w("| 对比 | 容差 | 差值 | 格点余量可造 | 可归因？ | 扎实差异单元 |")
    w("|---|---|---:|---:|---|---:|")
    for k, v in res.items():
        if not v.get("available") or k.startswith("mir1k"):
            continue
        w(f"| {k.split('@')[0].replace('_vs_', ' vs ')} | {k.split('@')[1]} | "
          f"{v['gap_pp']:+.2f}pp | {v['max_spurious_gap_pp']:.2f}pp | "
          f"{'**是**' if v['gap_exceeds_grid_slack'] else '否'} | {v['solid_disagreement_units']:,} |")
    w("")
    w("### MIR-1K（人工连续真值，预测仍在 80ms 格点上）")
    w("")
    w("| 对比 | 容差 | 差值 | 格点余量可造 | 可归因？ | 扎实差异单元 |")
    w("|---|---|---:|---:|---|---:|")
    for k, v in res.items():
        if not v.get("available") or not k.startswith("mir1k"):
            continue
        body = k[len("mir1k "):]
        names, tol_label = body.split("@", 1)
        left, right = names.split("_vs_", 1)
        w(f"| `{left}` vs `{right}` | {tol_label} | "
          f"{v['gap_pp']:+.2f}pp | {v['max_spurious_gap_pp']:.2f}pp | "
          f"{'**是**' if v['gap_exceeds_grid_slack'] else '否'} | {v['solid_disagreement_units']:,} |")
    w("")
    w("## 3. 对本会话既往结论的追溯性限定（不改原文，只加限定）")
    w("")
    w("- 第 15 轮「联合求解改善**首单元** +2.78pp」：与本轮 `r2_vs_r1@50ms` 同一量级，"
      "**在 50ms 上已低于格点余量界 ⇒ 该 pp 差不可作为独立证据**；"
      "但同轮的 AUC/MAE 型指标不受此限（不依赖阈值判定）。")
    w("- 第 4/5/9/10 轮各系统的 hit@100 差值凡 <3pp 者（含集成成员排序、选择器对比）"
      "均应视为**未分离**；索引 A3 的「r1→r2 ≤0.5pp」原本就是"
      "差值小于噪声的表述，本轮把它升级为可计算的界。")
    w("- 不受影响的结论：所有 lift/AUC/相关性型结论（第 15/19/20/26 轮）、"
      "结构非法率与阶段归因（第 12–16 轮，不涉及阈值判定）。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_label_noise_ceiling.py")
    w("PYTHONPATH=src python scripts/evaluation/report_metric_stability.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_label_noise_ceiling.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "metric_stability_metrics_v1", "stability": stab, "gap_artifact": gap,
         "headline": {
             "attributable": {k: bool(v.get("gap_exceeds_grid_slack")) for k, v in res.items()
                             if v.get("available")},
             "gaps_pp": {k: v.get("gap_pp") for k, v in res.items() if v.get("available")},
             "grid_slack_bounds_pp": {k: v.get("max_spurious_gap_pp") for k, v in res.items()
                                      if v.get("available")},
             "rule": "differences in hit@tol smaller than max_spurious_gap_pp are not attributable",
             "affected_session_claims": [
                 "round 15 first-unit +2.78pp (below the 50ms grid-slack bound)",
                 "any sub-3pp hit@100 comparison in rounds 4/5/9/10"]}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
