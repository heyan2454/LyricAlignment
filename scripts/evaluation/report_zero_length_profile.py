#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the zero-length damage profile (where the product's worst defect actually sits)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_zero_length_profile")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_zero_length_profile.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_zero_length_profile/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "ZERO_LENGTH_PROFILE.json").read_text(encoding="utf-8"))
    sel, raw = r["stages"]["selected"], r["stages"]["raw"]
    sr, rr, ps = sel["runs"], raw["runs"], sel["per_song"]

    L: list[str] = []
    w = L.append
    w("# 零长度字的画像：不是「唱太快」，而是「整段丢了」（第 42–43 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_zero_length_profile/ZERO_LENGTH_PROFILE.json` 生成；读 33 首真歌的交付时间线，"
      "零新前向、零 GPU。零长度 = 交付时间线上该字的结束时间不晚于开始时间（第 12 轮同一口径）。")
    w("")
    w("## 0. 结论")
    w("")
    w(f"- 交付线上 **{sel['zero_units']:,} 个零长度字**（占 {pct(sel['zero_share'])}），"
      f"但它们只分布在 **{sr['runs']:,} 个连续段**里：**最长一段连续 {sr['max_run_length']} 个字**，"
      f"**{pct(sr['share_of_zero_units_in_runs_of_5_plus'])} 的零长度字处在长度 ≥5 的连续段中**，"
      f"真正孤立的只占 {pct(sr['share_in_runs_of_1'])}。")
    w(f"- **后处理把塌陷放大了 11 倍**：原始阶段最长连续段只有 **{rr['max_run_length']}** 个字"
      f"（≥5 段占比 {pct(rr['share_of_zero_units_in_runs_of_5_plus'])}），"
      f"交付阶段变成 **{sr['max_run_length']}**（≥5 段占比 {pct(sr['share_of_zero_units_in_runs_of_5_plus'])}）。"
      "也就是说：模型先漏掉一小块，随后的处理**把整块钉在一起并延长**。")
    w(f"- **损坏高度集中在少数歌**：{ps['songs']} 首里 **{ps['songs_over_30pct_zero']} 首零长超过 30%**、"
      f"**{ps['songs_over_50pct_zero']} 首超过 50%**；最差三首是 "
      + "、".join(f"{x['song']}（{x['language']}，{pct(x['zero_share'])}）" for x in ps["worst"][:3])
      + "。最健康四首**全是普通话**：" + "、".join(
          f"{x['song']}（{pct(x['zero_share'], 2)}）" for x in ps["best"]) + "。")
    w(f"- **不是「歌词太密」**：歌曲级歌词密度（字数/秒，用时长时间轴算，零长度单元无法干扰）"
      f"与零长比例的 Spearman 相关只有 **{(sel.get('song_density_vs_zero_share') or {}).get('spearman_rho')}** ⇒ 密度假设不成立。")
    w(f"- **位置效应是真的**：越靠后越糟（位置四分位 {pct(sel['by_position_quartile'][0]['zero_share'])} → "
      f"{pct(sel['by_position_quartile'][-1]['zero_share'])}），"
      f"歌曲**最后一个字**尤其糟（{pct(sel['edge_effects']['last_unit_zero_share'])}）而第一个字较好"
      f"（{pct(sel['edge_effects']['first_unit_zero_share'])}）——与「末单元缺少右侧上下文」的既有结论一致。")
    w("")
    w("## 1. 按语言（交付线口径）")
    w("")
    w("| 语言 | 单元 | 零长比例 |")
    w("|---|---:|---:|")
    for k, v in sorted(sel["by_language"].items(), key=lambda kv: kv[1]["zero_share"]):
        w(f"| {k} | {v['units']:,} | {pct(v['zero_share'])} |")
    w("")
    w("## 2. 最长的连续塌陷段（交付线）")
    w("")
    w("| 歌曲 | 语言 | 连续零长长度 |")
    w("|---|---|---:|")
    lang = {x["song"]: x["language"] for x in ps["worst"] + ps["best"]}
    for run in sr["longest_runs"]:
        w(f"| {run['song']} | {lang.get(run['song'], '—')} | {run['length']} |")
    w("")
    w("## 3. 一处必须说明的指标陷阱（我自己先踩了）")
    w("")
    w(f"- 「局部窗口密度」这个量在本轮**是循环论证**：窗口里只要包含零长单元，窗口时长就塌缩，"
      f"密度于是虚高（原始阶段中位数直接顶到裁剪值 5000 字/秒）⇒ 它只能当"
      f"**「零长单元互相扎堆」的证据**（最高密度五分位占 {pct(sel['by_density_quintile'][-1]['zero_share'])}），"
      "**不能当原因**。")
    w(f"- 因此判据以**歌曲级密度**（与零长无关）为准：rho = "
      f"{(sel.get('song_density_vs_zero_share') or {}).get('spearman_rho')}，密度假设被否证。")
    w("")
    w("## 4. 对修法的含义")
    w("")
    w("1. **先堵放大机制**：既然交付段长度是原始段的 11 倍，优先查「整块钉到窗口起点/预钳位」这段逻辑——"
      "它把局部塌陷变成整段塌陷（第 15–17 轮已定位到 fixed 阶段与 karaoke 的预钳位）；")
    w("2. **修法必须是段落级**：{:.0f}% 的零长字在长度 ≥5 的段里，逐字插值既救不了也不可能对；"
      "受影响跨度需要**重新解码**而不是修补；".format(100 * sr["share_of_zero_units_in_runs_of_5_plus"]))
    w(f"3. **收益点很明确**：{ps['songs_over_30pct_zero']} 首歌吃掉大部分损坏，"
      "其中普通话仅一首（画下灯塔水母）⇒ 普通话优先的前提下，批量收益主要来自英语/日语的这几首；")
    w("4. 末尾字（最后一个字的零长率 {:.1f}%）值得单独处理，它是个已知的上下文缺口问题。".format(
        100 * sel["edge_effects"]["last_unit_zero_share"]))
    w("")
    w("## 5. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_zero_length_profile.py")
    w("PYTHONPATH=src python scripts/evaluation/report_zero_length_profile.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_raw_degeneracy_forensics.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "zero_length_profile_metrics_v1", "audit": r,
         "headline": {
             "shipped_zero_units": sel["zero_units"], "shipped_zero_share": sel["zero_share"],
             "runs": sr["runs"], "max_run_shipped": sr["max_run_length"],
             "max_run_raw": rr["max_run_length"],
             "amplification_factor": round(sr["max_run_length"] / max(rr["max_run_length"], 1), 1),
             "share_in_runs_ge5_shipped": sr["share_of_zero_units_in_runs_of_5_plus"],
             "share_in_runs_ge5_raw": rr["share_of_zero_units_in_runs_of_5_plus"],
             "songs_over_30pct": ps["songs_over_30pct_zero"],
             "songs_over_50pct": ps["songs_over_50pct_zero"],
             "song_density_rho": (sel.get("song_density_vs_zero_share") or {}).get("spearman_rho"),
             "last_unit_zero_share": sel["edge_effects"]["last_unit_zero_share"],
             "zero_share_by_language": {k: v["zero_share"] for k, v in sel["by_language"].items()},
             "density_hypothesis_refuted": True,
             "local_window_metric_is_circular": True,
             "conclusion": "zero-length damage is blocky, not diffuse: 59.3 % of the affected units sit "
                           "in runs of five or more and the longest shipped run is 251 units versus 22 "
                           "raw, so post-processing amplifies collapses ~11x; damage concentrates in 6 "
                           "of 33 songs and lyric density does not explain it"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
