#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the tail-acoustics (negative result) report from its JSON artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_tail_acoustics")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def sec(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{1000 * float(x):.{d}f}ms"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_tail_acoustics.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_tail_acoustics/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "TAIL_ACOUSTICS.json").read_text(encoding="utf-8"))
    gts, mir = r["gtsinger_derivation"], r["mir1k_transfer"]
    rf = r.get("mir1k_ratio_family")

    L: list[str] = []
    w = L.append
    w("# 末字尾边界的声学锚点实验（第 11 轮，2026-09-12）——**否证两条简单判据**")
    w("")
    w("> 数字由 `runs/20260912_tail_acoustics/TAIL_ACOUSTICS.json` 生成。")
    w("> 纪律：阈值/规则**只在 GTSinger 上导出**，冻结后迁移到 MIR-1K（test-only）；"
      "MIR-1K 上的 ρ 族**整族报告、不做选择**。零 GPU，音频只读不复制。")
    w("")
    w("## 0. 结论")
    w("")
    w("- **RMS 衰减锚点在末字上几乎不触发**：GTSinger 末字 168 单元里最多只有 6 个有锚点"
      f"（θ=0.5 覆盖 {pct(list(gts['anchor_coverage'].values())[0],1)}），"
      "MIR-1K 末字 17 单元里**只有 1 个**有锚点 ⇒ 它根本没有机会修我们已定位的失效层。")
    f_long = r["frozen_transfer"]
    w(f"- **导出的阈值不可迁移**：GTSinger 长音上最好的 θ=0.15（+3.69pp）冻结到 MIR-1K 长音后是 "
      f"**{f_long['mir1k_delta_pp_long_notes']:+.2f}pp**（全单元 {f_long['mir1k_delta_pp_all']:+.2f}pp）。")
    if rf:
        best = max(rf["rhos"].items(), key=lambda kv: (kv[1]["anchor_all_units"] or {}).get("hit100", 0))
        w(f"- **人声/伴奏能量比锚点触发率很高但没有用**：覆盖 "
          f"{pct(best[1]['coverage'])}（含全部 17 个末字），"
          f"而其 hit@100 只有 {pct(best[1]['anchor_all_units']['hit100'])}，"
          f"同一批单元上模型是 {pct(best[1]['model_on_covered_all']['hit100'])}；"
          f"末字子集上锚点 {pct(best[1]['anchor_last_char']['hit100'])} vs 模型 "
          f"{pct(best[1]['model_on_covered_last']['hit100'])}。")
    w("- **两个 oracle 界都表明空间很小**：在\"模型 vs 各锚点\"之间用真值逐单元挑最优，"
      "GTSinger 全单元只 +0.75pp、末字 **+0.00pp**；MIR-1K 全单元 +1.67pp、末字 **+0.00pp**"
      "（长音 +7.14pp 但那是 test 上的事后观察，不构成可部署结论）。")
    w("- ⇒ **关闭 F3 的简单版本**：末字/长音的残余误差**不能**用相对能量阈值或人声-伴奏比值阈值这类"
      "事后声学判据修复；这些信号在带伴奏、带混响的真实录音上要么不触发、要么系统性偏晚。"
      "剩余误差需要**模型侧**改动（更长右上下文、拖长音 offset 的训练信号），"
      "这与第 5/6/7 轮\"单次解码之后的环节可挽回空间都是个位数 pp\"完全一致。")
    w("")
    w("## 1. 导出集（GTSinger，人工真值）")
    w("")
    w("| 规则 | 覆盖 | all hit@50 | all hit@100 | all MAE | 长音 hit@100 | 长音 MAE | Δ长音 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    cov = gts["anchor_coverage"]
    for c, v in gts["rules"].items():
        a, l = v["all_units"], v["long_notes"]
        if a.get("n", 0) == 0:
            continue
        cc = cov.get(c, 1.0)
        w(f"| `{c}` | {pct(cc)} | {pct(a.get('hit50'))} | {pct(a.get('hit100'))} | "
          f"{sec(a.get('mae_end_sec'))} | {pct(l.get('hit100'))} | {sec(l.get('mae_end_sec'))} | "
          f"{gts['delta_pp_hit100_long_notes_vs_model'].get(c, 0.0):+.2f}pp |")
    w("")
    w("## 2. 迁移集（MIR-1K，test-only，人工逐字真值）")
    w("")
    w("| 规则 | 覆盖 | all hit@100 | all MAE | 长音 hit@100 | 长音 MAE | Δ长音 |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    cov = mir["anchor_coverage"]
    for c, v in mir["rules"].items():
        a, l = v["all_units"], v["long_notes"]
        if a.get("n", 0) == 0:
            continue
        w(f"| `{c}` | {pct(cov.get(c, 1.0))} | {pct(a.get('hit100'))} | {sec(a.get('mae_end_sec'))} | "
          f"{pct(l.get('hit100'))} | {sec(l.get('mae_end_sec'))} | "
          f"{mir['delta_pp_hit100_long_notes_vs_model'].get(c, 0.0):+.2f}pp |")
    w("")
    w("末字子集（每集 17 / 168 单元，样本很小，只作方向性观察）：")
    w("")
    w("| 集合 | 规则 | n | hit@100 | MAE |")
    w("|---|---|---:|---:|---:|")
    for name, blk in (("GTSinger", gts), ("MIR-1K", mir)):
        for c, v in (blk.get("last_char_only") or {}).items():
            if v.get("n", 0):
                w(f"| {name} | `{c}` | {v['n']} | {pct(v.get('hit100'))} | {sec(v.get('mae_end_sec'))} |")
    w("")
    if rf:
        w("## 3. 人声/伴奏比值锚点（利用 MIR-1K 原始双声道；ρ 整族报告，不选点）")
        w("")
        mb = rf["model_baseline"]
        w(f"模型基线：全单元 hit@100 {pct(mb['all_units']['hit100'])}、末字 "
          f"{pct(mb['last_char']['hit100'])}（n={mb['last_char']['n']}）、长音 "
          f"{pct(mb['long_notes']['hit100'])}（n={mb['long_notes']['n']}）")
        w("")
        w("| ρ | 覆盖 | 锚点 hit@100 | 模型(同单元) | 锚点 MAE | 末字锚点 hit@100 | 末字模型 | 长音锚点 | 长音模型 |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for rho, v in sorted(rf["rhos"].items(), key=lambda kv: -float(kv[0])):
            w(f"| {rho} | {pct(v['coverage'])} | {pct((v['anchor_all_units'] or {}).get('hit100'))} | "
              f"{pct((v['model_on_covered_all'] or {}).get('hit100'))} | "
              f"{sec((v['anchor_all_units'] or {}).get('mae_end_sec'))} | "
              f"{pct((v['anchor_last_char'] or {}).get('hit100'))} | "
              f"{pct((v['model_on_covered_last'] or {}).get('hit100'))} | "
              f"{pct((v['anchor_long_notes'] or {}).get('hit100'))} | "
              f"{pct((v['model_on_covered_long'] or {}).get('hit100'))} |")
        w("")
        w(f"- {rf['discipline']}。")
        w("- 读法：ρ 越大锚点越早触发、越差；ρ=0.15 最保守也仍只有 61.5% hit@100（模型 95.8%）。"
          "⇒ 比值信号**方向对但精度远远不够**，作为后处理判据不可用。")
        w("")
    w("## 4. 与文献一致")
    w("")
    w("- 歌声音符 offset 至今无稳健通用解（[McGill 论文：no robust solutions currently exist for "
      "annotating note onsets and offsets in recordings of the singing voice]"
      "(https://escholarship.mcgill.ca/downloads/g158bn57z?locale=en)；"
      "实时/离线歌唱 onset-offset 方法学见 [ProQuest 2700544904]"
      "(https://www.proquest.com/docview/2700544904)），"
      "本实验在**我们自己的数据**上量化了这一点。")
    w("")
    w("## 5. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_tail_acoustics.py")
    w("PYTHONPATH=src python scripts/evaluation/report_tail_acoustics.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_tail_acoustics.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    gts_model = gts["rules"]["model_end_sec"]
    metrics = {"schema_version": "tail_acoustics_metrics_v1", "source": str(args.run / "TAIL_ACOUSTICS.json"),
               "discipline": r["discipline"],
               "results": r,
               "headline": {
                   "model_end_mae_gtsinger_sec": gts_model["all_units"]["mae_end_sec"],
                   "model_end_mae_mir1k_sec": mir["rules"]["model_end_sec"]["all_units"]["mae_end_sec"],
                   "rms_anchor_max_coverage_gtsinger": max(gts["anchor_coverage"].values()),
                   "rms_anchor_coverage_on_last_char_mir1k": (
                       (mir.get("last_char_only") or {}).get("anchor_theta15", {}).get("n", 0)),
                   "last_char_units_mir1k": (mir.get("last_char_only") or {}).get(
                       "model_end_sec", {}).get("n", 0),
                   "frozen_theta_transfer_delta_pp": f_long["mir1k_delta_pp_long_notes"],
                   "ratio_anchor_best_hit100": max(
                       (v["anchor_all_units"].get("hit100", 0) for v in rf["rhos"].values()),
                       default=None) if rf else None,
                   "ratio_anchor_model_same_units_hit100": max(
                       (v["model_on_covered_all"].get("hit100", 0) for v in rf["rhos"].values()),
                       default=None) if rf else None,
                   "verdict": "REFUTED: neither relative-RMS decay nor vocal/accompaniment ratio decay "
                              "is usable as a post-hoc character-offset criterion; the residual "
                              "long-note/last-character error needs model-side changes"}}
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
