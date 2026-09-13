#!/usr/bin/env python3
"""Is the validation plateau still creeping up?  A block-bootstrap trend test.

The L1 curve has one point per ~50 steps and a per-point standard error of the same order as the
differences under discussion, so eyeballing a rolling mean cannot settle "still rising slowly" vs
"flat with noise" — consecutive points are also autocorrelated (they share most of the same songs
and the same weights drift), which makes an ordinary least-squares error bar far too optimistic.
This script therefore resamples *contiguous blocks* of points (moving-block bootstrap) to get an
honest confidence interval for the slope and for the first-half/second-half difference.

    PYTHONPATH=src python scripts/training/analyze_val_trend.py --run-dir <run> --variant fixed \
        --from-step 1000 --out results/by_run/<...>/TREND.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Callable

VARIANTS = ("fixed", "raw", "raw_targeted")


def read_points(path: Path, variant: str, level: str = "l1") -> list[tuple[int, float]]:
    """(step, value) pairs of the latest record per step, sorted by step."""
    out: dict[int, float] = {}
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            block = (json.loads(line) or {}).get("funnel_eval")
        except json.JSONDecodeError:
            continue
        if not block or block.get("level") != level:
            continue
        summary = (block.get("variants") or {}).get(variant) or {}
        value = summary.get("macro_within_primary")
        if value is None:
            continue
        out[int(block["evaluated_step"])] = float(value)
    return [(step, out[step]) for step in sorted(out)]


def ols_slope(points: list[tuple[int, float]]) -> float:
    """Slope of value on (step / 1000); returned in percentage points per 1000 steps."""
    if len(points) < 2:
        return 0.0
    xs = [step / 1000.0 for step, _ in points]
    ys = [value for _, value in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return 100.0 * sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator


def block_bootstrap(points: list[tuple[int, float]], statistic: Callable[[list[tuple[int, float]]], float],
                    *, block: int = 5, resamples: int = 2000, seed: int = 20260724) -> dict[str, Any]:
    """Moving-block bootstrap: resample contiguous blocks so autocorrelation is preserved."""
    if len(points) < block + 1:
        return {"estimate": statistic(points), "low": None, "high": None, "resamples": 0}
    rng = random.Random(seed)
    starts = list(range(0, len(points) - block + 1))
    samples: list[float] = []
    for _ in range(resamples):
        drawn: list[tuple[int, float]] = []
        while len(drawn) < len(points):
            offset = rng.choice(starts)
            drawn.extend(points[offset:offset + block])
        samples.append(statistic(drawn[:len(points)]))
    samples.sort()
    low = samples[int(0.05 * len(samples))]
    high = samples[int(0.95 * len(samples)) - 1]
    return {"estimate": statistic(points), "low": low, "high": high, "resamples": len(samples)}


def window_difference(points: list[tuple[int, float]], *, window: int = 40) -> float:
    """Mean of the last `window` points minus the mean of the first `window`, in percentage points.

    Deliberately a difference of two *means*: a moving-block bootstrap concatenates resampled blocks
    in a random order, so any statistic that depends on the global ordering of the series (an
    "earlier half vs later half" computed on the resample) is destroyed by the resampling and would
    report a confidence interval that does not even contain its own point estimate.
    """
    if len(points) < 2:
        return 0.0
    window = max(1, min(window, len(points) // 2))
    early = [value for _, value in points[:window]]
    late = [value for _, value in points[-window:]]
    return 100.0 * (sum(late) / len(late) - sum(early) / len(early))


def analyse(points: list[tuple[int, float]], *, block: int = 5, resamples: int = 2000,
            window: int = 40, seed: int = 20260724) -> dict[str, Any]:
    slope = block_bootstrap(points, ols_slope, block=block, resamples=resamples, seed=seed)
    # the window difference needs its own bootstrap: both means must be resampled *within their own
    # window*, otherwise the windows mix and the statistic collapses towards zero
    early, late = (points[:window], points[-window:]) if len(points) >= 2 else (points, points)
    early_ci = block_bootstrap(early, lambda rows: 100.0 * sum(v for _, v in rows) / max(1, len(rows)),
                               block=block, resamples=resamples, seed=seed)
    late_ci = block_bootstrap(late, lambda rows: 100.0 * sum(v for _, v in rows) / max(1, len(rows)),
                              block=block, resamples=resamples, seed=seed + 1)
    halves = {"estimate": window_difference(points, window=window),
              "low": (None if early_ci["low"] is None or late_ci["low"] is None
                      else late_ci["low"] - early_ci["high"]),
              "high": (None if early_ci["high"] is None or late_ci["high"] is None
                       else late_ci["high"] - early_ci["low"]),
              "window_points": min(window, max(1, len(points) // 2)), "resamples": resamples}
    span = (points[-1][0] - points[0][0]) if points else 0
    verdict = "inconclusive"
    if slope["low"] is not None:
        if slope["low"] > 0:
            verdict = "rising"
        elif slope["high"] < 0:
            verdict = "falling"
        else:
            verdict = "flat_within_noise"
    return {"points": len(points), "first_step": points[0][0] if points else None,
            "last_step": points[-1][0] if points else None, "span_steps": span,
            "slope_pp_per_1000": slope, "window_difference_pp": halves,
            "implied_change_over_span_pp": (None if slope["low"] is None else
                                            slope["estimate"] * span / 1000.0),
            "verdict": verdict}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--variant", default="fixed")
    parser.add_argument("--from-step", type=int, default=0)
    parser.add_argument("--block", type=int, default=5)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    path = args.run_dir / "funnel_evals.jsonl"
    variants = VARIANTS if args.variant == "all" else (args.variant,)
    payload: dict[str, Any] = {"source": str(path), "from_step": args.from_step, "block": args.block,
                               "resamples": args.resamples, "variants": {}}
    for variant in variants:
        points = [(step, value) for step, value in read_points(path, variant) if step >= args.from_step]
        payload["variants"][variant] = analyse(points, block=args.block, resamples=args.resamples)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
