#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the geometry + cross-domain bias-direction report (round 21)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_decodability_ceiling")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_decodability_geometry.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_decodability_geometry/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "GEOMETRY.json").read_text(encoding="utf-8"))
    geo, chk = r["geometry"], r["transfer_check_long_note_end"]
    sb, tb = r["studio_end_bias_gtsinger"], r["target_end_bias_mir1k"]

    L: list[str] = []
    w = L.append
    w("# 不可达真值在哪：候选之间还是跨度之外？以及偏置能不能跨域（第 21 轮，2026-09-12）")
    w("")
    w(f"> 数字由 `{args.run.name}/GEOMETRY.json` 生成（格点 {r['timestamp_step_sec']}s）。只读既有面板、零前向。")
    w("> 纪律：结论依据是 GTSinger（人工真值、非 test）；MIR-1K（test-only）只用于报告**它自身偏置的方向**，"
      "不用于任何校准。")
    w("")
    w("## 0. 结论：两条看似自然的省算力路径都被关掉了")
    w("")
    w(f"- **(a) 「在两候选之间插值」不可行**：不可达时**候选跨度中位数只有 "
      f"{geo['long_note']['end']['candidate_span_bins_when_unreachable']['median_sec']}s（1 格）**，"
      f"所以真值几乎从不在两候选之间——全体不可达里只有 {pct(geo['all_units']['end']['between_candidates_share_of_unreachable'])} "
      f"在跨度内、长音只有 {pct(geo['long_note']['end']['between_candidates_share_of_unreachable'])}；"
      f"**{pct(geo['long_note']['end']['outside_span_share_of_unreachable'])} 的长音不可达情形落在跨度之外**"
      f"（外移距离中位 {geo['long_note']['end']['distance_outside_bins']['median_sec_when_outside']}s）。"
      "⇒ top-1/top-2 是**相邻格点**，重排/插值不可能造出真值。")
    w(f"- **(b) 「全局偏置修正」不可跨域迁移**：长音端点偏置方向在两个域**相反**——"
      f"录音室（GTSinger r2）中位 **{sb['long_note']['end']['median_ms']:+.1f}ms**、"
      f"偏晚比例 {sb['long_note']['end']['late_share']:.3f}（**截早**）；"
      f"真实伴奏（MIR-1K r2_full）中位 **{tb['long_note']['end']['median_ms']:+.1f}ms**、"
      f"偏晚比例 {tb['long_note']['end']['late_share']:.3f}（**拖晚**）；"
      f"两者 late-share 差 **{chk['late_share_gap']:.3f}** ⇒ {chk['verdict']}")
    w(f"- 末单元更极端：GTSinger 的 last_unit 不可达情形 **100% 落在跨度右侧**"
      f"（真值比两个候选都晚），偏置中位 {sb['last_unit']['end']['median_ms']:+.1f}ms、"
      f"偏晚比例仅 {sb['last_unit']['end']['late_share']:.3f} ⇒ 录音室里模型**系统性截断拖长音的尾巴**；"
      f"而首单元不可达 {pct(geo['first_unit']['end']['outside_left_share_of_unreachable'])} 偏左"
      "⇒ 与硬裁片段起点一致。")
    w("- 合起来：**长音尾边界不是"
      "「选错了」，而是「候选里根本没有，而且两个域错向相反」**；"
      "能往前走的两件事仍然是（i）训练信号（第 19 轮已证可把长音不可达率 70.8%→21.7%）、"
      "（ii）产生新候选的重解码（更长右上下文；且**必须按域分别验证**，不能共用一条修正规则）。")
    w("")
    w("## 1. 不可达几何（端点，±1 格容差；GTSinger 人工真值）")
    w("")
    w("| 层 | 单元 | 不可达率 | 在跨度之间 | **在跨度之外** | 偏左 | 偏右 | 候选跨度中位 | 外移距离中位 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, blk in geo.items():
        e = blk["end"]
        w(f"| {name} | {blk['units']:,} | {pct(e['unreachable_share'])} | "
          f"{pct(e['between_candidates_share_of_unreachable'])} | "
          f"**{pct(e['outside_span_share_of_unreachable'])}** | "
          f"{pct(e['outside_left_share_of_unreachable'])} | {pct(e['outside_right_share_of_unreachable'])} | "
          f"{e['candidate_span_bins_when_unreachable'].get('median_sec')}s | "
          f"{e['distance_outside_bins'].get('median_sec_when_outside')}s |")
    w("")
    w("起点侧对照（首单元不可达全部偏左 ⇒ 片段被硬裁、模型无法预测到裁剪点之前）：")
    w("")
    w("| 层 | 不可达率 | 在跨度之间 | 偏左 | 偏右 |")
    w("|---|---:|---:|---:|---:|")
    for name, blk in geo.items():
        s = blk["start"]
        w(f"| {name} | {pct(s['unreachable_share'])} | {pct(s['between_candidates_share_of_unreachable'])} | "
          f"{pct(s['outside_left_share_of_unreachable'])} | {pct(s['outside_right_share_of_unreachable'])} |")
    w("")
    w("## 2. 偏置方向对照（pred − 人工真值，端点）")
    w("")
    w("| 域 / 层 | 单元 | 中位 | 均值 | 偏晚比例 |")
    w("|---|---:|---:|---:|---:|")
    for tag, blk in (("GTSinger r2（录音室清唱）", sb), ("MIR-1K r2_full（真实伴奏）", tb)):
        for name, v in blk.items():
            e = v["end"]
            w(f"| {tag} · {name} | {v['units']:,} | {e['median_ms']:+.1f}ms | {e['mean_ms']:+.1f}ms | "
              f"{pct(e['late_share'])} |")
    w("")
    w(f"- 机判结论：`same_direction = {chk['same_direction']}`，"
      f"late-share 差 {chk['late_share_gap']:.3f}。")
    w("- 这条同时**回收了第 11 轮的疑问**：当时声学衰减阈值的"
      "最优 θ 在两个域之间不可迁移（导出 θ=0.15 迁移后 −13.4pp）；"
      "现在能看到根因不是阈值选错，而是**两个域的端点误差本身方向相反**。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_decodability_geometry.py")
    w("PYTHONPATH=src python scripts/evaluation/report_decodability_geometry.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_decodability_geometry.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "decodability_geometry_metrics_v1", "audit": r,
         "headline": {
             "long_note_unreachable_share": geo["long_note"]["end"]["unreachable_share"],
             "long_note_outside_span_share": geo["long_note"]["end"]["outside_span_share_of_unreachable"],
             "long_note_between_share": geo["long_note"]["end"]["between_candidates_share_of_unreachable"],
             "candidate_span_median_sec_when_unreachable":
                 geo["long_note"]["end"]["candidate_span_bins_when_unreachable"]["median_sec"],
             "studio_long_note_end_median_ms": sb["long_note"]["end"]["median_ms"],
             "studio_long_note_late_share": sb["long_note"]["end"]["late_share"],
             "accompanied_long_note_end_median_ms": tb["long_note"]["end"]["median_ms"],
             "accompanied_long_note_late_share": tb["long_note"]["end"]["late_share"],
             "bias_transferable": chk["same_direction"],
             "conclusion": "top-1 and top-2 are adjacent bins so interpolation cannot reach the truth, "
                           "and the long-note end bias has opposite sign in studio vs accompanied "
                           "singing so a global offset cannot transfer"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
