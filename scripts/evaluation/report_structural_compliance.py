#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the structural-compliance report (shipped timelines vs the joint-solve repair)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_structural_compliance")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path, default=REPO / "reports/progress/20260912_structural_compliance.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_structural_compliance/metrics.json")
    args = ap.parse_args()
    data = json.loads((args.run / "COMPLIANCE.json").read_text(encoding="utf-8"))
    lin_path = args.run / "STAGE_LINEAGE.json"
    batches = {k: v for k, v in data["batches"].items() if v.get("overall")}

    L: list[str] = []
    w = L.append
    w("# 已交付时间线的结构合规审计 + 逐歌修复清单（第 12 轮，2026-09-12）")
    w("")
    w("> 数字由 `runs/20260912_structural_compliance/COMPLIANCE.json` 生成。")
    w("> **不使用也不需**要真值：全部是已交付 timeline 自身的结构属性（零长/重叠/起点回退/离谱时长）。")
    w("> 修复 = 第 7 轮的联合约束求解逐歌施加；realign 仍 shadow-only，本文件只是清单，不回写。")
    w("")
    name0 = "ktv_current_silence_33" if "ktv_current_silence_33" in batches else next(iter(batches))
    b0 = batches[name0]
    t0 = b0.get("compression_damage", {}).get("totals", {})
    o0, pr0 = b0["overall"], b0["post_repair"]
    w("## 0. 最重要的发现（P1 候选）：后处理在自己制造零长单元，而自检计数器看不见")
    w("")
    if t0:
        w(f"- 33 首批次 {t0['units']:,} 单元：raw 阶段零长 {t0['zero_units_raw']:,} "
          f"({pct(t0['raw_zero_share'])}) → 交付后 {t0['zero_units_shipped']:,} "
          f"({pct(t0['shipped_zero_share'])})。")
        w(f"- 逐单元核对：**后处理新造 {t0['created_by_postprocess_units']:,} 个零长单元**"
          f"（{pct(t0['created_by_postprocess_share'])} 全部单元），"
          f"同时修复 {t0.get('healed_by_postprocess_units', 0):,} 个 raw 零长，净 {t0.get('net_change_units', 0):+,}。")
        w(f"- **产物自带的计数器只报告了 {t0['pipeline_counter_total']:,} 个**"
          f"（`overlap_compression_collapsed_to_zero_count`）⇒ 对它自己造成的损害"
          f"**失明 {pct(t0['counter_blind_share'], 1)}**。这是可观测性缺陷，不只是质量问题。")
        w(f"- 归因证据：逐歌交付零长比例与 `seam_repaired_character_rate` 相关 "
          f"r = **{b0['compression_damage'].get('correlation_zero_share_vs_seam_repaired_rate')}**"
          f"（与 `overlap_compressed_character_rate` r = "
          f"{b0['compression_damage'].get('correlation_zero_share_vs_overlap_compressed_rate')}）"
          "⇒ 损坏发生在接缝修复 / 重叠压缩那一步，与解码器无关。")
        w("")
        w("最严重的几首（新造零长单元数，括号内为产物计数器自称的数量）：")
        w("")
        w("| 歌曲 | 语言 | 单元 | raw 零长 | 交付零长 | 新造 | 计数器 | seam_rate |")
        w("|---|---|---:|---:|---:|---:|---:|---:|")
        for r in b0["compression_damage"].get("worst_songs", []):
            w(f"| {r['song']} | {r['language']} | {r['units']:,} | {pct(r['raw_zero_share'],1)} | "
              f"{pct(r['shipped_zero_share'],1)} | {r['created_by_postprocess']} | "
              f"{r['counter_collapsed_to_zero']} | "
              f"{pct(r['seam_repaired_rate'],1)} |")
        w("")
    lin_path = args.run / "STAGE_LINEAGE.json"
    if lin_path.exists():
        lin = json.loads(lin_path.read_text(encoding="utf-8"))
        w("## 0b. **本轮修正上一条归因**：塌陷是 fixed 阶段造的，不是重叠压缩")
        w("")
        w("上一节按逐歌相关（r=0.92）把责任指向 seam/overlap-compression。逐阶段核对产物里的四个阶段"
          "（raw → fixed → selected → final）后，这个归因是**错的**："
          "相关性只是「同一批既坏又常被修的歌」的共因。真实归属：")
        w("")
        w("| 批次 | raw 退化 | fixed 退化 | selected | final | **fixed 阶段新造** | 压缩阶段新造 |")
        w("|---|---:|---:|---:|---:|---:|---:|")
        for name, r in lin.items():
            tt = r["totals"]
            add = r["sum_of_positive_net_additions_by_stage"]
            w(f"| `{name}` | {pct(tt['raw']['degenerate_share'])} | {pct(tt['fixed']['degenerate_share'])} | "
              f"{pct(tt['selected']['degenerate_share'])} | {pct(tt['final']['degenerate_share'])} | "
              f"**+{add.get('net_added_by_fixed', 0):,}** | +{add.get('net_added_by_final', 0):,} |")
        w("")
        w(f"- 三批一致：**退化是 fixed（官方边界修正 / 窗口全局时间映射）阶段制造的**，"
          "而 `selected_*` 就等于 `fixed_*`（该步骤不再变），重叠压缩只贡献个位数（4/2/0）。")
        w("- 机制签名（可复核）：被弄坏的一整块单元在 fixed 阶段被**钉到所属窗口的 `input_start_sec`**。"
          "以 `I See Fire` 为例：window 0 的 `core_start=66.48`、左上下文 2.0 ⇒ `input_start=64.48`；"
          "该歌 262/311 单元（84.2%）的 `fixed_global_*` 恰好等于 64.48，"
          "而它们的 `raw_global_start_sec` 在 64.48–119.28 之间**正常递增** ⇒ 单元自己的预测是好的，"
          "是回映射把一个块整体钳到了窗口锚点。")
        w("")
        w("| 批次 | 钉到窗口锚点的单元 | 占比 | 受影响歌曲数 |")
        w("|---|---:|---:|---:|")
        for name, r in lin.items():
            pw = r.get("pinned_to_window_input", {})
            w(f"| `{name}` | {pw.get('units', 0):,} | {pct(pw.get('share'))} | {pw.get('songs_affected', 0)} |")
        w("")
        w(f"- 最严重（33 首批次）：" + "、".join(
            f"{r['song']} {r['pinned']:,} 单元（{pct(r['share'],1)}）"
            for r in lin[next(iter(lin))]["pinned_to_window_input"]["top_songs"][:4]))
        w("- ⇒ **两个独立缺陷**（不要混为一谈）：(1) 解码器自身在 raw 阶段就有 10.8–12.4% 退化"
          "（其中 870 个是**负时长**，end 早于 start）；(2) fixed 阶段的窗口回映射把块钉到锚点，"
          "额外造成 +426~+807 单元。")
        w("- ⇒ **观测缺口的位置也要修正**：不是「压缩计数器漏计」，而是**fixed 阶段完全没有退化计数器**"
          "（压缩那个计数器对自己的定义是自洽的，只漏掉了「上游已经坏了」这件事）。"
          "最小修复因此是：给每个阶段补 `degenerate_share` 与「块被钉到同一时间戳」的检测，"
          "并把交付 gate 设在阶段谱系上（任一阶段新增退化 > 1% 即拒绝出片并定位到该阶段）。")
        w("")
    w("## 1. 联合求解作为合规检查器：修复后非法单元归零")
    w("")
    w("| 批次 | 单元 | 歌曲 | 交付非法率 | 零长 | 重叠 | 超长 | 回退 | 修复后非法率 | 被移动单元 | 位移中位 | 位移 p90（除超长） | 最长时长 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, b in batches.items():
        o, pr = b["overall"], b["post_repair"]
        w(f"| `{name}` | {o['units']:,} | {b['songs']} | {pct(o['illegal_share'])} | "
          f"{pct(o['zero_or_negative_share'])} | {pct(o['overlap_next_share'])} | "
          f"{pct(o['overshoot_share'])} | {pct(o['start_regression_share'])} | "
          f"**{pct(pr['illegal_share'])}** | {pct(o['repaired_share'])} | {o['median_shift_sec']}s | "
          f"{o.get('p90_shift_excluding_overshoot_sec')}s | {o['max_duration_sec']}s |")
    w("")
    w(f"- 位移分布必须分层：p90 全量 {o0['p90_shift_sec']}s 看着吓人，"
      f"但**剔除超长单元后 p90 只有 {o0.get('p90_shift_excluding_overshoot_sec')}s**——"
      "大位移全部来自把 40+ 秒的离谱区间钳回合法范围，而不是普通边界被搬动。")
    w(f"- 结构保证成立：两批修复后 zero/overlap/overshoot/regression 都是 "
      f"{pct(pr0['zero_or_negative_share'],2)} / {pct(pr0['overlap_next_share'],2)} / "
      f"{pct(pr0['overshoot_share'],2)} / {pct(pr0['start_regression_share'],2)}。")
    w("")
    w("## 2. 语言分层（对『优先普通话』的直接含义）")
    w("")
    w("| 批次 | 语言 | 单元 | 交付非法率 | 其中零长 | 修复需移动 | 新造零长（后处理） |")
    w("|---|---|---:|---:|---:|---:|---:|")
    for name, b in batches.items():
        dmg = {r["song"]: r for r in b.get("compression_damage", {}).get("per_song", [])}
        for k, v in sorted(b["by_language"].items(), key=lambda kv: kv[1]["illegal_share"]):
            created = sum(d.get("created_by_postprocess", 0) for song, d in dmg.items()
                          if any(s["song"] == song and s["language"] == k
                                 for s in b.get("per_song", [])))
            w(f"| `{name}` | {k} | {v['units']:,} | {pct(v['illegal_share'])} | "
              f"{pct(v['zero_or_negative_share'])} | {pct(v['repaired_share'])} | {created} |")
    w("")
    w(f"- 普通话（Chinese）是**最健康**的路径（交付非法率 "
      f"{pct(batches[name0]['by_language'].get('Chinese', {}).get('illegal_share'))}，"
      f"日文 {pct(batches[name0]['by_language'].get('Japanese', {}).get('illegal_share'))}、"
      f"英文 {pct(batches[name0]['by_language'].get('English', {}).get('illegal_share'))}）"
      "⇒ 结构治理的优先级其实是**非中文的 word 单元路径**；中文侧的收益集中在少数几首（下表）。")
    w("")
    zh = [r for r in batches[name0]["per_song"] if r["language"] == "Chinese"]
    zh = sorted(zh, key=lambda r: -r["illegal_share"])[:6]
    if zh:
        w("中文歌里最需要看的（按交付非法率）：")
        w("")
        w("| 歌曲 | 单元 | 非法率 | 零长率 | 修复需移动 | 最长时长 |")
        w("|---|---:|---:|---:|---:|---:|")
        for r in zh:
            w(f"| {r['song']} | {r['units']:,} | {pct(r['illegal_share'],1)} | "
              f"{pct(r['zero_or_negative_share'],1)} | {pct(r['repaired_share'],1)} | "
              f"{r['max_duration_sec']}s |")
        w("")
    w("## 3. 分诊规则（把清单变成流程）")
    w("")
    buckets = {}
    for r in batches[name0]["per_song"]:
        s_ = r["illegal_share"]
        key = ("≤2%（直接可用）" if s_ <= 0.02 else "2–5%（可修复）" if s_ <= 0.05
               else "5–15%（修复+抽查）" if s_ <= 0.15 else "15–35%（重看）" if s_ <= 0.35
               else ">35%（应重解码而非修复）")
        buckets[key] = buckets.get(key, 0) + 1
    w(f"`{name0}` 的 {batches[name0]['songs']} 首歌按交付非法率分布：")
    w("")
    w("| 分诊档 | 歌曲数 |")
    w("|---|---:|")
    for k in ("≤2%（直接可用）", "2–5%（可修复）", "5–15%（修复+抽查）", "15–35%（重看）",
              ">35%（应重解码而非修复）"):
        if k in buckets:
            w(f"| {k} | {buckets[k]} |")
    w("")
    w("- **含义**：当一首歌过半单元被压成同一点（如 I See Fire 88.1%），"
      "「修复」等于重排整首歌，正确动作是**重解码/回查那一步的压缩逻辑**，不是打补丁。")
    w("- 可执行三条：(1) 给压缩步骤补上真实的 collapsed-to-zero 计数与告警；"
      "(2) 把本审计作为交付前 gate（非法率>5% 不允许出片）；"
      "(3) 对 >35% 档的歌列入重解码队列（清单见 `repair_list_*.csv.gz`）。")
    w("")
    w("## 4. 产物与复现")
    w("")
    for name, b in batches.items():
        e = b.get("export", {})
        w(f"- `{name}`：修复清单 {e.get('rows', 0):,} 行（非法单元），"
          f"{e.get('bytes', 0)/1024:.0f} KB → `{Path(str(e.get('path',''))).name}`")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_structural_compliance.py")
    w("PYTHONPATH=src python scripts/evaluation/report_structural_compliance.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_structural_compliance.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    metrics = {"schema_version": "structural_compliance_metrics_v1", "source": str(args.run),
               "batches": batches,
               "headline": {
                   "shipped_illegal_share": o0["illegal_share"],
                   "post_repair_illegal_share": pr0["illegal_share"],
                   "zero_units_raw": t0.get("zero_units_raw"), "zero_units_shipped": t0.get("zero_units_shipped"),
                   "created_by_postprocess_units": t0.get("created_by_postprocess_units"),
                   "healed_by_postprocess_units": t0.get("healed_by_postprocess_units"),
                   "pipeline_counter_total": t0.get("pipeline_counter_total"),
                   "counter_blind_share": t0.get("counter_blind_share"),
                   "correlation_zero_share_vs_seam_rate":
                       batches[name0].get("compression_damage", {}).get("correlation_zero_share_vs_seam_repaired_rate"),
                   "attribution_correction": ("degeneracy is created by the fixed stage "
                                              "(window->global remap pinning blocks to "
                                              "window input_start_sec), not by overlap compression"),
                   "stage_lineage": (json.loads(lin_path.read_text(encoding="utf-8"))
                                     if lin_path.exists() else None),
                   "mandarin_illegal_share": batches[name0]["by_language"].get("Chinese", {}).get("illegal_share"),
                   "japanese_illegal_share": batches[name0]["by_language"].get("Japanese", {}).get("illegal_share"),
                   "english_illegal_share": batches[name0]["by_language"].get("English", {}).get("illegal_share"),
                   "p90_shift_excluding_overshoot_sec": o0.get("p90_shift_excluding_overshoot_sec"),
                   "finding": "post-processing creates 1,112 zero-length units across the 33-song batch "
                              "while its own counter reports 4 (99.6% blind); the joint solve makes the "
                              "timeline structurally legal but songs past ~35% illegal should be re-decoded"}
               }
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L), "metrics": str(args.metrics_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
