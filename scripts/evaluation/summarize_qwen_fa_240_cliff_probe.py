#!/usr/bin/env python3
"""Summarize the controlled Qwen FA ~240 s cliff probe."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def finite_mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def segment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fixed_errors: list[float] = []
    raw_errors: list[float] = []
    signed_class_errors: list[int] = []
    gt_probabilities: list[float] = []
    repaired = 0
    slots = 0
    for row in rows:
        fixed_errors.extend(
            [float(row["fixed_start_abs_error_sec"]), float(row["fixed_end_abs_error_sec"])]
        )
        raw_errors.extend(
            [float(row["raw_start_abs_error_sec"]), float(row["raw_end_abs_error_sec"])]
        )
        signed_class_errors.extend(
            [
                int(row["raw_start_signed_class_error"]),
                int(row["raw_end_signed_class_error"]),
            ]
        )
        for key in ("gt_start_class_probability", "gt_end_class_probability"):
            if row.get(key) is not None:
                gt_probabilities.append(float(row[key]))
        repaired += int(bool(row["start_repaired"])) + int(bool(row["end_repaired"]))
        slots += 2
    return {
        "character_count": len(rows),
        "slot_count": slots,
        "raw_mae_sec": finite_mean(raw_errors),
        "fixed_mae_sec": finite_mean(fixed_errors),
        "raw_signed_class_error_mean": finite_mean([float(value) for value in signed_class_errors]),
        "raw_signed_class_error_min": min(signed_class_errors) if signed_class_errors else None,
        "raw_signed_class_error_max": max(signed_class_errors) if signed_class_errors else None,
        "gt_class_probability_mean": finite_mean(gt_probabilities),
        "repaired_slot_rate": repaired / slots if slots else None,
        "catastrophic_fixed_gt_5s": bool(fixed_errors and finite_mean(fixed_errors) > 5.0),
    }


def tensor_length(audit: dict[str, Any], key: str, dimension: int) -> int | None:
    shape = audit.get("tensors", {}).get(key, {}).get("shape")
    if not isinstance(shape, list) or len(shape) <= dimension:
        return None
    return int(shape[dimension])


def summarize_model(model_dir: Path) -> dict[str, Any]:
    identity = json.loads((model_dir / "identity.json").read_text(encoding="utf-8"))
    selection = json.loads((model_dir / "selection.json").read_text(encoding="utf-8"))
    config = json.loads((model_dir / "config_probe.json").read_text(encoding="utf-8"))
    items = {row["variant_item_id"]: row for row in read_jsonl(model_dir / "item_summary.jsonl")}
    audits = {row["variant_item_id"]: row for row in read_jsonl(model_dir / "input_audit.jsonl")}
    rows_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(model_dir / "diagnostic_rows.jsonl"):
        rows_by_variant[str(row["variant_item_id"])].append(row)

    variants: list[dict[str, Any]] = []
    for variant_id, item in items.items():
        audit = audits[variant_id]
        rows = rows_by_variant[variant_id]
        by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_role[str(row.get("segment_role") or "all")].append(row)
        variants.append(
            {
                "condition": item.get("probe_condition"),
                "variant_item_id": variant_id,
                "variant_kind": item["variant_kind"],
                "offset_sec": float(item["variant_offset_sec"]),
                "audio_duration_sec": float(item["audio_duration_sec"]),
                "input_ids_length": tensor_length(audit, "input_ids", 1),
                "attention_mask_valid_tokens": (
                    audit.get("tensors", {})
                    .get("attention_mask", {})
                    .get("nonzero_count_by_sample", [None])[0]
                ),
                "input_feature_frames": tensor_length(audit, "input_features", 2),
                "input_feature_valid_frames": (
                    audit.get("tensors", {})
                    .get("input_features_mask", {})
                    .get("nonzero_count_by_sample", [None])[0]
                ),
                "timestamp_logit_class_count": int(item["timestamp_logit_class_count"]),
                "overall": segment_summary(rows),
                "segments": {role: segment_summary(role_rows) for role, role_rows in sorted(by_role.items())},
            }
        )
    variants.sort(key=lambda row: (row["variant_kind"], row["offset_sec"], str(row["condition"])))

    sweep = [row for row in variants if row["variant_kind"] == "shift_cliff_sweep"]
    controls = [row for row in variants if row["variant_kind"] == "equal_total_control"]
    first_catastrophic = next(
        (row for row in sorted(sweep, key=lambda row: row["offset_sec"]) if row["overall"]["catastrophic_fixed_gt_5s"]),
        None,
    )
    return {
        "identity": identity,
        "selection": selection,
        "config_probe": config,
        "variants": variants,
        "shift_sweep": sweep,
        "equal_total_controls": controls,
        "first_catastrophic_shift": first_catastrophic,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    models: dict[str, Any] = {}
    for model_dir in sorted(path for path in args.input_root.iterdir() if path.is_dir()):
        required = (
            "identity.json",
            "selection.json",
            "config_probe.json",
            "diagnostic_rows.jsonl",
            "item_summary.jsonl",
            "input_audit.jsonl",
        )
        if all((model_dir / name).is_file() for name in required):
            models[model_dir.name] = summarize_model(model_dir)
    if not models:
        raise RuntimeError(f"no completed model probes under {args.input_root}")

    conditions: dict[str, dict[str, Any]] = defaultdict(dict)
    for model_name, model in models.items():
        for variant in model["variants"]:
            conditions[str(variant["condition"])][model_name] = {
                "offset_sec": variant["offset_sec"],
                "input_ids_length": variant["input_ids_length"],
                "audio_duration_sec": variant["audio_duration_sec"],
                "overall_fixed_mae_sec": variant["overall"]["fixed_mae_sec"],
                "overall_raw_mae_sec": variant["overall"]["raw_mae_sec"],
                "A_fixed_mae_sec": variant["segments"].get("A", {}).get("fixed_mae_sec"),
                "B_fixed_mae_sec": variant["segments"].get("B", {}).get("fixed_mae_sec"),
                "catastrophic": variant["overall"]["catastrophic_fixed_gt_5s"],
            }

    payload = {
        "schema_version": "qwen_fa_240_cliff_summary_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input_root),
        "models": models,
        "condition_comparison": dict(sorted(conditions.items())),
        "interpretation_contract": {
            "equal_total_late_A": "silence(240)+A+B; A and B are late",
            "equal_total_mid_A": "silence(180)+A+silence(60)+B; A is mid, B has same late start",
            "equal_total_early_A": "A+silence(240)+B; A is early, B has same late start",
            "rules": [
                "If A changes with position while B is consistently bad, target absolute position is implicated.",
                "If both A and B are bad in all three equal-total controls, total input length is implicated.",
                "If early A is good but the same late B is bad in all controls, late target position is implicated.",
                "If the cliff coincides with a sharp input_ids-length threshold, inspect position/token limits.",
            ],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"models": sorted(models), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
