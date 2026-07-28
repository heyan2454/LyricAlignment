#!/usr/bin/env python3
"""Collect a bounded evidence archive from the inline-realign experiment."""
from __future__ import annotations

import argparse
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in materialized),
        encoding="utf-8",
    )
    return len(materialized)


def copy_evidence_file(source: Path, destination: Path) -> None:
    """Copy one evidence file after creating its relative destination tree.

    State records live below nested paths such as ``state/items/<item>.json``.
    A fresh temporary staging directory contains none of those parents, so raw
    ``shutil.copy2`` raises ``FileNotFoundError`` unless the collector creates
    them explicitly.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def read_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]



_HEAVY_KEYS = {
    "decoded_rows", "baseline_rows", "processor_units", "audit", "attempts",
    "replacement_preview", "fused_replacement_rows", "rows", "audio", "waveform",
    "logits", "hidden_states", "full_alignment",
}

def recursively_compact(value: Any, *, depth: int = 0, max_list: int = 24) -> Any:
    """Bound nested evidence such as context trials without losing decisions."""
    if depth > 8:
        return {"truncated": True, "reason": "maximum_compaction_depth"}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key in _HEAVY_KEYS:
                if isinstance(child, list):
                    result[f"{key}_count"] = len(child)
                elif child is not None:
                    result[f"{key}_omitted"] = True
                continue
            result[key] = recursively_compact(child, depth=depth + 1, max_list=max_list)
        return result
    if isinstance(value, list):
        compacted = [recursively_compact(child, depth=depth + 1, max_list=max_list) for child in value[:max_list]]
        if len(value) > max_list:
            compacted.append({"truncated": True, "total_count": len(value), "kept_count": max_list})
        return compacted
    return value

def compact_followup_payload(filename: str, payload: dict[str, Any], *, mode: str, max_cases: int) -> dict[str, Any]:
    """Keep stage evidence useful without copying large per-attempt diagnostic bodies."""
    if mode == "full":
        return payload
    result = {key: value for key, value in payload.items() if key not in {
        "trials", "windows", "cases", "decisions", "audit", "processor_units",
        "replacement_preview", "anchor_diagnostics", "rows",
    }}
    list_key = next((key for key in ("trials", "windows", "cases", "decisions") if isinstance(payload.get(key), list)), None)
    if list_key is not None:
        rows = list(payload.get(list_key) or [])
        compact_rows: list[dict[str, Any]] = []
        for row in rows[:max_cases]:
            compact_rows.append(recursively_compact(row, max_list=max(8, max_cases * 4)))
        result[list_key] = compact_rows
        result[f"{list_key}_total_count"] = len(rows)
        result[f"{list_key}_truncated"] = len(rows) > len(compact_rows)
    result["evidence_compaction"] = {"mode": mode, "source": filename}
    return result


def compact_stable_segment(segment: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in segment.items() if key != "rows"}


def compact_attempt(attempt: dict[str, Any], *, include_probes: bool) -> dict[str, Any]:
    keep = (
        "attempt_index", "expansion_index", "status", "target_character_count",
        "budget_support_sec", "candidate_character_start", "candidate_character_end",
        "committed_prefix_count", "lookahead_count", "core_boundary_observed",
        "next_input_boundary_observed", "next_window_input_character_start",
        "output_decoder_kind", "serial_control_decoder_kind",
    )
    result = {key: attempt.get(key) for key in keep}
    if include_probes:
        result["probe_rows"] = list(attempt.get("probe_rows") or [])
    else:
        result["probe_row_count"] = len(attempt.get("probe_rows") or [])
    return result


def compact_window(item_id: str, branch: str, row: dict[str, Any], *, include_probes: bool) -> dict[str, Any]:
    stable_suffix = row.get("stable_suffix_candidate")
    return {
        "item_id": item_id,
        "branch": branch,
        "window_index": row.get("window_index"),
        "core_start_sec": row.get("core_start_sec"),
        "core_end_sec": row.get("core_end_sec"),
        "input_start_sec": row.get("input_start_sec"),
        "input_end_sec": row.get("input_end_sec"),
        "window_plan_policy": row.get("window_plan_policy"),
        "input_character_start_before": row.get("input_character_start_before"),
        "committed_cursor_before": row.get("committed_cursor_before"),
        "committed_cursor_after": row.get("committed_cursor_after"),
        "committed_character_start": row.get("committed_character_start"),
        "committed_character_end": row.get("committed_character_end"),
        "next_window_input_character_start": row.get("next_window_input_character_start"),
        "next_uncommitted_character_start": row.get("next_uncommitted_character_start"),
        "vocal_activity": row.get("vocal_activity"),
        "precommit_diagnostic": row.get("precommit_diagnostic"),
        "attempt_expansion_stability": row.get("attempt_expansion_stability"),
        "stable_prefix_reproduction": row.get("stable_prefix_reproduction"),
        "stable_suffix_candidate": (
            None if stable_suffix is None else compact_stable_segment(stable_suffix)
        ),
        "attempts": [
            compact_attempt(attempt, include_probes=include_probes)
            for attempt in row.get("attempts", [])
        ],
    }


def anomaly_indices(payload: dict[str, Any], *, radius: int = 4) -> set[int]:
    result: set[int] = set()
    for window in payload.get("window_trace", []):
        diagnostic = window.get("precommit_diagnostic") or {}
        if not diagnostic.get("triggered"):
            continue
        spans = list(diagnostic.get("anomaly_spans") or [])
        if not spans:
            spans = [{
                "character_start": int(window.get("committed_character_start", 0)),
                "character_end": max(
                    int(window.get("committed_character_start", 0)),
                    int(window.get("committed_character_end", 0)) - 1,
                ),
            }]
        for span in spans:
            start = int(span["character_start"]); end = int(span["character_end"])
            for index in range(max(0, start - radius), end + radius + 1):
                result.add(index)
    for row in payload.get("characters", []):
        index = int(row["global_character_index"])
        duration = float(row["end_sec"]) - float(row["start_sec"])
        if duration <= 1e-9 or bool(row.get("overlap_compressed")):
            for nearby in range(max(0, index - radius), index + radius + 1):
                result.add(nearby)
    return result


def compact_character(item_id: str, branch: str, row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "global_character_index", "character", "line_index", "start_sec", "end_sec",
        "selected_start_sec", "selected_end_sec", "raw_global_start_sec", "raw_global_end_sec",
        "official_fixed_global_start_sec", "official_fixed_global_end_sec",
        "raw_boundary_margin_mean", "owner_window_index", "overlap_compressed",
        "overlap_compression_sec", "overlap_compression_collapsed_to_zero",
    )
    return {"item_id": item_id, "branch": branch, **{field: row.get(field) for field in fields}}


def collect(root: Path, staging: Path, *, mode: str, max_cases: int) -> dict[str, Any]:
    for filename in (
        "input_audit.json", "experiment_manifest.jsonl", "experiment_summary.json",
        "complete.json", "run_status.jsonl", "pipeline_request.json",
        "pipeline_status.jsonl", "pipeline_complete.json", "pipeline_failure.json",
        "demo_render_summary.json", "demo_publish_summary.json", "followup_analysis_summary.json",
        "followup_analysis_summary.md", "resolved_config.json", "visualization_summary.json",
        "live_status.json", "experiment_live_status.json", "analysis_complete.json",
        "render_complete.json",
    ):
        source = root / filename
        if source.is_file():
            copy_evidence_file(source, staging / filename)
    state_root = root / "state"
    for source in sorted(state_root.rglob("*.json")) if state_root.is_dir() else []:
        relative = source.relative_to(root)
        # State files are compact identities/status records and are essential for resume audit.
        copy_evidence_file(source, staging / relative)
    character_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    item_summaries: list[dict[str, Any]] = []
    manifest_rows = read_manifest(root / "experiment_manifest.jsonl")
    manifest_ids = [str(row.get("item_id")) for row in manifest_rows]
    all_item_roots = sorted(path for path in (root / "items").glob("*") if path.is_dir())
    stale_item_ids = [path.name for path in all_item_roots if path.name not in set(manifest_ids)]
    item_roots = [root / "items" / item_id for item_id in manifest_ids if (root / "items" / item_id).is_dir()]
    visual_index: list[dict[str, Any]] = []
    for item_root in item_roots:
        item_id = item_root.name
        item_summary = read_json(item_root / "item_summary.json")
        if item_summary:
            item_summaries.append(item_summary)
        failure = read_json(item_root / "failure.json")
        if failure:
            write_json(staging / "failures" / f"{item_id}.json", failure)
        shadow = read_json(item_root / "inline_realign_shadow.json")
        decisions = sorted(
            shadow.get("decisions", []),
            key=lambda row: (not bool(row.get("automatic_gate_accepted_shadow") or row.get("gt_oracle_improved_shadow") or row.get("manual_gate_accepted_shadow")), -int((row.get("trigger") or {}).get("severity", 0))),
        )[:max_cases]
        for decision in decisions:
            case_rows.append({"item_id": item_id, **recursively_compact(decision, max_list=max(8, max_cases * 4))})
        for filename in (
            "stable_window_assistance.json",
            "stable_window_assistance_trials.json",
            "text_dosage_trials.json",
            "forced_expansion_trials.json",
            "pending_confirmation_shadow.json",
            "tail_two_window_rollback_shadow.json",
            "legacy_r2_comparison.json",
            "synthetic_seam_gt_summary.json",
        ):
            payload = read_json(item_root / filename)
            if payload:
                write_json(
                    staging / "followup_experiments" / item_id / filename,
                    compact_followup_payload(filename, payload, mode=mode, max_cases=max_cases),
                )
        automatic_incomplete = read_json(item_root / "automatic_incomplete_shadow" / "alignment.json")
        if automatic_incomplete:
            write_json(staging / "automatic_incomplete_shadows" / f"{item_id}.json", {
                "item_id": item_id,
                "summary": automatic_incomplete.get("summary"),
                "unresolved": automatic_incomplete.get("unresolved"),
                "automatic_shadow_only": automatic_incomplete.get("automatic_shadow_only"),
            })
        incomplete = read_json(item_root / "incomplete_guard" / "alignment.json")
        if incomplete:
            write_json(staging / "incomplete_guards" / f"{item_id}.json", {
                "item_id": item_id,
                "summary": incomplete.get("summary"),
                "unresolved": incomplete.get("unresolved"),
                "constructed_for_validation": incomplete.get("constructed_for_validation"),
            })
        visual = read_json(item_root / "visuals" / "visual_analysis.json")
        if visual:
            visual_index.append({
                "item_id": item_id,
                "pages": visual.get("pages"),
                "duration_distributions": visual.get("duration_distributions"),
                "structural": visual.get("structural"),
                "inconsistency": visual.get("inconsistency"),
                "detector_span_count": visual.get("detector_span_count"),
                "available_visual_files": [
                    str(path.relative_to(root)) for path in sorted((item_root / "visuals").rglob("*")) if path.is_file()
                ],
                "available_render_files": [
                    str(path.relative_to(root)) for path in sorted((item_root / "renders").rglob("*.mp4")) if path.is_file()
                ],
            })
        experimental_summaries: list[dict[str, Any]] = []
        for alignment_path in sorted((item_root / "experimental_alignments").glob("*/alignment.json")):
            payload = read_json(alignment_path)
            experimental_summaries.append({
                "variant": alignment_path.parent.name,
                "summary": payload.get("summary"),
                "experimental": payload.get("experimental"),
            })
        if experimental_summaries:
            write_json(staging / "experimental_alignment_summaries" / f"{item_id}.json", {
                "item_id": item_id, "variants": experimental_summaries,
            })
        for branch_root in sorted((item_root / "branches").glob("*")):
            alignment_path = branch_root / "alignment.json"
            if not alignment_path.is_file():
                continue
            branch = branch_root.name
            payload = read_json(alignment_path)
            planner = payload.get("planner_divergence") or {}
            if planner:
                write_json(
                    staging / "followup_experiments" / item_id / f"{branch}_planner_divergence.json",
                    {
                        "item_id": item_id, "branch": branch,
                        "evaluated_window_count": planner.get("evaluated_window_count"),
                        "diverged_window_count": planner.get("diverged_window_count"),
                        "first_divergence_window": planner.get("first_divergence_window"),
                        "windows": [row for row in planner.get("windows", []) if row.get("diverged")],
                    },
                )
            indices = anomaly_indices(payload)
            rows = payload.get("characters", [])
            if mode == "full":
                selected = rows
            elif mode == "anomaly":
                selected = [row for row in rows if int(row["global_character_index"]) in indices]
            else:
                selected = [
                    row for row in rows
                    if float(row["end_sec"]) - float(row["start_sec"]) <= 1e-9
                    or bool(row.get("overlap_compression_collapsed_to_zero"))
                ]
            if mode == "minimal":
                selected = selected[:32]
            character_rows.extend(compact_character(item_id, branch, row) for row in selected)
            selected_windows = list(payload.get("window_trace", []))
            if mode == "minimal":
                selected_windows = [row for row in selected_windows if (row.get("precommit_diagnostic") or {}).get("triggered")][:8]
            window_rows.extend(
                compact_window(item_id, branch, row, include_probes=mode == "full")
                for row in selected_windows
            )
            summary = read_json(branch_root / "summary.json")
            if summary:
                write_json(staging / "branch_summaries" / item_id / f"{branch}.json", summary)
    write_json(staging / "item_summaries.json", item_summaries)
    write_json(staging / "visual_index.json", visual_index)
    write_json(staging / "stale_item_report.json", {
        "manifest_item_count": len(manifest_ids),
        "collected_item_count": len(item_roots),
        "stale_item_directory_count": len(stale_item_ids),
        "stale_item_directories": stale_item_ids,
    })
    character_count = write_jsonl(staging / "characters.jsonl", character_rows)
    window_count = write_jsonl(staging / "windows.jsonl", window_rows)
    case_count = write_jsonl(staging / "inline_realign_cases.jsonl", case_rows)
    return {
        "mode": mode,
        "item_count": len(item_roots),
        "manifest_item_count": len(manifest_ids),
        "stale_item_directory_count": len(stale_item_ids),
        "character_row_count": character_count,
        "window_row_count": window_count,
        "case_row_count": case_count,
    }


def make_archive(staging: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
        archive.add(staging, arcname="inline_realign_evidence")
    temporary.replace(output)
    return output.stat().st_size


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input_root", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--max-total-mib", type=float, default=8.0)
    p.add_argument("--max-cases-per-item", type=int, default=12)
    return p


def main() -> int:
    args = parser().parse_args()
    root = args.input_root.expanduser().resolve()
    if not (root / "experiment_summary.json").is_file():
        raise FileNotFoundError(root / "experiment_summary.json")
    output = (
        args.output or root / "inline_realign_evidence.tar.gz"
    ).expanduser().resolve()
    cap = int(args.max_total_mib * 1024 * 1024)
    attempts = (
        ("full", args.max_cases_per_item, None),
        ("anomaly", min(args.max_cases_per_item, 8), "full_evidence_exceeded_cap"),
        ("severe", min(args.max_cases_per_item, 4), "anomaly_evidence_exceeded_cap"),
        ("minimal", min(args.max_cases_per_item, 2), "severe_evidence_exceeded_cap"),
    )
    size = 0
    metadata: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="inline_realign_collect_") as temporary:
        staging = Path(temporary) / "staging"
        for mode, max_cases, fallback in attempts:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            metadata = collect(root, staging, mode=mode, max_cases=max_cases)
            write_json(staging / "collection_manifest.json", {
                "schema_version": "inline_realign_evidence_collection_v2",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "input_root": str(root),
                "max_total_bytes": cap,
                "fallback_reason": fallback,
                **metadata,
                "excluded": [
                    "audio", "video", "model weights", "full stdout logs",
                    "full non-anomalous character rows when size fallback is active",
                    "rendered videos and ASS work files",
                ],
            })
            size = make_archive(staging, output)
            if size <= cap:
                break
    if size > cap:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"bounded evidence exceeds cap: {size} > {cap}")
    print(json.dumps({
        "status": "complete", "output": str(output),
        "size_bytes": size, "size_mib": size / (1024 * 1024),
        "cap_mib": args.max_total_mib, **metadata,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
