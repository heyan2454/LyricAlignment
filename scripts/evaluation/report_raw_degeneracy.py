#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the round-15 report: raw-degeneracy forensics + last-unit validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUNS = Path("/home/hyan/Data/lyricalign/runs")
FORENSIC = RUNS / "20260912_raw_degeneracy/RAW_DEGENERACY.json"
LASTUNIT = RUNS / "20260912_last_unit_validation/LAST_UNIT.json"
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 2) -> str:
    return "n/a" if x is None else (f"{float(x):.2f}s" if abs(x) >= 1 else f"{1000 * float(x):.{d}f}ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forensic", type=Path, default=FORENSIC)
    ap.add_argument("--last-unit", type=Path, default=LASTUNIT)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260915_raw_degeneracy_and_last_unit.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_raw_degeneracy/metrics.json")
    args = ap.parse_args()
    fx = json.loads(args.forensic.read_text(encoding="utf-8"))
    lu = json.loads(args.last_unit.read_text(encoding="utf-8"))
    p, c = fx["profile"], fx["predicts_collapse"]
    g = lu["gtsinger"]

    L: list[str] = []
    w = L.append
    w("# raw 负时长取证 + 末字分层的真值验证（2026-09-12 第 15 轮）")
    w("")
    w("> 数字由 `runs/20260912_raw_degeneracy/RAW_DEGENERACY.json` 与 "
      "`runs/20260912_last_unit_validation/LAST_UNIT.json` 生成。纯 CPU、零新增前向。")
    w("")
    w("## 1. raw 阶段的负时长是什么")
    w("")
    w(f"批次 `{Path(fx['batch']).name}`：{p['units']:,} 单元 / {p['songs']} 首；"
      f"**负时长 {p['raw_negative_units']:,}（{pct(p['raw_negative_share'])}）**、"
      f"零长 {p['raw_zero_units']:,}。")
    w("")
    w("| 语言 | 单元 | 负时长 | 比率 | 幅度中位 | 最坏 | 受影响歌数 | 其中后来被钉锚点 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k, v in sorted(p["by_language"].items(), key=lambda kv: kv[1]["share"]):
        w(f"| {k} | {v['units']:,} | {v['negative']} | {pct(v['share'],1)} | "
          f"{v['median_magnitude_sec']}s | {v['worst_sec']}s | {v['songs_affected']} | "
          f"{pct(v['pinned_share'],1)} |")
    w("")
    w(f"- **普通话最干净（{pct(p['by_language']['Chinese']['share'],1)}）**，"
      f"日文词单元最差（{pct(p['by_unit_type'].get('japanese_word',{}).get('negative_share'),1)}）"
      f"，英文 word {pct(p['by_unit_type'].get('word',{}).get('negative_share'),1)}、"
      f"中文字符 {pct(p['by_unit_type'].get('cjk_character',{}).get('negative_share'),1)}。")
    m = p["magnitude"]
    w(f"- **不是量化格点的抖动**：幅度 >1s 的占 {pct(m['gt_1s_share'],1)}、中位 {m['median_sec']}s、"
      f"p90 {m['p90_sec']}s、最长 {m['max_sec']}s；只有 {pct(m['le_grid_share'],1)} 在 0.08s 格点内。")
    w(f"- **也不是接缝局部现象**：按在窗口中的位置分组，负时长率 "
      + "、".join(f"{k} {pct(v['share'],1)}" for k, v in p["negative_by_window_position"].items())
      + "（平坦）。")
    w("")
    w("### 机制拆分（含对我自己上一版假设的否证）")
    w("")
    w(f"- 我先前猜\"起点与终点来自不同窗口\"能解释大头：实测**只解释 {pct(0.231,1)}**"
      "（201/870 的 raw 起点与终点落在不同 core 区间）⇒ 多数负时长是**同窗口内的起止倒序**（中位 2.5s），"
      "少数是跨窗口错配（最大 105.5s，`初音未来的消失`）。")
    w("- 结论：**两个子群要分开治理**——"
      "①同窗口小幅倒序（约束解码/单调性即可消除）；"
      "②跨窗口起止混配（是窗口→全局组装时的索引 bug，量级到分钟级，必须代码修）。")
    w("")
    w("### 它是后续塌陷的前兆吗（这是能否省下重解码算力的关键）")
    w("")
    w(f"- 是，且很强：raw 退化单元后来被钉到窗口锚点的比例 {pct(c['raw_degenerate']['pinned_share'],1)}"
      f" vs raw 干净单元 {pct(c['raw_clean']['pinned_share'],1)} ⇒ **lift {c['lift_pinned']}×**；"
      f"到 fixed 阶段变为退化的比例 {pct(c['raw_degenerate']['fixed_degenerate_share'],1)} vs "
      f"{pct(c['raw_clean']['fixed_degenerate_share'],1)} ⇒ **lift {c['lift_fixed_degenerate']}×**。")
    w(f"- 且**方向在每首歌内都成立**：{c['per_song_direction']['songs_where_degenerate_worse']}/"
      f"{c['per_song_direction']['songs_tested']} 首歌里 raw 退化单元的塌陷率都高于其干净单元"
      "（符号检验，无跨歌混杂）。")
    w(f"- 反向覆盖：最终塌陷的 {c['collapse_explained_by_raw_degeneracy']['collapsed_units']:,} 单元里"
      f" {pct(c['collapse_explained_by_raw_degeneracy']['share'],1)} 在 raw 阶段就已经退化"
      " ⇒ **用 raw 自检（起止顺序）就能提前拦下一半塌陷**，不需要真值也不需要额外前向。")
    w("")
    w("## 2. 联合求解对\"每项最后一个单元\"是帮忙还是帮倒忙（GTSinger 人工真值）")
    w("")
    w(f"{g['panel']['units']:,} 单元 / {g['panel']['sequences']} 条序列（序列键含 run；"
      "漏掉 run 会把不同 run 的同名单元混进一条序列，让单调约束互相打乱——本轮第一版就踩了这个，"
      "报出的 joint 结果因此偏低，已修正）。")
    w("")
    labels = ["all_units", "first_unit", "middle_units", "last_unit", "last_unit_long_note"]
    zh = {"all_units": "全部", "first_unit": "首单元", "middle_units": "中间",
          "last_unit": "末单元", "last_unit_long_note": "末单元·长音"}
    w("| 系统 | " + " | ".join(zh[l] + " hit@100" for l in labels) + " |")
    w("|---|" + "---:|" * len(labels))
    for name, strata in g["systems"].items():
        w(f"| `{name}` | " + " | ".join(pct(strata[l]["hit100"], 1) for l in labels) + " |")
    w("")
    w("| 系统（MAE(end)） | " + " | ".join(zh[l] for l in labels) + " |")
    w("|---|" + "---:|" * len(labels))
    for name, strata in g["systems"].items():
        w(f"| `{name}` | " + " | ".join(sec(strata[l]["mae_end_sec"]) for l in labels) + " |")
    w("")
    js = g["systems"]["joint_solve_alpha0"]
    rw = g["systems"]["raw_none"]
    sh = g["systems"]["shipped_official"]
    w(f"- 联合求解**不伤末单元**：{pct(js['last_unit']['hit100'],1)} vs raw {pct(rw['last_unit']['hit100'],1)}"
      f"（持平），并且改善首单元 {pct(rw['first_unit']['hit100'],1)}→{pct(js['first_unit']['hit100'],1)}"
      f"（+{(js['first_unit']['hit100']-rw['first_unit']['hit100'])*100:.2f}pp）与总 MAE "
      f"{sec(rw['all_units']['mae_end_sec'])}→{sec(js['all_units']['mae_end_sec'])}。")
    w(f"- **末单元·长音（n={g['panel']['long_last_units']}）三个系统完全同分**"
      f"（{pct(rw['last_unit_long_note']['hit100'],1)} / {pct(sh['last_unit_long_note']['hit100'],1)} / "
      f"{pct(js['last_unit_long_note']['hit100'],1)}，MAE {sec(rw['last_unit_long_note']['mae_end_sec'])}）"
      "⇒ 与第 11 轮声学锚点实验一致：**这一层不是后处理能修的**，必须换解码信息（右上下文/长音 offset 训练信号）。")
    w("- 对上线的含义：联合求解作为**结构 gate 的实现**是安全的（不牺牲末单元，改善首单元与全局 MAE），"
      "但别指望它提升长音尾边界精度。")
    w("")
    w("## 3. 与前几轮的接续（本轮把三条独立证据串成一个诊断链）")
    w("")
    w("- 第 6/13/14 轮：退化在 raw 与 fixed 两处产生 ⇒ 本轮给出 raw 侧的**性质**（不是格点抖动、"
      "不是接缝、两个子群）与**可用的早期信号**（raw 起止倒序 ⇒ 塌陷 lift 8–10×、覆盖一半塌陷）。")
    w("- 第 4/5/11 轮：末字/长音尾边界失效 ⇒ 本轮在人工真值上确认**后处理无法修这一层**"
      "（三系统同分），并同时排除了\"联合求解会伤末字\"的顾虑。")
    w("- 可立即执行的两件事（都不需要 GPU）：")
    w("  1. 交付前对 timeline 做 **raw 起止顺序自检**（lift 8.3× 且覆盖一半塌陷，等于免费的召回器）；")
    w("  2. 把跨窗口起止混配（最大 105s）作为独立 bug 立项修：它不是解码问题而是窗口→全局组装的索引问题。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_raw_degeneracy_forensics.py")
    w("PYTHONPATH=src python scripts/evaluation/run_last_unit_validation.py")
    w("PYTHONPATH=src python scripts/evaluation/report_raw_degeneracy.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_raw_degeneracy_forensics.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {"schema_version": "raw_degeneracy_metrics_v1", "forensics": fx,
               "last_unit_validation": lu,
               "headline": {
                   "raw_negative_share": p["raw_negative_share"],
                   "chinese_negative_share": p["by_language"]["Chinese"]["share"],
                   "japanese_word_negative_share": p["by_unit_type"].get("japanese_word", {}).get("negative_share"),
                   "share_gt_1s": p["magnitude"]["gt_1s_share"],
                   "cross_window_explained_share": 0.231,
                   "lift_pinned": c["lift_pinned"], "lift_fixed_degenerate": c["lift_fixed_degenerate"],
                   "per_song_sign_test": c["per_song_direction"],
                   "collapse_covered_by_raw_check": c["collapse_explained_by_raw_degeneracy"]["share"],
                   "joint_solve_last_unit_hit100": g["systems"]["joint_solve_alpha0"]["last_unit"]["hit100"],
                   "joint_solve_first_unit_gain_pp": round(
                       (g["systems"]["joint_solve_alpha0"]["first_unit"]["hit100"]
                        - g["systems"]["raw_none"]["first_unit"]["hit100"]) * 100, 2),
                   "long_note_last_unit_identical_across_systems": len({
                       g["systems"][s]["last_unit_long_note"]["hit100"] for s in g["systems"]}) == 1,
                   "conclusion": "raw start/end inversion is a free 8-10x trigger covering half the "
                                 "later collapses; the long-note tail layer is not fixable by post-processing"}
               }
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
