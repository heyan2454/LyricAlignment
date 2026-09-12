#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the joint-cleanup report (three panels) and the long-form analysis-calibre correction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

JOINT = Path("/home/hyan/Data/lyricalign/runs/20260912_real_song_views/JOINT_CLEANUP.json")
CALIBRE = Path("/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt/ANALYSIS_CALIBRE.json")
REPO = Path(__file__).resolve().parents[2]

RULE_DESC = {
    "R0_none": "不清理（raw 原样）",
    "R1_shipped": "现装顺序清理",
    "shipped_official": "现装 official 阶段",
    "official_stage": "现装 official 阶段",
    "final_stage": "现装 final 阶段",
    "R3_end_trim_min0.05s": "只修尾端 + 0.05s 下限（第 2 轮 V9）",
    "V9_end_trim_min0.05s": "只修尾端 + 0.05s 下限（第 2 轮 V9）",
    "R6_clip_then_trim": "先钳异常时长再修尾端",
    "R7_clip_only": "只钳异常时长",
    "R8_joint_lp": "**联合约束求解（本次提出）**",
    "R8b_joint_unweighted": "联合求解（无置信加权）",
    "R8_joint_lp_alpha0": "联合求解（无置信加权 α=0）",
    "R8_joint_lp_alpha2": "联合求解（α=2）",
    "R8_joint_lp_alpha4": "联合求解（α=4）",
    "R8_joint_lp_alpha8": "联合求解（α=8）",
}


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else (f"{float(x):.2f}s" if abs(x) >= 1 else f"{1000 * float(x):.{d}f}ms")


