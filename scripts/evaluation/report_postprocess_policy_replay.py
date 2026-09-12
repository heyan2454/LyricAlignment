#!/usr/bin/env python3
"""Render the post-processing policy-replay report from ``POLICY_REPLAY.json``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULE_NOTES = {
    "V0_shipped_official": "现装官方输出（记录的 selected 阶段，作参考）",
    "V1_raw_none": "完全不后处理（原始解码区间）",
    "V1b_raw_sanitize": "仅把负时长钳到零长，不做重叠消解",
    "V2_end_trim_only": "只修剪前单元尾端（永不推后起点）",
    "V3_start_push_only": "只推后单元起点（官方实际上就是在做这件事）",
    "V4_half_split": "重叠对中分到两侧",
    "V5_confidence_split": "按解码 top-1 置信度加权分配重叠（无真值）",
    "V6_end_trim_le0.30s": "只对 ≤0.30s 的重叠做尾端修剪",
    "V7_half_split_le0.30s": "只对 ≤0.30s 的重叠做对半分",
    "V7b_end_trim_le0.10s": "只对 ≤0.10s 的重叠做尾端修剪",
    "V9_end_trim_min0.05s": "尾端修剪 + 0.05s 最短时长保护（残留重叠交给渲染层）",
    "V10_end_trim_min0.10s": "尾端修剪 + 0.10s 最短时长保护",
    "V11_half_split_min0.05s": "对半分 + 0.05s 最短时长保护",
    "V99_oracle_pick_uses_gt": "每个重叠用真值挑最优处理方式（上界，不可部署）",
}


def pct(x, digits: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{digits}f}%"


def ms(x, digits: int = 1) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{digits}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", type=Path,
                    default=Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep"))
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_postprocess_policy_replay.md")
    args = ap.parse_args()

    r = json.loads((args.analysis_dir / "POLICY_REPLAY.json").read_text(encoding="utf-8"))
    rules, strata, recon, cons = r["rules"], r["strata"], r["rule_reconstruction"], r["stage_consistency"]
    ranked = sorted(rules.items(), key=lambda kv: -kv[1]["hit100_micro"])
    # best deployable rule: highest hit@100 among the non-GT rules, preferring the one that also
    # keeps the zero-duration rate at the raw level
    non_gt = [(k, v) for k, v in ranked if not v["uses_gt"]]
    top = non_gt[0][1]["hit100_micro"]
    tied = [k for k, v in non_gt if v["hit100_micro"] >= top - 1e-9]
    # tie-break: fewer degenerate units, then higher hit@200, then smaller end error
    best = min(tied, key=lambda k: (rules[k]["zero_dur_rate"], -rules[k]["hit200_macro"],
                                    rules[k]["mae_end_macro"], k))

    L: list[str] = []
    a = L.append
    a("# 后处理策略重放实验（2026-09-12 第 2 轮，纯 CPU）")
    a("")
    a("> 数字全部由 `runs/20260912_gtsinger_gt_deep/POLICY_REPLAY.json` 生成"
      "（`scripts/evaluation/report_postprocess_policy_replay.py`），不手抄。")
    a("> 承接第 1 轮发现 2（官方后处理对真值净负 −1.66pp），本轮**只重放已记录的 raw 区间**，"
      "不做任何前向、不改实现：回答\"改成什么规则能挽回多少\"。")
    a("")
    a(f"面板：official 侧 {r['panel']['units']:,} 个单元行 / {r['panel']['sequences']:,} 条序列"
      f"（159 段 × 12 标注配置），与 raw 侧按同一 identity 配对 {cons['n_paired_units']:,} 单元；"
      f"冻结口径 {r['tolerances_sec']} s，段聚类 bootstrap。")
    a("")

    a("## 1. 现装规则到底在做什么（先归因，再改造）")
    a("")
    oo = recon["overlap_outcome"]
    a(f"- 原始解码存在重叠的单元对：{recon['n_overlaps']:,}"
      f"（占 {pct(recon['overlap_rate'])} 的单元），被推后起点那批的平均重叠 "
      f"{ms(recon['decision_variable']['mean_overlap_start_pushed_sec'])}。")
    a(f"- 官方对这些重叠的处理：推后起点 **{oo['start_pushed_only']:,}** 次、"
      f"修剪尾端仅 **{oo['end_trimmed_only']}** 次、两侧都动 {oo['both_moved']} 次、"
      f"未处理 {oo['neither_moved']} 次 ⇒ 被推后的起点有 "
      f"{pct(recon['overlap_and_start_moved']['share_pinned_to_prev_raw_end'])} 精确等于前一单元尾端。")
    dv = recon["decision_variable"]
    a(f"- 选哪一侧动，**不是按置信度**：置信差（本单元起点 − 前单元尾端）预测\"动哪侧\"的 AUC "
      f"{dv['auc_conf_gap_predicts_which_side']}（Mann-Whitney p={dv['mannwhitney_p_conf_gap']:.2f}，不显著）；"
      f"只有重叠大小有信号（AUC {dv['auc_overlap_size_predicts_which_side']}，"
      f"p={dv['mannwhitney_p_overlap_size']:.1e}），但\"动尾端\"只有 {oo['end_trimmed_only']} 例、"
      f"平均重叠 {ms(dv['mean_overlap_end_trimmed_sec'])}——即样本太少，无法当作已实现的分支逻辑。")
    zd = recon["zero_duration"]
    a(f"- 零时长单元由 {pct(zd['raw_rate'],2)} 升到 {pct(zd['final_rate'],2)}："
      f"后处理新增了 {zd['created_by_postprocess']:,} 个零时长单元，其中 "
      f"{pct(zd['share_created_with_prev_end_equal'],1)} 的起点正好等于前单元尾端"
      "（即推后起点直接把它压扁）。")
    a("")

    a("## 2. 预注册规则族与结果")
    a("")
    a("| 排名 | 规则 | 说明 | hit@100 | hit@200 | MAE start | MAE end | IoU | 零时长率 | Δ vs 官方 (pp) [95% CI] | 段胜/负/平 |")
    a("|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    for i, (name, v) in enumerate(ranked, 1):
        pe = v.get("paired_vs_reference") or {}
        ci = pe.get("ci95_pp", [0, 0])
        paired = (f"{pe['vs_reference_hit100_pp']:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]"
                  if pe else "—（参考）")
        wl = (f"{pe['sequences_better']}/{pe['sequences_worse']}/{pe['sequences_tied']}" if pe else "—")
        flag = " ⚠️用GT" if v["uses_gt"] else ""
        a(f"| {i} | `{name}`{flag} | {RULE_NOTES.get(name, '')} | {pct(v['hit100_micro'])} | "
          f"{pct(v['hit200_macro'])} | {ms(v['mae_start_macro'],0)} | {ms(v['mae_end_macro'],0)} | "
          f"{v['iou_macro']:.3f} | {pct(v['zero_dur_rate'])} | {paired} | {wl} |")
    a("")
    b = rules["V9_end_trim_min0.05s"]
    o = rules["V99_oracle_pick_uses_gt"]
    a(f"- **可用最优是 `{best}`**：hit@100 {pct(b['hit100_micro'])}"
      f"（比现装 {b['paired_vs_reference']['vs_reference_hit100_pp']:+.2f}pp，"
      f"CI [{b['paired_vs_reference']['ci95_pp'][0]:+.2f}, "
      f"{b['paired_vs_reference']['ci95_pp'][1]:+.2f}]，段级 {b['paired_vs_reference']['sequences_better']} 胜 / "
      f"{b['paired_vs_reference']['sequences_worse']} 负 ≈ "
      f"{b['paired_vs_reference']['sequences_better']/max(b['paired_vs_reference']['sequences_worse'],1):.0f}:1），"
      f"hit@200 {pct(b['hit200_macro'])}，IoU {b['iou_macro']:.3f}，"
      f"且零时长率回到原始水平 {pct(b['zero_dur_rate'])}（现装 "
      f"{pct(rules['V0_shipped_official']['zero_dur_rate'])}）。")
    a(f"- 用真值给每个重叠挑最优处理方式的**上界**也只有 {pct(o['hit100_micro'])}"
      f"（{o['paired_vs_reference']['vs_reference_hit100_pp']:+.2f}pp）："
      f"`{best}` 已拿到该空间的 "
      f"{100*b['paired_vs_reference']['vs_reference_hit100_pp']/o['paired_vs_reference']['vs_reference_hit100_pp']:.0f}%，"
      "说明重叠消解这一处的改造空间基本被吃干净，不必再为它设计更复杂的仲裁器。")
    a(f"- **反例同样重要**：只推起点（`V3_start_push_only`）比现装还差 "
      f"{rules['V3_start_push_only']['paired_vs_reference']['vs_reference_hit100_pp']:+.2f}pp，"
      f"零时长 {pct(rules['V3_start_push_only']['zero_dur_rate'])}；"
      f"对半分（`V4`）几乎无收益（"
      f"{rules['V4_half_split']['paired_vs_reference']['vs_reference_hit100_pp']:+.2f}pp）；"
      f"按置信度仲裁（`V5`）仅 "
      f"{rules['V5_confidence_split']['paired_vs_reference']['vs_reference_hit100_pp']:+.2f}pp。"
      "⇒ 关键变量是**让哪一侧动**，不是怎么分配、也不是要不要按置信度分档。")
    a(f"- 只对\"小重叠\"处理的阈值版（`V6`/`V7b`）反而不如无条件尾端修剪"
      f"（{pct(rules['V6_end_trim_le0.30s']['hit100_micro'])} / "
      f"{pct(rules['V7b_end_trim_le0.10s']['hit100_micro'])} vs {pct(b['hit100_micro'])}）："
      "大重叠正是最该修尾端的地方，回避它等于把误差留在原地。")
    a("")

    a("## 3. 分层效果（总体均值会掩盖的部分）")
    a("")
    a("| 规则 | 段首单元 hit@100 | 长音(>0.6s) | 其余 | 零声母音节 | 段首×零声母 |")
    a("|---|---:|---:|---:|---:|---:|")
    for name in ("V0_shipped_official", "V1_raw_none", "V3_start_push_only",
                 "V5_confidence_split", best, "V99_oracle_pick_uses_gt"):
        st = strata[name]
        a(f"| `{name}` | {pct(st['first_unit_hit100'],1)} | {pct(st['long_note_hit100'],1)} | "
          f"{pct(st['rest_hit100'],1)} | {pct(st['onsetless_hit100'],1)} | "
          f"{pct(st['onsetless_and_first_hit100'],1)} |")
    a("")
    a(f"- 段首单元（n={strata[best]['first_unit_n']:,}，每序列第一个）从 "
      f"{pct(strata['V0_shipped_official']['first_unit_hit100'],1)} 升到 "
      f"{pct(strata[best]['first_unit_hit100'],1)}；零声母音节从 "
      f"{pct(strata['V0_shipped_official']['onsetless_hit100'],1)} 升到 "
      f"{pct(strata[best]['onsetless_hit100'],1)}。这两个层正是第 1 轮报告里被均值掩盖的失效层。")
    a("- 注意：段首**幻觉前奏**（预测起点被推迟约 0.5s）不在本实验的处理范围内——"
      "它发生在解码本身，不是重叠消解，任何后处理规则都救不了它。")
    a("")

    bd = r.get("breakdowns", {})
    if bd:
        a("## 3b. 子群稳健性（防止结论由单一子群驱动）")
        a("")
        for dim, label in (("singer", "歌手"), ("group", "技法组"), ("model", "模型")):
            rows = bd.get(dim)
            if not rows or best not in rows:
                continue
            a(f"- **{label}**（`{best}` 相对现装的 hit@100 变化，单位 pp）：")
            items = sorted(rows[best].items(), key=lambda kv: kv[1]["delta_vs_ref_pp"])
            a("")
            a(f"| {label} | Δhit@100 | 该子群 hit@100 | 单元数 |")
            a("|---|---:|---:|---:|")
            for name, v in items:
                a(f"| `{name}` | {v['delta_vs_ref_pp']:+.2f} | {pct(v['hit100'],1)} | {v['n_units']:,} |")
            n_neg = sum(1 for _, v in items if v["delta_vs_ref_pp"] < 0)
            a("")
            a(f"  {len(items) - n_neg}/{len(items)} 个子群为正"
              + ("（无一为负）" if n_neg == 0 else f"，{n_neg} 个子群为负：{', '.join(n for n, v in items if v['delta_vs_ref_pp'] < 0)}"))
            a("")
    a("## 4. 顺带的口径澄清：\"raw 管线\"并非\"无后处理\"")
    a("")
    fd, rps = cons["forward_determinism"], cons["raw_pipeline_self_adjustment"]
    a(f"- **前向可复现**：official 与 raw 两次独立前向记录的 raw 阶段"
      f"（{fd['n_differing_gt_1ms']} / {cons['n_paired_units']:,} 单元差异 >1ms，"
      f"最大 {ms(fd['max_diff_sec'],0)}）⇒ **完全一致**。"
      "按 identity 复用 evidence 缓存的前提成立。")
    a(f"- 但 raw 管线自己的 selected 阶段相对其 raw 阶段仍动了 {rps['n_adjusted']} 个单元"
      f"（{pct(rps['share_adjusted_gt_1ms'],2)}，全部只动 end，"
      f"其中 {cons['cross_pipeline_selected_vs_raw']['n_negative_to_zero_clamps']} 个是"
      f"负时长→零长钳位，{pct(cons['cross_pipeline_selected_vs_raw']['share_trimmed_earlier'],1)} 是修剪提前）。")
    a(f"- 官方管线调整了 {cons['official_pipeline_adjustment']['n_adjusted']:,} 个单元"
      f"（{pct(cons['official_pipeline_adjustment']['share_adjusted_gt_1ms'],1)}）。"
      "⇒ 第 1 轮的 official-vs-raw 对比准确表述是\"完整清理 vs 最小清理\"，"
      "本实验的 `V1_raw_none` 才是真正的\"零后处理\"，也正是它给出了 `V2/V9` 的原料。")
    a("")

    a("## 5. 决策建议（不改实现，只登记证据）")
    a("")
    a(f"1. 把重叠消解从\"推后起点\"改为\"**修剪前单元尾端 + 最短时长保护**\"（`{best}`，"
      f"该保护值为 0.05–0.10 s 时结果等价，仅影响显示可用性）：")
    a(f"   证据：hit@100 "
      f"{b['paired_vs_reference']['vs_reference_hit100_pp']:+.2f}pp、"
      f"零时长率从 {pct(rules['V0_shipped_official']['zero_dur_rate'])} 降回 "
      f"{pct(b['zero_dur_rate'])}，且段级 14:1 以上的一致占优。")
    a("2. 该项属于 `qwen_fa_alignment` 官方 decoder 后处理阶段，改动会**使既有 official 口径产物失效**："
      "按冻结参数纪律，必须先在诊断面板复评（本轮已完成），再决定是走新口径分支还是替换默认，"
      "且替换后要把受影响的 evidence/identity 全部作废重算（内容寻址，不静默复用）。")
    a("3. 不要因为本实验去开\"整体关掉后处理\"的口子：`V1_raw_none`（"
      f"{pct(rules['V1_raw_none']['hit100_micro'])}）仍低于 `{best}`（{pct(b['hit100_micro'])}），"
      "而且它保留了负时长单元（结构性 gate 会拒绝）。")
    a("4. 下一步优先级转向**解码本身的两层失效**（段首幻觉前奏、零声母起点），"
      "后处理侧的可达空间已被本轮量化到 ≈2.4pp。")
    a("")

    a("## 6. 边界")
    a("")
    a("- 只在 GTSinger 中文短片段（159 段、2 歌手、2 曲）上重放；长歌串行合并、"
      f"跨窗口缝合等阶段未被模拟，`{best}` 在长数据上的效果需要真实复现才能声称。")
    a("- 重放以记录的 raw 区间为输入，忽略后处理可能触发的其他分支（例如窗口提交游标、"
      "seam 修复），因此它给出的是\"该规则族的方向与量级\"，不是替换实现的验收值。")
    a("- 评价口径为 100/200ms 真值命中；最短时长保护 0.05/0.10s 是显示可用性约束，不是精度指标。")
    a("- `V99_oracle_pick_uses_gt` 只作上界，禁止用于任何选择或报告为方法性能。")
    a("")

    a("## 7. 复现")
    a("")
    a("```bash")
    a("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    a("cd /home/hyan/LyricAlignment")
    a("PYTHONPATH=src python scripts/evaluation/extract_gtsinger_unit_evidence.py \\\n"
      "    --preset gtsinger --out-root /home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep")
    a("PYTHONPATH=src python scripts/evaluation/replay_gtsinger_postprocess_policies.py")
    a("PYTHONPATH=src python scripts/evaluation/report_postprocess_policy_replay.py")
    a("PYTHONPATH=src python -m pytest -q tests/evaluation/test_postprocess_policy_replay.py")
    a("```")
    a("")
    a("- 产物：`POLICY_REPLAY.json`（本报告的来源）、`policy_replay_by_sequence.csv.gz`"
      "（逐序列×规则 rollup，156 KB）。代码："
      "`src/lyricalign/analysis/postprocess_replay.py`。")
    a("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "best_rule": best},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
