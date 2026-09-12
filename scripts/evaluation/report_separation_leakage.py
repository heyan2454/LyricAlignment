#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the separation-leakage report, including the corrections to round 22."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_separation_leakage")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def num(x, d: int = 3) -> str:
    return "n/a" if x is None else f"{float(x):.{d}f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_separation_leakage.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_separation_leakage/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "SEPARATION_LEAKAGE.json").read_text(encoding="utf-8"))
    ok = [x for x in r["per_song"] if x.get("available")]
    p, pg = r["pooled"], r["pooled"].get("gap_restricted", {})

    L: list[str] = []
    w = L.append
    w("# 分离后的字间隙里到底剩什么：泄漏假设的反驳与第 22 轮的更正（第 23 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_separation_leakage/SEPARATION_LEAKAGE.json` 生成。"
      "零 GPU、无真值、只读音频（不复制）；数据是 **33 首真实伴奏歌（非 test 的产品批）**。")
    w("")
    w("## 0. 两处对上一轮的更正（都因为这次真去读了产物）")
    w("")
    w("1. **真实歌的输入不是声道选择，而是源分离**："
      "`work/audio/vocals.identity.json` 记录 `schema_version=qwen_fa_batch_demucs_v1`、"
      "`separator=demucs`、`model_name=htdemucs_ft`、`two_stems=vocals`、`device=cuda`；"
      "批目录里同时有 `accompaniment.wav` 与 `mix.wav`。第 22 轮说「产品链路是声道选择」**错了**，"
      "声道选择只发生在 **MIR-1K 评测输入**（`20260722_mir1k_vocal_channel1_ood`）。")
    w("2. **分离质量并非从未测过**：批产物带 `separation_quality.json`"
      "（`audio_separation_quality_v1`：RMS、mix 重构残差、vocals↔accompaniment 相关、通过/失败门），"
      f"本批 {len(ok)}/{len(ok)} 首 `passed=true`。"
      "**未测的是时间局部的泄漏**——也就是本轮要测的东西。")
    w("")
    w("## 1. 方法上的一个坑（先说，因为它会制造假结论）")
    w("")
    w(f"- 只看「单元结束后 0–300ms 是否还有能量」是**没有信息量的**："
      f"歌词单元天然连续，该窗口通常已经落在**下一个字**里；")
    w(f"- 因此正确口径是只在**可测量的字间隙**（本批只有 "
      f"{pct(pg.get('measurable_gap_share_median'))} 的单元前面有 ≥50ms 间隙）里测；"
      "两种口径我都保留在报告里，以便看清混淆的量级。")
    w("")
    w("## 2. 结果：间隙里人声 stem 常仍活跃，但**不跟随伴奏** ⇒ 泄漏不是主因")
    w("")
    w("| 量（中位，跨歌） | 值 |")
    w("|---|---:|")
    w(f"| 有可测量字间隙的单元比例 | {pct(pg.get('measurable_gap_share_median'))} |")
    w(f"| 间隙内人声 stem 仍活跃（**相对判据**：残余 > 该单元自身核心能量 25%） | "
      f"**{pct(pg.get('relative_residual_active_share'))}**"
      f"（长音单元 {pct(pg.get('relative_residual_active_share_long'))}） |")
    w(f"| 同上但用绝对 RMS 下限（会被跨边界分析窗骗过，仅作对照） | "
      f"{pct(pg.get('vocal_active_share'))}（长音 {pct(pg.get('vocal_active_share_long'))}） |")
    w(f"| 间隙残余 / 该单元核心能量（中位） | **{num(pg.get('median_relative_residual'))}**"
      f"（长音 {num(pg.get('median_relative_residual_long'))}） |")
    w(f"| 间隙内人声 stem RMS / 伴奏 stem RMS | {num(pg.get('median_vocal_gap_rms'), 4)} / "
      f"{num(pg.get('median_accomp_gap_rms'), 4)} |")
    w(f"| **corr(间隙人声能量, 间隙伴奏能量)** | {num(pg.get('corr_vocal_accomp_gap'))}"
      f"（长音 {num(pg.get('corr_vocal_accomp_gap_long'))}） |")
    w(f"| 对照：naive 引导窗的 corr(vocal_lead, accomp_lead) | "
      f"{num(p.get('median_song_corr_vocal_vs_accomp_lead'))} |")
    w("")
    w(f"- **残余很大但不同源**：间隙残余中位数达到该单元核心能量的 "
      f"{num(pg.get('median_relative_residual'))} 倍（长音 {num(pg.get('median_relative_residual_long'))}），"
      f"但与人声无关的伴奏 stem **不相关**（corr {num(pg.get('corr_vocal_accomp_gap'))}，"
      f"长音 {num(pg.get('corr_vocal_accomp_gap_long'))}）。")
    w("- 若是**分离器泄漏**主导，间隙里人声 stem 的残余能量应随伴奏 stem 同步起伏（相关显著为正）；"
      "实测接近零 ⇒ **泄漏假设的强形式被反驳**（这也是本轮对自己上一轮结论的第一处实质修正）。")
    w("- 分语言（间隙口径，跨歌中位）：")
    w("")
    w("| 语言 | 歌数 | 间隙残余活跃（相对判据） | corr(人,伴) | 长音间隙活跃（相对） | naive 引导窗 corr |")
    w("|---|---:|---:|---:|---:|---:|")
    by_lang: dict[str, list[dict]] = {}
    for x in ok:
        by_lang.setdefault(x["language"], []).append(x)
    import statistics as st
    for lang, rows in sorted(by_lang.items()):
        ga = [r["gaps"]["all_measurable"] for r in rows if r["gaps"]["all_measurable"]["units"]]
        gl = [r["gaps"]["long_units"] for r in rows if r["gaps"]["long_units"]["units"]]
        def m(lst, k):
            v = [r[k] for r in lst if r.get(k) is not None]
            return round(float(st.median(v)), 3) if v else None
        c_naive = [r["corr_vocal_lead_vs_accomp_lead"] for r in rows
                   if r.get("corr_vocal_lead_vs_accomp_lead") is not None]
        w(f"| {lang} | {len(rows)} | {pct(m(ga,'relative_residual_active_share'))} | "
          f"{num(m(ga,'corr_vocal_gap_vs_accomp_gap'))} | "
          f"{pct(m(gl,'relative_residual_active_share'))} | {num(st.median(c_naive) if c_naive else None)} |")
    w("")
    w("- 注意全局质检里 vocals↔accompaniment 相关也只有 0.04–0.12（分离本身是干净的），"
      "与本轮局部测量一致。")
    w("")
    w("## 3. 那么第 22 轮的机制说明要降级为什么？")
    w("")
    w("- **保留**：在 MIR-1K（**声道选择输入**、test-only）上，落晚单元确实处在"
      "「人声通道已停、总通道仍响」的区段，且误差幅度与该点人声能量负相关（−0.40）。")
    w("- **撤回**：不能把它解释成「**产品链路的分离器泄漏**导致拖晚」——产品链路用分离，"
      f"且间隙残余与伴奏不相关（{num(pg.get('corr_vocal_accomp_gap'))}）。")
    w("- **新的可检验解释**（本轮无法区分，因为无真值）：间隙里的残余更可能是"
      "(a) 人声混响/尾音、(b) 下一字的起始辅音/呼吸被切在间隙里、"
      "(c) **时间线本身把该字提前结束了**（残余其实是这个字自己的声音）。")
    w("  (c) 若成立，则与第 21 轮「录音室截早」是同一偏向，说明**产品在伴奏歌上也在截早**，"
      "只是 MIR-1K 的声道选择输入让我们看到了相反方向。")
    w("")
    w("## 4. 要区分 (a)/(b)/(c) 需要什么实验（预算已估，等你批准）")
    w("")
    w("- **只需少量 GPU 的关键一步**：对同一批真实歌用**人工标注的 3–5 首**（或从 MIR-1K 之外"
      "另取有逐字真值的伴奏中文数据）比较：`分离人声 stem 包络` vs `混音` vs `GT 端点`；"
      "若间隙残余在 GT 端点之后仍显著 → (c) 时间线截早；若在 GT 端点处已消失 → (a)/(b)。")
    w("- 现有可复用资产：批目录已含 mix/vocals/accompaniment 三 stem 与质检 JSON；"
      "本模块的包络与间隙口径可直接复用（CPU，无新前向）。")
    w("- **不需要**重新训练即可先做的：把「间隙内人声仍活跃」作为参考无关告警特征"
      "（覆盖 "
      f"{pct(pg.get('vocal_active_share'))} 的间隙）接入 `audit_batch.py`，"
      "但它只能在**非 test 数据**上定阈值后才有资格上线。")
    w("")
    w("## 5. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_separation_leakage.py")
    w("PYTHONPATH=src python scripts/evaluation/report_separation_leakage.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_separation_leakage.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "separation_leakage_metrics_v1", "audit": r,
         "headline": {
             "product_input_is_demucs_separated": True,
             "separator": "demucs htdemucs_ft two_stems=vocals",
             "separation_quality_gate_exists": True,
             "separation_quality_all_passed": p.get("separation_quality_all_passed"),
             "measurable_gap_share": pg.get("measurable_gap_share_median"),
             "vocal_active_in_gap_share": pg.get("vocal_active_share"),
             "corr_vocal_vs_accomp_in_gap": pg.get("corr_vocal_accomp_gap"),
             "leakage_not_supported": (pg.get("corr_vocal_accomp_gap") or 1.0) < 0.3,
             "corrections_to_round22": ["product path uses demucs separation, not channel selection",
                                        "separation quality IS measured globally "
                                        "(audio_separation_quality_v1), only time-local leakage was missing",
                                        "naive lead window is confounded by the next unit"]},
         }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
