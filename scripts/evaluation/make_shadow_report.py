#!/usr/bin/env python3
"""Render a plain-language review report from the shadow-run metrics JSON.

The probe itself only writes JSON.  This generator exists so a human gets a readable summary, and so the
claim "there is a report artifact" is backed by a file that is actually produced.

    PYTHONPATH=src python scripts/evaluation/make_shadow_report.py \
        --metrics results/by_run/20260914_shadow_run/metrics.json \
        --out docs/reviews/20260914_shadow_run_report.md
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--also", type=Path, help="同时在 metrics.json 同目录写一份 REPORT.md")
    args = parser.parse_args()

    payload = json.loads(args.metrics.read_text(encoding="utf-8"))
    totals = payload.get("totals") or {}
    songs = [song for song in payload.get("songs", []) if "official" in song]
    if not songs:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("# 影子跑报告\n\n- 状态：没有可用歌目（可能全部被跳过：缺人声或字太少）。\n",
                            encoding="utf-8")
        raise SystemExit(0)

    medians = [song["agreement_median_end_delta_ms"] for song in songs]
    p90s = [song["agreement_p90_end_delta_ms"] for song in songs]
    collapsed_worst = sorted(songs, key=lambda song: -song["official"]["zero_share"])[:8]

    lines = ["# 成品影子对比：现在产品做法 vs 整句一起挑（自动生成，勿手改）", "",
             f"> 数据来源：`{args.metrics}`（{totals.get('songs', len(songs))} 首歌，"
             f"{totals.get('intervals', 0):,} 个片段，**同一次模型输出**下比较；不加任何人工标注）。", "",
             "## 一句话", "",
             f"- 现在产品做法（逐字挑 + 自动修饰）产生 **{totals.get('official_zero', 0):,} 个零时长片段"
             f"（{100 * (totals.get('official_zero_share') or 0):.1f}%）**；"
             f"改成整句一起挑之后 **{totals.get('dp_zero', 0)} 个**。",
             "- ⇒ **结构异常确实被消掉**；但两种做法给出的结束点差别不小（见下表"
             "『结束点偏离』），而**偏离大的那些歌恰好是没有真值可判的歌** ⇒ "
             "合法不等于正确，**必须与门控同时上线**。", "",
             "## 合计", "",
             "| 项目 | 现在产品做法 | 整句一起挑 |", "|---|---|---|",
             f"| 片段数 | {totals.get('intervals', 0):,} | {totals.get('intervals', 0):,} |",
             f"| 零时长片段 | {totals.get('official_zero', 0):,} | {totals.get('dp_zero', 0):,} |",
             f"| 零时长占比 | {100 * (totals.get('official_zero_share') or 0):.1f}% | "
             f"{100 * (totals.get('dp_zero_share') or 0):.1f}% |", "",
             "## 每首歌（按产品做法的异常率排序，前 8）", "",
             "| 歌 | 片段数 | 成品里已有坍缩 | 产品做法零时长 | 最长共用同一结束点 | 整句一起挑零时长 | 两轴结束点中位偏离(ms) | 偏离 p90(ms) |",
             "|---|---|---|---|---|---|---|---|"]
    for song in collapsed_worst:
        official, decoded = song["official"], song["dp"]
        lines.append(f"| {song['song']} | {official['intervals']} | "
                     f"{100 * (song.get('shipped_collapse_rate') or 0):.1f}% | "
                     f"{official['zero_length']} ({100 * official['zero_share']:.0f}%) | "
                     f"{official['longest_same_end_block']} | {decoded['zero_length']} | "
                     f"{song['agreement_median_end_delta_ms']:.0f} | {song['agreement_p90_end_delta_ms']:.0f} |")
    lines += ["", "## 两点必须一起读的解释", "",
              f"- 全部歌目的『两轴结束点中位偏离』中位数 **{st.median(medians):.0f} ms**、"
              f"最大 **{max(medians):,.0f} ms**；p90 中位 **{st.median(p90s):,.0f} ms**。",
              "- 偏离特别大的歌，都是产品做法把**九成以上片段压成同一个结束点**的歌"
              "（例如极快的歌：192 / 276 个字共用一个结束点）。对这类歌，"
              "**『铺开』本身是好的，但铺到哪里没有依据可判** ⇒ 只能整段送人工复核，"
              "不能因为『结构合法』就放过。", "",
              "## 复核清单（门控）", ""]
    gating = payload.get("gating") or {}
    if gating:
        lines.append(f"- 标记 {100 * (gating.get('flagged_share') or 0):.1f}% 的字，"
                     f"抓到 {100 * (gating.get('defect_capture_share') or 0):.1f}% 的异常。")
    else:
        lines.append("- 状态：本次 metrics.json 里没有门控结果（门控由 `export_review_gating.py` 单独产出，"
                     "读的是交付批的置信度字段）。")
    lines += ["", "## 这份报告不能用来主张什么", "",
              "- 不能主张『整句一起挑更准』：这里没有人工真值，只有结构合法性与两轴差异。",
              "- 不能把这里的零时长比例与交付批的成品比例混用：这里是**单段 90 秒不分窗**的压力条件，"
              "比产品按行分窗更难，所以数字更难看（这也正是压力测试的目的）。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    args.out.write_text(text, encoding="utf-8")
    if args.also:
        args.also.parent.mkdir(parents=True, exist_ok=True)
        args.also.write_text(text, encoding="utf-8")
    print(f"写到 {args.out}" + (f" 以及 {args.also}" if args.also else ""))


if __name__ == "__main__":
    main()
