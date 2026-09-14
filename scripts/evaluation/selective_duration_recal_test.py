#!/usr/bin/env python3
'''Test *selective* post-hoc duration recalibration: only fix characters the model itself flags.

Motivation: the implied duration of the shipped absolute model has median error 0 ms (rank correlation 0.92
with truth), so a global monotone recalibration can only hurt — it must move the correctly-predicted bulk.
The remaining hope was that failures are idiosyncratic and confined to uncertain/long candidates, so we
apply the map only to those.  This script settles whether that helps; it did not (≥2 s miss got worse).

Inputs are the dumped slot distributions from `offset_distribution_probe.py` (no ground truth is used to
flag characters — only the model's own entropy proxy and its implied duration).

    PYTHONPATH=src python scripts/evaluation/selective_duration_recal_test.py \
        --rows results/by_run/20260914_offset_dist/rows.jsonl \
        --out results/by_run/20260914_selective_recal/metrics.json
'''

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2


def entropy_proxy(block: dict[str, Any]) -> float:
    '''Lower bound on the slot entropy from the stored top-k probabilities (tail mass omitted).'''
    probs = [value for value in (block.get("top_probs") or []) if value > 0]
    if not probs:
        return 0.0
    return -sum(value * math.log(value) for value in probs)


def load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        step = float(row["step_sec"])
        onset, offset = row["onset"], row["offset"]
        rows.append({"song": row["song"],
                     "gt_end": row["gt_end_bin"] * step,
                     "gt_dur": (row["gt_end_bin"] - row["gt_start_bin"]) * step,
                     "start": onset["argmax_bin"] * step,
                     "implied": (offset["argmax_bin"] - onset["argmax_bin"]) * step,
                     "entropy": entropy_proxy(offset)})
    return rows


def fit_map(pairs: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    by_bin: dict[int, list[float]] = defaultdict(list)
    for implied, truth in pairs:
        by_bin[int(min(19, max(0, implied * 4)))].append(truth)
    xs: list[float] = []
    ys: list[float] = []
    for index in range(20):
        values = by_bin.get(index)
        if values and len(values) >= 8:
            xs.append((index + 0.5) / 4.0)
            ys.append(st.median(values))
    return xs, ys


def apply_map(xs: list[float], ys: list[float], value: float) -> float:
    if len(xs) < 2:
        return value
    if value <= xs[0]:
        return ys[0] + (value - xs[0])
    if value >= xs[-1]:
        return ys[-1] + (value - xs[-1])
    for index in range(len(xs) - 1):
        if xs[index] <= value <= xs[index + 1]:
            span = xs[index + 1] - xs[index]
            ratio = 0.0 if span <= 0 else (value - xs[index]) / span
            return ys[index] + ratio * (ys[index + 1] - ys[index])
    return value


def run(rows: list[dict[str, Any]], *, quantile: float, min_implied: float) -> dict[str, Any]:
    songs = sorted({row["song"] for row in rows})
    by_song = {song: [row for row in rows if row["song"] == song] for song in songs}
    buckets: dict[str, dict[str, list[float]]] = {
        name: {"raw": [], "cal": []} for name in ("all", "1-2s", ">=2s")}
    touched = 0
    for held in songs:
        other = [row for song in songs if song != held for row in by_song[song]]
        xs, ys = fit_map([(row["implied"], row["gt_dur"]) for row in other])
        entropies = sorted(row["entropy"] for row in other)
        threshold = entropies[min(len(entropies) - 1, int(quantile * len(entropies)))] if entropies else 0.0
        for row in by_song[held]:
            flagged = row["entropy"] >= threshold and row["implied"] >= min_implied
            touched += int(flagged)
            duration = apply_map(xs, ys, row["implied"]) if flagged else row["implied"]
            raw_error = abs(row["start"] + row["implied"] - row["gt_end"])
            cal_error = abs(row["start"] + duration - row["gt_end"])
            for name, low, high in (("all", 0.0, 99.0), ("1-2s", 1.0, 2.0), (">=2s", 2.0, 99.0)):
                if low <= row["gt_dur"] < high:
                    buckets[name]["raw"].append(raw_error)
                    buckets[name]["cal"].append(cal_error)

    def summarise(values: list[float]) -> dict[str, Any]:
        return {"characters": len(values),
                "miss_share": round(sum(1 for value in values if value > TOL) / len(values), 4) if values else None,
                "median_err_ms": round(1000 * st.median(values), 1) if values else None,
                "mean_err_ms": round(1000 * st.mean(values), 1) if values else None}
    out: dict[str, Any] = {"quantile": quantile, "min_implied_sec": min_implied,
                           "flagged_characters": touched,
                           "flagged_share": round(touched / max(1, len(rows)), 4), "buckets": {}}
    for name, pair in buckets.items():
        raw, cal = summarise(pair["raw"]), summarise(pair["cal"])
        out["buckets"][name] = {"raw": raw, "recalibrated": cal,
                                "miss_delta_pp": None if raw["miss_share"] is None or cal["miss_share"] is None
                                else round(100 * (cal["miss_share"] - raw["miss_share"]), 3)}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quantiles", default="0.90,0.80,0.95")
    parser.add_argument("--min-implied", type=float, default=0.8)
    args = parser.parse_args()
    rows = load(args.rows)
    payload = {"schema_version": "selective_recal_v1", "rows": str(args.rows), "characters": len(rows),
               "tolerance_sec": TOL, "runs": []}
    for quantile in (float(value) for value in args.quantiles.split(",")):
        payload["runs"].append(run(rows, quantile=quantile, min_implied=args.min_implied))
    very_long = [run_ for run_ in payload["runs"]]
    helps = any((run_["buckets"].get(">=2s", {}).get("miss_delta_pp") or 0) < -0.5 for run_ in very_long)
    payload["verdict"] = ("selective recalibration helps" if helps else
                          "selective recalibration does NOT help (>=2s miss unchanged or worse)")
    payload["mechanism"] = ("原始隐含时长的**中位误差为 0**、秩相关 0.92 ⇒ 多数字符本来就对；"
                            "失败是个体的、不是单调尺度偏差 ⇒ 任何只用分布的单调映射要么不动失败点、"
                            "要么把已经正确的多数一起挪坏。事后时长校准（全局与选择性）到此关闭。")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"],
                      "runs": [{"quantile": run_["quantile"], "flagged_share": run_["flagged_share"],
                                "ge2s_delta_pp": run_["buckets"][">=2s"]["miss_delta_pp"],
                                "ge1to2s_delta_pp": run_["buckets"]["1-2s"]["miss_delta_pp"]}
                               for run_ in payload["runs"]]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
