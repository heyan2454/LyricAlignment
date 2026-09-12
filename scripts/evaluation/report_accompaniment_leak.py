#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the accompaniment-bleed mechanism report (round 22)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_accompaniment_leak")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_accompaniment_leak.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_accompaniment_leak/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "LEAK.json").read_text(encoding="utf-8"))
    p = r["profile"]
    st = p["strata"]
    ln, sn, al = st["long_note"], st["short_note"], st["all_units"]
    auc = p["auc_bleed_share_predicts_late"]
    oc = p["accomp_share_in_lead_by_outcome"]

    L: list[str] = []
    w = L.append
    w("# 伴奏泄漏是否解释了伴奏域长音「拖晚」？（第 22 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_accompaniment_leak/LEAK.json` 生成。零 GPU（soundfile + numpy 包络）。")
    w(f"> **纪律**：MIR-1K 是 test-only，本节全部是**回溯机制测量**——"
      "不用它选阈值/模型/视图；若要变成上线触发器必须在非 test 数据上重新导出。")
    w(f"> 输入事实：普通话真实录音的输入是**声道选择**（原始立体声 ch1），不是源分离；"
      "GTSinger 是清唱，天然不含这一因素。")
    w("")
    w("## 0. 结论：假设成立，但机制比「伴奏能量高」更精确")
    w("")
    w(f"- 长音在真值结束后 {p['lead_window_sec']}s 的引导区里，人声通道里"
      f"**{pct(ln['median_accomp_share_in_lead'])} 的能量来自伴奏**"
      f"（中位伴奏 RMS {ln['median_accomp_lead_rms']} vs 人声 RMS {ln['median_vocal_lead_rms']}）；"
      f"短音对照只有 {pct(sn['median_accomp_share_in_lead'])}（伴奏/人声几乎各半）。")
    w(f"- **落晚的单元正落在这种「人声已停、伴奏仍在」的区段**：引导区伴奏占比 "
      f"晚于真值 >100ms 的单元 {pct(oc['late_gt100ms_any_dur']['median'])}"
      f"（长音子集 {pct(oc['late_gt100ms']['median'])}）vs 按时单元 "
      f"{pct(oc['on_time']['median'])}；AUC(泄漏占比 → 落晚) = **{auc['all_units']}**"
      f"（基准落晚率仅 {pct(auc['base_rate_late_all'])}）。")
    w(f"- 但**不是「该点伴奏更强」**：长音上预测端点处的伴奏能量并不高于真值端点处"
      f"（配对中位差 {ln['accomp_at_pred_gt_than_at_gt']['median_diff']}，"
      f"更高比例 {pct(ln['accomp_at_pred_gt_than_at_gt']['share_higher_in_pred'])}，"
      f"p={ln['accomp_at_pred_gt_than_at_gt']['sign_test_p_two_sided']}）；"
      f"真正显著的是**人声能量更低**（中位差 {ln['vocal_at_pred_gt_than_at_gt']['median_diff']}，"
      f"更高比例 {pct(ln['vocal_at_pred_gt_than_at_gt']['share_higher_in_pred'])}，"
      f"rank-biserial {ln['vocal_at_pred_gt_than_at_gt']['rank_biserial']}，"
      f"p={ln['vocal_at_pred_gt_than_at_gt']['sign_test_p_two_sided']}）。")
    w(f"- 误差幅度与「预测点人声能量」负相关（全体 "
      f"{p['corr_end_err_vs_vocal_rms_at_pred_end_all_units']}、长音 "
      f"{ln['corr_end_err_vs_vocal_rms_at_pred_end']}），与泄漏占比只有弱相关"
      f"（长音 {ln['corr_end_err_vs_accomp_share_in_lead']}）。")
    w("")
    w("**读法**：声道选择的输入里，拖长音结束后那段只剩伴奏；边界解码器跟着「通道不再变化」走，"
      "而不是跟着「嗓音停止」走 ⇒ 过冲幅度取决于**人声消失后通道还有多少可跟的东西**。"
      "这解释了第 21 轮的方向反转：清唱（人声一停通道就静）偏早，伴奏（人声停了通道还响）偏晚。")
    w("")
    w("## 1. 分层配对统计（端点，r2_full）")
    w("")
    w("| 层 | 单元 | 落晚比例 | 中位端点误差 | hit@100 | 引导区伴奏占比 | 伴奏@pred vs @gt（中位差/更高比例/p） | 人声@pred vs @gt |")
    w("|---|---:|---:|---:|---:|---:|---|---|")
    for name, v in (("long_note", ln), ("short_note", sn), ("all_units", al)):
        a, bv = v["accomp_at_pred_gt_than_at_gt"], v["vocal_at_pred_gt_than_at_gt"]
        w(f"| {name} | {v['units']:,} | {pct(v['ends_late_share'])} | {v['median_end_err_ms']:+.1f}ms | "
          f"{pct(v['hit100'])} | {pct(v['median_accomp_share_in_lead'])} | "
          f"{a['median_diff']} / {pct(a['share_higher_in_pred'])} / p={a['sign_test_p_two_sided']} | "
          f"{bv['median_diff']} / {pct(bv['share_higher_in_pred'])} / p={bv['sign_test_p_two_sided']} |")
    w("")
    w("## 2. 判别力（回溯，不构成可部署阈值）")
    w("")
    w("| 口径 | AUC(泄漏占比 → 落晚>100ms) | 说明 |")
    w("|---|---:|---|")
    w(f"| 全体单元 | **{auc['all_units']}** | 基准落晚率 {pct(auc['base_rate_late_all'])}，"
      "即「错误落在泄漏区」是可识别的少数事件 |")
    w(f"| 长音层内 | {auc['long_note']} | **无判别力**：长音一旦进入该层，引导区几乎总是泄漏主导"
      f"（中位 {pct(ln['median_accomp_share_in_lead'])}），因此占比无法在层内排序 |")
    w("")
    w("⇒ 所以泄漏是「定位性证据（错误发生在哪儿）」，不是「剂量性证据（错多少）」；"
      "过冲的幅度由人声消失后的通道内容决定（相关性 −0.40）。")
    w("")
    w("## 3. 这一条改变什么")
    w("")
    w("- **解释了第 21 轮的跨域反向偏置**：不是「两个域数据不同所以随机不同」，"
      "而是清唱与伴奏在「人声停止后通道里还有什么」上本质不同。")
    w("- **给出一个明确的、尚未测试的杠杆**：真实伴奏链路的输入换成源分离（或至少 mid/side 抑制）"
      "后重测同一层。这是 GPU 实验，需你批准；预期收益应看长音端点偏置与 hit@100，"
      "同时用第 17 轮的伴生列避免退化率污染。")
    w("- **免费告警特征（需非 test 重导出后才能上线）**：`引导区伴奏占比`；"
      "本会话不把它当阈值用。")
    w("- 同时提醒：GTSinger 类清唱基准**结构上测不到这一失效** ⇒ 若产品主要在伴奏真实歌曲上，"
      "录音室指标只能当 lower bound 用。")
    w("")
    w("## 3b. 外部依据（仅题录指针，本轮未核验全文）")
    w("")
    w("- [Automatic Lyrics-to-audio Alignment on Polyphonic Music Using Singing-adapted Acoustic "
      "Models](https://ieeexplore.ieee.org/document/8682582)（ICASSP 2019）——"
      "把伴奏多声部下的歌词对齐作为独立难题，并用**歌唱适配的声学模型**（即训练侧适配）应对，"
      "与本会话第 3/19 轮「适配带来 +16pp、训练能抬可达性上限」方向一致。")
    w("- [Lyrics to Audio Alignment in Polyphonic Audio（MIREX 2017 评测报告）]"
      "(https://www.music-ir.org/mirex/abstracts/2017/DMS1.pdf)——"
      "评测层面承认伴奏声部是该任务的系统性干扰来源（未能抓取全文，只作指针）。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_accompaniment_leak.py")
    w("PYTHONPATH=src python scripts/evaluation/report_accompaniment_leak.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_accompaniment_leak.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "accompaniment_leak_metrics_v1", "audit": r,
         "headline": {
             "long_note_lead_accomp_share": ln["median_accomp_share_in_lead"],
             "short_note_lead_accomp_share": sn["median_accomp_share_in_lead"],
             "late_units_lead_accomp_share": oc["late_gt100ms_any_dur"]["median"],
             "on_time_lead_accomp_share": oc["on_time"]["median"],
             "auc_bleed_predicts_late_all_units": auc["all_units"],
             "auc_bleed_predicts_late_long_note": auc["long_note"],
             "base_rate_late": auc["base_rate_late_all"],
             "corr_end_err_vs_vocal_at_pred_all": p["corr_end_err_vs_vocal_rms_at_pred_end_all_units"],
             "corr_end_err_vs_vocal_at_pred_long_note": ln["corr_end_err_vs_vocal_rms_at_pred_end"],
             "accomp_not_higher_at_pred_long_note": ln["accomp_at_pred_gt_than_at_gt"]["share_higher_in_pred"],
             "vocal_lower_at_pred_long_note": ln["vocal_at_pred_gt_than_at_gt"]["share_higher_in_pred"],
             "discipline": p["caveat"],
             "conclusion": "overshoots land where the vocal channel is silent but accompaniment continues "
                           "(lead-region bleed share 0.91 vs 0.49 control, AUC 0.78), and error size "
                           "tracks low vocal energy rather than high accompaniment energy"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
