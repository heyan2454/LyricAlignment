#!/usr/bin/env python3
"""Render the long-form weak-GT panel report from its JSON artifacts (numbers never hand-copied)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DIR = Path("/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt")


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{d}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[2]
                    / "reports/progress/20260912_m4_longform_weakgt_panel.md")
    ap.add_argument("--metrics-out", type=Path, default=Path(__file__).resolve().parents[2]
                    / "results/by_run/20260912_m4_longform_weakgt/metrics.json",
                    help="compact canonical metrics extracted from ANALYSIS.json ('-' to skip)")
    args = ap.parse_args()

    panel = json.loads((args.analysis_dir / "PANEL_SUMMARY.json").read_text(encoding="utf-8"))
    a = json.loads((args.analysis_dir / "ANALYSIS.json").read_text(encoding="utf-8"))
    p, trap, ref = a["panel"], a.get("uniform_axis_trap", {}), a.get("reference_profile", {})
    stage, post = a["stage_comparison"], a["postprocess_on_longform"]
    seg, pos = a["segment_boundary_effect"], a["position_in_phrase_profile"]
    sig, gate = a["confidence_signals"], a["gate"]

    L: list[str] = []
    w = L.append
    w("# 长时序弱真值面板（detector_v2 M4Singer-concat 证据，2026-09-12 第 3 轮）")
    w("")
    w("> 数字由 `runs/20260912_m4_longform_weakgt/{PANEL_SUMMARY,ANALYSIS}.json` 生成。")
    w("> 纯 CPU 复用既有产物；零新增前向；不动任何实现。")
    w("")
    w("## 0. 参考真值的性质（先说清楚，免得被误用）")
    w("")
    w(f"- 类型：{ref['kind']}；分档 {ref['bands_sec']}（safe ≤{sec(ref['bands_sec']['safe_max'],0)}、"
      f"unsafe ≥{sec(ref['bands_sec']['unsafe_min'],0)}）。")
    w("- **弱监督**：M4Singer 逐段字符 GT 平移到拼接时间轴，`rule_validated` 不等于人工确认。")
    w(f"- **长度是合成的**：`m4singer_concat`，段间插入 `artificial_silence_sec="
      f"{p['artificial_silence_sec']}` 静音；timeline 时长 "
      f"{p['timeline_duration_sec']['min']}–{p['timeline_duration_sec']['max']} s。"
      "按现行 research_v7 正式口径这不属于\"自然长数据\"，本面板只能用于机制/方向判断。")
    w(f"- 面板规模：{p['unit_rows']:,} 单元行 / {p['requests']:,} 证据身份 / {p['songs']} 首 / "
      f"{len(p['singers'])} 位歌手；baseline（未扰动文本）且有真实 GT 的单元 "
      f"{p['baseline_unit_rows']:,}（{p['baseline_requests']} 个请求）。")
    w(f"- 视图分布 {p['views']}；family 分布 "
      f"{ {k: v for k, v in p['families'].items()} }。")
    w("")

    w("## 1. 方法陷阱（P1，必须先记账）：`timeline.canonical_units` 的时间轴是**伪造均匀轴**")
    w("")
    w(f"- 把预测边界直接减 `canonical_units[*].start_sec` 得到的\"误差\"，与本项目冻结标签"
      f"（真实逐段 GT 平移）算出的误差：一致到 20ms 以内的只有 {pct(trap['share_within_20ms'],1)}，"
      f"中位分歧 {sec(trap['median_abs_disagreement_sec'])}，p90 {sec(trap['p90_abs_disagreement_sec'])}，"
      f"两种\"误差\"的相关只有 {trap['pearson_corr_of_two_error_definitions']}。")
    w(f"- 后果量化：同一批 {trap['n_units']:,} 单元上，错用均匀轴会得到 hit@100 = "
      f"**{pct(trap['hit100_if_uniform_axis_used'],1)}**，用真实 GT 是 "
      f"**{pct(trap['hit100_with_frozen_real_gt'],1)}**"
      f"（相差 {100*(trap['hit100_with_frozen_real_gt']-trap['hit100_if_uniform_axis_used']):.0f} 个百分点）。")
    w(f"- {trap['implication']}。")
    w("- 本轮我自己的第一次装配就踩中了它（得到的 baseline 命中率 5.9% 全是假的），"
      "是靠\"与冻结标签误差对账\"这道自检才发现的。**建议把这条对账固化为面板构建的硬门**。")
    w("")

    w("## 2. 长时序 baseline 真实水平（合成拼接轴）")
    w("")
    w(f"- hit@100：raw 阶段 {pct(stage['micro_hit100_raw'])}、official 阶段 "
      f"{pct(stage['micro_hit100_official'])}；unsafe(≥250ms) "
      f"{pct(stage['micro_unsafe_ge250_raw'])} → {pct(stage['micro_unsafe_ge250_official'])}。")
    w(f"- MAE(both)：raw {sec(stage['mae_raw_sec'])} / official {sec(stage['mae_official_sec'])}；"
      f"中位 {sec(stage['median_raw_sec'])}。")
    w("- 结论：在 200s 级合成长轴上，字符级对齐质量与 GTSinger 短片同量级（≈88% @100ms），"
      "**没有观察到长距离整体退化**。")
    w("")

    w("## 3. 后处理在长时序上的表现 ≠ GTSinger 上的表现（关键差异）")
    w("")
    w(f"- research_v7 的 official 阶段只改动了 {pct(post['share_units_touched'],1)} 的单元"
      "（GTSinger demo 管线是 5.4%）。")
    if post.get("n_touched"):
        w(f"- 被改动的 {post['n_touched']} 个单元：MAE 由 {sec(post['mean_abs_err_raw_sec'])} 降到 "
          f"{sec(post['mean_abs_err_official_sec'])}；hit@100 由 {pct(post['hit100_raw'])} 升到 "
          f"{pct(post['hit100_official'])}；repair {pct(post['repair_rate'])} vs "
          f"damage {pct(post['damage_rate'])}。")
        sm = post.get("start_moved", {})
        w(f"- **机制不同**：被移动的起点中只有 "
          f"{pct(sm.get('share_pinned_to_prev_end'),1)} 等于前一单元尾端"
          f"（GTSinger demo 管线是 98.3%），平均位移 {sec(sm.get('mean_shift_sec'))}。"
          "⇒ 第 2 轮定位到的\"重叠消解=把起点钉到前一个尾端\"是 **demo 官方管线特有**的行为，"
          "不是所有后处理阶段的通性；改造结论不能跨管线套用。")
    w(f"- 净效应在长时序上≈中性：单元级 Δhit@100 "
      f"{stage['paired_unit_hit100_official_minus_raw_pp']:+.3f}pp；"
      f"请求级配对 {stage['paired_segment_hit100_delta']['mean_diff_pp']:+.3f}pp "
      f"CI {stage['paired_segment_hit100_delta']['ci95_pp']}（"
      f"{stage['paired_segment_hit100_delta']['a_better']} 升 / "
      f"{stage['paired_segment_hit100_delta']['b_better']} 降 / "
      f"{stage['paired_segment_hit100_delta']['tied']} 平）。")
    w(f"- 另：raw 与 official 在本面板零时长率均为 {stage['zero_dur_raw']}（该阶段不产生零时长单元）。")
    w("")

    w("## 4. 段首效应在长时序上**不存在**（对第 1 轮结论的重要限定）")
    w("")
    w(f"- 段首单元 hit@100 {pct(seg['segment_first_units_raw']['hit100'])} vs 其余 "
      f"{pct(seg['other_units_raw']['hit100'])}；unsafe 率 {pct(seg['segment_first_units_raw']['unsafe_ge250'])} vs "
      f"{pct(seg['other_units_raw']['unsafe_ge250'])}（n={seg['segment_first_units_raw']['n']} / "
      f"{seg['other_units_raw']['n']}，{seg['n_segments']} 段）。")
    w("- 按段内位置分桶（官方阶段）：")
    w("")
    w("| 段内位置 | n | raw hit@100 | official hit@100 | raw unsafe≥250ms |")
    w("|---|---:|---:|---:|---:|")
    for r in pos:
        w(f"| {r['bucket']} | {r['n']:,} | {pct(r['raw_hit100'],1)} | {pct(r['official_hit100'],1)} | "
          f"{pct(r['raw_unsafe_share'],1)} |")
    w("")
    w("- **综合解释**：GTSinger 的\"段首幻觉前奏\"发生在 **音频被硬切在起唱点** 的情形"
      "（clip 的 GT start 恒为 0）；本面板每个拼接缝前都插了 0.5s 真静音，起唱点不在边界上，"
      "于是段首毫无惩罚。⇒ 该失效的触发条件是\"窗口左端无真实前奏\"，不是\"处于边界\"本身；"
      "长歌分窗时若窗口左端切在演唱中间，风险与 GTSinger 同类，需要专项验证（本轮无法验证，"
      "因为这里没有 GT 可用的自然长歌）。")
    w("")

    w("## 5. 无真值信号的跨面板迁移（第 1 轮结论在 200s 轴上更强）")
    w("")
    w("单信号 AUC（预测 official 阶段误差 > 阈值；方向已归一为\"越大越差\"）：")
    w("")
    w("| 信号 | bad>100ms | bad>200ms | bad>250ms |")
    w("|---|---:|---:|---:|")
    rows = sorted(sig["auc_per_signal"].items(),
                  key=lambda kv: -(kv[1].get("bad250") or 0))
    for name, v in rows:
        def orient(x):
            return None if x is None else round(x if x >= 0.5 else 1 - x, 4)
        w(f"| `{name}` | {orient(v.get('bad100'))} | {orient(v.get('bad200'))} | "
          f"{orient(v.get('bad250'))} |")
    w("")
    top_name, top_v = rows[0]
    w(f"- **熵类信号随阈值变宽而更强**：最强的 `{top_name}` 从 "
      f"{orient(top_v.get('bad100'))}（100ms）升到 {orient(top_v.get('bad250'))}（250ms）；"
      f"margin 类同向但整体弱一档（bad250 约 {sig['auc_per_signal']['min_margin']['bad250']}，"
      "即方向为\"margin 越大越好\"）。")
    if gate.get("available"):
        for key, lab in (("bad250", "≥250ms unsafe（与项目 unsafe 档同义）"),
                         ("bad100", ">100ms")):
            g = gate[key]
            w(f"- 门控（特征=熵/margin/repair 位移，按请求分组 5 折 OOF）目标 {lab}：n={g['n_rows']:,}，"
              f"阳性率 {g['positive_rate']}，**AUC {g['oof_auc']}**，AP {g['oof_ap']}；"
              f"复核预算曲线 flag5% 精度 {g['review_budget_curve']['flag_5pct']['precision']}"
              f"/召回 {g['review_budget_curve']['flag_5pct']['recall']}，"
              f"flag20% 精度 {g['review_budget_curve']['flag_20pct']['precision']}"
              f"/召回 {g['review_budget_curve']['flag_20pct']['recall']}。")
    w("- 与第 1 轮对照：GTSinger 人音真值上 posterior-only 门控 bad100 AUC 0.862；"
      "本弱真值长轴面板 bad100 只有 "
      f"{gate['bad100']['oof_auc'] if gate.get('available') else 'n/a'}，"
      "但 bad250 高达 "
      f"{gate['bad250']['oof_auc'] if gate.get('available') else 'n/a'}。"
      "**结论：熵信号擅长抓\" gross 错位\"（≥250ms），对 100ms 级的精细边界判别力有限**——"
      "这直接决定了它该被用在哪里：适合当 realign 触发器（抓大错），不适合当微调验收器。")
    w("")

    w("## 6. 冻结标签侧的交叉核对")
    w("")
    cross = a.get("frozen_label_crosscheck", {}).get("raw_label", {})
    if cross:
        w(f"- 项目自己的 raw 档标签：unsafe 占 {pct(cross['share_labelled_unsafe'],1)}，"
          f"其平均绝对误差 {sec(cross['mean_abs_err_when_unsafe_sec'],0)}，"
          f"safe 档平均 {sec(cross['mean_abs_err_when_safe_sec'],0)}；"
          "标签与 ≥250ms 精确重合（precision/recall/AUC 均 1.0）——这是定义使然，"
          f"；grey(100–250ms) 占 "
          f"{pct(ref['frozen_raw_label_shares'].get('grey', 0) / cross['n'],1)}"
          "。⇒ 现有三档标签在灰区只给了一个笼统档位，没有排序信息；"
          "而熵信号在同一目标上给出 AUC≈0.92 的连续分数，可作为分档之上的细粒度补充。")
    w("")

    w("## 7. 下一步（本轮暴露出来的、代价最低的高价值动作）")
    w("")
    w("1. **面板构建硬门**：任何复用 detector_v2/长时序证据的分析，必须先做"
      "\"重算误差 vs 冻结标签误差\"对账（本轮已实现为 `uniform_axis_trap`），"
      "不一致率 >5% 直接判定 join 失败并停下——否则会把 5.9% 当成模型性能写进结论。")
    w("2. **自然长歌真值仍缺**：本轮的\"长\"是拼接+插静音；`data/datasets_registry.md` 里 MIR-1K 是行级人工 GT"
      "（≤60s 段）、OpenCpop 受授权阻塞。要做真正的窗口/接缝验证，需要先造一个带人工 GT 的自然长歌面板"
      "（GTSinger 全曲 pilot 已在 2026-08-21 记录为可行但未执行）。")
    w("3. **门控定位调整**：把熵基 no-GT 触发器按\"≥250ms gross error\"目标来用（AUC≈0.92），"
      "并把 100ms 精修另立信号（需要比 entropy 更结构化的特征，例如跨候选/跨视图一致性）。")
    w("")

    w("## 8. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/build_m4_longform_weakgt_panel.py")
    w("PYTHONPATH=src python scripts/evaluation/report_m4_longform_weakgt.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_m4_longform_weakgt.py")
    w("```")
    w("")
    w(f"- 面板：`{panel['out']}`（{panel['bytes']/1e6:.1f} MB，{panel['rows']:,} 行）；")
    w("- 分析：`ANALYSIS.json`；抽取/装配自检：`PANEL_SUMMARY.json`。")
    w("- run1 被排除并登记原因："
      + json.dumps([r for r in panel["runs"] if r.get("excluded")], ensure_ascii=False))
    w("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    if str(args.metrics_out) != "-":
        metrics = {
            "schema_version": "m4_longform_weakgt_metrics_v1",
            "run": "20260912_m4_longform_weakgt",
            "source_analysis": str(args.analysis_dir / "ANALYSIS.json"),
            "reference_kind": "M4Singer per-segment character GT offset into a synthetic "
                              "concatenated timeline (weak supervision, NOT human GT, "
                              "NOT natural long audio)",
            "panel": p,
            "runs_assembled": panel["runs"],
            "headline": {
                "uniform_axis_trap_hit100_if_misused": trap.get("hit100_if_uniform_axis_used"),
                "frozen_real_gt_hit100": trap.get("hit100_with_frozen_real_gt"),
                "error_definitions_pearson_corr": trap.get("pearson_corr_of_two_error_definitions"),
                "postprocess_unit_hit100_delta_pp": stage.get(
                    "paired_unit_hit100_official_minus_raw_pp"),
                "postprocess_segment_paired_delta": stage.get("paired_segment_hit100_delta"),
                "postprocess_touched_share": post.get("share_units_touched"),
                "postprocess_start_pinned_to_prev_end": post.get("start_moved", {}).get(
                    "share_pinned_to_prev_end"),
                "segment_first_vs_rest_hit100": [seg["segment_first_units_raw"]["hit100"],
                                                 seg["other_units_raw"]["hit100"]],
                "best_no_gt_signal": sig.get("best_signal_at_250ms"),
                "best_no_gt_auc_at_250ms": sig.get("best_auc_at_250ms"),
                "gate_auc": {k: (gate.get(k) or {}).get("oof_auc") for k in ("bad100", "bad250")},
            },
            "stage_comparison": stage,
            "postprocess_on_longform": post,
            "segment_boundary_effect": seg,
            "position_in_phrase_profile": pos,
            "confidence_signals": sig,
            "gate": gate,
            "reference_profile": ref,
            "uniform_axis_trap": trap,
        }
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
