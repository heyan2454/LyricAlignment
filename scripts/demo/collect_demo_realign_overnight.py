#!/usr/bin/env python3
"""Collect smoke/overnight summaries and build a size-bounded handoff archive."""
from __future__ import annotations

import argparse
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def copy_if_exists(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def plan_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def case_summary(root: Path) -> dict[str, Any]:
    comparison = root / "q2_natural_realign" / "comparison.json"
    if comparison.is_file():
        return read_json(comparison)
    cases = root / "q2_natural_realign" / "cases"
    return {
        "case_count": len([path for path in cases.glob("*.json") if not path.name.endswith((".status.json", ".failure.json"))]) if cases.exists() else 0,
        "failure_count": len(list(cases.glob("*.failure.json"))) if cases.exists() else 0,
    }


def compact_selected_cases(source_root: Path, destination: Path, maximum: int = 20) -> None:
    cases = []
    for path in sorted(source_root.glob("*.json")):
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        selection = payload.get("final_non_gt_selection") or {}
        if selection.get("selected"):
            cases.append({
                "case_id": payload.get("case_id"),
                "item_id": payload.get("item_id"),
                "audio_variant": payload.get("audio_variant"),
                "core_sec": payload.get("core_sec"),
                "source_candidate": payload.get("source_candidate"),
                "final_non_gt_selection": selection,
            })
        if len(cases) >= maximum:
            break
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in cases:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--max-archive-mib", type=float, default=10.0)
    args = parser.parse_args()
    root = args.out_root.resolve()
    stages = []
    for path in sorted((root / "stage_status").glob("*.json")):
        stages.append(read_json(path))
    summary = {
        "status": "complete" if stages and all(row.get("status") in {"complete", "complete_empty_plan"} for row in stages if not str(row.get("stage", "")).startswith("99_")) else "incomplete",
        "input_audit": read_json(root / "input_audit.json") if (root / "input_audit.json").is_file() else None,
        "decoder_cache": read_json(root / "decoder_cache" / "summary.json") if (root / "decoder_cache" / "summary.json").is_file() else None,
        "decoder_training": {
            architecture: read_json(root / "decoder_training" / architecture / "summary.json")
            if (root / "decoder_training" / architecture / "summary.json").is_file() else None
            for architecture in ("tcn", "transformer")
        },
        "decoder_evaluation": {
            architecture: read_json(root / "decoder_evaluation" / architecture / "metrics.json")
            if (root / "decoder_evaluation" / architecture / "metrics.json").is_file() else None
            for architecture in ("tcn", "transformer")
        },
        "plans": {profile: plan_count(root / "plans" / f"{profile}.jsonl") for profile in ("exact", "plus2", "plus4")},
        "realign": {
            profile: {
                decoder: case_summary(root / "realign" / profile / decoder)
                for decoder in ("official", "gpu_tcn", "gpu_transformer")
            }
            for profile in ("exact", "plus2", "plus4")
        },
        "stage_status": stages,
        "interpretation": {
            "m4singer_item_count_is_not_anomaly_count": True,
            "paired_realign": True,
            "decoder_families": ["official", "gpu_tcn", "gpu_transformer"],
            "cartesian_product_executed": False,
            "funnel": ["exact", "plus2", "plus4"],
        },
    }
    atomic_json(root / "overnight_summary.json", summary)

    with tempfile.TemporaryDirectory(prefix="lyricalign_overnight_collect_") as temporary_dir:
        staging = Path(temporary_dir) / "handoff"
        fixed = [
            "input_audit.json", "overnight_summary.json",
            "decoder_cache/summary.json",
            "decoder_training/tcn/summary.json", "decoder_training/tcn/resolved_data.json",
            "decoder_training/transformer/summary.json", "decoder_training/transformer/resolved_data.json",
            "decoder_evaluation/tcn/metrics.json", "decoder_evaluation/transformer/metrics.json",
        ]
        for relative in fixed:
            copy_if_exists(root / relative, staging / relative)
        for path in sorted((root / "stage_status").glob("*.json")):
            copy_if_exists(path, staging / "stage_status" / path.name)
        for profile in ("exact", "plus2", "plus4"):
            copy_if_exists(root / "plans" / f"{profile}.jsonl", staging / "plans" / f"{profile}.jsonl")
            copy_if_exists(root / "plans" / f"{profile}.summary.json", staging / "plans" / f"{profile}.summary.json")
            for decoder in ("official", "gpu_tcn", "gpu_transformer"):
                source = root / "realign" / profile / decoder / "q2_natural_realign"
                copy_if_exists(source / "comparison.json", staging / "realign" / profile / decoder / "comparison.json")
                compact_selected_cases(source / "cases", staging / "realign" / profile / decoder / "selected_cases.compact.jsonl")
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        temporary_archive = args.archive.with_suffix(args.archive.suffix + ".tmp")
        with tarfile.open(temporary_archive, "w:gz") as archive:
            archive.add(staging, arcname="LyricAlignment_overnight_handoff")
        size = temporary_archive.stat().st_size
        maximum = int(args.max_archive_mib * 1024 * 1024)
        if size > maximum:
            temporary_archive.unlink()
            raise RuntimeError(f"compact archive exceeds limit: {size} > {maximum} bytes")
        temporary_archive.replace(args.archive)
    print(json.dumps({"summary": str(root / "overnight_summary.json"), "archive": str(args.archive), "archive_bytes": args.archive.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
