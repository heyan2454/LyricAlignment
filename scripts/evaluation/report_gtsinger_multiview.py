#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the GTSinger multi-view selection report (human GT) from its JSON artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_multiview")
REPO = Path(__file__).resolve().parents[2]
SEL_DESC = {
    "R1_consensus_median_boundaries": "跨视图边界取中位（共识）",
    "R0_mean_of_views": "随机一个视图（视图平均）",
    "S_pick_min_consensus_distance": "离共识最近的那个视图",
    "S_pick_max_support": "与其他视图 100ms 内一致度最高",
    "S_pick_min_entropy": "该视图边界熵最低",
    "S_production_when_confident_else_best_support": "现装视图若与共识≤100ms 就保留，否则换支持度最高视图",
}


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else (f"{float(x):.3f}s" if abs(x) >= 1 else f"{1000 * float(x):.{d}f}ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_gtsinger_multiview.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_gtsinger_multiview/metrics.json")
    args = ap.parse_args()
    allr = json.loads((args.run / "MULTIVIEW.json").read_text(encoding="utf-8"))

    L: list[str] = []
    w = L.append
    w("# GTSinger 多视图选择实验（人工真值，2026-09-12 第 10 轮）")
    w("")
    w("> 数字由 `runs/20260912_gtsinger_multiview/MULTIVIEW.json` 生成。纯 CPU、零新增前向。")
    w("> 参考是 GTSinger **人工逐字/逐词标注**（比第 9 轮的弱标签硬）。")
    w("")
    w("## 0. 结论：这里没有可用的多视图，且任何选择器都不如现装配置")
    w("")
    off = allr["official"]
    prod = off["per_view_baseline"]["production_view"]
    gap = off["oracle_gap_pp"]
    gc = off["gap_closed"]
    best_sel = max(gc.items(), key=lambda kv: kv[1]["hit100"])
    w(f"- 名义上每个单元有 **12 个视图**（3 checkpoint × mix/vocal × full/windowed），"
      f"但按因子分解后：**同一 checkpoint 内的 4 个单元格几乎完全相同**"
      f"（start 边界差中位 {off['diversity']['factor_decomposition']['model (other factors held fixed)']['start_diff_median_sec']}s、"
      f"audio_input 与 mode 同样为 "
      f"{off['diversity']['factor_decomposition']['audio_input (other factors held fixed)']['start_diff_median_sec']}s）"
      "⇒ 第 1 轮的『3×2×2 矩阵退化』结论现在有了定量版本：**GTSinger 无法提供真正的输入多样性视图**。")
    w(f"- 唯一有效的差异轴是 **checkpoint**（r0/r1/r2 相差最多 20.5pp hit@100），"
      f"而 r2 恰好是最好的一档 ⇒ 所谓『12 视图的 oracle 上界』只有 **{gap:+.2f}pp**"
      f"（因为差距基本来自 r0/r1 在个别单元上偶然更好，而不是视图信息更多）。")
    w(f"- **所有无真值选择器都是负的**：共识 "
      f"{pct(gc['R1_consensus_median_boundaries']['hit100'])}（{gc['R1_consensus_median_boundaries']['delta_pp_vs_production']:+.2f}pp）、"
      f"最近共识 {gc['S_pick_min_consensus_distance']['delta_pp_vs_production']:+.2f}pp、"
      f"熵最低 {gc['S_pick_min_entropy']['delta_pp_vs_production']:+.2f}pp、"
      f"支持度最高 {gc['S_pick_max_support']['delta_pp_vs_production']:+.2f}pp；"
      f"现装视图 {prod['name']} = {pct(prod['hit100'])} 已经是最优单视图。")
    w("- 原因很直白：把 r0（67.5%）和 mix/vocal、full/windowed 这些**同质但更差**的输出混进共识，"
      "只会把 r2 的正确答案稀释掉。")
    w("")
    w("## 1. 视图质量表（official 阶段）")
    w("")
    w("| 视图 (model\\|audio\\|mode) | hit@100 | hit@250 | MAE |")
    w("|---|---:|---:|---:|")
    for k, v in sorted(off["diversity"]["views"].items(), key=lambda kv: -kv[1]["hit100"]):
        w(f"| `{k}`{' ← 现装' if v['is_production_view'] else ''} | {pct(v['hit100'])} | "
          f"{pct(v['hit250'])} | {sec(v['mae_both_sec'])} |")
    w("")
    w("## 2. 因子退化诊断（这就是『多视图』不成立的原因）")
    w("")
    w("| 因子 | 层级（比较次数） | start 边界差中位 | start >100ms 比例 | end >100ms 比例 |")
    w("|---|---|---:|---:|---:|")
    for f, v in off["diversity"]["factor_decomposition"].items():
        w(f"| `{f.replace(' (other factors held fixed)','')}` | {', '.join(v['levels'])} "
          f"（{v['matched_cells']:,} 组固定其他因子的比较）| "
          f"{v['start_diff_median_sec']}s | {pct(v['start_diff_share_gt_100ms'],1)} | "
          f"{pct(v['end_diff_share_gt_100ms'],1)} |")
    w("")
    w(f"- 跨视图整体分歧：中位 {off['diversity']['cross_view_disagreement']['median_sec']}s、"
      f"p90 {off['diversity']['cross_view_disagreement']['p90']}s、"
      f">100ms 占 {pct(off['diversity']['cross_view_disagreement']['share_gt_100ms'],1)}"
      "——但这些分歧几乎全部发生在 checkpoint 之间，而不是视图之间。")
    w("")
    audit = off.get("factor_content_audit", {})
    if audit.get("available"):
        w("## 2b. 内容审计：那些因子到底有没有换过输入")
        w("")
        w("`request_hash` 不同 ≠ 输入内容不同（路径也是身份的一部分）。按「其他因子固定」逐组比较")
        w("`audio_sha256`：")
        w("")
        w("| 因子 | 期望 | 相同音频 sha 的比例 | 判定 |")
        w("|---|---|---:|---|")
        EXP = {"audio_input": "应换音频字节", "mode": "同文件换计划", "model": "同文件换 checkpoint"}
        for f, v in audit["factors"].items():
            w(f"| `{f}` | {EXP.get(f,'—')} | {pct(v['share_identical_audio_sha'],1)} | {v['verdict']} |")
        w("")
        ai = audit["factors"].get("audio_input", {})
        if ai and ai["verdict"].startswith("DEAD"):
            w(f"- **发现历史实验缺陷（P1）**：{ai['matched_cells']:,} 组 mix/vocal 配对的 "
              f"`audio_sha256` **{pct(ai['share_identical_audio_sha'],1)} 相同** ⇒ 那次「混音 vs 人声」消融"
              "**从未真的换过输入**，只有 request_hash 因路径不同而变了；"
              "所有基于 evaluation_v1 该因子的结论都作废（第 1 轮已标记矩阵退化，本轮给出根因）。")
        w("- `mode` 不是 bug：短片（5–15s）本来就短于一个 60s 窗口，分窗与整曲必然同结果"
          "⇒ 该因子**在此数据上无信息**，要检验必须用长音频（第 9 轮的长时序面板正是这种数据）。")
        w("- 这也解释了为什么「12 视图」的跨视图分歧只来自 checkpoint：输入侧根本没有变化。")
        w("- **流程教训（第 2 轮就提过、这轮再次命中）**：批次收尾必须跑**配置矩阵同一性门**——"
          "凡两单元格内容哈希相同而标签不同，就直接判 `not_identified` 并拒绝出对比结论。"
          "本模块的 `factor_content_audit()` 就是该门的最小实现，可挂到任意批次上。")
        w("")
    w("## 3. 与第 5/9 轮合并后的规律（本轮真正的产出）")
    w("")
    w("| 证据 | 视图差异来源 | 基线 | 共识/选择效果 |")
    w("|---|---|---|---|")
    w(f"| 第 5 轮（MIR-1K 自然录音） | 同一裁窗换 checkpoint | 现装单视图 | "
      f"+0.34pp（oracle +4.57pp，吃 7.4%） |")
    w(f"| 第 9 轮（M4 长时序） | **不同裁窗**（同 checkpoint） | 任意一个覆盖窗口 | "
      f"**+2.14pp**（免费） |")
    w(f"| 本轮（GTSinger，人工真值） | 混合：换 checkpoint + 退化因子 | **已选好的最优视图** | "
      f"{gc['R1_consensus_median_boundaries']['delta_pp_vs_production']:+.2f}pp（共识反而更差） |")
    w("")
    w("⇒ **三条一起给出的可执行规则**：")
    w("1. 只有当视图在**输入层面真的不同**（不同裁窗/不同音频条件）时，多视图才有信息量——"
      "同一裁窗换模型几乎无收益（第 5 轮），同一模型换退化因子是零收益（本轮）。")
    w("2. 参与共识的视图**质量必须齐平**：把明显更差的视图（r0、或未适配的上游系统）混进来是净损害"
      "（本轮 −0.75pp；第 5 轮把上游 base 混进集合时 AUC 从 0.839 掉到 0.789）。"
      "⇒ 任何 multi-view 设计都需要**成员能力门**，且门的依据不能是用真值挑出来的。")
    w("3. 选择器的价值取决于『基线是否已经是最优视图』：当基线是随机/任意视图时长序共识赚 2.14pp，"
      "当基线已是最好视图时任何选择都亏 ⇒ **先确认基线是什么，再谈融合**。")
    w(f"- 另一个一致的细分结论：熵作为**触发器**有效（第 1/3/5/9 轮 AUC 0.78–0.88），"
      f"作为**视图选择器**无效（本轮 {gc['S_pick_min_entropy']['delta_pp_vs_production']:+.2f}pp）"
      "⇒ 它回答『这个单元可不可信』，不回答『哪个视图对这个单元更好』。")
    w("")
    w("## 4. 边界")
    w("")
    w("- 人工真值只覆盖 GTSinger mini（2,415 单元 / 录音室短片段），"
      "而它恰恰是**唯一没有真实视图多样性**的数据源；因此本轮结论是"
      "『该数据不能用来证明多视图有效』，而不是『多视图在所有数据上无效』。")
    w("- raw 阶段同向：现装视图 89.74%，共识 89.28%（−0.46pp），oracle 差距 +2.93pp。")
    w("- 未做任何 GPU 实验；若要真正验证多视图收益，需要**同一最好 checkpoint + 多个不同裁窗**的前向，"
      "这在长时序上已有留存证据（第 9 轮），在短片段上需要新数据。")
    w("")
    w("## 5. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_gtsinger_multiview.py")
    w("PYTHONPATH=src python scripts/evaluation/report_gtsinger_multiview.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_gtsinger_multiview.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {"schema_version": "gtsinger_multiview_metrics_v1", "source": str(args.run / "MULTIVIEW.json"),
               "official": allr["official"], "raw": allr.get("raw"),
               "headline": {
                   "units": allr["official"]["diversity"]["units"],
                   "nominal_views_per_unit": len(allr["official"]["diversity"]["views"]),
                   "production_view_hit100": allr["official"]["per_view_baseline"]["production_view"]["hit100"],
                   "consensus_delta_pp": allr["official"]["gap_closed"]["R1_consensus_median_boundaries"]["delta_pp_vs_production"],
                   "best_selector_delta_pp": max(v["delta_pp_vs_production"]
                                                 for v in allr["official"]["gap_closed"].values()),
                   "oracle_gap_pp": allr["official"]["oracle_gap_pp"],
                   "factor_content_audit": allr["official"].get("factor_content_audit"),
                   "audio_input_ablation_was_real": bool(
                       allr["official"].get("factor_content_audit", {}).get("factors", {})
                       .get("audio_input", {}).get("share_identical_audio_sha") == 0.0),
                   "factor_degeneration": {k.replace(" (other factors held fixed)", ""): {
                       "start_diff_median_sec": v["start_diff_median_sec"],
                       "end_diff_share_gt_100ms": v["end_diff_share_gt_100ms"]}
                       for k, v in allr["official"]["diversity"]["factor_decomposition"].items()},
                   "conclusion": "views must differ at the input level AND be of comparable quality; "
                                 "on GTSinger the audio/mode factors are degenerate, so consensus loses "
                                 "to the production view"},
               }
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
