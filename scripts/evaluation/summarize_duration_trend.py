#!/usr/bin/env python3
'''Summarise the structural arm's trend probes, including whether semantics are actually switching.

A null result at 6000 steps is ambiguous on its own: either the duration parameterisation is useless, or
the model never finished switching away from absolute end bins.  The rank correlation between the implied
duration (slot-2 minus slot-1 argmax) and the true duration separates the two: correlation near 1 with a
falling error means the semantic switch completed, correlation near 0 late in training means the head is
still emitting absolute positions and the run answered nothing.

    PYTHONPATH=src python scripts/evaluation/summarize_duration_trend.py \
        --glob 'results/by_run/20260914_duration_trend/step*/per_character.jsonl' \
        --extra results/by_run/20260914_earlycheck_duration_step500/per_character.jsonl:500 \
        --out results/by_run/20260914_duration_trend/summary.json
'''

from __future__ import annotations

import argparse
import glob
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2


def load_pairs(path: Path) -> list[dict[str, float]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(str(row["item_id"]), int(row["index"]))][row["kind"]] = row
    out: list[dict[str, float]] = []
    for slots in per.values():
        if len(slots) != 2:
            continue
        onset, offset = slots["onset"], slots["offset"]
        gt_duration = float(offset["duration"])
        out.append({"start_err": abs(float(onset.get("abs_err_argmax") or 0.0)),
                    # §6i: 监控"没被改动的那个槽位"（起始点）的判别性，比终态指标灵敏得多。
                    "start_entropy": float(onset["entropy_nats"]) if onset.get("entropy_nats") is not None else None,
                    "start_p_top1": float(onset["p_top1"]) if onset.get("p_top1") is not None else None,
                    "end_err": abs(float(offset.get("abs_err_argmax") or 0.0)),
                    "implied_duration": float(offset.get("pred_sec") or 0.0) - float(onset.get("pred_sec") or 0.0),
                    "gt_duration": gt_duration,
                    "end_miss": 1.0 if abs(float(offset.get("abs_err_argmax") or 0.0)) > TOL else 0.0})
    return out


def spearman(pairs: list[dict[str, float]]) -> float | None:
    '''Rank correlation between implied and true duration (ties averaged; no scipy needed).'''
    if len(pairs) < 20:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        result = [0.0] * len(values)
        cursor = 0
        while cursor < len(order):
            stop = cursor + 1
            while stop < len(order) and values[order[stop]] == values[order[cursor]]:
                stop += 1
            average = (cursor + stop - 1) / 2.0
            for position in range(cursor, stop):
                result[order[position]] = average
            cursor = stop
        return result

    first = ranks([row["implied_duration"] for row in pairs])
    second = ranks([row["gt_duration"] for row in pairs])
    mean_a, mean_b = st.mean(first), st.mean(second)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in zip(first, second))
    spread = (sum((a - mean_a) ** 2 for a in first) * sum((b - mean_b) ** 2 for b in second)) ** 0.5
    return round(covariance / spread, 4) if spread else None


def summarise(label: str, rows: list[dict[str, float]]) -> dict[str, Any]:
    if not rows:
        return {"step_label": label, "status": "empty"}
    long_rows = [row for row in rows if row["gt_duration"] >= 1.0]
    ent = [row["start_entropy"] for row in rows if row.get("start_entropy") is not None]
    top1 = [row["start_p_top1"] for row in rows if row.get("start_p_top1") is not None]
    return {"step_label": label, "status": "measured", "characters": len(rows),
            "median_start_entropy_nats": round(st.median(ent), 2) if ent else None,
            "median_start_p_top1": round(st.median(top1), 3) if top1 else None,
            "median_start_err_ms": round(1000 * st.median(row["start_err"] for row in rows), 1),
            "p90_start_err_ms": round(1000 * sorted(row["start_err"] for row in rows)[int(0.9 * (len(rows) - 1))], 1),
            "median_end_err_ms": round(1000 * st.median(row["end_err"] for row in rows), 1),
            "median_end_err_ms_long": round(1000 * st.median([row["end_err"] for row in long_rows]), 1) if long_rows else None,
            "end_miss_share": round(sum(row["end_miss"] for row in rows) / len(rows), 4),
            "median_implied_duration_sec": round(st.median(row["implied_duration"] for row in rows), 3),
            "median_true_duration_sec": round(st.median(row["gt_duration"] for row in rows), 3),
            "spearman_duration": spearman(rows)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glob", default="results/by_run/20260914_duration_trend/step*/per_character.jsonl")
    parser.add_argument("--extra", action="append", default=[],
                        help="额外的一份 dump，格式 path:step_label")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    entries: list[tuple[str, Path]] = []
    for spec in args.extra:
        if ":" not in spec:
            continue
        raw_path, label = spec.rsplit(":", 1)
        entries.append((label, Path(raw_path)))
    for path in sorted(glob.glob(args.glob)):
        directory = Path(path).parent.name
        label = directory.replace("step", "")
        entries.append((label, Path(path)))

    payload = {"schema_version": "duration_trend_v1", "tolerance_sec": TOL, "points": []}
    for label, path in entries:
        if not path.exists():
            payload["points"].append({"step_label": label, "status": "missing", "path": str(path)})
            continue
        payload["points"].append(summarise(label, load_pairs(path)))
    ordered = sorted(payload["points"], key=lambda item: int(item["step_label"]) if str(item.get("step_label", "")).isdigit() else 10 ** 9)
    payload["points"] = ordered
    header = ["# 结构臂趋势（生成，勿手改）", "",
              "起始点误差是 duration 参数化下结束点误差的**硬下界**（end = start + duration）；",
              "`spearman_duration` ≈ 0 且结束点误差仍大 ⇒ 语义没换过来，本轮**无法**判参数化无效。", "",
              "| 步 | n | 起始中位(ms) | 起始 p90 | **起始熵(nats)** | **起始 p_top1** | 结束中位(ms) | ≥1s 结束中位 | 结束超差率 | 估时长中位(s) | 真时长中位(s) | 时长秩相关 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for point in ordered:
        if point.get("status") != "measured":
            header.append(f"| {point.get('step_label')} | — | 未产出（{point.get('status')}） | | | | | | | |")
            continue
        header.append(f"| {point['step_label']} | {point['characters']} | {point['median_start_err_ms']} | "
                      f"{point['p90_start_err_ms']} | **{point['median_start_entropy_nats']}** | "
                      f"**{point['median_start_p_top1']}** | {point['median_end_err_ms']} | "
                      f"{point['median_end_err_ms_long']} | {100 * point['end_miss_share']:.2f}% | "
                      f"{point['median_implied_duration_sec']} | {point['median_true_duration_sec']} | "
                      f"{point['spearman_duration']} |")
    payload["markdown"] = "\n".join(header) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        Path("docs/status/20260914_duration_trend.md").write_text(payload["markdown"], encoding="utf-8")
    print(payload["markdown"])


if __name__ == "__main__":
    main()
