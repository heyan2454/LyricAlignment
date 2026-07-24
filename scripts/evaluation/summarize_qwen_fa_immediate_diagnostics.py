#!/usr/bin/env python3
"""Aggregate immediate Qwen FA diagnostics across models and experiments."""
from __future__ import annotations
import argparse, json, math, statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] if lo == hi else values[lo] * (hi - index) + values[hi] * (index - lo)


def stats(values: Iterable[float]) -> dict[str, float | None]:
    data = [float(value) for value in values if math.isfinite(float(value))]
    return {
        "count": len(data),
        "mean": statistics.fmean(data) if data else None,
        "median": statistics.median(data) if data else None,
        "p90": quantile(data, 0.90),
        "p95": quantile(data, 0.95),
        "maximum": max(data) if data else None,
    }


def abs_time_bin(value: float) -> str:
    edges = (0, 30, 60, 90, 120, 150, 180, 240, 300, 400)
    for left, right in zip(edges, edges[1:]):
        if left <= value < right:
            return f"{left:03d}-{right:03d}"
    return "400+"


def seam_bin(value: float | None) -> str:
    if value is None:
        return "no_seam"
    for left, right in ((0, .25), (.25, .5), (.5, 1), (1, 2), (2, 5)):
        if left <= value < right:
            return f"{left:g}-{right:g}"
    return "5+"


def pair_errors(row: dict[str, Any], prefix: str) -> list[float]:
    return [float(row[f"{prefix}_start_abs_error_sec"]), float(row[f"{prefix}_end_abs_error_sec"])]


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw = [value for row in rows for value in pair_errors(row, "raw")]
    fixed = [value for row in rows for value in pair_errors(row, "fixed")]
    repaired = sum(int(row["start_repaired"]) + int(row["end_repaired"]) for row in rows)
    slots = 2 * len(rows)
    return {
        "character_count": len(rows),
        "raw_boundary_abs_error_sec": stats(raw),
        "fixed_boundary_abs_error_sec": stats(fixed),
        "repair_amplification_mean_sec": (statistics.fmean(fixed) - statistics.fmean(raw)) if raw else None,
        "repaired_slot_count": repaired,
        "repaired_slot_rate": repaired / slots if slots else None,
        "raw_invalid_character_count": sum(bool(row.get("raw_invalid_interval", False)) for row in rows),
        "raw_invalid_character_rate": sum(bool(row.get("raw_invalid_interval", False)) for row in rows) / len(rows) if rows else None,
        "fixed_invalid_character_count": sum(bool(row["fixed_invalid_interval"]) for row in rows),
        "fixed_invalid_character_rate": sum(bool(row["fixed_invalid_interval"]) for row in rows) / len(rows) if rows else None,
    }


def shift_consistency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["source_item_id"]), int(row["source_character_index"]))].append(row)
    raw_values: list[float] = []
    fixed_values: list[float] = []
    by_offset: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"raw": [], "fixed": []})
    for variants in grouped.values():
        base = next((row for row in variants if float(row["variant_offset_sec"]) == 0.0), None)
        if base is None:
            continue
        for row in variants:
            offset = float(row["variant_offset_sec"])
            if offset == 0:
                continue
            for boundary in ("start", "end"):
                raw_error = abs((float(row[f"raw_{boundary}_sec"]) - offset) - float(base[f"raw_{boundary}_sec"]))
                fixed_error = abs((float(row[f"fixed_{boundary}_sec"]) - offset) - float(base[f"fixed_{boundary}_sec"]))
                raw_values.append(raw_error); fixed_values.append(fixed_error)
                by_offset[f"{offset:g}"]["raw"].append(raw_error)
                by_offset[f"{offset:g}"]["fixed"].append(fixed_error)
    return {
        "raw_shift_equivariance_error_sec": stats(raw_values),
        "fixed_shift_equivariance_error_sec": stats(fixed_values),
        "by_offset_sec": {
            offset: {
                "raw": stats(payload["raw"]),
                "fixed": stats(payload["fixed"]),
            }
            for offset, payload in sorted(by_offset.items(), key=lambda item: float(item[0]))
        },
    }


def crop_consistency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["source_item_id"]), int(row["source_character_index"]))].append(row)
    raw_values: list[float] = []
    fixed_values: list[float] = []
    by_variant: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"raw": [], "fixed": []})
    for variants in grouped.values():
        base = next((row for row in variants if row["variant_kind"] == "full"), None)
        if base is None:
            continue
        for row in variants:
            if row["variant_kind"] != "crop":
                continue
            variant = str(row["variant_item_id"]).split(":", 3)[:3]
            label = ":".join(variant)
            for boundary in ("start", "end"):
                raw_error = abs(float(row[f"raw_global_{boundary}_sec"]) - float(base[f"raw_global_{boundary}_sec"]))
                fixed_error = abs(float(row[f"fixed_global_{boundary}_sec"]) - float(base[f"fixed_global_{boundary}_sec"]))
                raw_values.append(raw_error); fixed_values.append(fixed_error)
                by_variant[label]["raw"].append(raw_error)
                by_variant[label]["fixed"].append(fixed_error)
    return {
        "raw_crop_consistency_error_sec": stats(raw_values),
        "fixed_crop_consistency_error_sec": stats(fixed_values),
        "by_crop": {key: {"raw": stats(value["raw"]), "fixed": stats(value["fixed"])} for key, value in sorted(by_variant.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(args.input_root.glob("**/diagnostic_rows.jsonl"))
    if not paths:
        raise FileNotFoundError(f"no diagnostic_rows.jsonl under {args.input_root}")
    all_rows = [row for path in paths for row in read_jsonl(path)]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        grouped[(str(row["model_name"]), str(row["experiment"]))].append(row)
    result: dict[str, Any] = {
        "schema_version": "qwen_fa_immediate_diagnostic_summary_v1",
        "input_root": str(args.input_root),
        "source_files": [str(path) for path in paths],
        "models": {},
    }
    for (model, experiment), rows in sorted(grouped.items()):
        model_entry = result["models"].setdefault(model, {})
        payload = summarize_group(rows)
        by_abs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_seam: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            midpoint = (float(row["gt_global_start_sec"]) + float(row["gt_global_end_sec"])) / 2
            by_abs[abs_time_bin(midpoint)].append(row)
            by_seam[seam_bin(row.get("distance_to_nearest_seam_sec"))].append(row)
        payload["by_absolute_time_sec"] = {key: summarize_group(value) for key, value in sorted(by_abs.items())}
        payload["by_seam_distance_sec"] = {key: summarize_group(value) for key, value in sorted(by_seam.items())}
        if experiment == "shift":
            payload["shift_consistency"] = shift_consistency(rows)
        if experiment == "crop":
            payload["crop_consistency"] = crop_consistency(rows)
        model_entry[experiment] = payload
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "models": list(result["models"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
