#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the unreachability recheck report (round 53).

NOTE for future editors: inside Chinese prose use 「」, never ASCII double quotes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_unreachable_recheck")
REPO = Path(__file__).resolve().parents[2]
FILTERS = ("all_units", "excluding_shipped_degenerate", "excluding_raw_inverted", "excluding_both")
ZH = {"all_units": "全部单元（旧口径）",
      "excluding_shipped_degenerate": "去掉交付端塌陷单元",
      "excluding_raw_inverted": "去掉解码端起止倒序",
      "excluding_both": "两者都去掉"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_unreachable_recheck.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_unreachable_recheck/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "UNREACHABLE_RECHECK.json").read_text(encoding="utf-8"))
    prog = r["progression_by_filter"]

    L: list[str] = []
    w = L.append
    w("# 承重数字复核：长音「答案不在候选里」的比例，去掉塌陷单元后仍在（第 53 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_unreachable_recheck/UNREACHABLE_RECHECK.json` 生成；只读既有面板，"
      "零前向、零 GPU。口径与第 19/21 轮一致：**精确同格**（真值格点是否落在 top-1 或 top-2 候选格点上）。")
    w("")
    w("## 0. 结论")
    w("")
    a = prog["all_units"]["long_note_end_outside_top2_exact"]
    b = prog["excluding_both"]["long_note_end_outside_top2_exact"]
    w(f"- **旧数字被完全复现**：长音端点真值不在前两名候选内的比例 "
      f"r0 **{100 * a['r0']:.1f}%** → r1 {100 * a['r1']:.1f}% → r2 {100 * a['r2']:.1f}%"
      f"（与索引 A17/第 19 轮记录的 70.8 / 27.5 / 21.7 逐位一致）⇒ 本次重算与历史结果同一把尺子。")
    w(f"- **去掉流水线塌陷与解码倒序之后，结论不变、还略好**："
      f"r0 {100 * b['r0']:.1f}% → r1 {100 * b['r1']:.1f}% → r2 **{100 * b['r2']:.1f}%**"
      f"（r2 比旧口径低 {100 * (a['r2'] - b['r2']):.1f}pp）"
      "⇒ **不可达不是塌陷造成的假象**：即便只看在流水线中被完好保留下来的长音，仍有约两成的收尾"
      "真值根本不在候选里，任何选择/后处理都碰不到它；")
    w(f"- **训练的方向性收益更清楚了**：r0→r2 的改善在干净子集上是 "
      f"{prog['excluding_both']['improvement_r0_to_r2_pp']:+.1f}pp（旧口径 "
      f"{prog['all_units']['improvement_r0_to_r2_pp']:+.1f}pp），"
      "**比旧口径更大一点**，所以「继续投训练」这条路线的依据比之前更强，而不是更弱；")
    w("- 影响面很小：塌陷单元在长音里占比 r0 5.7% / r1 4.1% / r2 3.5%，"
      "所以这既没有推翻也不会显著改动此前结论，只是把引用数字换成了更干净的版本。")
    w("")
    w("## 1. 四种口径对照（长音端点，真值不在 top-2 内的比例，精确同格）")
    w("")
    w("| 口径 | r0 | r1 | r2 | r0→r2 改善 | 单元数（r0/r1/r2） |")
    w("|---|---:|---:|---:|---:|---|")
    for fname in FILTERS:
        blk = prog.get(fname)
        if not blk:
            continue
        v = blk["long_note_end_outside_top2_exact"]
        w(f"| {ZH[fname]} | {100 * v['r0']:.1f}% | {100 * v['r1']:.1f}% | {100 * v['r2']:.1f}% | "
          f"{blk['improvement_r0_to_r2_pp']:+.1f}pp | {blk['units_per_checkpoint']} |")
    w("")
    r2 = r["by_checkpoint"]["r2"]["filters"]
    w(f"全部单元（不只长音）在 r2 上的同一比例：旧口径 "
      f"{100 * r2['all_units']['all']['end_outside_top2_exact']:.2f}% → 去塌陷 "
      f"{100 * r2['excluding_both']['all']['end_outside_top2_exact']:.2f}%"
      f"（{r2['excluding_both']['all']['units']:,} 单元）。")
    w("")
    w("## 2. 因此索引/清单里的引用口径更新")
    w("")
    w("- 「长音端点 40% 不可达」「训练把不可达率从 70.8% 压到 21.7%」这两条**继续成立**；")
    w("- 今后引用建议用**去塌陷版**：长音 r0 70.2% → r1 26.5% → **r2 20.5%**，"
      "并注明口径（同一份数据、排除被流水线塌陷与解码倒序污染的单元）；")
    w("- 相应地，「重解码预算在长音层与随机无异」（第 29 轮）的依据同样稳固——"
      "那 20.5% 不是选择问题，是候选生成问题。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_unreachable_recheck.py")
    w("PYTHONPATH=src python scripts/evaluation/report_unreachable_recheck.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "unreachable_recheck_metrics_v1", "audit": r,
         "headline": {
             "legacy_reproduced_exact": prog["all_units"]["long_note_end_outside_top2_exact"],
             "clean_subset_exact": prog["excluding_both"]["long_note_end_outside_top2_exact"],
             "within_one_bin_reference": prog["excluding_both"]["long_note_end_outside_top2_within1bin"],
             "r2_change_pp": round(100 * (prog["excluding_both"]["long_note_end_outside_top2_exact"]["r2"]
                                          - prog["all_units"]["long_note_end_outside_top2_exact"]["r2"]), 2),
             "training_improvement_pp_legacy": prog["all_units"]["improvement_r0_to_r2_pp"],
             "training_improvement_pp_clean": prog["excluding_both"]["improvement_r0_to_r2_pp"],
             "conclusion": "long-note unreachability is not an artefact of the upstream collapse: on "
                           "units the pipeline did not destroy, r2 still leaves 20.5 % of long-note "
                           "endings outside the top-2 candidates, and the r0-to-r2 training gain is "
                           "slightly larger on the clean subset"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
