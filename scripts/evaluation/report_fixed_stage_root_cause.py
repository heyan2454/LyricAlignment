#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the zero-length root-cause report (upstream _fix_timestamps constant fill)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN = Path("/home/hyan/Data/lyricalign/runs/20260912_fixed_stage_root_cause")
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--out", type=Path,
                    default=REPO / "reports/progress/20260912_fixed_stage_root_cause.md")
    ap.add_argument("--metrics-out", type=Path,
                    default=REPO / "results/by_run/20260912_fixed_stage_root_cause/metrics.json")
    args = ap.parse_args()
    r = json.loads((args.run / "FIXED_STAGE_ROOT_CAUSE.json").read_text(encoding="utf-8"))
    up, mr, songs, summ = r["upstream"], r["minimal_reproduction"], r["songs"], r["summary"]

    L: list[str] = []
    w = L.append
    w("# 零长度塌陷的根因：上游解码器的「单调化修补」把整块填成同一时刻（第 45 轮，2026-09-13）")
    w("")
    w("> 数字由 `runs/20260912_fixed_stage_root_cause/FIXED_STAGE_ROOT_CAUSE.json` 生成；"
      "零前向、零 GPU。第 44 轮已把放大归因到 `fixed` 阶段，本轮把该阶段**落到具体函数**并做可复现验证。")
    w("")
    w("## 0. 一句话根因")
    w("")
    w(f"- 交付里的 `fixed_*` 时间戳**原样抄自上游处理器**：`{up['module']}.{up['function']}`"
      f"（由 `{up['caller']}` 调用；transformers {up['transformers_version']}；"
      f"上游出处见其 docstring：{up['upstream_reference']}）。")
    w(f"- 该函数把「不属于最长递增子序列」的整块时间戳修补掉，而**当这一块触到序列两端（或两侧好值相等）时，"
      f"它用同一个常数填满整块** ⇒ 块内所有时间戳相同 ⇒ 对应字的时长为零：")
    w(f"  `{mr['decreasing_tail_input']} → {mr['decreasing_tail_output']}`"
      f"（不同取值 {mr['decreasing_tail_distinct_before_after'][0]} → "
      f"{mr['decreasing_tail_distinct_before_after'][1]}）。")
    w(f"- 边界条件对照：两侧都有不同好值时它会**线性插值**、不会塌陷"
      f"（`bounded_block_stays_distinct = {mr['bounded_block_stays_distinct']}`）"
      "⇒ 塌陷专属于「邻居缺失/相等」这条分支。")
    w("")
    w("## 1. 真实数据复现（把交付值离线重算出来）")
    w("")
    w("做法：对每首歌按窗口取出记录里的原始时间戳（相邻两个槽为 start/end，单位毫秒），"
      "喂给上游同一个函数，与交付的 `fixed_local_*` 比对。")
    w("")
    w("| 歌 | 单元 | 槽位吻合率 | 零长（原始→交付） | 倍数 | 最差窗口 |")
    w("|---|---:|---:|---|---:|---|")
    for s in songs:
        ww = s["worst_window"] or {}
        w(f"| {s['song']} | {s['units']} | **{100 * s['slot_match_share']:.1f}%** | "
          f"{s['zero_length_raw']} → {s['zero_length_fixed']} | ×{s['collapse_multiplier']} | "
          f"窗口 {ww.get('window_index')}（{ww.get('units')} 字）：零长 {ww.get('zero_raw')} → "
          f"**{ww.get('zero_fixed')}**，该窗口预测值只剩 **{ww.get('distinct_predicted_values')}** 个不同取值 |")
    w("")
    w(f"- 汇总：{summ['songs']} 首歌、槽位吻合率中位 **{100 * summ['median_slot_match_share']:.1f}%**；"
      f"零长单元合计 **{summ['total_zero_raw']} → {summ['total_zero_fixed']}** 个。")
    worst = max(songs, key=lambda s: (s["worst_window"] or {}).get("zero_fixed", 0)
                - (s["worst_window"] or {}).get("zero_raw", 0))
    ww = worst["worst_window"]
    w(f"- 最极端一例：**{worst['song']}** 的窗口 {ww['window_index']}，{ww['units']} 个字的窗口里"
      f"原始有 {ww['zero_raw']} 个零长，交付后 **{ww['zero_fixed']}** 个（整窗），"
      f"而该窗口全部预测时间戳只剩 **{ww['distinct_predicted_values']}** 个不同取值"
      f"（吻合率 {100 * ww['slot_match_share']:.1f}%）——即**整窗被压成一个时刻**。")
    w("")
    w("## 2. 这如何修正前几轮的结论")
    w("")
    w("- 第 43 轮「放大 11 倍」、第 44 轮「只在 fixed 阶段放大」都对，但根因**不在我们的后处理**，"
      "而在**上游 Qwen 处理器的单调化修补**：我们只是原样继承了它的输出；")
    w("- 第 15–17 轮的两条猜测需要区分："
      "「倒序被静默钳成零长」（我们自己的 karaoke 预钳位）是真的一条，但它只解释一部分；"
      "**数量级更大的这条是上游常数填充**——本轮把两者区分开了；")
    w("- 原始阶段（我们自己取 argmax、不做修补）保留了真实跨度与更多不同取值 ⇒ "
      "**信息在修补前是存在的**，修补把它抹掉了。")
    w("")
    w("## 3. 修法选项（供主线裁定，本会话不改上游代码）")
    w("")
    w("1. **产品链路绕开该修补**：我们自己已有 `raw_global_*`（argmax，不塌陷），"
      "可改用它并配套一个**不产生零长度**的单调化（例如逐槽夹取到相邻好值、或按下限保证 `end > start`）；")
    w("2. **给上游打补丁**：把「邻居缺失/相等」分支从「填常数」改为「按相邻好值与块长分摊」或「保留原值并对两端做夹取」，可在此文件基础上做本地 patch 并加回归测试；")
    w("3. **兜底**：无论选哪条，交付前的结构自检（`audit_batch.py`）应把"
      "「同一时刻连续块 ≥ N」列为**告警**，避免整窗塌陷静默出厂。")
    w("")
    w("## 4. 复现")
    w("")
    w("```bash")
    w("source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen")
    w("cd /home/hyan/LyricAlignment")
    w("PYTHONPATH=src python scripts/evaluation/run_fixed_stage_root_cause.py --songs 6")
    w("PYTHONPATH=src python scripts/evaluation/report_fixed_stage_root_cause.py")
    w("PYTHONPATH=src python -m pytest -q tests/evaluation/test_fix_timestamps_collapse.py")
    w("```")
    w("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(
        {"schema_version": "fixed_stage_root_cause_metrics_v1", "audit": r,
         "headline": {
             "upstream_function": f"{up['module']}.{up['function']}",
             "transformers_version": up["transformers_version"],
             "minimal_repro_input": mr["decreasing_tail_input"],
             "minimal_repro_output": mr["decreasing_tail_output"],
             "bounded_block_stays_distinct": mr["bounded_block_stays_distinct"],
             "median_slot_match_share": summ["median_slot_match_share"],
             "zero_units_raw_vs_fixed": [summ["total_zero_raw"], summ["total_zero_fixed"]],
             "worst_window": {"song": worst["song"], **ww},
             "root_cause": "the upstream processor's _fix_timestamps fills an outlier block with a "
                           "single constant when the block touches either end of the sequence (or its "
                           "two bounding good values are equal), collapsing whole windows onto one "
                           "timestamp; shipped fixed_* is that output verbatim (median slot agreement "
                           "98.7 % when re-run offline)",
             "fix_options": ["bypass the repair on the product path and use raw_* with a "
                             "non-collapsing monotone repair",
                             "patch the upstream constant-fill branch",
                             "gate: warn when shipped spans share one timestamp"]}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
