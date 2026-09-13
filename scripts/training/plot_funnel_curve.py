#!/usr/bin/env python3
"""Plot the funnelled-validation curve of a training run (rolling-window view).

The run writes one L1 evaluation every `l1_every` steps to `funnel_evals.jsonl`, so that file *is*
the validation curve; `topup_evals.jsonl` adds the medium/full-set points that the in-training
funnel never got to.  Because the per-point noise (1 SE over ~14-29 songs) is of the same order as
the differences being looked at, the script draws both the raw points and a rolling mean.

    PYTHONPATH=src python scripts/training/plot_funnel_curve.py --run-dir <run> \
        --out-png <run>/plots/val_curve.png --out-csv results/by_run/<...>/VAL_CURVE.csv
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

VARIANTS = ("fixed", "raw", "raw_targeted")
METRIC_KEY = "macro_within_primary"


def read_records(path: Path, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        block = payload.get(key)
        if isinstance(block, dict):
            rows.append(block)
    return rows


def series(records: list[dict[str, Any]], *, level: str, variant: str) -> list[dict[str, float]]:
    """(step, value, se, usable_rate) per evaluated step, latest record winning, sorted by step."""
    out: dict[int, dict[str, float]] = {}
    for block in records:
        if block.get("level") != level:
            continue
        if level == "l1":
            summary = (block.get("variants") or {}).get(variant) or {}
            value = summary.get(METRIC_KEY)
            se = block.get("se") if variant == (block.get("selection") or {}).get("variant") else None
            usable = summary.get("usable_rate")
        else:
            metric = (block.get("variants") or {}).get(variant) or {}
            value, se, usable = (metric.get("macro_song_within_primary"),
                                 metric.get("macro_song_se_primary"), metric.get("usable_rate"))
        if value is None:
            continue
        step = int(block.get("evaluated_step", block.get("step") or 0))
        out[step] = {"step": step, "value": float(value), "se": float(se or 0.0),
                     "usable_rate": float(usable) if usable is not None else float("nan")}
    return [out[step] for step in sorted(out)]


def rolling_mean(values: list[float], window: int) -> list[float]:
    """Centred rolling mean with shrinking edges (a trailing mean would lag the plateau)."""
    window = max(1, int(window))
    half = window // 2
    out: list[float] = []
    for index in range(len(values)):
        low, high = max(0, index - half), min(len(values), index + half + 1)
        chunk = values[low:high]
        out.append(sum(chunk) / len(chunk))
    return out


def summarize(points: list[dict[str, float]], window: int) -> list[dict[str, float]]:
    smoothed = rolling_mean([point["value"] for point in points], window)
    return [{**point, "rolling": smoothed[index]} for index, point in enumerate(points)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-png", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path)
    parser.add_argument("--window", type=int, default=3, help="rolling window in L1 points")
    parser.add_argument("--baseline-fixed", type=float, default=None)
    parser.add_argument("--baseline-raw-targeted", type=float, default=None)
    args = parser.parse_args()

    funnel = read_records(args.run_dir / "funnel_evals.jsonl", "funnel_eval")
    topup = read_records(args.run_dir / "topup_evals.jsonl", "topup_eval")
    curves = {variant: summarize(series(funnel, level="l1", variant=variant), args.window)
              for variant in VARIANTS}
    medium = {variant: series(topup, level="l2", variant=variant) for variant in VARIANTS}
    full = {variant: series(topup, level="l3", variant=variant) for variant in VARIANTS}
    history_full = {variant: series(funnel, level="l3", variant=variant) for variant in VARIANTS}

    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        lines = ["level,step,variant,value,rolling,se,usable_rate"]
        for variant in VARIANTS:
            for point in curves[variant]:
                lines.append(f"l1,{point['step']},{variant},{point['value']:.6f},{point['rolling']:.6f},"
                             f"{point['se']:.6f},{point['usable_rate']:.6f}")
        for level, blocks in (("l2", medium), ("l3", full), ("l3_in_training", history_full)):
            for variant, points in blocks.items():
                for point in points:
                    lines.append(f"{level},{point['step']},{variant},{point['value']:.6f},,"
                                 f"{point['se']:.6f},{point['usable_rate']:.6f}")
        args.out_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"fixed": "#1f77b4", "raw": "#ff7f0e", "raw_targeted": "#2ca02c"}
    figure, (top, bottom) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                         gridspec_kw={"height_ratios": [3, 1]})
    for variant in VARIANTS:
        points = curves[variant]
        if not points:
            continue
        steps = [point["step"] for point in points]
        top.plot(steps, [point["value"] for point in points], color=colors[variant], alpha=0.25,
                 linewidth=1.0, marker=".", markersize=3)
        top.plot(steps, [point["rolling"] for point in points], color=colors[variant], linewidth=2.0,
                 label=f"{variant} (L1, {args.window}-point rolling)")
        bottom.plot(steps, [100.0 * (1.0 - point["usable_rate"]) for point in points],
                    color=colors[variant], linewidth=1.6, alpha=0.9)
    for level, blocks, marker in (("L2", medium, "o"), ("L3", full, "s")):
        for variant in VARIANTS:
            points = blocks[variant]
            if not points:
                continue
            top.scatter([point["step"] for point in points], [point["value"] for point in points],
                        color=colors[variant], marker=marker, s=45, zorder=5,
                        label=f"{variant} ({level}, full protocol)")
    for variant in VARIANTS:
        for point in history_full[variant]:
            top.scatter([point["step"]], [point["value"]], facecolors="none", edgecolors=colors[variant],
                        marker="s", s=60, zorder=4)
    if args.baseline_fixed is not None:
        top.axhline(args.baseline_fixed, color=colors["fixed"], linestyle=":", linewidth=1.2)
    if args.baseline_raw_targeted is not None:
        top.axhline(args.baseline_raw_targeted, color=colors["raw_targeted"], linestyle=":", linewidth=1.2)
    top.set_ylabel("fraction of characters within 0.2 s\n(song macro average)")
    top.set_title("Validation curve — funnelled protocol (L1 every 50 steps, rolling view)")
    top.grid(alpha=0.25)
    top.legend(fontsize=8, loc="lower right")
    bottom.set_xlabel("training step")
    bottom.set_ylabel("unusable units (%)")
    bottom.grid(alpha=0.25)
    args.out_png.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(args.out_png, dpi=140)
    peak = max((point["rolling"], point["step"]) for point in curves["fixed"]) if curves["fixed"] else None
    print(json.dumps({"png": str(args.out_png), "csv": str(args.out_csv) if args.out_csv else None,
                      "l1_points": {variant: len(points) for variant, points in curves.items()},
                      "l2_points": {variant: len(points) for variant, points in medium.items()},
                      "l3_points": {variant: len(points) for variant, points in full.items()},
                      "best_rolling_fixed": (None if peak is None else {"value": round(peak[0], 4),
                                                                        "step": peak[1]})},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
