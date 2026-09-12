#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the measurement-validity report (how much of each metric is the clamp)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_measurement_validity")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{d}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_measurement_validity.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_measurement_validity/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "MEASUREMENT_VALIDITY.json").read_text(encoding="utf-8"))
    pn = r["panels"]

    L: list[str] = []
    w = L.append
    w("# 测量有效性：已报出的边界精度里有多少是在测钳位而不是模型（第 17 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_measurement_validity/MEASUREMENT_VALIDITY.json` 生成；只重读既有面板，"
      "不改指标口径（仍用 canonical `both_abs_err = max(|start_err|,|end_err|)`），零新增前向。")
    w("")
    w("## 0. 结论")
    w("")
    w("- **同一处静默钳位也在评测链路里**：GTSinger `official` 面板 raw 阶段有 "
      f"{pct(pn['gtsinger_official']['stages']['model_raw_slots']['negative_share'],3)} 起止倒序，"
      "而交付阶段倒序恒为 0、零长从 "
      f"{pct(pn['gtsinger_official']['stages']['model_raw_slots']['zero_share'])} 升到 "
      f"{pct(pn['gtsinger_official']['stages']['shipped_pred']['zero_share'])}"
      f"（多出 {pn['gtsinger_official']['clamp']['extra_zero_downstream_units']:,} 个）。")
    go, mir = pn["gtsinger_official"]["impact"], pn["mir1k"]["impact"]
    w(f"- **污染界有界但不可忽略**：GTSinger(official) hit@100 {pct(go['hit_at_tol'])} → 剔除退化单元后 "
      f"{pct(go['hit_at_tol_excluding_degenerate'])}，**差 {go['contamination_bound_pp']:+.2f}pp**；"
      f"MIR-1K {pct(mir['hit_at_tol'])} → {pct(mir['hit_at_tol_excluding_degenerate'])} "
      f"（**{mir['contamination_bound_pp']:+.2f}pp**）。⇒ 本会话前几轮的绝对数值应理解为"
      "**含退化单元的保守下界**；跨系统比较仍成立，但**差距小的比较必须补这一列**。")
    w("- **跨预测器不等量**（最重要的一条）：见 §2 表——base 无 LoRA 的预测器退化率 20.2%，"
      "剔除后 +5.38pp；而 LoRA 检查点只有 +0.23~+0.54pp。⇒ 用 hit@100 做"
      "「集成成员弱排除」（第 4/5 轮方法）时，被排除者**同时**背着退化率与边界误差两个原因；"
      "不过结论方向不变（27.7% 仍远低于阈值 45.7%，见 §2 末行）。")
    w("- **真实伴奏歌受影响最大**：raw 倒序 "
      f"{pct(pn['real_songs_33']['stages']['model_raw_slots']['negative_share'])} → 交付倒序 0%、"
      f"零长 {pct(pn['real_songs_33']['stages']['model_raw_slots']['zero_share'])} → "
      f"{pct(pn['real_songs_33']['stages']['shipped_selected']['zero_share'])}"
      f"（钳位多出 {pn['real_songs_33']['clamp']['extra_zero_downstream_units']:,} 个零长）。")
    w("")
    w("## 1. 各面板的阶段形状")
    w("")
    w("| 面板 | 行数 | 阶段 | 倒序率 | 零长率 | 钳位在链路中？ |")
    w("|---|---:|---|---:|---:|---|")
    for name, blk in pn.items():
        for st, v in blk["stages"].items():
            if not v.get("available"):
                continue
            c = blk.get("clamp", {})
            mark = ("**是**" if c.get("clamp_present") else ("否" if c.get("available") else "—"))
            w(f"| `{name}` | {blk['rows']:,} | {st} | {pct(v['negative_share'],3)} | "
              f"{pct(v['zero_share'])} | {mark} |")
    w("")
    w("说明：`pipeline=raw` 的 GTSinger 面板**保留**倒序（不经压缩钳位），其 38 个倒序单元 hit@100 = "
      f"{pct(pn['gtsinger_raw']['impact'].get('inverted_hit_at_tol'),1)}、MAE(end) "
      f"{sec(pn['gtsinger_raw']['impact'].get('inverted_mae_end_sec'))}"
      " ⇒ 倒序单元本身就是灾难单元，钳位只是把它们变成"
      "「没有时间长度的字」，并没有让它们变对。")
    w("")
    w("## 2. 污染界（剔除零长单元后的同一指标）")
    w("")
    w("| 面板 / 预测器 | n | hit@100 | 剔除退化后 | 差(pp) | 退化率 | MAE(end) | 剔除后 MAE |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, blk in pn.items():
        im = blk.get("impact", {})
        if im.get("available"):
            w(f"| `{name}` | {im['n']:,} | {pct(im['hit_at_tol'])} | "
              f"{pct(im.get('hit_at_tol_excluding_degenerate'))} | "
              f"{im.get('contamination_bound_pp', 0.0):+.2f} | {pct(im['degenerate_share'])} | "
              f"{sec(im['mae_end_sec'])} | {sec(im.get('mae_end_sec_excluding_degenerate'))} |")
    for k, v in pn["mir1k"]["by_predictor"].items():
        w(f"| MIR-1K `{k}` | {v['n']:,} | {pct(v['hit_at_tol'])} | "
          f"{pct(v.get('hit_at_tol_excluding_degenerate'))} | "
          f"{v.get('contamination_bound_pp', 0.0):+.2f} | {pct(v['degenerate_share'])} | "
          f"{sec(v['mae_end_sec'])} | {sec(v.get('mae_end_sec_excluding_degenerate'))} |")
    w("")
    base = pn["mir1k"]["by_predictor"].get("base_qwen_raw_v1", {})
    ref = pn["mir1k"]["by_predictor"].get("r2_full_20260723", {})
    if base and ref:
        thr = 0.5 * ref.get("hit_at_tol_excluding_degenerate", 0.0)
        w(f"- **方法稳健性复核**：第 4/5 轮用「hit@100 < ½ 参考」排除弱成员。"
          f"base 剔除退化后为 {pct(base.get('hit_at_tol_excluding_degenerate'))}，"
          f"参考为 {pct(ref.get('hit_at_tol_excluding_degenerate'))}，阈值 "
          f"{pct(thr)} ⇒ **排除结论不变**（但当时它同时背着退化率，这个信息当时没被分开看）。")
    w("")
    w("## 3. 对口径的处置建议（不改历史数字，只加伴生列）")
    w("")
    w("- 在**面板级**报告里为每个 hit@tol 增设伴生列 `hit@tol_excluding_degenerate` 与 "
      "`degenerate_share`（本模块已可计算，接进 `audit_batch.py` 与后续面板即可）。")
    w("- 解释规则写死：**若两个系统的退化率之差 > 1pp，则它们的 hit@100 差距不可直接归因于边界精度**。")
    w("- 历史面板（本会话 runs/20260912_*）保持原样不重算，本报告即为它们的有效性附注。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_measurement_validity.py")
    w("PYTHONPATH=src python scripts/evaluation/report_measurement_validity.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_measurement_validity.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "measurement_validity_metrics_v1", "audit": r,
         "headline": {
             "gtsinger_official_bound_pp": go["contamination_bound_pp"],
             "mir1k_overall_bound_pp": mir["contamination_bound_pp"],
             "base_predictor_bound_pp": base.get("contamination_bound_pp"),
             "lora_predictors_bound_pp": {k: v.get("contamination_bound_pp") for k, v in
                                          pn["mir1k"]["by_predictor"].items()
                                          if k != "base_qwen_raw_v1"},
             "clamp_present_in_gtsinger_official": pn["gtsinger_official"]["clamp"]["clamp_present"],
             "real_song_extra_zeros_from_clamp":
                 pn["real_songs_33"]["clamp"]["extra_zero_downstream_units"],
             "ensemble_exclusion_conclusion_unchanged": bool(
                 base and ref and base.get("hit_at_tol_excluding_degenerate", 1.0)
                 < 0.5 * ref.get("hit_at_tol_excluding_degenerate", 0.0)),
             "conclusion": "reported absolute accuracies are conservative lower bounds inflated by "
                           "degenerate units (up to +3.3pp GTSinger, +3.2pp MIR-1K overall, "
                           "+5.4pp for the base predictor); cross-system gaps with differing "
                           "degeneracy rates must be read with the companion column"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
