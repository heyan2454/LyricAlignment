#!/usr/bin/env python3
"""Recompute corrected tolerant character metrics from preserved row-level evidence.

This tool never overwrites the original metric file unless the caller explicitly
chooses the same output path. The recommended output is ``metrics.corrected.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.metrics.character import evaluate_tolerant


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_original(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def recompute(
    *,
    references: Path,
    predictions: Path,
    output: Path,
    original_metrics: Path | None = None,
    primary_tolerance: float = 1e-12,
) -> dict[str, Any]:
    reference_rows = read_jsonl(references)
    prediction_rows = read_jsonl(predictions)
    corrected = evaluate_tolerant(reference_rows, prediction_rows)
    original = load_original(original_metrics)
    original_metric = original.get("metric", original) if original else {}
    old_primary = original_metric.get("song_macro_boundary_mae_sec")
    new_primary = corrected["song_macro_boundary_mae_sec"]
    primary_delta = None if old_primary is None else new_primary - float(old_primary)
    if primary_delta is not None and abs(primary_delta) > primary_tolerance:
        raise RuntimeError(
            "correcting auxiliary prediction-state metrics unexpectedly changed "
            f"song_macro_boundary_mae_sec by {primary_delta}"
        )

    result: dict[str, Any] = {
        "schema_version": 1,
        "recomputed_at": datetime.now(timezone.utc).isoformat(),
        "recompute_tool": "scripts/evaluation/recompute_character_metrics.py",
        "references_path": str(references),
        "references_sha256": sha256(references),
        "predictions_path": str(predictions),
        "predictions_sha256": sha256(predictions),
        "original_metrics_path": str(original_metrics) if original_metrics else None,
        "original_metrics_sha256": sha256(original_metrics) if original_metrics and original_metrics.is_file() else None,
        "primary_metric_unchanged": primary_delta is None or abs(primary_delta) <= primary_tolerance,
        "primary_metric_delta_sec": primary_delta,
        "metric": corrected,
    }
    if "loss" in original:
        result["loss"] = original["loss"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--original-metrics", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--primary-tolerance", type=float, default=1e-12)
    args = parser.parse_args()
    result = recompute(
        references=args.references,
        predictions=args.predictions,
        original_metrics=args.original_metrics,
        output=args.out,
        primary_tolerance=args.primary_tolerance,
    )
    print(json.dumps({
        "out": str(args.out),
        "metric_schema_version": result["metric"]["metric_schema_version"],
        "primary_metric_unchanged": result["primary_metric_unchanged"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
