#!/usr/bin/env python3
"""Does low confidence push the predicted duration toward the corpus mode?

The night's mechanism claim is "duration regression to the common value": when the timestamp head is
unsure it emits an interval of a *typical* length rather than the true long one.  That claim has so
far been tested against ground truth.  This script tests the version that matters operationally: the
relation must be visible **without** ground truth, i.e. from (confidence, predicted duration) alone —
otherwise it cannot drive a runtime detector.

Reads the per-character dump of `measure_predicted_boundary_acoustics.py` (one row per
character/kind/channel) and cross-tabulates predicted-duration behaviour against confidence quartiles,
within ground-truth duration buckets.  Reported per cell: median predicted duration, median
pred/gt ratio, and how far the predicted duration sits from the corpus mode.

    PYTHONPATH=src python scripts/evaluation/confidence_duration_interaction.py \
        --dump results/by_run/20260914_mech_validation_uniform/per_character.jsonl \
        --out results/by_run/20260914_confidence_duration/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
MODE_SEC = 0.48          # 语料里最长的时长桶代表值（0.25-0.5s 桶中位附近）


def characters(path: Path) -> list[dict[str, Any]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    out: list[dict[str, Any]] = []
    for (item, index), kinds in per.items():
        if len(kinds) != 2:
            continue
        onset, offset = kinds["onset"], kinds["offset"]
        gt_dur = float(onset["duration"])
        pred_dur = float(offset["pred_sec"]) - float(onset["pred_sec"])
        max_err = max(float(onset["abs_err_argmax"]), float(offset["abs_err_argmax"]))
        entropy = (float(onset["entropy_nats"]) + float(offset["entropy_nats"])) / 2.0
        p_top1 = min(float(onset.get("p_top1") or 0.0), float(offset.get("p_top1") or 0.0))
        out.append({"key": f"{item}|{index}", "gt_dur": gt_dur, "pred_dur": pred_dur,
                    "max_err": max_err, "entropy": entropy, "p_top1": p_top1})
    return out


def bucket(duration: float) -> str:
    if duration < 0.5:
        return "0-0.5s"
    if duration < 1.0:
        return "0.5-1s"
    if duration < 2.0:
        return "1-2s"
    return "2s+"


def quartiles(rows: list[dict[str, Any]]) -> list[float]:
    values = sorted(row["entropy"] for row in rows)
    return [values[int(fraction * (len(values) - 1))] for fraction in (0.25, 0.5, 0.75)]


def entropy_label(value: float, cuts: list[float]) -> str:
    if value <= cuts[0]:
        return "Q1(最确信)"
    if value <= cuts[1]:
        return "Q2"
    if value <= cuts[2]:
        return "Q3"
    return "Q4(最不确信)"


def table(rows: list[dict[str, Any]], cuts: list[float]) -> dict[str, Any]:
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    bucket_totals: dict[str, int] = defaultdict(int)
    dropped: dict[str, int] = defaultdict(int)
    for row in rows:
        name = bucket(row["gt_dur"])
        bucket_totals[name] += 1
        cells[(name, entropy_label(row["entropy"], cuts))].append(row)
    out: dict[str, Any] = {"_bucket_totals": {name: {"characters": count} for name, count in bucket_totals.items()}}
    _ = dropped
    for (duration_bucket, entropy_bucket), group in sorted(cells.items()):
        if len(group) < 25:
            continue
        pred = [row["pred_dur"] for row in group]
        ratios = [row["pred_dur"] / row["gt_dur"] for row in group if row["gt_dur"] > 0]
        out.setdefault(duration_bucket, {})[entropy_bucket] = {
            "characters": len(group),
            "median_gt_dur": round(st.median([row["gt_dur"] for row in group]), 3),
            "median_pred_dur": round(st.median(pred), 3),
            "median_ratio": round(st.median(ratios), 3),
            "median_distance_to_mode": round(st.median([abs(value - MODE_SEC) for value in pred]), 3),
            "miss_rate": round(sum(1 for row in group if row["max_err"] > TOL) / len(group), 4)}
    return out


def correlation(rows: list[dict[str, Any]], *, only: str | None = None) -> dict[str, Any]:
    subset = [row for row in rows if only is None or bucket(row["gt_dur"]) == only]
    xs = [row["entropy"] for row in subset]
    ys = [abs(row["pred_dur"] - MODE_SEC) for row in subset]
    if len(subset) < 30:
        return {"status": "insufficient_data", "n": len(subset)}
    mx, my = st.mean(xs), st.mean(ys)
    spread_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    spread_y = sum((y - my) ** 2 for y in ys) ** 0.5
    n = len(subset)
    # A near-constant series has zero true variance but a *floating* residue, and dividing by that
    # residue invents a correlation out of noise (seen in tests: r=0.22 from nothing).
    if spread_x < 1e-9 or spread_y < 1e-9:
        return {"status": "degenerate_variance", "n": n,
                "reason": "一方近似恒定，真实方差为零；不计算相关以免把浮点残差当成信号"}
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (spread_x * spread_y)
    return {"status": "measured", "n": n, "pearson_r": round(r, 4),
            "t_approx": round(r * (n - 2) ** 0.5 / max(1e-9, (1 - r * r) ** 0.5), 2),
            "spearman_like_note": "距离对模式的绝对偏差 vs 熵；正相关支持『越不确定越靠近众数』"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = characters(args.dump)
    cuts = quartiles(rows)
    payload = {"schema_version": "confidence_duration_v1", "dump": str(args.dump),
               "characters": len(rows), "mode_sec": MODE_SEC, "tolerance_sec": TOL,
               "entropy_quartile_cuts": [round(value, 4) for value in cuts],
               "cells": table(rows, cuts),
               "distance_to_mode_vs_entropy": {
                   "all": correlation(rows),
                   "0-0.5s": correlation(rows, only="0-0.5s"),
                   "0.5-1s": correlation(rows, only="0.5-1s"),
                   "1-2s": correlation(rows, only="1-2s"),
                   "2s+": correlation(rows, only="2s+")}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"字符 {len(rows)}，熵四分位切点 {[round(v,2) for v in cuts]}")
    for duration_bucket, cells in payload["cells"].items():
        print(f"  {duration_bucket}:")
        for name in ("Q1(最确信)", "Q2", "Q3", "Q4(最不确信)"):
            if name not in cells:
                continue
            block = cells[name]
            print(f"    {name:10s} n={block['characters']:5d} gt {block['median_gt_dur']:.2f}s "
                  f"pred {block['median_pred_dur']:.2f}s 比 {block['median_ratio']:.3f} "
                  f"距众数 {block['median_distance_to_mode']:.3f}s 超差 {100*block['miss_rate']:.2f}%")
    print("熵 vs |预测时长 − 众数| 相关：")
    for name, block in payload["distance_to_mode_vs_entropy"].items():
        if block.get("status") != "measured":
            print(f"  {name:8s} 数据不足（n={block.get('n')}）")
            continue
        print(f"  {name:8s} n={block['n']:5d} r={block['pearson_r']:+.4f} (t≈{block['t_approx']})")


if __name__ == "__main__":
    main()
