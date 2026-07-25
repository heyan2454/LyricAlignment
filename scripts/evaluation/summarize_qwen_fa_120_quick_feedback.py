#!/usr/bin/env python3
"""Create compact JSON and Markdown readouts for the quick 120s probes."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    grouped: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(args.input_root.rglob("item_summary.jsonl")):
        if any("identity_mismatch" in part or ".incomplete" in part for part in path.parts):
            continue
        for row in read_jsonl(path):
            experiment = str(row["experiment"])
            if experiment == "shift":
                x = float(row["variant_offset_sec"])
            else:
                condition = row.get("probe_condition") or {}
                x = float(condition.get("requested_total_duration_sec", row["declared_duration_sec"]))
            grouped[(str(row["model_name"]), experiment, x)].append(row)
    if not grouped:
        raise ValueError(f"no item_summary.jsonl under {args.input_root}")

    series: list[dict[str, Any]] = []
    baselines: dict[tuple[str, str], float] = {}
    for model, experiment in sorted({(key[0], key[1]) for key in grouped}):
        xs = sorted(key[2] for key in grouped if key[0] == model and key[1] == experiment)
        baseline_x = 0.0
        baseline_rows = grouped[(model, experiment, baseline_x)]
        baseline = mean([float(row["fixed_boundary_error_sec"]["mean"]) for row in baseline_rows])
        if baseline is None:
            raise RuntimeError("missing baseline")
        baselines[(model, experiment)] = baseline
        for x in xs:
            rows = grouped[(model, experiment, x)]
            fixed = mean([float(row["fixed_boundary_error_sec"]["mean"]) for row in rows])
            raw = mean([float(row["raw_boundary_error_sec"]["mean"]) for row in rows])
            repair = mean([float(row["repaired_slot_rate"]) for row in rows])
            amplification = mean([float(row["repair_amplification_mean_sec"]) for row in rows])
            assert fixed is not None and raw is not None and repair is not None and amplification is not None
            series.append(
                {
                    "model": model,
                    "experiment": experiment,
                    "x_sec": x,
                    "x_label": "native" if experiment == "tailpad" and x == 0 else f"{x:g}",
                    "sample_count": len(rows),
                    "fixed_boundary_mae_sec": fixed,
                    "raw_boundary_mae_sec": raw,
                    "fixed_delta_vs_baseline_sec": fixed - baseline,
                    "repaired_slot_rate": repair,
                    "repair_amplification_mean_sec": amplification,
                }
            )

    payload = {
        "schema_version": "qwen_fa_120_quick_feedback_summary_v1",
        "scope": "diagnostic_only; no training and no checkpoint selection",
        "interpretation": {
            "shift": "same short content moved later by prefix silence; tests absolute timestamp position",
            "tailpad": "target remains early while trailing silence increases total input length",
        },
        "series": series,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Qwen FA 120s quick feedback",
        "",
        "> Diagnostic only. These probes do not select checkpoints and do not replace natural-long evaluation.",
        "",
    ]
    for experiment, title in (("shift", "Absolute-position shift"), ("tailpad", "Fixed-position total-length")):
        lines.extend([f"## {title}", "", "| model | x (s) | samples | fixed MAE (s) | delta vs baseline (s) | raw MAE (s) | repaired slots |", "|---|---:|---:|---:|---:|---:|---:|"])
        for row in [item for item in series if item["experiment"] == experiment]:
            lines.append(
                f"| {row['model']} | {row['x_label']} | {row['sample_count']} | "
                f"{row['fixed_boundary_mae_sec']:.4f} | {row['fixed_delta_vs_baseline_sec']:+.4f} | "
                f"{row['raw_boundary_mae_sec']:.4f} | {row['repaired_slot_rate']:.2%} |"
            )
        lines.append("")
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
