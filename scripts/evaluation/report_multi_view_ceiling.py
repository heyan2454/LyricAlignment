#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the multi-decode headroom report + the one-page pre-delivery checklist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_multi_view_ceiling")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_multi_view_ceiling.md")
    ap.add_argument("--checklist", type=Path,
                    default=REPO / "docs/status/20260912_predelivery_checklist.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_multi_view_ceiling/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "MULTI_VIEW_CEILING.json").read_text(encoding="utf-8"))
    gts, mir = r["panels"]["gtsinger_12_views"], r["panels"]["mir1k_6_checkpoints"]

    def table(blk):
        rows = ["| 层 | 单元 | 生产视图 | 最好单视图 | **并集 oracle** | 选择可挽回 | 无任何视图正确 | 全对 | 错误相关性 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name, st in blk["strata"].items():
            rows.append(f"| {name} | {st['units']:,} | {pct(st.get('production_view_hit'))} | "
                        f"{pct(st['best_single_view_hit'])} | **{pct(st['union_oracle_hit'])}** | "
                        f"{st.get('regret_recoverable_by_selection_pp', 0):+.2f}pp | "
                        f"{pct(st['no_view_correct_share'],1)} | {pct(st['all_views_correct_share'],1)} | "
                        f"{st.get('mean_pairwise_error_correlation_with_production')} |")
        return rows

    L: list[str] = []
    w = L.append
    w("# 多解码选择的空间有多大：并集 oracle 与错误相关性（第 20 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_multi_view_ceiling/MULTI_VIEW_CEILING.json` 生成；只读既有面板，零前向。")
    w("> **纪律**：MIR-1K 是 test-only，其数字只作为**回溯上界**报告，"
      "不用于选 checkpoint/视图/阈值；决策依据是 GTSinger（人工真值、非 test）与 M4（弱标签）。")
    w("")
    w("## 0. 结论")
    w("")
    ga, gl = gts["strata"]["all_units"], gts["strata"]["long_note"]
    ma, ml = mir["strata"]["all_units"], mir["strata"]["long_note"]
    w(f"- **在录音室中文数据上，多视图选择这条路可以关掉了**：12 个视图的并集 oracle 只有 "
      f"{pct(ga['union_oracle_hit'])}（生产视图 {pct(ga['production_view_hit'])}，"
      f"**最多再赚 {ga['regret_recoverable_by_selection_pp']:+.2f}pp**）；"
      f"长音层更少：{gl['regret_recoverable_by_selection_pp']:+.2f}pp。")
    w(f"- 原因是**错误高度相关**：各视图与生产视图的错误相关性 "
      f"全体 {ga['mean_pairwise_error_correlation_with_production']}、"
      f"首单元 {gts['strata']['is_first']['mean_pairwise_error_correlation_with_production']}"
      "（选择需要的是**去相关**）；同时全体有 "
      f"{pct(ga['no_view_correct_share'],1)} 的单元**12 个视图全错**"
      f"（长音 {pct(gl['no_view_correct_share'],1)}、首单元 "
      f"{pct(gts['strata']['is_first']['no_view_correct_share'],1)}）⇒ 与第 19 轮「真值不在候选里」同源。")
    w(f"- **真实录音上留白更大**（MIR-1K，6 个 checkpoint，回溯上界）：并集 {pct(ma['union_oracle_hit'])} vs "
      f"生产 {pct(ma['production_view_hit'])} ⇒ **{ma['regret_recoverable_by_selection_pp']:+.2f}pp**；"
      f"长音层 **{ml['regret_recoverable_by_selection_pp']:+.2f}pp**（错误相关性只有 "
      f"{ml['mean_pairwise_error_correlation_with_production']}，去相关更高）。"
      f"但第 9 轮实测的共识收益只有 +2.3pp ⇒ **oracle 与实际选择器之间还差约一半**，"
      "那需要新的证据（换窗口/重解码），不是更好的平均。")
    w(f"- **口径警告（对 detector_v2 的 SAFE 带很重要）**：容差敏感性显示 50ms 时并集 oracle 掉到 "
      f"{pct(gts['tolerance_sensitivity']['50ms']['union_oracle_hit'],1)}"
      f"（MIR-1K {pct(mir['tolerance_sensitivity']['50ms']['union_oracle_hit'],1)}），"
      f"且 {pct(gts['tolerance_sensitivity']['50ms']['no_view_correct_share'],1)} / "
      f"{pct(mir['tolerance_sensitivity']['50ms']['no_view_correct_share'],1)} 的单元"
      "**没有任何视图能达标** ⇒ 在 50ms 尺度上，指标主要在测解码上限，不是在测选择能力。")
    w("")
    w("## 1. GTSinger：12 视图并集 oracle（人工真值，非 test）")
    w("")
    L.extend(table(gts))
    w("")
    w("## 2. MIR-1K：6 个 checkpoint 并集 oracle（test-only，仅作回溯上界）")
    w("")
    L.extend(table(mir))
    w("")
    w("## 3. 一页式交付前检查清单（已单独写入 docs/status）")
    w("")
    w(f"- 见 `{args.checklist.relative_to(REPO)}`；条目来自本会话第 12–20 轮的实测阈值与教训，"
      "不是从别处抄来的清单。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_multi_view_ceiling.py")
    w("PYTHONPATH=src python scripts/evaluation/report_multi_view_ceiling.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_multi_view_ceiling.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")

    C: list[str] = []
    c = C.append
    c("# 对齐产物交付前检查清单（一页，2026-09-12 本会话沉淀）")
    c("")
    c("> 每条都对应本会话一次实测；阈值写在括号里，是本会话建议默认值，可在项目内讨论后调整。")
    c("> 机器执行入口：`PYTHONPATH=src python scripts/evaluation/audit_batch.py --batch <dir> "
      "[--compare-batch <dir>] [--triage-language Chinese --triage-out <csv.gz>]`")
    c("")
    c("| # | 检查 | 判据 | 依据 |")
    c("|---|---|---|---|")
    c("| 1 | **身份可归因** | 每首歌都有 `identity.audio.sha256` / `request_hash` / `schema_version`；"
      "缺任一项 ⇒ 该批结论标记为 unattributable | 第 5/11/13 轮（slot 批次 100% 缺失） |")
    c("| 2 | **批内因子真的变了** | 比较前先看内容哈希；两个单元格的音频/计划/权重相同 ⇒ 该因子是 dead config | "
      "第 10 轮（mix==vocal） |")
    c("| 3 | **批间可比** | `audit_pair` 必须返回 `identified`；`duplicate_configuration` / "
      "`not_comparable` 直接禁止出对比表 | 第 11 轮（B4 vs current = 重复运行；slot = 索引漂移） |")
    c("| 4 | **口径声明** | 每个表注明 attempt 级还是 unit 级；错误一律 `both_abs_err = max(|Δs|,|Δe|)` | "
      "第 7 轮 |")
    c("| 5 | **结构合法性** | 非法单元比例 ≤5%（零长/重叠/起点回退/超 3s 四类）| 第 6/12/13 轮 |")
    c("| 6 | **阶段归因** | 任一阶段净新增退化 ≤1%；超标要指到 `raw / processor_decoded / selected / final` 哪一步 | "
      "第 13/14/16 轮（fixed 阶段钉锚点 + 倒序钳零） |")
    c("| 7 | **起止顺序自检** | 各阶段 `start_after_end` ≤2%；raw 超阈 ⇒ 这些单元标为需重解码，"
      "**不要静默钳成零长** | 第 16 轮（870 个倒序被钳成 595 个零长） |")
    c("| 8 | **钉锚点检测** | 被钉到窗口 `input_start_sec` 的单元 ≤2%；超阈说明回映射把块钉死 | 第 13 轮（946 单元 6.89%） |")
    c("| 9 | **退化率的口径影响** | 报告 `hit@tol` 时同时给 `hit@tol_excluding_degenerate` 与 "
      "`degenerate_share`；两系统退化率差 >1pp 时不得把差值解释成精度差 | 第 17 轮（最多 +3.3pp 假差） |")
    c("| 10 | **可达性标注** | 报告分层：多少单元的 GT 格点连 top-2 候选都不是（长音实测 40%）；"
      "这部分不计入后处理的空间 | 第 19/20 轮 |")
    c("| 11 | **分诊** | >35% 非法 ⇒ 重解码，不打补丁；15–35% ⇒ 修复+复核；≤5% ⇒ 可发布 | 第 12/14 轮 |")
    c("| 12 | **不得从 test/OOD 选择** | checkpoint / 视图 / 阈值只能用非 test 面板确定；"
      "test 上只允许回溯式上界并显式标注 | 第 11/20 轮 |")
    c("| 13 | **realign 语义** | shadow-only，`actual_writeback` 必须为 0 | 项目硬约束 |")
    c("")
    c("## 已证否的路径（避免重复投入）")
    c("")
    c("- 事后声学阈值（RMS 衰减、人声/伴奏比值）修末字/长音：**否证**（第 11 轮，末字 oracle 界 +0.00pp）；")
    c("- 局部修补倒序（交换端点 / 邻居顺延）：**否证**（第 18 轮，结构反而更差、正确率仍≈0）；")
    c("- 在录音室中文数据上继续做多视图选择/共识：**空间已耗尽**（第 20 轮，最多 +2.4pp，长音 +0.88pp）。")
    c("")
    c("## 还剩什么")
    c("")
    c("- 训练侧（已被证明能抬高上限：长音不可达率 70.8%→21.7%，r1→r2 递减）；")
    c("- 换窗口/新证据的重解码触发器（raw 起止倒序 + 低置信度 + 钉锚点，三者都是免费的）；")
    c("- 需要真实长片段（≥180s）自然收尾的人工真值：GTSinger 全曲连续片段可做（第 9 轮已确认可行），需少量 GPU。")
    c("")
    args.checklist.parent.mkdir(parents=True, exist_ok=True)
    args.checklist.write_text("\n".join(C) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "multi_view_ceiling_metrics_v1", "audit": r,
         "headline": {
             "gtsinger_union_oracle_all": ga["union_oracle_hit"],
             "gtsinger_selection_regret_pp_all": ga["regret_recoverable_by_selection_pp"],
             "gtsinger_selection_regret_pp_long_note": gl["regret_recoverable_by_selection_pp"],
             "gtsinger_no_view_correct_share_all": ga["no_view_correct_share"],
             "gtsinger_error_correlation_all": ga["mean_pairwise_error_correlation_with_production"],
             "mir1k_union_oracle_all": ma["union_oracle_hit"],
             "mir1k_selection_regret_pp_all": ma["regret_recoverable_by_selection_pp"],
             "mir1k_selection_regret_pp_long_note": ml["regret_recoverable_by_selection_pp"],
             "union_oracle_at_50ms_gtsinger": gts["tolerance_sensitivity"]["50ms"]["union_oracle_hit"],
             "note": "MIR-1K figures are retrospective bounds on test-only data; nothing is selected with them",
             "conclusion": "multi-view selection is closed on studio Mandarin (+2.4pp max, +0.9pp on long "
                           "notes because 16% of units are wrong in all 12 views); real-recording checkpoints "
                           "leave ~+4.8pp of oracle headroom, half of which needs new evidence not better averaging"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "checklist": str(args.checklist)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
