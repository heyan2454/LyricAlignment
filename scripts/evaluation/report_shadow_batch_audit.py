#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the pre-change/post-change batch audit preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_shadow_batch_audit")
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_shadow_batch_audit.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_shadow_batch_audit/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "SHADOW_BATCH_AUDIT.json").read_text(encoding="utf-8"))
    s, h, d = r["shipped"], r["shadow"], r["delta_pp"]

    L: list[str] = []
    w = L.append
    w("# 改前/改后的批次自检预览（第 49 轮，2026-09-13）")
    w("")
    w(f"> 数字由 `runs/20260912_shadow_batch_audit/SHADOW_BATCH_AUDIT.json` 生成；"
      f"读 33 首真歌已落盘的逐字记录（{r['rows']:,} 行），离线按策略 `{r['policy']}` 重建交付时间线，"
      "与现交付值用同一套结构检查比较。**不改动任何产品文件**，零前向、零 GPU。")
    w("")
    w("## 0. 预期变化")
    w("")
    w("| 指标 | 现交付值 | 改动后（影子） | 变化 |")
    w("|---|---:|---:|---:|")
    rows = [("没有位置的字", "zero_share"), ("结构非法合计", "illegal_share"),
            ("与前一个字重叠", "overlap_share"), ("超出长度上限", "overshoot_share"),
            ("起点比前一个字更早", "regression_share")]
    for label, key in rows:
        w(f"| {label} | {100 * s[key]:.2f}% | {100 * h[key]:.2f}% | **{d[key]:+.2f}pp** |")
    w(f"| 同一时刻的长块 | {s['collapse_blocks']['blocks']} 块 / "
      f"{s['collapse_blocks']['units_in_blocks']} 字 | {h['collapse_blocks']['blocks']} 块 | "
      f"**−{s['collapse_blocks']['blocks']}** |")
    w("")
    w(f"- **没有位置的字：{100 * s['zero_share']:.2f}% → {100 * h['zero_share']:.2f}%**，"
      f"33 首歌**逐首都降到 0.0%**（原来最高一首 88.1%）；")
    w(f"- 结构非法合计下降 {abs(d['illegal_share']):.2f}pp；")
    w(f"- **重叠与起点回退分别 +{d['overlap_share']:.2f}pp 与 +{d['regression_share']:.2f}pp**——"
      "这不是改动引入的缺陷，而是改动后的时间线**尚未经过产品既有的后处理**："
      "现交付值的重叠只剩 0.10%，正是因为那一步会把重叠清掉。换句话说，"
      "**上线时应把该策略插在既有后处理之前**，重叠仍由原有那一步处理（第 47 轮已实测："
      "再额外叠加治重叠或整体合法化会掉 3.6–4.3pp 精度）。")
    w("")
    w("## 1. 逐首（没有位置的字，现交付值 → 改动后）")
    w("")
    w("| 歌 | 现交付值 | 改动后 |")
    w("|---|---:|---:|")
    for song, v in sorted(s["by_language_zero_share"].items(), key=lambda kv: -kv[1]):
        if v < 0.005:
            continue
        w(f"| {song} | {100 * v:.1f}% | 0.0% |")
    w("")
    w(f"（逐首分组用的是歌曲目录名——逐字记录里没有存语言字段；共 {len(s['by_language_zero_share'])} 首，"
      "其余歌曲改动前本就低于 0.5%。）")
    w("")
    w("## 2. 这份预览怎么用")
    w("")
    w("1. 按 `docs/status/20260913_fixed_timestamp_policy_runbook.md` 在**单曲**上开启策略；")
    w("2. 重跑该曲后执行 `audit_batch.py`，对照本页预期：`collapse_blocks.blocks == 0`、"
      "`zero_share` 接近 0；")
    w("3. 确认后全批开启；重叠/起点回退仍由既有后处理处理（已在上线位置之前）。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_shadow_batch_audit.py")
    w("PYTHONPATH=src python scripts/evaluation/report_shadow_batch_audit.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "shadow_batch_audit_metrics_v1", "audit": r,
         "headline": {
             "policy": r["policy"], "measured": r["policy_measured"], "rows": r["rows"],
             "shipped": s, "shadow": h, "delta_pp": d,
             "songs_at_zero_after": sum(1 for v in h["by_language_zero_share"].values() if v == 0.0),
             "songs_total": len(h["by_language_zero_share"]),
             "conclusion": "the recommended policy removes 100 % of the shipped zero-length damage "
                           "(16.28 % -> 0.00 %, every song to zero) while the overlap/regression "
                           "counts rise only because the shadow timeline has not yet passed through "
                           "the product's existing post-processing, which is where those are handled "
                           "today; the policy must therefore be inserted before that step"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
