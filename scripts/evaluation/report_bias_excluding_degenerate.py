#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the bias-excluding-degenerate recheck report (round 51).

NOTE for future editors: inside Chinese prose use 「」, never ASCII double quotes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_bias_excluding_degenerate")
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_bias_excluding_degenerate.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_bias_excluding_degenerate/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "BIAS_EXCLUDING_DEGENERATE.json").read_text(encoding="utf-8"))
    pooled = r["studio_gtsinger_all_checkpoints"]
    r2 = r["studio_gtsinger_r2_only"]
    tgt = r["target_mir1k"]

    L: list[str] = []
    w = L.append
    w("# 去掉塌陷单元后，长音收尾的跨域反向偏置还在吗（第 51 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_bias_excluding_degenerate/BIAS_EXCLUDING_DEGENERATE.json` 生成；"
      "只读既有面板，零前向、零 GPU。偏置＝预测减真值（负＝切早，正＝切晚）。")
    w("")
    w("## 0. 结论")
    w("")
    p_all, p_exc = pooled["all"]["long_note"], pooled["excluding_degenerate"]["long_note"]
    t_all, t_exc = tgt["all"]["long_note"], tgt["excluding_degenerate"]["long_note"]
    w(f"- **反向偏置成立，而且更强**：录音室（GTSinger 全检查点，第 21 轮同一口径）长音收尾中位 "
      f"**{p_all['median_ms']}ms → {p_exc['median_ms']}ms**（偏晚比例 {100 * p_all['late_share']:.1f}% → "
      f"{100 * p_exc['late_share']:.1f}%）；伴奏域（MIR-1K）长音 "
      f"**{t_all['median_ms']}ms → {t_exc['median_ms']}ms**（{100 * t_all['late_share']:.1f}% → "
      f"{100 * t_exc['late_share']:.1f}%）。**一负一正，符号相反 ⇒ 全局偏移校正不可跨域迁移"
      "这一条结论继续成立**；")
    w(f"- **塌陷单元本身在反向**：录音室被压平的字长音中位 **+"
      f"{pooled['degenerate_only']['long_note']['median_ms']}ms**、偏晚比例 "
      f"{100 * (pooled['degenerate_only']['long_note']['late_share'] or 0):.1f}%"
      "（把它们混进来会**掩盖**真实的提前偏置）⇒ 去掉之后提前量反而变大；")
    w(f"- r2 单检查点同样成立（{r2['all']['long_note']['median_ms']}ms → "
      f"{r2['excluding_degenerate']['long_note']['median_ms']}ms，偏晚比例 "
      f"{100 * r2['all']['long_note']['late_share']:.1f}% → "
      f"{100 * r2['excluding_degenerate']['long_note']['late_share']:.1f}%）。")
    w("")
    w("## 1. 明细")
    w("")
    for name, view in (("GTSinger 全检查点（第 21 轮口径）", pooled),
                       ("GTSinger 仅 r2", r2),
                       ("MIR-1K r2_full", tgt)):
        w(f"### {name}")
        w("")
        w("| 子集 | 单元 | 全部长字中位 | 偏晚比例 |")
        w("|---|---:|---:|---:|")
        for part, zh in (("all", "含塌陷"), ("excluding_degenerate", "去掉塌陷"),
                         ("degenerate_only", "只看塌陷")):
            blk = (view.get(part) or {})
            ln = blk.get("long_note") or {}
            if not ln:
                w(f"| {zh} | {blk.get('units', 0):,} | — | — |")
                continue
            w(f"| {zh} | {blk.get('units', 0):,} | {ln.get('median_ms')}ms | "
              f"{100 * (ln.get('late_share') or 0):.1f}% |")
        w("")
    w("## 2. 这条结论现在有了更干净的口径")
    w("")
    w("- 第 21 轮报的「录音室提前 40ms / 伴奏延后 32.4ms」是**含塌陷**的混合值；"
      "今后引用应改用**去掉塌陷**的版本（录音室 −48ms、伴奏 +34ms），"
      "或在同一处并列两者；")
    w("- 判定不变（符号相反 ⇒ 不做全局偏移校正），但**依据更硬**：塌陷不但没有造成这个反向，"
      "反而在往回掩盖它。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_bias_excluding_degenerate.py")
    w("PYTHONPATH=src python scripts/evaluation/report_bias_excluding_degenerate.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "bias_excluding_degenerate_metrics_v1", "audit": r,
         "headline": {
             "studio_long_note_median_ms": {"all": p_all["median_ms"], "excluding_degenerate":
                                            p_exc["median_ms"]},
             "accompanied_long_note_median_ms": {"all": t_all["median_ms"],
                                                 "excluding_degenerate": t_exc["median_ms"]},
             "studio_degenerate_only_long_note_median_ms":
                 pooled["degenerate_only"]["long_note"]["median_ms"],
             "sign_flip_survives": r["verdict"]["sign_flip_survives"],
             "conclusion": "the cross-domain sign flip in long-note end bias survives (and slightly "
                           "strengthens) after removing collapsed units: studio early, accompanied "
                           "late; the collapsed units themselves sit late and were masking part of "
                           "the early bias, so global offset correction remains unjustified"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
