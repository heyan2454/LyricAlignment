#!/usr/bin/env python3
"""Collect Quick v2/v2.1 results and build a size-bounded handoff archive.

The full evidence and full per-case payloads remain under OUT_ROOT.  The default
handoff archive contains compact per-case summaries and excludes large window
traces, local row dumps, inference logits/audits, and repeated whole-song rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.realign_diagnostics import collect_quick_results, utc_now


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def compact_metric(metric: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "requested_unit_count", "matched_unit_count", "missing_unit_count", "missing_indices",
        "onset_mae_sec", "offset_mae_sec", "boundary_mae_sec", "boundary_median_sec",
        "boundary_p90_sec", "boundary_max_sec", "joint_within_0p08_rate",
        "joint_within_0p16_rate", "joint_within_0p50_rate",
    )
    return {key: metric.get(key) for key in keep if key in metric}


def compact_repair(candidate: dict[str, Any], ordinal: int) -> dict[str, Any]:
    metrics = candidate.get("metrics", {})
    return {
        "ordinal": ordinal,
        "mode": candidate.get("mode"),
        "anchor_mode": candidate.get("anchor_mode"),
        "crop_mode": candidate.get("crop_mode"),
        "padding_sec": candidate.get("padding_sec"),
        "context_units": candidate.get("context_units"),
        "target_indices": candidate.get("target_indices"),
        "replacement_indices": candidate.get("replacement_indices"),
        "splice": candidate.get("splice"),
        "anchor_reproduction": candidate.get("anchor_reproduction"),
        "acceptance": candidate.get("acceptance"),
        "modification_summary": candidate.get("modification_summary"),
        "metrics": {
            "before": compact_metric(metrics.get("before", {})),
            "after": compact_metric(metrics.get("after", {})),
            "replacement_before": compact_metric(metrics.get("replacement_before", {})),
            "replacement_after": compact_metric(metrics.get("replacement_after", {})),
        },
    }


def compact_case(payload: dict[str, Any], source_path: Path, *, minimal: bool) -> dict[str, Any]:
    base = {
        "source_path": str(source_path),
        "schema_version": payload.get("schema_version"),
        "case_id": payload.get("case_id"),
        "family": payload.get("family"),
        "item_id": payload.get("item_id"),
        "audio_variant": payload.get("audio_variant"),
        "core_sec": payload.get("core_sec"),
        "target_indices": payload.get("target_indices") or payload.get("source_candidate", {}).get("character_indices"),
        "final_non_gt_selection": payload.get("final_non_gt_selection"),
    }
    if payload.get("source_candidate") is not None:
        source = payload["source_candidate"]
        base["source_candidate"] = {
            key: source.get(key) for key in (
                "case_id", "candidate_type", "observed_character_start", "observed_character_end",
                "dependency_character_start", "dependency_character_end", "target_unit_count",
                "trigger_counts", "trigger_flags_by_index", "constraint_dependency_trace",
                "cross_window_disagreement_peak_sec", "cross_window_disagreement_metadata", "severity_score",
            ) if key in source
        }
    if payload.get("detector") is not None:
        detector = payload["detector"]
        base["detector"] = {
            "known_injected": detector.get("known_injected"),
            "injection_effectiveness": detector.get("injection_effectiveness"),
            "structural": detector.get("structural"),
            "baseline_target": compact_metric(detector.get("baseline_target", {})),
            "perturbed_target": compact_metric(detector.get("perturbed_target", {})),
        }
    if payload.get("injection") is not None:
        injection = payload["injection"]
        base["injection"] = {
            key: value for key, value in injection.items()
            if key not in {"raw_rows", "decoded_rows", "perturbed_target_rows", "inference_audit"}
        }
    if not minimal:
        base["original_rows"] = payload.get("original_rows")
        base["stage_transition_provenance"] = payload.get("stage_transition_provenance")
        base["ground_truth_rows"] = payload.get("ground_truth_rows")
        base["repair_candidates"] = [
            compact_repair(candidate, ordinal)
            for ordinal, candidate in enumerate(payload.get("repair_candidates", []))
        ]
        base["context_consensus"] = payload.get("context_consensus")
    else:
        selected_ordinal = payload.get("final_non_gt_selection", {}).get("candidate_ordinal")
        repairs = payload.get("repair_candidates", [])
        selected = []
        if isinstance(selected_ordinal, int) and 0 <= selected_ordinal < len(repairs):
            selected.append(compact_repair(repairs[selected_ordinal], selected_ordinal))
        base["selected_repair_candidate"] = selected[0] if selected else None
        base["repair_candidate_count"] = len(repairs)
    return base


def selector_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in rows if (row.get("final_non_gt_selection") or {}).get("selected")]
    gt_selected = [
        row for row in selected
        if str((row.get("final_non_gt_selection") or {}).get("anchor_mode")) in {"gt_oracle", "gt_oracle_fallback"}
    ]
    context_required = [
        row for row in selected
        if (row.get("final_non_gt_selection") or {}).get("require_context_agreement")
    ]
    context_supported = [
        row for row in context_required
        if ((row.get("final_non_gt_selection") or {}).get("context_agreement") or {}).get("supported")
    ]
    mode_counts: dict[str, int] = {}
    anchor_counts: dict[str, int] = {}
    crop_counts: dict[str, int] = {}
    deltas: list[float] = []
    for row in selected:
        selection = row.get("final_non_gt_selection") or {}
        for mapping, key in ((mode_counts, "mode"), (anchor_counts, "anchor_mode"), (crop_counts, "crop_mode")):
            value = str(selection.get(key))
            mapping[value] = mapping.get(value, 0) + 1
        candidate = row.get("selected_repair_candidate")
        if candidate is None:
            ordinal = selection.get("candidate_ordinal")
            repairs = row.get("repair_candidates") or []
            if isinstance(ordinal, int) and 0 <= ordinal < len(repairs):
                candidate = repairs[ordinal]
        if candidate:
            metrics = candidate.get("metrics") or {}
            before = (metrics.get("before") or {}).get("boundary_mae_sec")
            after = (metrics.get("after") or {}).get("boundary_mae_sec")
            if before is not None and after is not None:
                deltas.append(float(after) - float(before))
    return {
        "schema_version": "demo_realign_quick_v2_1_selector_audit",
        "created_at": utc_now(),
        "case_count": len(rows),
        "selected_case_count": len(selected),
        "ground_truth_anchor_selected_count": len(gt_selected),
        "ground_truth_anchor_selection_passed": len(gt_selected) == 0,
        "context_agreement_required_selected_count": len(context_required),
        "context_agreement_supported_selected_count": len(context_supported),
        "selection_mode_counts": dict(sorted(mode_counts.items())),
        "selection_anchor_mode_counts": dict(sorted(anchor_counts.items())),
        "selection_crop_mode_counts": dict(sorted(crop_counts.items())),
        "selected_gt_boundary_mae_delta_sec": {
            "count": len(deltas),
            "mean": sum(deltas) / len(deltas) if deltas else None,
            "improved_count": sum(delta < -1e-12 for delta in deltas),
            "unchanged_count": sum(abs(delta) <= 1e-12 for delta in deltas),
            "worsened_count": sum(delta > 1e-12 for delta in deltas),
            "worst_worsening_sec": max(deltas, default=None),
        },
    }


def copy_if_exists(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def build_staging(out_root: Path, staging: Path, *, minimal: bool) -> dict[str, Any]:
    fixed = [
        "summary.json", "failure_summary.json", "plan.json", "resolved_inputs.json",
        "resolved_model_source.txt", "resolved_checkpoint.txt", "command.sh",
        "return_code.txt", "collect_return_code.txt", "repair_candidates.csv",
        "q1_anchor_scan/aggregate.json", "q1_anchor_scan/recommended_shortlist.json",
        "q1_anchor_scan/precision_coverage.csv", "q2_natural_realign/comparison.json",
        "q2_v2_1_selector_audit.json",
        "q2_natural_realign/trace.md", "q3_injection_matrix/detector_summary.json",
        "q3_injection_matrix/repair_summary.json", "q3_injection_matrix/plan.resolved.json",
    ]
    for relative in fixed:
        copy_if_exists(out_root / relative, staging / relative)
    for log_name in ("quick_controller.log", "collect.log", "nohup.log"):
        source = out_root / "logs" / log_name
        if source.is_file():
            # Keep only the last 1 MiB of each log in the upload package.
            data = source.read_bytes()
            destination = staging / "logs" / log_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data[-1024 * 1024:])

    counts: dict[str, int] = {}
    compact_rows_by_family: dict[str, list[dict[str, Any]]] = {}
    for family, directory in (
        ("q2", out_root / "q2_natural_realign" / "cases"),
        ("q3", out_root / "q3_injection_matrix" / "cases"),
    ):
        rows = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                if path.name.endswith((".status.json", ".failure.json")):
                    continue
                try:
                    payload = read_json(path)
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("status") == "complete":
                    rows.append(compact_case(payload, path, minimal=minimal))
        write_jsonl(staging / f"{family}_cases_compact.jsonl", rows)
        compact_rows_by_family[family] = rows
        counts[family] = len(rows)
    write_json(staging / "q2_v2_1_selector_audit.json", selector_audit(compact_rows_by_family.get("q2", [])))
    manifest = {
        "schema_version": "demo_realign_quick_v2_1_compact_handoff",
        "created_at": utc_now(),
        "source_out_root": str(out_root),
        "minimal_mode": minimal,
        "excluded": [
            "evidence/**", "full per-case JSON", "local row dumps", "window traces",
            "inference audits/logits", "repeated whole-song metric details",
        ],
        "case_counts": counts,
        "full_results_remain_on_server": True,
    }
    write_json(staging / "COMPACT_HANDOFF_MANIFEST.json", manifest)
    return manifest


def make_archive(staging: Path, archive_path: Path, root_name: str) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with tarfile.open(temporary, "w:gz") as tar:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(Path(root_name) / path.relative_to(staging)), recursive=False)
    temporary.replace(archive_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--exclude-evidence", action="store_true", help="legacy alias; compact mode is preferred")
    parser.add_argument("--max-archive-mib", type=float, default=10.0)
    args = parser.parse_args()
    out_root = args.out_root.resolve()
    summary, failures = collect_quick_results(out_root)
    q2_audit_rows: list[dict[str, Any]] = []
    q2_directory = out_root / "q2_natural_realign" / "cases"
    if q2_directory.exists():
        for path in sorted(q2_directory.glob("*.json")):
            if path.name.endswith((".status.json", ".failure.json")):
                continue
            try:
                payload = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("status") == "complete":
                q2_audit_rows.append(compact_case(payload, path, minimal=True))
    write_json(out_root / "q2_v2_1_selector_audit.json", selector_audit(q2_audit_rows))
    archive_path = None
    archive_size = None
    used_minimal_mode = False
    if args.archive:
        archive_path = args.archive.resolve()
        if args.compact or args.exclude_evidence:
            with tempfile.TemporaryDirectory(prefix="realign_quick_v2_collect_") as temp:
                staging = Path(temp)
                build_staging(out_root, staging, minimal=False)
                make_archive(staging, archive_path, out_root.name)
                limit = int(args.max_archive_mib * 1024 * 1024)
                if archive_path.stat().st_size > limit:
                    used_minimal_mode = True
                    shutil.rmtree(staging)
                    staging.mkdir(parents=True)
                    build_staging(out_root, staging, minimal=True)
                    make_archive(staging, archive_path, out_root.name)
                archive_size = archive_path.stat().st_size
                if archive_size > limit:
                    raise RuntimeError(
                        f"compact archive is {archive_size / 1024 / 1024:.2f} MiB, above "
                        f"the requested {args.max_archive_mib:.2f} MiB limit"
                    )
        else:
            with tarfile.open(archive_path, "w:gz") as tar:
                for path in sorted(out_root.rglob("*")):
                    if path.is_file() and path != archive_path:
                        tar.add(path, arcname=str(Path(out_root.name) / path.relative_to(out_root)), recursive=False)
            archive_size = archive_path.stat().st_size
    print(json.dumps({
        "created_at": utc_now(),
        "summary_path": str(out_root / "summary.json"),
        "failure_summary_path": str(out_root / "failure_summary.json"),
        "archive_path": str(archive_path) if archive_path else None,
        "archive_size_bytes": archive_size,
        "minimal_compact_mode": used_minimal_mode,
        "summary": summary,
        "failure_count": failures["failure_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
