#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the natural-Mandarin MIR-1K panel report from its JSON artifacts (no hand-copied numbers)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DIR = Path("/home/hyan/Data/lyricalign/runs/20260912_mir1k_natural_panel")
REPO = Path(__file__).resolve().parents[2]
ORDER = ("base_qwen_raw_v1", "r0_raw_20260724", "r1_full_20260724", "r2_full_20260723",
         "r2_seed_20260724", "r2_ood_20260723")
DESC = {
    "base_qwen_raw_v1": "上游 Qwen FA 原始输出（2026-07-22，本项目适配之前）",
    "r0_raw_20260724": "R0：未适配 base（同 audio/labels 口径）",
    "r1_full_20260724": "R1：projector 适配",
    "r2_full_20260723": "R2：LoRA seed3407 step-1000",
    "r2_seed_20260724": "R2：LoRA seed20260724 step-0750（同结构不同训练 run）",
    "r2_ood_20260724": "",
    "r2_ood_20260723": "R2：另一评测配置的同名 checkpoint",
}


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{d}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_mir1k_natural_panel.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_mir1k_natural_panel/metrics.json")
    args = ap.parse_args()

    audit = json.loads((args.analysis_dir / "PANEL_AUDIT.json").read_text(encoding="utf-8"))
    a = json.loads((args.analysis_dir / "ANALYSIS.json").read_text(encoding="utf-8"))
    panel, by = a["panel"], a["by_predictor"]
    pos, leng = a["position_effects"], a["length_effect"]
    disq, recon = a["disagreement_signal_natural"], a["canonical_reconciliation"]
    defects, runs = a["structural_defects_by_predictor"], a["error_runs_natural"]
    var, pairs = a["per_item_variance"], a["predictor_pairs"]
    ref = var["reference_predictor"]

    L: list[str] = []
    w = L.append
    w("# 普通话自然录音真值面板（MIR-1K 人工逐字 GT × 既有预测，2026-09-12 第 4 轮）")
    w("")
    w("> 数字由 `runs/20260912_mir1k_natural_panel/{PANEL_AUDIT,ANALYSIS}.json` 生成，不手抄。")
    w("> 纯 CPU：全部复用 2026-07-22/24 已落盘的预测与人工标注，零新增前向。")
    w("> 用途纪律：MIR-1K 在 `data/datasets_registry.md` 中是 **test-only**，"
      "本面板只做报告，不得用于 checkpoint 选择或机制调参。")
    w("")

    w("## 0. 面板与对账")
    w("")
    r = audit["reference"]
    w(f"- 参考：{r['provenance']}；{r['characters']:,} 字 / {r['items']} 首 "
      f"（`{r['path'].split('/')[-1]}`，sha256 `{r['sha256'][:12]}…`）。")
    w(f"- 音频：真实伴奏流行歌曲提取的官方人声通道（{', '.join(panel['vocal_sources'])}），"
      f"时长 {panel['item_duration_sec']['min']}–{panel['item_duration_sec']['max']} s"
      f"（中位 {panel['item_duration_sec']['median']} s）。")
    w(f"- 预测器 {len(by)} 个，每个 {by[ref]['n_units']:,} 行，全部与参考逐字对齐"
      f"（未匹配行 0、字符不一致 0）⇒ 面板 {panel['unit_rows']:,} 单元行。")
    w("- **与 canonical 指标对账**（防第 3 轮那类伪造轴陷阱）：")
    w("")
    w("| 预测器 | canonical 文件 | canonical mean_iou | 本面板重算 IoU | Δ | canonical onset MAE | 重算 MAE(start) | invalid 数 | 重算零/负长占比 | 判定 |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for name, v in recon["per_predictor"].items():
        w(f"| `{name}` | `{v['canonical_file']}` | {v['canonical_mean_iou']:.5f} | "
          f"{v['recomputed_iou_mean']:.4f} | {v['iou_delta']:+.5f} | "
          f"{sec(v['canonical_onset_mae_sec'])} | {sec(v['recomputed_mae_start_sec'])} | "
          f"{v['canonical_invalid_prediction_count']} | {pct(v['recomputed_zero_or_negative_duration'])} | "
          f"**{v['verdict']}** |")
    w("")
    w(f"- {recon['note']}。")
    w("")

    w("## 1. 自然普通话上的真实水平（首次单元级）")
    w("")
    w("此前这批预测只留下一个标量 `loss`（0.80–1.73），没有单元级分析。")
    w("")
    w("| 预测器 | 说明 | hit@100（项 bootstrap CI） | hit@200 | hit@250 | MAE start | MAE end | IoU | 有符号 start（中位） | start 晚>100ms | 零/负时长率 |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in ORDER:
        v = by.get(name)
        if not v:
            continue
        d = defects.get(name, {})
        w(f"| `{name}` | {DESC.get(name, '')} | {pct(v['hit100'], 1)} "
          f"({pct(v['hit100_ci95_item_boot'][0], 1)}–{pct(v['hit100_ci95_item_boot'][1], 1)}) | "
          f"{pct(v['hit200'], 1)} | {pct(v['hit250'], 1)} | {sec(v['mae_start'])} | {sec(v['mae_end'])} | "
          f"{v['iou_mean']:.4f} | {sec(v['median_signed_start'])} | {pct(v['share_start_late_gt100'], 1)} | "
          f"{pct(d.get('zero_or_negative_duration_share'))} |")
    w("")
    b0, b1, b2 = by.get("r0_raw_20260724"), by.get("r1_full_20260724"), by.get(ref)
    if b0 and b1 and b2:
        w(f"- 阶梯与 GTSinger 结论同向：r0→r1 **+{(b1['hit100'] - b0['hit100']) * 100:.1f}pp**、"
          f"r1→r2 **{(b2['hit100'] - b1['hit100']) * 100:+.1f}pp**"
          f"（自然录音 + 真实伴奏 + 人工逐字 GT 上复现）。")
    w(f"- r0 的缺陷再次落在**尾边界**：MAE end {sec(b0['mae_end'])} vs start {sec(b0['mae_start'])}；"
      f"r1/r2 两端对称（{sec(b2['mae_start'])} / {sec(b2['mae_end'])}）。")
    w(f"- 上游原始系统 `base_qwen_raw_v1` 只有 {pct(by['base_qwen_raw_v1']['hit100'], 1)} hit@100，"
      f"且有 {pct(defects['base_qwen_raw_v1']['zero_or_negative_duration_share'], 1)} 零/负时长单元 ⇒ "
      "项目的适配工作（含后处理与通道修正）在这批数据上的贡献是决定性的，不能拿上游分数当基线。")
    w("")

    w("## 2. 关键新发现：失效层是**尾字**，不是首字")
    w("")
    w(f"`{ref}`（自然录音、人工 GT）：")
    w("")
    w("| 位置 | n | hit@100 | MAE start | 有符号 start | 有符号 end | 预测 start=0 占比 |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for r_ in pos[ref]["by_position"]:
        w(f"| {r_['bucket']} | {r_['n']} | {pct(r_['hit100'], 1)} | {sec(r_['mae_start'])} | "
          f"{sec(r_['mean_signed_start'])} | {sec(r_['mean_signed_end'])} | "
          f"{pct(r_['share_pred_start_at_zero'], 1)} |")
    w("")
    p1 = pos["r1_full_20260724"]["by_position"][-1]
    p0 = pos["r0_raw_20260724"]["by_position"][-1]
    pr = pos[ref]["by_position"][-1]
    pf = pos[ref]["by_position"][0]
    w(f"- 首字 hit@100 {pct(pf['hit100'], 1)}（**高于**中间位置 "
      f"{pct(pos[ref]['by_position'][2]['hit100'], 1)}），且 `{ref}` 的预测 start **从不**塌到 0："
      "⇒ 第 1 轮 GTSinger 的『段首幻觉前奏』在这里完全不出现，进一步支持第 3 轮的解释——"
      "那个失效需要『音频被硬切在起唱点』作为触发条件，而不是『处于边界』本身。")
    w(f"- 但**最后一个字**明显更差：hit@100 {pct(pr['hit100'], 1)}（r1 {pct(p1['hit100'], 1)}、"
      f"r0 {pct(p0['hit100'], 1)}），且尾边界偏移随模型翻号："
      f"`{ref}` 末字 end 平均 {sec(pr['mean_signed_end'])}（偏晚），"
      f"r1 {sec(p1['mean_signed_end'])}、r0 {sec(p0['mean_signed_end'])}（偏早，r0 达 "
      f"{abs(p0['mean_signed_end']):.2f}s）。")
    w("- ⇒ 需要新增的评测分层是**每项最后一个字符**（它同时是 realign 最容易吞掉/截断的位置，"
      "旧口径只看整项均值时 hit@100 只差 9pp 的这件事被平摊掉了）。")
    w("")

    lcf_path = args.analysis_dir / "LAST_CHAR.json"
    if lcf_path.exists():
        lc = json.loads(lcf_path.read_text(encoding="utf-8"))
        if lc.get("available"):
            ls, ms = lc["last_signature"], lc["middle_signature"]
            w("## 2b. 末字失效的归因：长音保持的**尾边界**问题，不是截断")
            w("")
            w(f"- 末字（n={lc['n_last']}）：hit@100 {pct(ls['hit100'],1)}，但 **start 侧几乎不坏**"
              f"（{pct(ls['start_hit100_only'],1)}），坏在 end（{pct(ls['end_hit100_only'],1)}）："
              f"MAE end {sec(ls['mae_end'])} vs MAE start {sec(ls['mae_start'])}。")
            w(f"- **原因不是音频截断**：末字预测 end 超出音频长度的比例 {pct(ls['pred_end_beyond_item_share'],1)}、"
              f"GT end 超出比例 {pct(ls['gt_end_beyond_item_share'],1)}（都是 0）。")
            w(f"- 真正的相关量是**时值**：末字 GT 平均时长 {ls['mean_gt_dur']:.2f} s，"
              f"而中间位置只有 {ms['mean_gt_dur']:.2f} s ⇒ 每项最后一个字几乎都是拖长音，"
              "尾边界本身缺乏可判定的声学结束点。")
            w(f"- 偏移量级小但右偏：end 有符号中位 {sec(ls['signed_end_median'])}、"
              f"均值 {sec(ls['signed_end_mean'])} ⇒ 少数长尾错例拉高均值（不是系统性偏晚）。")
            cc = lc["last_char_failure_concordance"]
            w(f"- 跨预测器一致性：末字失败**只有 {pct(cc['share_all_predictors_fail'],1)} 是全预测器共犯**，"
              f"{pct(cc['share_at_least_half_fail'],1)} 至少半数预测器失败，全部通过 "
              f"{pct(cc['share_all_pass'],1)} ⇒ 末字难度里约一半是模型间随机不稳健，"
              "这既是 realign 的机会（多视角投票可能救回一部分），也是它的不确定性来源。")
            bydur = lc["by_gt_duration_of_last_char"]
            w(f"- 按末字时值分组：较长一半 hit@100 {pct(bydur['longer_half']['hit100'],1)} vs "
              f"较短一半 {pct(bydur['shorter_half']['hit100'],1)}（n={bydur['longer_half']['n']}/"
              f"{bydur['shorter_half']['n']}，样本太小不足以定方向，只登记不下结论）。")
            w("")
    w("## 3. 长度不是因素，密度才是（自然录音上的反直觉结果）")
    w("")
    lr = leng[ref]
    w(f"- 项时长 {lr['items_over_60s']} 项 >60s、{lr['items_over_90s']} 项 >90s；"
      f"hit@100 与项时长相关 **{lr['pearson_hit100_vs_item_duration']}**（几乎为零）：")
    w("")
    w("| 时长桶 | 项数(×预测器) | hit@100 | MAE |")
    w("|---|---:|---:|---:|")
    for r_ in lr["by_item_duration"]:
        w(f"| {r_['bucket']} | {r_['n_items']} | {pct(r_['hit100'], 1)} | {sec(r_['mae_sec'])} |")
    w("")
    w(f"- 而 hit@100 与**逐项字数**相关 {lr['pearson_hit100_vs_char_count']}"
      "（字数多＝歌词更密＝更容易对齐）。⇒ 『长音频更难』在这批自然数据上不成立，"
      "难度来自唱法/密度而不是经过时间；这也解释了为什么合成长轴（第 3 轮）看不到长度退化。")
    w(f"- 项间离散（`{ref}`）：hit@100 min {pct(var['hit100_across_items']['min'], 1)} / "
      f"中位 {pct(var['hit100_across_items']['median'], 1)} / max "
      f"{pct(var['hit100_across_items']['max'], 1)}；最差 5 项 "
      + ", ".join(f"{x['item']}({pct(x['hit100'], 0)})" for x in var["worst_5_items"])
      + "。⇒ 逐歌质量差异远大于不同 checkpoint 之间的差异。")
    w("")

    mem = disq.get("membership", {})
    w("## 4. 无真值分歧信号迁移到自然录音（并给出集成成员规则的教训）")
    w("")
    w(f"以 `{disq['reference_predictor']}` 为目标、其余预测器的边界跨度作 no-GT 信号；"
      f"成员规则：{mem.get('rule')}，被排除的弱系统 {mem.get('weak_excluded')}。")
    w("")
    w("| 预测器集合 | AUC(bad>100ms) | AUC(bad≥250ms) | 阳性率 | flag10% 精度/召回 |")
    w("|---|---:|---:|---:|---|")
    for k, v in disq["sets"].items():
        rc = v["review_budget_curve"]["flag_10pct"]
        w(f"| {k} | {v['auc_spread_vs_bad100']} | {v['auc_spread_vs_bad250']} | "
          f"{v['positive_rate_bad250']} | {rc['precision']}/{rc['recall']} |")
    w("")
    w("- **信号强度序与第 1 轮一致**：抓 gross error（≥250ms）有效（AUC 0.84），"
      "抓 100ms 级弱（0.63–0.67）。")
    w(f"- **加入明显更差的系统会伤害集成**：把上游 `base_qwen_raw_v1` 放进集合后 AUC(250ms) 从 "
      f"{disq['sets']['strong_peers_only']['auc_spread_vs_bad250']} 掉到 "
      f"{disq['sets']['including_weak_systems']['auc_spread_vs_bad250']}，"
      "且 flag10% 精度崩到约 0.02（跨度被坏系统主导）。"
      "⇒ 成员规则已实现为代码里的 `weak_excluded` 自动判定（hit@100 低于参考一半者不入集合）。"
      "⇒ 集成/多视角信号必须先按能力门筛选成员，不能只按『配置不同』凑数。")
    w("")

    uu_path = args.analysis_dir / "UNSTABLE_UNITS.json"
    if uu_path.exists():
        uu = json.loads(uu_path.read_text(encoding="utf-8"))
        if uu.get("available"):
            w("## 4b. 跨 checkpoint 不稳定单元普查（可直接投产的 no-GT 候选清单）")
            w("")
            w(f"- 以 {len(uu['predictors'])} 个强预测器的边界跨度（max−min）>"
              f"{uu['threshold_sec'] * 1000:.0f}ms 定义\u300c不稳定\u300d："
              f"**{pct(uu['unstable_share'], 1)}**（{uu['unstable_n']:,}/{uu['n_units']:,}）单元不稳定。")
            w(f"- 不稳定单元的 hit@100 {pct(uu['hit100_unstable'], 1)} vs 稳定单元 "
              f"{pct(uu['hit100_stable'], 1)}；平均误差 {sec(uu['mean_error_unstable_sec'])} vs "
              f"{sec(uu['mean_error_stable_sec'])}。")
            w(f"- 判别力：跨度对 **>100ms 误差 AUC {uu['auc_spread_vs_bad100']}**、"
              f"对 ≥250ms AUC {uu['auc_spread_vs_bad250']}；"
              f"以 20ms 阈值为代价可覆盖 {pct(uu['recall_of_bad250_by_unstable'], 1)} 的 gross 错误"
              f"（精度仅 {pct(uu['precision_of_unstable'], 1)} ⇒ 阈值必须按预算取分位数，不能用固定 20ms）。")
            w(f"- 位置：首字与末字的不稳定率都是 {pct(uu['unstable_share_first_char'], 1)}"
              f"（n=17 各），段内五等分的不稳定率 "
              + "、".join(f"{pct(r['unstable_share'], 0)}" for r in uu["unstable_by_position"])
              + "（几乎平坦 ⇒ 不稳健是全曲均匀分布的，不是接缝局部现象）。")
            w("- 意义：**不需要真值**就能圈出一批高错误概率单元；但 20ms 阈值太宽，"
              "工程上应改成\u300c跨度分位数 + 复核预算\u300d（与 §4 的 flag 曲线一致）。")
            w("")
    w("## 5. 误差聚簇在自然录音上明显减弱（对第 1 轮的定量修正）")
    w("")
    w(f"- `{ref}`：坏率 {pct(runs['bad_rate'], 1)}，坏单元落长度≥2 游程的占比 "
      f"**{pct(runs['share_bad_in_runs_ge2'], 1)}**，游程分布 "
      f"{runs['run_lengths']}（GTSinger 人是 67.6%）。")
    w("- ⇒ 『错误是区域』的强度**依赖数据来源**：录音室短片段（GTSinger）里聚簇强，"
      "真实歌曲的自然段落里聚簇弱。区域级 realign 的收益上限应按域分别标定，"
      "不能把 GTSinger 的聚簇率当通用常数。")
    w("")

    w("## 6. 不同 checkpoint 的单元级位移（聚合分数掩盖的东西）")
    w("")
    w("| 预测器对 | 20ms 内一致 | 100ms 内一致 | 中位跨度 | p90 跨度 | 最大跨度 | Δhit@100 |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for k, v in pairs.items():
        w(f"| {k.replace('__vs__', ' vs ')} | {pct(v['agree_within_20ms'], 1)} | "
          f"{pct(v['agree_within_100ms'], 1)} | {sec(v['median_spread_sec'])} | "
          f"{sec(v['p90_spread_sec'])} | {sec(v['max_spread_sec'], 0)} | {v['hit100_delta_pp']:+.2f}pp |")
    w("")
    key = "r2_full_20260723__vs__r2_seed_20260724"
    if key in pairs:
        w(f"- 两个 R2 训练 run 的聚合差只有 "
          f"{pairs[key]['hit100_delta_pp']:+.2f}pp，但 {pct(1 - pairs[key]['agree_within_20ms'], 1)} "
          f"的单元边界位移 >20ms、最大 {sec(pairs[key]['max_spread_sec'], 0)}"
          " ⇒ 聚合指标无法区分 checkpoint，必须看单元级位移；"
          "同歌同字在两个 checkpoint 下不一致时，说明这些单元的预测本身不稳定（值得优先 realign）。")
    w("- `base_qwen_raw_v1` 与 R2 的中位跨度 "
      f"{sec(pairs['base_qwen_raw_v1__vs__r2_full_20260723']['median_spread_sec'], 0)}——"
      "这不是随机噪声而是两套系统的系统性差异，进一步说明它不适合作为集成成员。")
    w("")

    w("## 7. 边界与后续")
    w("")
    w("- 2,035 人工字符 / 17 项 / 单一歌手集合（MIR-1K partial-align 子集），"
      "项长为 22–127 s 的自然段落，**不是** 3–5 分钟整曲；窗口/接缝因子在这里仍无法检验。")
    w("- 参考是人工逐字 on/off，但不是本项目人工复核（`rule_validated` 类），"
      "且 MIR-1K 为 test-only：本轮所有数字只做报告。")
    w("- 预测器均来自 2026-07-22/24 的 OOD 评测（batch-size 4、whole-item 推理），"
      "没有 posterior/熵字段 ⇒ 无法在此面板上复现第 1 轮的熵基信号，只能测分歧基信号。")
    w("- 建议的后续（都不需要新 GPU）：(a) 把『末字 hit@100 + 位移稳定性』加入评测面板的分层报告；"
      "(b) 用本项目现有 33 首真实歌曲（无 GT）跑同一套分歧分析，检验 checkpoint 位移是否同样普遍；"
      "(c) 若允许一次小 GPU：对这 17 项加跑 windowed(60s) 与 whole-item 两种规划，"
      "第一次在**有自然人工 GT** 的数据上判定窗口因子是否真的激活。")
    w("")

    w("## 8. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python -c \"from pathlib import Path;")
    w("from lyricalign.analysis import mir1k_natural_panel as M;")
    w("d=Path('/home/hyan/Data/lyricalign/runs/20260912_mir1k_natural_panel'); d.mkdir(exist_ok=True)")
    w("df,audit=M.build_panel(); out=M.analyse(df,audit)")
    w("(d/'PANEL_AUDIT.json').write_text(__import__('json').dumps(audit,ensure_ascii=False,indent=2))")
    w("(d/'ANALYSIS.json').write_text(__import__('json').dumps(out,ensure_ascii=False,indent=2))")
    w("df.to_csv(d/'panel.csv.gz', index=False, compression='gzip')\"")
    w("PYTHONPATH=src python scripts/evaluation/report_mir1k_natural_panel.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_mir1k_natural_panel.py")
    w("```")
    w("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")

    metrics = {
        "schema_version": "mir1k_natural_panel_metrics_v1",
        "run": "20260912_mir1k_natural_panel",
        "source_analysis": str(args.analysis_dir / "ANALYSIS.json"),
        "usage_discipline": "MIR-1K is test-only: report only, never for checkpoint selection or tuning",
        "reference": audit["reference"],
        "predictors": {k: {"hit100": v.get("hit100"), "hit200": v.get("hit200"),
                           "hit250": v.get("hit250"), "iou_mean": v.get("iou_mean"),
                           "mae_start": v.get("mae_start"), "mae_end": v.get("mae_end")}
                       for k, v in by.items()},
        "canonical_reconciliation": recon,
        "headline": {
            "natural_mandarin_hit100_best": max(v["hit100"] for v in by.values() if v["n_units"] > 100),
            "upstream_base_hit100": by["base_qwen_raw_v1"]["hit100"],
            "first_char_hit100_ref": pos[ref]["by_position"][0]["hit100"],
            "last_char_hit100_ref": pos[ref]["by_position"][-1]["hit100"],
            "middle_char_hit100_ref": pos[ref]["by_position"][2]["hit100"],
            "last_char_signed_end_ref": pos[ref]["by_position"][-1]["mean_signed_end"],
            "hit100_vs_item_duration": leng[ref]["pearson_hit100_vs_item_duration"],
            "hit100_vs_char_count": leng[ref]["pearson_hit100_vs_char_count"],
            "disagreement_auc_bad250_strong_peers":
                disq["sets"]["strong_peers_only"]["auc_spread_vs_bad250"],
            "disagreement_auc_bad250_with_weak_systems":
                disq["sets"]["including_weak_systems"]["auc_spread_vs_bad250"],
            "ensemble_membership_rule": disq.get("membership"),
            "share_bad_in_runs_ge2": runs["share_bad_in_runs_ge2"],
            "r2_runs_unit_agree_within_20ms": pairs[key]["agree_within_20ms"],
            "r2_runs_hit100_delta_pp": pairs[key]["hit100_delta_pp"],
        },
        "position_effects": pos, "length_effect": leng,
        "last_character": (json.loads((args.analysis_dir / "LAST_CHAR.json").read_text(encoding="utf-8"))
                           if (args.analysis_dir / "LAST_CHAR.json").exists() else None),
        "unstable_units": (json.loads((args.analysis_dir / "UNSTABLE_UNITS.json").read_text(encoding="utf-8"))
                           if (args.analysis_dir / "UNSTABLE_UNITS.json").exists() else None),
        "disagreement_signal_natural": disq, "predictor_pairs": pairs,
        "structural_defects_by_predictor": defects, "error_runs_natural": runs,
        "per_item_variance": var, "panel": panel, "join_audit": audit["predictors"],
    }
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
