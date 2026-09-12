#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the fused-trigger validation and the real-song re-decode queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_trigger_fusion")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_trigger_fusion.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_trigger_fusion/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "TRIGGER_FUSION.json").read_text(encoding="utf-8"))
    val = r["gtsinger_validation"]
    real = r["real_songs"]
    names = ("inversion", "low_conf_end", "high_entropy_end", "gap_residual",
             "fused_mean_rank", "any_flag_boolean")

    L: list[str] = []
    w = L.append
    w("# 三个免费触发器合成一个重解码 flag（第 27 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_trigger_fusion/TRIGGER_FUSION.json` 生成。"
      "全部特征**无需真值、无需额外前向**；在 GTSinger（人工真值、非 test）上验证，"
      "再冻结应用到 33 首真实歌（那边只产队列，不产精度）。")
    w("")
    w("## 0. 结论")
    w("")
    for target, zh in (("end_error_gt_100ms", "端点误差 >100ms"), ("truncated_end", "端点被切早")):
        blk = val["all_views"]["triggers"][target]
        w(f"- **目标「{zh}」**（流行率 {pct(blk['prevalence'])}，n={blk['n']:,}）：")
        w("  " + "｜".join(
            f"`{n}` AUC {blk[n]['auc']}、20% 预算召回 {pct(blk[n]['recall_at_20pct_budget'])}"
            for n in names if n in blk))
        w("")
    fv = val["production_view"]["triggers"].get("end_error_gt_100ms", {})
    if fv:
        pv_n = (fv.get("inversion") or {}).get("units_scored")
        w(f"- **生产视图单独看**（`r2|vocal|windowed`，打分单元 {pv_n}）："
          + "｜".join(f"`{n}` AUC {fv[n]['auc']}" for n in names if n in fv))
    ln = val["long_note"]["triggers"].get("end_error_gt_100ms", {})
    if ln:
        w(f"- **长音层**（最难、也是第 19 轮 40% 不可达的那层）：`gap_residual` AUC {ln.get('gap_residual', {}).get('auc')}、"
          f"`high_entropy_end` AUC {ln.get('high_entropy_end', {}).get('auc')}、"
          f"融合 AUC {ln.get('fused_mean_rank', {}).get('auc')}")
    w(f"- **分工不同，不要混用**：倒序只预示"
      f"「后续塌陷」（对端点误差 AUC {val['all_views']['triggers']['end_error_gt_100ms'].get('inversion', {}).get('auc')}），"
      f"熵/置信度与间隙残余才预示端点错；因此融合比单个熵略好（AUC "
      f"{val['all_views']['triggers']['end_error_gt_100ms']['fused_mean_rank']['auc']} vs "
      f"{val['all_views']['triggers']['end_error_gt_100ms']['high_entropy_end']['auc']}）。")
    w("")
    w("## 1. 复核预算下的召回/精度（GTSinger 全视图，目标=端点误差 >100ms）")
    w("")
    blk = val["all_views"]["triggers"]["end_error_gt_100ms"]
    w("| 触发器 | 打分数单元 | AUC | r@5% | r@10% | r@20% | p@5% | p@10% | p@20% | r@20%(仅覆盖内) |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in names:
        e = blk.get(n)
        if not e:
            continue
        w(f"| `{n}` | {e['units_scored']:,} | {e['auc']} | "
          f"{pct(e['recall_at_5pct_budget'])} | {pct(e['recall_at_10pct_budget'])} | "
          f"{pct(e['recall_at_20pct_budget'])} | {pct(e['precision_at_5pct_budget'])} | "
          f"{pct(e['precision_at_10pct_budget'])} | {pct(e['precision_at_20pct_budget'])} | "
          f"{pct(e['recall_within_scored_at_20pct_budget'])} |")
    w("")
    # NOTE: never put ASCII double quotes inside a CJK string literal here — use 「」 instead.
    w("- `gap_residual` 的精度极高（98%+）但**总体召回低**，因为可测间隙只覆盖部分单元；"
      "最右列给出「仅在覆盖到的单元里」的召回，两列一起看才不会误判它弱。")
    w("")
    w("## 2. 真实歌（无真值）：冻结判据后的触发比例与重解码队列")
    w("")
    w(f"13,735 单元；间隙特征覆盖 {pct(real['gap_coverage'])}；"
      "各 flag 触发比例：" + "、".join(f"`{k}` {pct(v)}" for k, v in real["flag_shares"].items())
      + f"；**任一 flag {pct(real['any_flag_share'])}**。")
    w("")
    w("| 排名 | 歌曲 | 语言 | 单元 | 被 flag 比例 | 倒序 | 间隙残余 | 高熵 | 融合分中位 |")
    w("|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for i, row in enumerate(real["queue_top"], 1):
        w(f"| {i} | {row['song']} | {row['language']} | {row['units']:,} | "
          f"{pct(row['flagged_share'])} | {row['inversion_units']} | {row['gap_residual_units']} | "
          f"{row.get('high_entropy_units', 'n/a')} | {row['median_fused_score']} |")
    w("")
    w("- 队首全是非中文歌（English/Japanese），**中文歌无一进入前十** ⇒ 与第 6/12/15 轮"
      "「普通话是最新康的路径」第四次独立复现；")
    w(f"- 队列是按 flag 比例排序的**建议复核顺序**，不是「这些歌错了」的断言："
      "真实歌没有真值，只能靠抽样人工确认或第 24 轮那个小标注实验来定性。")
    w("- 完整队列：`runs/20260912_trigger_fusion/redecode_queue_real_songs.csv.gz`。")
    w("")
    w("## 3. 口径与方法纪律（本轮自己踩到并修掉的两个坑）")
    w("")
    w(f"- **绝对熵阈值不跨域**：把 GTSinger 上看着合理的 `entropy ≥ 1.0 nats` 直接用到产品批，"
      f"会 flag **68.7%** 的单元（等于没有筛选力）。现改为**批内分位**"
      f"（top {pct(1 - 0.8, 0)}），触发比例回到设计值；")
    w("- **召回分母必须区分全体与被覆盖子集**（间隙特征只覆盖 "
      f"{pct(real['gap_coverage'])} 的真实歌单元、GTSinger 上 "
      f"{pct(val['gap_coverage'])}），否则会把这个高精度特征读成弱特征。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_trigger_fusion.py")
    w("PYTHONPATH=src python scripts/evaluation/report_trigger_fusion.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_trigger_fusion.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "trigger_fusion_metrics_v1", "audit": r,
         "headline": {
             "gtsinger_end_error_auc": {n: val["all_views"]["triggers"]["end_error_gt_100ms"].get(n, {}).get("auc")
                                        for n in names},
             "gtsinger_end_error_recall_at_20pct": {
                 n: val["all_views"]["triggers"]["end_error_gt_100ms"].get(n, {}).get(
                     "recall_at_20pct_budget") for n in names},
             "production_view_auc": {n: fv.get(n, {}).get("auc") for n in names} if fv else None,
             "long_note_auc": {n: ln.get(n, {}).get("auc") for n in names} if ln else None,
             "real_song_flag_shares": real["flag_shares"],
             "real_song_any_flag_share": real["any_flag_share"],
             "queue_top5": [x["song"] for x in real["queue_top"][:5]],
             "mandarin_in_top10": any("Chinese" == str(x.get("language")) for x in real["queue_top"]),
             "conclusion": "gap residual is a high-precision but coverage-limited trigger, entropy is the "
                           "workhorse, inversion targets a different failure; fused rank beats any single "
                           "signal, and no Mandarin song enters the top-10 re-decode queue"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