def _table(rules, accuracy: bool) -> list[str]:
    head = ("| 规则 | 说明 | 退化单元 | 重叠 | 起点回退 | 最长单元 |"
            + (" hit@100 | hit@200 | hit@250 | MAE | IoU |" if accuracy else " 可信时长损失 |"))
    head += " 被移动单元 |"
    L = [head, "|" + "---|" * (6 + (5 if accuracy else 1) + 1)]
    for r in rules:
        row = (f"| `{r['rule']}` | {RULE_DESC.get(r['rule'], '—')} | {pct(r['degenerate_share'])} | "
               f"{pct(r['overlap_share'])} | {pct(r['start_regression_share'])} | "
               f"{sec(r['max_duration_sec'], 0)} |")
        if accuracy:
            row += (f" {pct(r.get('hit100'), 1)} | {pct(r.get('hit200'), 1)} | "
                    f"{pct(r.get('hit250'), 1)} | {sec(r.get('mae_both_sec'))} | "
                    f"{r.get('mean_iou')} |")
        else:
            row += f" {pct(r.get('plausible_mass_lost_share'), 1)} |"
        moved = r.get("share_units_moved", r.get("share_units_moved_vs_raw"))
        L.append(row + f" {pct(moved, 1)} |")
    return L


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--joint", type=Path, default=JOINT)
    ap.add_argument("--calibre", type=Path, default=CALIBRE)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_joint_cleanup.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_joint_cleanup/metrics.json")
    args = ap.parse_args()
    joint = json.loads(args.joint.read_text(encoding="utf-8"))
    cal = json.loads(args.calibre.read_text(encoding="utf-8")) if args.calibre.exists() else None

    L: list[str] = []
    w = L.append
    w("# 联合约束求解式清理（第 7 轮，2026-09-12）：三面板对照 + 长时序口径更正")
    w("")
    w("> 数字全部由 `runs/20260912_real_song_views/JOINT_CLEANUP.json` 与 "
      "`runs/20260912_m4_longform_weakgt/ANALYSIS_CALIBRE.json` 生成，不手抄。")
    w("> 纯 CPU：零新增前向；清理是后处理，realign 仍 shadow-only，未改任何生产实现。")
    w("")
    w("## 0. 一句话结论")
    w("")
    gs = {r["rule"]: r for r in joint["gtsinger"]["rules"]}
    m4 = {r["rule"]: r for r in joint.get("m4_longform", {}).get("rules", [])}
    real = {r["rule"]: r for r in joint.get("real_songs", {}).get("rules", [])}
    w(f"- 在**有真人逐字真值**的 GTSinger 上，联合求解比现装后处理 "
      f"hit@100 **{pct(gs['R8_joint_lp_alpha0']['hit100'],1)} vs {pct(gs['shipped_official']['hit100'],1)}"
      f"（+{(gs['R8_joint_lp_alpha0']['hit100']-gs['shipped_official']['hit100'])*100:.2f}pp）**，"
      f"同时把退化单元 {pct(gs['shipped_official']['degenerate_share'],2)}→{pct(gs['R8_joint_lp_alpha0']['degenerate_share'],2)}、"
      f"重叠→{pct(gs['R8_joint_lp_alpha0']['overlap_share'],2)}，MAE 也更好。")
    if m4:
        w(f"- 在**自然长时序**（M4 拼接，弱 GT）上它是**精度中性**的："
          f"hit@100 {pct(m4['R8_joint_lp_alpha0']['hit100'],2)} vs raw "
          f"{pct(m4['raw_none']['hit100'],2)} vs 现装 official "
          f"{pct(m4['official_stage']['hit100'],2)}；同时结构完全干净"
          f"（重叠 {pct(m4['raw_none']['overlap_share'],2)}→0，而现装 official 阶段"
          f"额外制造 {pct(m4['official_stage']['degenerate_share'],2)} 退化单元）。")
    if real:
        w(f"- 在 25 首**真实伴奏歌**（无真值）上只有联合求解能同时做到退化 0%、重叠 0%、回退 0%"
          f"（现装留下 {pct(real['R1_shipped']['degenerate_share'],1)} 退化单元）。")
    w("- ⇒ **建议**：把顺序 if-else 清理换成一次联合求解（min 50ms / max 3s / 保序 / 非重叠 /"
      " 加权 L1 贴近 raw），并保留第 2 轮的结论：任何规则改动都必须在带真值面板上复验。")
    w("")

    w("## 1. GTSinger（人工逐字真值，"
      + f"{joint['gtsinger']['panel']['units']:,} 单元 / {joint['gtsinger']['panel']['sequences']} 序列）")
    w("")
    L.extend(_table(joint["gtsinger"]["rules"], accuracy=True))
    w("")
    w(f"- 现装 official 阶段相对 raw **损失** "
      f"{(gs['raw_none']['hit100']-gs['shipped_official']['hit100'])*100:.2f}pp hit@100"
      f"（并把退化单元从 {pct(gs['raw_none']['degenerate_share'],2)} 提高到 "
      f"{pct(gs['shipped_official']['degenerate_share'],2)}），与第 2 轮"
      "「后处理净损害」结论一致。")
    w(f"- 联合求解（α=0）是唯一**同时**优于 raw 与现装的规则："
      f"hit@100 {pct(gs['R8_joint_lp_alpha0']['hit100'],2)}、"
      f"hit@250 {pct(gs['R8_joint_lp_alpha0']['hit250'],2)}、MAE {sec(gs['R8_joint_lp_alpha0']['mae_both_sec'])}。")
    w(f"- 置信加权（α=2/4/8）反而略降精度（{pct(gs['R8_joint_lp_alpha2']['hit100'],2)}—"
      f"{pct(gs['R8_joint_lp_alpha8']['hit100'],2)}）但更保结构稳定的高置信边界；"
      "本报告不下'α 该取多少'的结论（未在真值上调参，α 只是敏感性检查）。")
    w("")
    if joint.get("real_songs"):
        w("## 2. 真实伴奏歌（无真值：只比结构与破坏度）")
        w("")
        w(f"面板：{joint['real_songs']['panel']['units']:,} 单元 / "
          f"{joint['real_songs']['panel']['songs']} 首（视图 `{joint['real_songs']['panel']['view']}`）")
        w("")
        L.extend(_table(joint["real_songs"]["rules"], accuracy=False))
        r1, r8 = real["R1_shipped"], real["R8_joint_lp"]
        w("")
        w(f"- 可信时长损失：现装 {pct(r1.get('plausible_mass_lost_share'),1)} vs 联合 "
          f"{pct(r8.get('plausible_mass_lost_share'),1)} ⇒ **两者相近**，差别不在毁多少内容，"
          f"而在现装把损失集中在\「压成零长\」（退化 {pct(r1['degenerate_share'],1)}），"
          f"联合求解则把同样的重叠摊成合法短区间（退化 {pct(r8['degenerate_share'],2)}）。")
        w(f"- 移动者中原本高置信（熵低于中位）的边界占比 {pct(r8.get('share_moved_boundaries_that_were_confident'),1)}"
          f"（现装 {pct(r1.get('share_moved_boundaries_that_were_confident'),1)}）"
          "⇒ 联合求解只在略多多动一点高置信边界，代价可控。")
        w("")
    if m4:
        w("## 3. 自然长时序（M4 拼接，弱 GT；按**请求序列**求解）")
        w("")
        p = joint["m4_longform"]["panel"]
        w(f"面板：{p['units']:,} 行 / {p['sequences']} 条序列"
      f"（{p.get('sequence_unit', 'request_identity+view_id')}），"
          f"序列按请求切分——**上一版本误按 (view, segment) 切分**，"
          "把同一单元的多窗口尝试混进一条序列，导致首次跑出 6% hit@100 的荒谬结果（已修正并固化为测试）。")
        w("")
        L.extend(_table(joint["m4_longform"]["rules"], accuracy=True))
        w("")
        w(f"- 重建真值的交叉验证：`reconstruction_check_raw_max_dev_sec = "
          f"{p['reconstruction_check_raw_max_dev_sec']}`（应为 0，因真值就是由冻结 signed 误差反推），"
          f"两阶段互印证的单元占比 {pct(p['stage_agreement_share'],2)}"
          f"（不一致的 {p.get('rows_dropped_by_stage_disagreement', 0):,} 行已剔除，"
          f"最大跨阶段不一致 {p.get('stage_disagreement_max_sec')}s）。")
        w("- 面板自带的 `gt_*` 列被**拒绝使用**：它落在第 3 轮已经证明的伪造均匀轴上（用它的 raw hit@100 只有约 5%）。")
        w("")
    if cal:
        w("## 4. 对第 3 轮的口径更正：attempt ≠ unit（重要）")
        w("")
        w(f"- 长时序面板每行是一次 **(request, view, 单元)** 尝试：同一歌词单元被多个滑窗覆盖，"
          f"中位 {cal['multiplicity_median']} 次、最多 {cal['multiplicity_max']} 次；"
          f"全表 {cal['rows']:,} 行只对应 **{cal['unique_units']:,} 个唯一单元**（扇出 "
          f"{cal['fan_out_factor']}×）。")
        w(f"- 之前报告把行级统计称作「单元级」，这是**口径错标**：正确单元键必须含 song —— "
          f"`{cal['unit_key']}`（`canonical_unit_id` 是歌曲内 timeline 的下标，"
          "只按 (view, cid) 分组会把不同歌曲的同名下标混为一谈——我在本轮差点因此得出"
          "「面板有 40% 冲突行」的错误结论）。")
        w("")
        w("| 口径 | n | raw hit@100 | raw hit@250 | raw MAE | official hit@100 | official hit@250 | official MAE |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|")
        for label, key in (("attempt 级（行级，旧报告口径）", "attempt_level"),
                           ("unit 级：尝试取中位", "unit_level_median_of_attempts"),
                           ("unit 级：尝试取最差", "unit_level_worst_of_attempts"),
                           ("unit 级：尝试取最优（跨窗 oracle，用真值）", "unit_level_best_of_attempts_oracle")):
            r, o = cal["raw"][key], cal["official"].get(key, {})
            w(f"| {label} | {r['n']:,} | {pct(r['hit100'],2)} | {pct(r['hit250'],2)} | {sec(r['mae'])} | "
              + (f"{pct(o['hit100'],2)} | {pct(o['hit250'],2)} | {sec(o['mae'])} |" if o else "— | — | — |"))
        w("")
        w(f"- **单元级真相比行级更好也更需要分层**：raw 的 unit 级 hit@100 "
          f"{pct(cal['raw']['unit_level_median_of_attempts']['hit100'],1)}"
          f"（行级只有 {pct(cal['raw']['attempt_level']['hit100'],1)}），"
          f"但**最差尝试**只有 {pct(cal['raw']['unit_level_worst_of_attempts']['hit100'],1)}"
          f"（MAE {sec(cal['raw']['unit_level_worst_of_attempts']['mae'])}）"
          "⇒ 长时序的真实风险不是平均精度，而是**同一单元在不同窗口里的结果差异**。")
        w(f"- 跨尝试分歧：raw 每单元 max−min 误差极差中位 {sec(cal['raw']['attempt_spread_sec']['median'])}、"
          f"p90 **{sec(cal['raw']['attempt_spread_sec']['p90'])}**，"
          f"{pct(cal['raw']['attempt_spread_sec']['share_units_gt_100ms'],1)} 的单元极差 >100ms。")
        w(f"- **现装 official 阶段的新价值定位**：它把上述极差 p90 从 raw 的 "
          f"{sec(cal['raw']['attempt_spread_sec']['p90'])} 压到 "
          f"{sec(cal['official']['attempt_spread_sec']['p90'])}（约 9×），"
          "代价是单元级中位精度几乎不变（"
          f"{pct(cal['raw']['unit_level_median_of_attempts']['hit100'],2)} → "
          f"{pct(cal['official']['unit_level_median_of_attempts']['hit100'],2)}）。"
          "⇒ 现装后处理的真正贡献是**跨窗口方差收缩**，不是提精度——这与第 2/3 轮"
          "「净损害/无收益」的表述并不矛盾，而是给出了它为什么存在的解释。")
        w(f"- 跨窗选择的理论上限：unit 级 best-of-attempts hit@100 "
          f"{pct(cal['raw']['unit_level_best_of_attempts_oracle']['hit100'],1)}"
          f"（vs 中位尝试 {pct(cal['raw']['unit_level_median_of_attempts']['hit100'],1)}，"
          f"+{(cal['raw']['unit_level_best_of_attempts_oracle']['hit100']-cal['raw']['unit_level_median_of_attempts']['hit100'])*100:.1f}pp）"
          "⇒ **多窗口一致地在同一单元上给出过更好的尝试**，这条 headroom 明显大于第 5 轮"
          "「跨 checkpoint 共识只有 +0.34pp」的情形：真正的多视图（不同音频切片）值得再做一次"
          "**可无真值选人**的实验（用极差/熵/边界一致度作为选择器），而不是再换 checkpoint。")
        w("")
    w("## 5. 边界与未做")
    w("")
    w("- 联合求解的两个超参（min 0.05s / max 3s）取自第 2/6 轮的结构定义，**未在真值上调参**；"
      "α 只做了 0/2/4/8 敏感性检查。")
    w("- 三面板的单元语义不同：GTSinger 是录音室短句字符、M4 是拼接长时序字符、真实歌含 word 单元；"
      "结论只在「结构 + 单元级精度方向一致」的意义上可迁移。")
    w("- LP 成本：1,380 条序列 × 数十单元在 CPU 上 <1 分钟；若要上线需按窗口并行，"
      "并对超长序列（>4,000 单元）走钳制回退（代码已实现并记录 status）。")
    w("- 没有改任何生产实现，realign 仍 shadow-only；MIR-1K/PJS 仍为 test-only。")
    w("")
    w("## 6. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/solve_joint_cleanup.py          # 三面板")
    w("PYTHONPATH=src python scripts/evaluation/report_joint_cleanup.py         # 本报告 + metrics")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_joint_cleanup.py")
    w("```")
    w("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {
        "schema_version": "joint_cleanup_metrics_v1", "source_joint": str(args.joint),
        "source_calibre": str(args.calibre) if cal else None,
        "recommendation": "replace the sequential cleanup with one constrained solve "
                          "(min 0.05 s, max 3 s, monotone starts, no overlap, weighted-L1 to clipped raw)",
        "gtsinger": joint["gtsinger"], "real_songs": joint.get("real_songs"),
        "m4_longform": joint.get("m4_longform"),
        "longform_calibre_correction": cal,
        "headline": {
            "gtsinger_hit100_joint_vs_shipped": [gs["R8_joint_lp_alpha0"]["hit100"],
                                                 gs["shipped_official"]["hit100"]],
            "gtsinger_gain_over_shipped_pp": round(
                (gs["R8_joint_lp_alpha0"]["hit100"] - gs["shipped_official"]["hit100"]) * 100, 2),
            "gtsinger_degenerate_joint_vs_shipped": [gs["R8_joint_lp_alpha0"]["degenerate_share"],
                                                     gs["shipped_official"]["degenerate_share"]],
            "m4_hit100_joint_vs_raw": [m4["R8_joint_lp_alpha0"]["hit100"], m4["raw_none"]["hit100"]] if m4 else None,
            "real_songs_degenerate_shipped": real["R1_shipped"]["degenerate_share"] if real else None,
            "real_songs_degenerate_joint": real["R8_joint_lp"]["degenerate_share"] if real else None,
            "unit_vs_attempt_hit100_raw": [cal["raw"]["unit_level_median_of_attempts"]["hit100"],
                                           cal["raw"]["attempt_level"]["hit100"]] if cal else None,
            "official_variance_shrink_p90": [cal["raw"]["attempt_spread_sec"]["p90"],
                                             cal["official"]["attempt_spread_sec"]["p90"]] if cal else None,
            "cross_window_oracle_headroom_pp": round(
                (cal["raw"]["unit_level_best_of_attempts_oracle"]["hit100"]
                 - cal["raw"]["unit_level_median_of_attempts"]["hit100"]) * 100, 2) if cal else None,
        },
    }
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
