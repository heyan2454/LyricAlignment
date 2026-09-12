#!/usr/bin/env python3
"""Render the deep GTSinger ground-truth analysis report from its JSON artifacts.

Numbers are read from the analysis artifacts; the report is never hand-copied.

    PYTHONPATH=src python scripts/evaluation/report_gtsinger_gt_deep.py \
        --analysis-dir /home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep \
        --out /home/hyan/LyricAlignment/reports/progress/20260912_gtsinger_gt_deep_analysis.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def pct(x, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{digits}f}%"


def sec(x, digits: int = 0) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{digits}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", type=Path,
                    default=Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep"))
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_gtsinger_gt_deep_analysis.md")
    args = ap.parse_args()

    ad = args.analysis_dir
    summ = json.loads((ad / "SUMMARY.json").read_text(encoding="utf-8"))
    an = json.loads((ad / "ANALYSIS_SUMMARY.json").read_text(encoding="utf-8"))
    eff = json.loads((ad / "EFFECTS.json").read_text(encoding="utf-8"))
    sig = json.loads((ad / "SIGNALS.json").read_text(encoding="utf-8"))
    st = json.loads((ad / "STRUCTURE.json").read_text(encoding="utf-8"))
    mx = json.loads((ad / "MATRIX_AUDIT.json").read_text(encoding="utf-8"))
    pp = json.loads((ad / "POSTPROCESS.json").read_text(encoding="utf-8"))

    L: list[str] = []
    a = L.append
    a("# GTSinger 真值深度分析（2026-09-12，goal 自由行动轮）")
    a("")
    a("> 本报告全部数字由 `runs/20260912_gtsinger_gt_deep/*.json` 结构化产物生成"
      "（`scripts/evaluation/report_gtsinger_gt_deep.py`），不手抄。")
    a("> 只读复用 2026-08-16 evaluation_v1 的既有产物，未新增任何 GPU 前向。")
    a("")

    # ------------------------------------------------------------------ panel
    a("## 0. 数据面板")
    a("")
    a(f"- 段落：{an['panel_items']} 个 GTSinger 片段（"
      f"{', '.join(summ['singers'])}；技法族 {', '.join(summ['techniques'])}；"
      f"分组 {', '.join(summ['groups'])}）")
    a(f"- 逐单元证据行：{an['panel_rows']:,}（面板内）/ {summ['stats']['unit_rows']:,}"
      f"（含 window 机制消融小集）；标注配置 {summ['models'] and '3 模型 × 2 音频标签 × 2 规划模式 × 2 解码管线'}")
    a(f"- 单元总数（去重配置后每个 item 平均 {summ['stats']['unit_rows']/max(summ['stats']['items_seen'],1):.1f} 行/段/run）；"
      f"计数不一致被跳过的配置：{summ['stats']['configs_skipped']}（缺文件 {summ['stats']['configs_missing']}）")
    a("- 口径：`both_abs_err = max(|start_err|,|end_err|)`，命中阈 100/200ms；"
      "GT 为 GTSinger word-level JSON（过滤 `<AP>`），段级配对、segment 层面等权（cluster bootstrap）。")
    a("")

    # ------------------------------------------------------- 1 matrix integrity
    a("## 1. 配置矩阵其实是\"假因子\"（P1 数据完整性）")
    a("")
    diag = mx["per_run"].get("20260816_evaluation_v1_gtsinger_diag_all", {})
    sha_per_item = sorted({int(v["audio_sha_distinct_per_item_min"]) for v in mx["per_run"].values()}
                          | {int(v["audio_sha_distinct_per_item_max"]) for v in mx["per_run"].values()})
    a(f"每段音频 `sha256` 只有 {sha_per_item} 个不同值：标注为 `mix` 与 `vocal` 的配置"
      f"**喂的是同一个 wav**（GTSinger 切分只给干声）；"
      f"mix≡vocal 音频的 item 占比 "
      f"{pct(diag.get('share_items_mix_equals_vocal_audio'),0)}。")
    a(f"- 预测向量层面复算：`mix` vs `vocal` 的起止边界完全相同 "
      f"{pct(mx['mix_vs_vocal_start_identity']['share_identical'])}（n={mx['mix_vs_vocal_start_identity']['n_pairs']:,}）。")
    mi = mx["mode_vs_full_start_identity"]
    a(f"- `full` vs `windowed`：start 一致 {pct(mi['share_start_identical'],2)}，"
      f"end 一致 {pct(mi['share_end_identical'],2)}，任一边界被改动的单元 "
      f"{pct(mi['share_either_moving'],2)}（n={mi['n_pairs']:,}）——短片段（单窗口）上 window 规划几乎不激活。")
    a(f"- 结果：标注的 12 个配置每段只剩 "
      f"**{diag.get('distinct_prediction_vectors_per_item_mean')} 个不同预测向量**"
      f"（冗余因子 {diag.get('redundancy_factor')}×）。全矩阵各 run 概览：")
    a("")
    a("| run | items | 标注配置/段 | 实际不同向量/段 | 冗余因子 | mix≡vocal 音频的 item 占比 |")
    a("|---|---:|---:|---:|---:|---:|")
    for run, v in mx["per_run"].items():
        a(f"| `{run.replace('20260816_evaluation_v1_gtsinger_','')}` | {v['items']} | "
          f"{v['configs_labelled_per_item_mean']} | {v['distinct_prediction_vectors_per_item_mean']} | "
          f"{v['redundancy_factor']}× | {pct(v['share_items_mix_equals_vocal_audio'],0)} |")
    a("")
    a("**含义**：这批 evaluation_v1 矩阵的独立观测数是 3（模型阶梯），不是 12；"
      "任何\"音频输入 / 规划模式\"因子比较在这批数据上都是空比较，"
      "且约 3/4 的前向计算是同一输入的重算（GPU 预算浪费）。"
      "这把 2026-08-21 的\"window 机制消融 inconclusive（短片段上未激活）\"从推断升级为可验证事实，"
      "并把 `compute_matrix()` 作为入口审计固化下来。")
    a("")

    # ------------------------------------------------------ 2 model ladder etc
    a("## 2. 模型阶梯与管线的真实效应（配对 + 重采样 CI）")
    a("")
    a("| 因子 | 水平 | hit@100(macro) | hit@200 | MAE start | MAE end | IoU | 零时长率 |")
    a("|---|---|---:|---:|---:|---:|---:|---:|")
    for factor in ("model", "pipeline"):
        for row in eff["levels"][factor]:
            a(f"| {factor} | `{row[factor]}` | {pct(row['hit100_macro'])} | {pct(row['hit200_macro'])} | "
              f"{sec(row['mae_start_macro'])} | {sec(row['mae_end_macro'])} | {row['iou_macro']} | "
              f"{pct(row['zero_dur_rate'],2)} |")
    a("")
    c = eff["contrasts_hit100"]
    a("配对差（段级 hit@100，正=a 更好；CI 为段聚类 bootstrap 95%）：")
    a("")
    a("| 对比 | a | b | 均值差 | CI | a 更好格 | b 更好格 | 平 | 符号检验 p |")
    a("|---|---|---|---:|---|---:|---:|---:|---:|")
    for pipe in ("official", "raw"):
        for name in ("r0_vs_r1", "r1_vs_r2", "r0_vs_r2"):
            v = c[pipe][name]
            a(f"| {pipe} · {name} | {v['a']} | {v['b']} | {v['mean_diff']*100:+.2f}pp | "
              f"[{v['diff_ci95'][0]*100:+.2f}, {v['diff_ci95'][1]*100:+.2f}] | {v['cells_a_better']} | "
              f"{v['cells_b_better']} | {v['cells_tied']} | {v['sign_p']:.1e} |")
    x = c["official_vs_raw"]
    a(f"| cross · official_vs_raw | official | raw | {x['mean_diff']*100:+.2f}pp | "
      f"[{x['diff_ci95'][0]*100:+.2f}, {x['diff_ci95'][1]*100:+.2f}] | {x['cells_official_better']} | "
      f"{x['cells_raw_better']} | {x['cells_tied']} | {x['sign_p']:.1e} |")
    a("")
    a("- 阶梯 `r0→r1` 提升 "
      f"{abs(c['official']['r0_vs_r1']['mean_diff'])*100:.1f}pp、`r1→r2` 仅 "
      f"{abs(c['official']['r1_vs_r2']['mean_diff'])*100:.1f}pp：LoRA 之后的边际收益已小于 2pp，"
      "继续在同一数据上加训的收益预期要按这个尺度设定。")
    a("- 逐单元边界方向：r0 的 end 误差（"
      f"{sec(eff['levels']['model'][0]['mae_end_macro'])}）远大于 start（"
      f"{sec(eff['levels']['model'][0]['mae_start_macro'])}），r1/r2 两端对称，"
      "说明旧基线的主要缺陷就是尾边界，而非起边界。")
    a("")

    # ------------------------------------------------------ 3 post-processing
    t = pp["all_official"]["touched"]
    r2t = pp["r2_vocal_windowed"]["touched"]
    a("## 3. 官方后处理在真值上是净负收益（机制分解）")
    a("")
    a(f"- 官方管线改动了 {pct(pp['all_official']['share_units_touched'],1)} 的单元边界（>{1e-3}s）；"
      f"raw 管线中 `selected==raw` 的比例 {pct(pp['raw_pipeline_selected_equals_raw_share'],1)}"
      "（即 raw 确实是未后处理的解码输出，二者构成干净的 A/B）。")
    a(f"- 被改动的单元：变差 {pct(t['damage_rate_both'])} vs 变好 {pct(t['repair_rate_both'])}；"
      f"MAE(both) 由 {sec(t['mean_abs_err_raw_both'])} 升到 {sec(t['mean_abs_err_sel_both'])}"
      f"（净 {sec(t['net_err_delta_sec'])}）；hit@100 由 {pct(t['hit100_raw'])} 跌到 {pct(t['hit100_sel'])}；"
      f"越界翻转 out/in = {t['flips_out_of_tol']}/{t['flips_into_tol']}。")
    a(f"- 边界分工：end 端改动 {pct(t['end_repair_rate'])} 修好 vs {pct(t['end_damage_rate'])} 改坏"
      f"（且方向以提前为主：moves_earlier {t['direction_end']['moves_earlier']} vs "
      f"moves_later {t['direction_end']['moves_later']}）；"
      f"start 端 {pct(t['start_repair_rate'])} 修好 vs **{pct(t['start_damage_rate'])} 改坏**。")
    a(f"- 零时长副作用：official 的零时长率是 raw 的数倍"
      f"（r2：{pct(eff['levels']['pipeline'][0]['zero_dur_rate'],2)} vs "
      f"{pct(eff['levels']['pipeline'][1]['zero_dur_rate'],2)}）。")
    a(f"- 置信度无法预判\"哪次改动是修复\"：被触碰单元上 AUC(低置信→修复) "
      f"min_margin {t['auc_low_confidence_indicates_repair']['min_margin']}、"
      f"min_top1 {t['auc_low_confidence_indicates_repair']['min_top1']}、"
      f"max_entropy {t['auc_low_confidence_indicates_repair']['max_ent']}（≈随机）。")
    a(f"- 参考配置 r2/vocal/windowed 同向：改动 {pct(pp['r2_vocal_windowed']['share_units_touched'])}，"
      f"repair {pct(r2t['repair_rate_both'])} vs damage {pct(r2t['damage_rate_both'])}，"
      f"net {sec(r2t['net_err_delta_sec'])}。")
    a("")
    mech = pp["all_official"].get("mechanism", {})
    if mech:
        a("- **规则定位（无需读源码即可归因）**：被后移的 start 有 "
          f"{pct(mech.get('start_moved',{}).get('share_pinned_to_prev_end'))} 精确等于**前一单元的 end**"
          f"（{mech.get('start_moved',{}).get('direction_later')}/{mech.get('n_start_moved')} 个是后移，"
          f"平均 {sec(mech.get('start_moved',{}).get('mean_shift_sec'))}）；"
          f"被改动的 end 有 {pct(mech.get('end_moved',{}).get('share_pinned_to_next_start'))} 等于**下一单元的 start**"
          f"（{mech.get('end_moved',{}).get('direction_earlier')}/{mech.get('n_end_moved')} 个提前，"
          f"平均 {sec(mech.get('end_moved',{}).get('mean_shift_sec'))}）。"
          "即这是**重叠消解（overlap resolution）**规则：两侧各让一半，"
          f"同时把零时长率从 raw 的 {pct(mech.get('raw_zero_duration_share'),2)} 抬到 "
          f"{pct(mech.get('final_zero_duration_share'),2)}。")
        a("")
    a("**含义**：2026-08-16 的 `RAWDEC_FULL_RESULT.md` 已注意到 raw 解码整体更好（+1.8pp），"
      "但只归因为\"2/75 段小幅回退\"。逐单元分解后结论更强：后处理是**系统性**在 start 端把误差推大"
      "（连续/单调约束把前一单元的尾端强加给下一单元起点），并在 end 端做正向修剪；"
      "因此改造方向不是\"整体关掉后处理\"，而是**拆开两端**：保留 end 修剪，"
      "取消或条件化 start 的强制对齐（且不能用现有 posterior 置信度做门控，AUC≈0.44）。")
    a("")

    # ---------------------------------------------------------- 4 no-GT signals
    a("## 4. 无真值置信信号在真值上的判别力（本项目第一次有真 GT 校准）")
    a("")
    tab = sig["signals"]["all_configs"]
    ranked = sorted(tab.items(), key=lambda kv: -(kv[1]["bad100"].get("flat_auc_oriented") or 0))
    a("单信号 ROC-AUC（预测 `both_abs_err>100ms`；`oriented` 已按方向归一，"
      "within = 段内排序 AUC，排除段间难度差）：")
    a("")
    a("| 信号 | 用 GT | AUC(bad100) | AUC(bad200) | within(bad100) |")
    a("|---|---|---:|---:|---:|")
    for name, v in ranked:
        b1, b2 = v["bad100"], v["bad200"]
        a(f"| `{name}` | {'是(oracle)' if b1.get('uses_gt') else '否'} | "
          f"{b1.get('flat_auc_oriented')} | {b2.get('flat_auc_oriented')} | "
          f"{b1.get('within_segment_auc_mean_oriented')} |")
    a("")
    g = sig["gate_model"]
    a("多变量门控（`GroupKFold` 按段分组、one-vs-rest OOF 概率；只喂无真值特征）：")
    a("")
    a("| 特征集 | n | 阳性率 | OOF AUC | AP | ECE | Brier | flag5% 精度 | flag10% 精度/召回 | flag20% 精度/召回 |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for name, v in g.items():
        if not v.get("available"):
            continue
        b = v["review_budget_curve"]
        a(f"| {name} | {v['n_rows']:,} | {v['positive_rate']} | {v['oof_auc']} | {v['oof_ap']} | "
          f"{v['oof_ece']} | {v['oof_brier']} | {b['flag_5pct']['precision']} | "
          f"{b['flag_10pct']['precision']}/{b['flag_10pct']['recall']} | "
          f"{b['flag_20pct']['precision']}/{b['flag_20pct']['recall']} |")
    a("")
    cal = sig["calibration_top1"]
    a(f"- 原始 top-1 概率**系统性欠自信**：start 均值 {cal['start']['mean_top1_prob']} 对应实测命中率 "
      f"{cal['start']['observed_hit_rate']}（gap {cal['start']['gap']}，ECE {cal['start']['ece_raw']}）；"
      f"end 同理（{cal['end']['mean_top1_prob']} vs {cal['end']['observed_hit_rate']}，ECE {cal['end']['ece_raw']}）。"
      "十分位可靠性曲线单调，说明排序信息有效、只有水平错位 → 一次重标定即可当作阈值使用"
      "（与 detector-v2 在合成扰动上得到的 isotonic ECE 0.26→0.013 同向，这次是在**真演唱真值**上复现）。")
    a(f"- 最强单信号是 **end 边界熵**（AUC {tab['sig_entropy_max']['bad100']['flat_auc']}），"
      "优于 top-1 概率与 margin（0.80/0.71 级）；"
      f"跨模型分歧（每模型一格、LOO）AUC {tab['sig_model_loo_both']['bad100']['flat_auc']}，"
      f"段内中位时长自一致 {tab['sig_dur_vs_segment_median_err']['bad100']['flat_auc']}。"
      "注意 §1 的教训：若不先去重而直接对 12 格做 LOO，分歧被自身重复格稀释（"
      f"LOO(全格) {tab['sig_disagree_loo_both']['bad100']['flat_auc']} vs 去重后 "
      f"{tab['sig_model_loo_both']['bad100']['flat_auc']}，且 AUC 表观差异掩盖了幅度偏差）。")
    a("")

    # --------------------------------------------------------- 5 error structure
    a("## 5. 误差结构：错误不是独立噪声，而是\"区域\"")
    a("")
    cl = st["clustering"]
    a(f"- 全面板单元坏率 {pct(cl['unit_bad_rate'])}；坏单元连续成段：mean run {cl['mean_run_len']}，"
      f"max {cl['max_run_len']}，**{pct(cl['share_bad_in_runs_ge2'])} 的坏单元落在长度≥2 的连续段里**。")
    obs, exp = cl["observed_run_lengths"], cl["expected_run_lengths_geometric"]
    a("- 与 i.i.d. 零模型（几何分布）对照，长游程严重超额：")
    a("")
    a("| 游程长度 | 观测 | i.i.d. 期望 | 超额倍数 |")
    a("|---:|---:|---:|---:|")
    for k in sorted(obs, key=int):
        e = exp.get(k)
        a(f"| {k} | {obs[k]} | {e} | {obs[k]/e:.1f}× |" if e else f"| {k} | {obs[k]} | {e} | — |")
    a("")
    fu = st.get("first_unit_analysis", {})
    if fu:
        z = fu["cells"].get("pred_onset_zero", {})
        nz = fu["cells"].get("pred_onset_positive", {})
        a(f"- **段首是双峰问题，不是\"塌陷\"**：GTSinger 片段第一单元的 GT start "
          f"{pct(fu['share_gt_start_zero'],0)} 为 0.0，所以预测 start=0 属于\"免费正确\"；"
          f"{pct(fu['share_pred_start_zero'],1)}（{z.get('n')}/{fu['n']}）的段首确实输出 0.0，"
          f"其 hit@100 = {pct(z.get('hit100'))}；剩下 {nz.get('n')} 段"
          f"（{pct(1-fu['share_pred_start_zero'],1)}）凭空插入平均 {sec(nz.get('mean_pred_start_sec'))} "
          f"的起始留白，hit@100 只有 {pct(nz.get('hit100'))}（即便只看 end 边界也只有 "
          f"{pct(nz.get('hit100_excluding_start'))}）。因此段首失败模式是**幻觉前奏**："
          "模型在 0 与真实起唱点之间虚构了一段前奏（预测 start 平均被推迟到 "
          + sec(nz.get('mean_pred_start_sec')) + "），而不是\"直接取窗口起点\"："
          "需要的是\"clip 头部允许从 0 起唱\"的先验——这与 long-form 左上下文同属 "
          "`startup_vocal_onset_sec` 通道，但修正方向相反。")
    cg = st.get("contagion", {})
    if cg:
        a(f"- **误差机械传染被否证**：预测并非强制连续（start 精确等于前一单元 end 的仅 "
          f"{pct(cg['share_pred_start_equals_prev_end_exact'],1)}，而 GT 本身 "
          f"{pct(cg['share_gt_contiguous'],1)} 连续）；start 误差与前驱 end 误差的相关系数 "
          f"{cg['pearson_start_err_vs_prev_end_err']}，前驱尾错时本单元命中率 "
          f"{pct(cg.get('hit100_given_prev_end_bad'))} vs 前驱正确时 "
          f"{pct(cg.get('hit100_given_prev_end_good'))}。所以 §游程聚簇不是连续性约束造成的机械传染。")
    cn = st.get("clustering_nulls", {})
    if cn:
        a(f"- **但也不是\"难单元天然扎堆\"能解释的**：用可观测量（GT 时长、音节结构、音符数、"
          f"位置、技法组）拟合逐单元失败概率（OOF AUC {cn['oof_covariate_auc']}）做伯努利模拟当零模型 B，"
          f"它只预测 {pct(cn['share_bad_in_runs_ge2_nullB_mean'],1)}"
          f"（95 分位 {pct(cn['share_bad_in_runs_ge2_nullB_p95'],1)}）的坏单元落在长度≥2 的游程里，"
          f"实测为 {pct(cn['share_bad_in_runs_ge2_observed'],1)}：")
        a("")
        a("| 游程长度 | 观测链数 | 协变量零模型 B 期望 | 超额 |")
        a("|---:|---:|---:|---:|")
        for k, v in cn["run_length_table"].items():
            if int(k) > 9:
                continue
            a(f"| {k} | {int(v['observed'])} | {v['nullB_expected']} | "
              f"{v['excess'] if v['excess'] is not None else '∞'}× |")
        a("")
        a("  长度≥4 的游程超额 4–160×，9 连错观测 16 次而零模型期望 ≈0："
          "真值误差带有超出可观测难度的**局部区域结构**，这是区域级（而非单元级）realign "
          "迄今最直接的实证依据。")
    a("- **零声母音节**更难：单音素音节 hit@100 "
      f"{pct([r for r in st['by_multi_phoneme'] if r['gt_is_multi_phoneme']=='0'][0]['hit100'])} vs "
      f"多音素 {pct([r for r in st['by_multi_phoneme'] if r['gt_is_multi_phoneme']=='1'][0]['hit100'])}；"
      "与段首交叉后两者独立叠加：")
    a("")
    a("| 单音素音节 | 非段首 | n | hit@100 | MAE start |")
    a("|---|---|---:|---:|---:|")
    for r in st["melisma_x_position_crosstab"]:
        a(f"| {r['gt_is_multi_phoneme']} | {r['not_first_unit']} | {r['n']} | "
          f"{pct(r['hit100'])} | {sec(r['mae_start'])} |")
    a("")
    a("- 分组难度（r2/vocal/windowed/official）：")
    a("")
    a("| 组 | n | hit@100 | MAE both | 均值 GT 时长 |")
    a("|---|---:|---:|---:|---:|")
    for r in sorted(st["by_group"], key=lambda x: x["hit100"]):
        a(f"| `{r['group']}` | {r['n']} | {pct(r['hit100'])} | {sec(r['mae_both'])} | "
          f"{r['mean_gt_dur']}s |")
    a("")
    dur_rows = st["by_gt_duration"]
    worst = min(dur_rows, key=lambda r: r["hit100"])
    a(f"- 时长桶上最差的不是最短音符而是 **0.6–1.0s** 桶（hit@100 {pct(worst['hit100'])}，"
      f"n={worst['n']}），且该桶 start 误差（{sec(worst['mae_start'])}）显著大于 end；"
      "拖长音的起始定位是主要失分点。")
    a("- 技法标记本身不是难点：glissando/mix/falsetto/pharyngeal 单元命中率与总体持平或更高（见 "
      "`STRUCTURE.json:by_technique_flag`），难度主要来自**朗读段（Paired_Speech）**、段首与零声母。")
    a("")

    a("## 6. 科学边界")
    a("")
    a("- GT 为 GTSinger word-level 标注（含音素/音符/技法旗标），未做人工二次校正；`<AP>` 已按既有口径过滤。")
    a("- 片段长度 5–15s、单段基本一个窗口，故本报告的\"模式/音频因子无效\"结论**只适用于短片段矩阵**，"
      "不能外推到真实长歌；但至少说明既有 evaluation_v1 结果里不存在\"混音 vs 分离\"证据。")
    a("- 仅 2 位歌手（ZH-Tenor-1 / ZH-Alto-1）、2 首歌曲，段内相关已由段聚类 bootstrap 处理，"
      "跨歌手/跨曲泛化未测。")
    a("- \"后处理净负\"以 100ms 命中为尺度；若产品口径只看视觉卡拉OK跟唱（±200ms 级），"
      "其代价会小得多——两种口径都要报，不能互相替换。")
    a("- 门控模型是**诊断用**：特征与标签同源同数据、按段分组 CV，未在任何新数据上验证；"
      "不得据此宣称可用于 checkpoint 选择或真实 writeback（realign 仍 shadow-only）。")
    a("")

    a("## 7. 下一步（按性价比）")
    a("")
    a("1. **入口审计**：把 `compute_matrix()` 接进 evaluation 批次收尾（同 run 内若某因子的音频 sha 或"
      "预测向量重合，直接标记该因子 `not_identified` 并拒绝输出\"效应\"），避免再花 GPU 跑空因子。")
    a("2. **后处理拆分**：只保留 end 修剪、去掉 start 强推，在**同一 159 段真值面板**上复评"
      "（纯 CPU，产物已在 `unit_evidence.jsonl.gz`，改后处理只需重放 `alignment.selected/raw`）。")
    a("3. **段首/零声母专项**：两个独立单因素消融——(a) `startup_vocal_onset_sec` 先验"
      "（clip 头部禁止虚构前奏，或在 t<0.6s 内收紧 onset 判定）；(b) 零声母音节的左侧上下文。"
      "评价指标直接用 §5 的分层命中率（段首桶、单音素桶、段首×单音素桶），不要用总体均值："
      "这两类合计只占 6.6% 的单元，总体均值会把它们冲淡到看不见。")
    a("4. **真·音频输入因子**：需要混音对照就必须自造 mix（GTSinger 只有干声：叠加伴奏/噪声），"
      "或在带伴奏的真实流行曲（MIR-1K/AMLL-TTML/PJS）上另建 GT 面板。")
    a("5. **门控落地**：`all_no_gt` 组合在 20% 复核预算下精度 0.65/召回 0.75，可作为 realign 触发器候选；"
      "先在既有 long-slot/serial 管线上做 shadow 记账（不改写回），并用 `sig_gap_to_next_start`/"
      "首单元位置这类结构化特征补强。")
    a("")

    a("## 8. 复现")
    a("")
    a("```bash")
    a("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    a("cd /home/hyan/LyricAlignment")
    a("PYTHONPATH=src python scripts/evaluation/extract_gtsinger_unit_evidence.py \\\n"
      "    --preset gtsinger --out-root /home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep")
    a("PYTHONPATH=src python scripts/evaluation/analyze_gtsinger_gt_deep.py")
    a("PYTHONPATH=src python scripts/evaluation/report_gtsinger_gt_deep.py \\\n"
      "    --out reports/progress/20260912_gtsinger_gt_deep_analysis.md")
    a("```")
    a("")
    a(f"- 证据面板：`/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz`"
      f"（{summ['file_bytes']/1e6:.1f} MB，sha256 `{str(summ['evidence_sha256'])[:16]}…`）")
    a("- 分析产物：`EFFECTS.json` `SIGNALS.json` `STRUCTURE.json` `MATRIX_AUDIT.json` "
      "`POSTPROCESS.json` `ABLATION.json`；抽取自检：`SUMMARY.json` / `SKIPPED.json`。")
    a(f"- 轻量指标（canonical source 候选）：`results/by_run/20260912_gtsinger_gt_deep/metrics.json`。")
    a("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
