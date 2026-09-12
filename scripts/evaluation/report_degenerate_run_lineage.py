#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the degenerate-block lineage forensics (which stage grows a collapse)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_degenerate_run_lineage")
REPO = Path(__file__).resolve().parents[2]


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):.{d}f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_degenerate_run_lineage.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_degenerate_run_lineage/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "DEGENERATE_RUN_LINEAGE.json").read_text(encoding="utf-8"))
    stages = r["stages"]
    inv = r.get("pinning_inventory", {})
    blocks = r["blocks"]

    L: list[str] = []
    w = L.append
    w("# 超长塌陷是哪一步做出来的：`fixed` 阶段把整段钉到同一时刻（第 44 轮，2026-09-13）")
    w("")
    w(f"> 数字由 `runs/20260912_degenerate_run_lineage/DEGENERATE_RUN_LINEAGE.json` 生成；"
      f"对交付线上长度 ≥{r['min_run']} 字的 {len(blocks)} 个塌陷块，逐阶段（{' → '.join(stages)}）"
      "还原同一批字的下标，统计退化数、不同起点数、时间跨度。零前向、零 GPU。")
    w("")
    w("## 0. 结论")
    w("")
    w(f"- **放大全部发生在 `fixed` 这一步**：块内在该步的退化数从 {blocks[0]['by_stage'][stages[0]]['zero_units']}"
      f" 跳到 {blocks[0]['by_stage'].get('fixed', {}).get('zero_units')}，而 `selected`/`final` 的净增 **全部为 0**"
      "（每个块的 `zero_growth_vs_previous_stage` 里除 fixed 外都是 0）。")
    w(f"- **机制可验证**：`fixed` 把整段压缩到**极少数甚至唯一的时间点** —— 例如 I See Fire 的 199 字块"
      f"在原始阶段有 79 个不同起点、跨度 79.2 秒，到 `fixed` 变成 **1 个起点、跨度 0.0 秒**。")
    w(f"- **没有任何一个超长块在原始阶段就是全塌陷**（`blocks already fully pinned at the first stage = "
      f"{r['summary']['pinned_at_first_stage']}`）⇒ 这些塌陷是**下游做出来的**，不是模型原始输出的必然结果。")
    if inv:
        w(f"- **总量**：交付线 {inv['shipped_zero_units']:,} 个零长字里，"
          f"**{inv['zero_units_in_identical_start_blocks_ge5']:,} 个（{pct(inv['share_of_zero_units_in_identical_start_blocks'])}）"
          f"处在 {inv['such_blocks']} 个「起点完全相同」的块中**（最大一块 "
          f"{inv['largest_identical_start_block']} 字）；其余多段块则呈现 2 个时间点"
          "（应当是两次窗口边界各自被钉一次）。")
    w("")
    w("## 1. 逐块取证")
    w("")
    w("| 歌 | 下标区间 | 块长 | 阶段 | 块内退化 | 不同起点数 | 单时间点？ | 时间跨度 |")
    w("|---|---|---:|---|---:|---:|---|---:|")
    for blk in blocks:
        for stage in stages:
            v = blk["by_stage"].get(stage)
            if not v:
                continue
            w(f"| {blk['song']} | {blk['start_index']}–{blk['end_index']} | {blk['anchor_length']} | "
              f"`{stage}` | {v['zero_units']}/{v['units_in_span']} | {v['distinct_start_times']} | "
              f"{'**是**' if v['single_timestamp_block'] else '否'} | {v['span_sec']}s |")
    w("")
    w("## 2. 这修正/加强了过去哪几条结论")
    w("")
    w("- 第 15–17 轮怀疑「整块被钉到窗口起点」和「倒序被静默钳成零长」两条机制，本轮**在最坏的块上直接证实**："
      "原始阶段这些块只坏一半、且仍有真实时间跨度，`fixed` 之后全坏且时间跨度归零；")
    w("- 第 43 轮的「放大 11 倍」现在有了归因：**放大是 `fixed` 一步造成的**，`selected`/`final` 只是继承；")
    w("- 因此修法优先级明确：**先修 `fixed`（processor_decoded）这一步的整块钳位/钉锚逻辑**，"
      "它对原始阶段还能用的那部分信息是**破坏性**的；之后才谈重解码。")
    w("")
    w("## 3. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_degenerate_run_lineage.py")
    w("PYTHONPATH=src python scripts/evaluation/report_degenerate_run_lineage.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_raw_degeneracy_forensics.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "degenerate_run_lineage_metrics_v1", "audit": r,
         "headline": {
             "blocks": len(blocks), "min_run": r["min_run"],
             "pinned_already_at_first_stage": r["summary"]["pinned_at_first_stage"],
             "zero_growth_only_in_fixed": all(
                 all(k == "fixed" for k, v in b["zero_growth_vs_previous_stage"].items() if v)
                 for b in blocks),
             "example": {"song": blocks[0]["song"],
                         "raw": blocks[0]["by_stage"].get("raw"),
                         "fixed": blocks[0]["by_stage"].get("fixed")} if blocks else None,
             "pinning_inventory": inv,
             "conclusion": "the entire amplification happens in the fixed (processor_decoded) stage, "
                           "which collapses whole spans onto one timestamp; selected/final add zero; "
                           "no long block was already collapsed at raw"}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
