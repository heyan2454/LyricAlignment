#!/usr/bin/env python3
"""Audit shipped timelines for collapse-type anomalies, per variant.

Why per variant: a research batch stores the same song under many variants (model stage x audio input x
windowing).  Counting files as songs inflates every total and made two genuinely different pipelines look
identical on 2026-09-14 — so variants are aggregated separately and only the delivery configuration is
presented as "the product".

Why three stages: each character carries the model's own answer (`raw_global_*`), the answer after the
upstream repair (`official_fixed_*`), and what actually ships (`start_sec`/`end_sec`).  Counting only the
last one hides which stage created or merely masked an anomaly.

    PYTHONPATH=src python scripts/evaluation/audit_batch_timeline_anomalies.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --out results/by_run/20260914_product_anomaly_audit/metrics.json
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any

EPS = 1e-6
MOVE_SEC = 0.2
LONG_SEC = 2.0
PRODUCT_VARIANT = "r2/vocal/windowed"
STAGES = (("raw", "raw_global_start_sec", "raw_global_end_sec"),
          ("official_fixed", "official_fixed_global_start_sec", "official_fixed_global_end_sec"),
          ("shipped", "start_sec", "end_sec"))


def variant_of(path: Path) -> str:
    parts = path.parts
    if "alignments" not in parts:
        return "unknown"
    index = len(parts) - 1 - list(reversed(parts)).index("alignments")
    tail = parts[index + 1:index + 4]
    return "/".join(tail) if len(tail) == 3 else "unknown"


def count_anomalies(intervals: list[tuple[float, float]]) -> dict[str, int]:
    zero = negative = overlap = regress = 0
    run = longest = 0
    for index, (start, end) in enumerate(intervals):
        if abs(end - start) <= EPS:
            zero += 1
            run += 1
            longest = max(longest, run)
        else:
            run = 0
            if end < start - EPS:
                negative += 1
        if index:
            previous_start, previous_end = intervals[index - 1]
            if start < previous_start - EPS:
                regress += 1
            if start < previous_end - EPS:
                overlap += 1
    return {"characters": len(intervals), "zero_duration": zero, "negative_duration": negative,
            "overlap_with_previous": overlap, "start_regresses": regress,
            "longest_collapse_run": longest, "long_ge_2s": sum(1 for a, b in intervals if b - a >= LONG_SEC)}


def audit_file(path: Path) -> dict[str, Any] | None:
    document = json.loads(path.read_text(encoding="utf-8"))
    characters = document.get("characters") or []
    if len(characters) < 5:
        return None
    stages: dict[str, dict[str, int]] = {}
    for label, start_key, end_key in STAGES:
        intervals: list[tuple[float, float]] = []
        for character in characters:
            start, end = character.get(start_key), character.get(end_key)
            if start is not None and end is not None:
                intervals.append((float(start), float(end)))
        if intervals:
            stages[label] = count_anomalies(intervals)
    raw_ends = [(c.get("raw_global_end_sec"), c.get("end_sec"), c.get("raw_end_top1_probability"))
                for c in characters]
    moved = low_conf_moved = 0
    for raw_end, shipped_end, confidence in raw_ends:
        if raw_end is None or shipped_end is None:
            continue
        if abs(float(shipped_end) - float(raw_end)) > MOVE_SEC:
            moved += 1
            if confidence is not None and float(confidence) < 0.5:
                low_conf_moved += 1
    quality_path = path.with_name("alignment.quality.json")
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    parts = path.parts
    song = parts[len(parts) - 6] if len(parts) >= 6 else path.parent.name
    return {"song": song, "variant": variant_of(path), "stages": stages,
            "moved_ge_0.2s": moved, "moved_and_low_confidence": low_conf_moved,
            "product_status": quality.get("status"),
            "structural_errors": quality.get("structural_errors") or [],
            "warnings": quality.get("warnings") or []}


def aggregate(group: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {"files": len(group),
                              "distinct_songs": len({row["song"] for row in group})}
    for stage, _sk, _ek in STAGES:
        for key in ("characters", "zero_duration", "negative_duration", "overlap_with_previous",
                    "start_regresses", "longest_collapse_run", "long_ge_2s"):
            values = [row["stages"][stage][key] for row in group if stage in row["stages"]]
            totals[f"{stage}_{key}"] = (max(values) if key == "longest_collapse_run"
                                        else sum(values)) if values else 0
        characters = totals[f"{stage}_characters"]
        totals[f"{stage}_zero_share"] = (round(totals[f"{stage}_zero_duration"] / characters, 4)
                                         if characters else None)
    totals["moved_ge_0.2s"] = sum(row["moved_ge_0.2s"] for row in group)
    totals["moved_and_low_confidence"] = sum(row["moved_and_low_confidence"] for row in group)
    totals["warn_but_no_structural_error"] = sum(
        1 for row in group if row["warnings"] and not row["structural_errors"])
    return totals


def table_lines(title: str, totals: dict[str, Any]) -> list[str]:
    lines = [f"**{title}**（{totals['files']} 份文件 / {totals['distinct_songs']} 首不同的歌）", "",
             "| 阶段 | 字数 | 零时长 | 零时长占比 | 负时长 | 字间重叠 | 开始时间倒退 | 最长连续坍缩 | ≥2s 长音 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for stage, label in (("raw", "模型原始"), ("official_fixed", "上游修补后"), ("shipped", "**成品**")):
        share = totals.get(f"{stage}_zero_share")
        lines.append(f"| {label} | {totals[f'{stage}_characters']} | {totals[f'{stage}_zero_duration']} | "
                     + ("—" if share is None else f"{100 * share:.1f}%") + " | "
                     f"{totals[f'{stage}_negative_duration']} | {totals[f'{stage}_overlap_with_previous']} | "
                     f"{totals[f'{stage}_start_regresses']} | {totals[f'{stage}_longest_collapse_run']} | "
                     f"{totals[f'{stage}_long_ge_2s']} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", action="append", required=True, type=Path)
    parser.add_argument("--pattern", default="*/alignments/*/*/*/alignment.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    payload: dict[str, Any] = {"schema_version": "product_anomaly_audit_v2",
                               "product_variant": PRODUCT_VARIANT,
                               "tolerance": {"move_sec": MOVE_SEC, "long_sec": LONG_SEC}, "batches": {}}
    for batch in args.batch:
        paths = sorted(glob.glob(str(batch / args.pattern)))
        if args.limit:
            paths = paths[: args.limit]
        rows = [row for path in map(Path, paths) if (row := audit_file(path))]
        variants = sorted({row["variant"] for row in rows})
        payload["batches"][batch.name] = {
            "batch": str(batch), "files": len(rows), "variants": variants,
            "distinct_songs": len({row["song"] for row in rows}),
            "totals": aggregate(rows),
            "totals_by_variant": {variant: aggregate([row for row in rows if row["variant"] == variant])
                                  for variant in variants},
            "worst": sorted(rows, key=lambda row: -row["stages"].get("shipped", {}).get("zero_duration", 0))[:8]}

    lines = ["# 成品异常审计（生成，勿手改）", "",
             "> 三个阶段都数一遍：**模型原始** → **上游修补后** → **用户看到的成品**。按变体分开统计。", ""]
    for name, block in payload["batches"].items():
        lines += [f"## 批：`{name}`（{block['distinct_songs']} 首不同的歌 × {len(block['variants'])} 个变体 "
                  f"= {block['files']} 份文件）", ""]
        if len(block["variants"]) > 1:
            lines += [f"⚠️ 这是研究矩阵（变体：{', '.join(block['variants'])}），**不是一批不同的歌**；"
                      "把文件当歌数会把同一首算好几遍（2026-09-14 19:40 我就差点把两条不同管道读成结论一致）。"
                      "下面只按**交付形态**读，合并数仅作参考。", ""]
        product = block["totals_by_variant"].get(PRODUCT_VARIANT)
        if product:
            lines += table_lines(f"交付形态 `{PRODUCT_VARIANT}`", product) + [""]
        if len(block["variants"]) > 1:
            lines += ["各变体的**成品零时长占比**（形态差别可能比批次差别还大）：", "",
                      "| 变体 | 文件数 | 模型原始 | 成品 | 成品最长连续坍缩 | ≥2s 长音：原始→成品 |",
                      "|---|---|---|---|---|---|"]
            for variant, variant_totals in sorted(block["totals_by_variant"].items()):
                lines.append(f"| {variant} | {variant_totals['files']} | "
                             f"{100 * (variant_totals.get('raw_zero_share') or 0):.1f}% | "
                             f"**{100 * (variant_totals.get('shipped_zero_share') or 0):.1f}%** | "
                             f"{variant_totals['shipped_longest_collapse_run']} | "
                             f"{variant_totals['raw_long_ge_2s']} → {variant_totals['shipped_long_ge_2s']} |")
            lines.append("")
        source = product or block["totals"]
        lines += [f"- 被流水线挪动 ≥0.2 秒的字数：**{source['moved_ge_0.2s']}**，其中 "
                  f"**{source['moved_and_low_confidence']}** 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方；",
                  f"- **自检漏检**：{source['warn_but_no_structural_error']} / {source['files']} 份文件"
                  "「有警告但结构错误记 0」⇒ 只看 status 的下游会以为一切正常。", "",
                  "最严重的文件（按成品零时长字数）：", "",
                  "| 歌 | 变体 | 字数 | 成品零时长 | 最长连续坍缩 | ≥2s 长音：原始→成品 | 自检 |",
                  "|---|---|---|---|---|---|---|"]
        for row in block["worst"]:
            shipped = row["stages"].get("shipped", {})
            raw_stage = row["stages"].get("raw", {})
            lines.append(f"| {row['song']} | {row['variant']} | {shipped.get('characters', 0)} | "
                         f"{shipped.get('zero_duration', 0)} | {shipped.get('longest_collapse_run', 0)} | "
                         f"{raw_stage.get('long_ge_2s', 0)} → {shipped.get('long_ge_2s', 0)} | "
                         f"`{row['product_status']}`（结构错误 {len(row['structural_errors'])}、"
                         f"警告 {len(row['warnings'])}） |")
        lines.append("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out.with_name("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
