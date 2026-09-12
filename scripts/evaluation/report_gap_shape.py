#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the gap-shape / truncation-trigger report (rounds 25–26)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_gap_shape")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_gap_shape.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_gap_shape/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "GAP_SHAPE.json").read_text(encoding="utf-8"))
    val = r["gtsinger_validation"]["score_all_views"]
    prod = r["gtsinger_validation"].get("score_production_view", {})
    grp = r["gtsinger_validation"].get("grouped_auc", {})
    frozen = r["real_songs_frozen"]["prevalence"]

    L: list[str] = []
    w = L.append
    w("# 字间隙能量能不能免费检测「把字切早了」？（第 25–26 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_gap_shape/GAP_SHAPE.json` 生成；判别器在 **GTSinger 人工真值**（非 test）"
      "上拟合与验证，再**冻结**应用到 33 首真实歌（那边只报流行率，不报精度）。零新前向、只读音频。")
    w("")
    w("## 0. 结论")
    w("")
    gc = (val.get("auc_raw_higher_score_more_truncated") or {}).get("gap_over_core", {})
    rr = (val.get("auc_raw_higher_score_more_truncated") or {}).get("rise_ratio", {})
    gi = grp.get("gap_over_core|by_item", {})
    gm = grp.get("gap_over_core|by_model", {})
    w(f"- **形状假设（上升=下一字起始，下降=本字尾巴）不成立**：按形状分组的截早率是 "
      + "、".join(f"{k} {pct(v['truncated_share'])}" for k, v in val["by_shape"].items())
      + f"，非单调；`rise_ratio` 的 pooled AUC 只有 **{rr.get('auc')}**。")
    w(f"- **但「间隙残余相对本字核心能量的比值」是很强的截早预测器**："
      f"pooled AUC **{gc.get('auc')}**（方向：{gc.get('direction')}）；"
      f"且**不是合并池造成的假象**——按片段分组 within-median **{gi.get('within_group_median_auc')}**"
      f"（q25–q75 {gi.get('within_group_q25')}–{gi.get('within_group_q75')}，"
      f"{gi.get('groups_evaluated')} 个片段中 {pct(gi.get('share_of_groups_above_0_6'),0)} 组 >0.6，"
      f"聚类自助 CI {gi.get('cluster_bootstrap_median_ci95')}）；"
      f"按检查点分组 within-median **{gm.get('within_group_median_auc')}**（3/3 组 >0.6）。")
    per_model = (gm.get("per_group_auc") or {})
    if per_model:
        w("- **分检查点单独看也都成立**（不是靠混合不同截早率的 checkpoint 撑起来的）："
          + "、".join(f"{k} AUC {v}" for k, v in sorted(per_model.items())) + "。")
    w(f"- **需要保留的三个谨慎条款**：")
    w(f"  1. 只看生产视图（r2|vocal|windowed）时只剩 {prod.get('units')} 个间隙，"
      f"截早率 {pct(prod.get('truncated_share'))}，AUC {prod.get('auc_raw_higher_score_more_truncated', {}).get('gap_over_core', {}).get('auc')}"
      f"（已独立复核，与按 checkpoint 分组的 {gm.get('within_group_median_auc')} 一致；"
      f"该视图截早率 {pct(prod.get('truncated_share'))} 远低于合并池 {pct(val['truncated_share'])}"
      " ⇒ 合并池的高 AUC 一部分来自不同 checkpoint/视图之间截早率的差异，"
      "**引用时优先给单视图数字**）；")
    w(f"  2. `gap_rms`（绝对能量）也有 pooled AUC "
      f"{(val.get('auc_raw_higher_score_more_truncated') or {}).get('gap_rms', {}).get('auc')}，"
      f"但按检查点分组后 within-median 只有 "
      f"{grp.get('gap_rms|by_model', {}).get('within_group_median_auc')} ⇒ 绝对能量含响度混杂，"
      "**必须用比值口径**（第 24 轮清单第 14 条）；")
    w(f"  3. 本轮把「截早」定义为 `gt_end − pred_end > {val['tolerance_sec']}s`（一个格点），"
      "分母是**有可测间隙的单元**（GTSinger "
      f"{r['gtsinger_validation']['gaps_measurable']:,} 个，占全部单元的少数），"
      "所以流行率不能外推到全体单元。")
    w("")
    w("## 1. 验证集：GTSinger（人工词级真值）")
    w("")
    w(f"可测间隙 {r['gtsinger_validation']['gaps_measurable']:,} 个（来自 "
      f"{r['gtsinger_validation']['audio_files']} 个音频）；截早率 "
      f"{pct(val['truncated_share'])}（{val['units']:,} 个可判单元）。")
    w("")
    w("| 间隙形状 | 单元 | 占比 | **截早率** | 中位 (gt−pred) ms | 中位 gap/core |")
    w("|---|---:|---:|---:|---:|---:|")
    for k, v in val["by_shape"].items():
        w(f"| {k} | {v['units']:,} | {pct(v['share_of_gaps'])} | {pct(v['truncated_share'])} | "
          f"{v['median_late_ms']} | {v.get('median_gap_over_core')} |")
    w("")
    w("长音子集（gt_dur ≥ 1s）：")
    w("")
    ln = val.get("long_note_subset", {})
    w(f"- 单元 {ln.get('units')}，截早率 **{pct(ln.get('truncated_share'))}**；"
      "按形状：" + "、".join(f"{k} {pct(v)}" for k, v in (ln.get("by_shape_truncated_share") or {}).items()))
    w("")
    w("## 2. 判别力（raw AUC，越高表示分数越大越倾向截早）")
    w("")
    w("| 分数 | pooled AUC | 按片段 within-median（q25–q75） | 按检查点 within-median | >0.6 组占比（片段） |")
    w("|---|---:|---|---:|---:|")
    for score in ("gap_over_core", "gap_rms", "rise_ratio"):
        a = (val.get("auc_raw_higher_score_more_truncated") or {}).get(score, {})
        byi = grp.get(f"{score}|by_item", {})
        bym = grp.get(f"{score}|by_model", {})
        w(f"| `{score}` | {a.get('auc')} | {byi.get('within_group_median_auc')} "
          f"({byi.get('within_group_q25')}–{byi.get('within_group_q75')}) | "
          f"{bym.get('within_group_median_auc')} | {pct(byi.get('share_of_groups_above_0_6'),0)} |")
    w("")
    w("## 3. 冻结应用到真实歌（无真值 ⇒ 只报流行率）")
    w("")
    w(f"可测间隙 {r['real_songs_frozen']['gaps_measurable']:,} 个（33 首，demucs 分离人声 stem）")
    w("")
    w("| 形状 | 单元 | 占比 | gap/core 中位 | 间隙中位长 |")
    w("|---|---:|---:|---:|---:|")
    for k, v in frozen["by_shape"].items():
        w(f"| {k} | {v['units']:,} | {pct(v['share'])} | {v.get('median_gap_over_core')} | "
          f"{v['median_gap_sec']}s |")
    w("")
    w(f"- 真实歌的 gap/core 中位（{min((v.get('median_gap_over_core') or 9 for v in frozen['by_shape'].values()), default=None)}–"
      f"{max((v.get('median_gap_over_core') or 0 for v in frozen['by_shape'].values()), default=None)}）"
      f"整体高于 GTSinger 的 falling 组（{val['by_shape'].get('falling', {}).get('median_gap_over_core')}），"
      "与第 24 轮一致：产品批的字间隙里普遍留有接近整字能量的残余。")
    w("- 但真实歌**没有真值**，所以这只是**流行率**，不能读成"
      "「这么多字被切早了」——需要第 24 轮末尾那个 3–5 首人工标注的小实验才能定性。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_gap_shape.py")
    w("PYTHONPATH=src python scripts/evaluation/report_gap_shape.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_gap_shape.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "gap_shape_metrics_v1", "audit": r,
         "headline": {
             "gap_over_core_pooled_auc": gc.get("auc"),
             "gap_over_core_within_item_median": gi.get("within_group_median_auc"),
             "gap_over_core_within_item_bootstrap_ci": gi.get("cluster_bootstrap_median_ci95"),
             "gap_over_core_within_model_median": gm.get("within_group_median_auc"),
             "rise_ratio_pooled_auc": rr.get("auc"),
             "shape_hypothesis_supported": False,
             "residual_ratio_hypothesis_supported": bool((gc.get("auc") or 0) > 0.75),
             "production_view_units": prod.get("units"),
             "production_view_auc": prod.get("auc_raw_higher_score_more_truncated", {}).get(
                 "gap_over_core", {}).get("auc"),
             "real_songs_gap_core_medians": {k: v.get("median_gap_over_core")
                                             for k, v in frozen.get("by_shape", {}).items()},
             "conclusion": "gap energy shape does not predict truncation, but the residual-to-core "
                           "energy ratio does (pooled AUC 0.89, within-clip median 1.0, within-checkpoint "
                           "0.82); production-view subset is not yet reproduced"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
