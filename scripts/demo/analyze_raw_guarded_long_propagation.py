#!/usr/bin/env python3
"""Analyze E5 long-sequence propagation and seam-masked accuracy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.alignment_artifacts import stage_rows
from lyricalign.demo.realign_diagnostics import atomic_json


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def max_error(row: dict[str, Any], gt: dict[str, Any]) -> float:
    return max(abs(float(row["start_sec"]) - float(gt["start_sec"])), abs(float(row["end_sec"]) - float(gt["end_sec"])))


def stable_recovery(flags: list[bool], start: int, stable_units: int) -> int | None:
    for cursor in range(start + 1, len(flags)):
        if cursor + stable_units <= len(flags) and not any(flags[cursor:cursor + stable_units]):
            return cursor
    return None


def near_seam(gt: dict[str, Any], seams: list[float], margin: float) -> bool:
    center = 0.5 * (float(gt["start_sec"]) + float(gt["end_sec"]))
    return any(abs(center - seam) <= margin + 1e-9 for seam in seams)


def selected_case_deltas(result_root: Path, item_id: str) -> list[float]:
    deltas: list[float] = []
    for path in sorted((result_root / "q2_natural_realign" / "cases").glob(f"*{item_id}*.json")):
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        if str(payload.get("item_id")) != item_id:
            continue
        selection = payload.get("final_non_gt_selection") or {}
        ordinal = selection.get("candidate_ordinal")
        candidates = payload.get("repair_candidates") or []
        if not selection.get("selected") or ordinal is None or not (0 <= int(ordinal) < len(candidates)):
            continue
        metrics = candidates[int(ordinal)].get("metrics") or {}
        before = (metrics.get("before") or {}).get("boundary_mae_sec")
        after = (metrics.get("after") or {}).get("boundary_mae_sec")
        if before is not None and after is not None:
            deltas.append(float(after) - float(before))
    return deltas


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--subset-root", type=Path, required=True)
    p.add_argument("--result-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--tolerance-sec", type=float, default=0.16)
    p.add_argument("--seam-margin-sec", type=float, default=0.5)
    p.add_argument("--stable-recovery-units", type=int, default=3)
    args = p.parse_args()
    songs: list[dict[str, Any]] = []
    for path in sorted((args.result_root / "evidence").glob("core_*s/demucs/*.json")):
        payload = read_json(path)
        if payload.get("status") != "complete":
            continue
        item_id = str(payload["request"]["item_id"])
        item_root = args.subset_root / "items" / item_id
        provenance = read_json(item_root / "source_manifest.json")
        seams = [float(value) for value in provenance.get("join_points_sec") or []]
        gt = {int(row["character_index"]): row for row in payload["ground_truth"]}
        final = sorted(stage_rows(payload["characters"], "final"), key=lambda row: int(row["global_character_index"]))
        evaluated = [(row, gt[int(row["global_character_index"])]) for row in final if int(row["global_character_index"]) in gt]
        errors = [max_error(row, ref) > args.tolerance_sec for row, ref in evaluated]
        internal = [not near_seam(ref, seams, args.seam_margin_sec) for _, ref in evaluated]
        internal_errors = sum(flag and keep for flag, keep in zip(errors, internal, strict=True))
        first = next((index for index, flag in enumerate(errors) if flag), None)
        recovery = stable_recovery(errors, first, args.stable_recovery_units) if first is not None else None
        zero = sum(float(row["end_sec"]) <= float(row["start_sec"]) + 1e-9 for row in final)
        compressed = sum(bool(row.get("overlap_compressed")) for row in final)
        trace = payload.get("window_trace") or []
        cursor = [int(row["next_window_input_character_start"]) for row in trace if row.get("next_window_input_character_start") is not None]
        deltas = selected_case_deltas(args.result_root, item_id)
        songs.append({
            "item_id": item_id,
            "source_item_id": provenance.get("source_item_id"),
            "duration_sec": provenance.get("duration_sec"),
            "join_points_sec": seams,
            "unit_count": len(evaluated),
            "error_count": sum(errors),
            "error_rate": sum(errors) / len(errors) if errors else 0.0,
            "seam_masked_internal_unit_count": sum(internal),
            "seam_masked_internal_error_count": internal_errors,
            "seam_masked_internal_error_rate": internal_errors / sum(internal) if sum(internal) else 0.0,
            "first_error_character_index": None if first is None else int(evaluated[first][0]["global_character_index"]),
            "recovery_character_index": None if recovery is None else int(evaluated[recovery][0]["global_character_index"]),
            "recovery_units": None if first is None or recovery is None else recovery - first,
            "zero_duration_count": zero,
            "overlap_compressed_count": compressed,
            "cursor_non_forward_or_repeat_count": sum(right <= left for left, right in zip(cursor, cursor[1:])),
            "selected_repair_count": len(deltas),
            "selected_repair_improved_count": sum(value < -1e-9 for value in deltas),
            "selected_repair_worsened_count": sum(value > 1e-9 for value in deltas),
            "selected_repair_mean_delta_sec": sum(deltas) / len(deltas) if deltas else None,
        })
    total_units = sum(row["unit_count"] for row in songs)
    total_errors = sum(row["error_count"] for row in songs)
    internal_units = sum(row["seam_masked_internal_unit_count"] for row in songs)
    internal_errors = sum(row["seam_masked_internal_error_count"] for row in songs)
    report = {
        "schema_version": "raw_guarded_e5_long_propagation_v1",
        "tolerance_sec": args.tolerance_sec,
        "seam_margin_sec": args.seam_margin_sec,
        "audio_origin": "m4singer_clean_vocal_not_demucs_output",
        "song_count": len(songs),
        "unit_count": total_units,
        "error_count": total_errors,
        "error_rate": total_errors / total_units if total_units else 0.0,
        "seam_masked_internal_unit_count": internal_units,
        "seam_masked_internal_error_count": internal_errors,
        "seam_masked_internal_error_rate": internal_errors / internal_units if internal_units else 0.0,
        "songs": songs,
    }
    atomic_json(args.output, report)
    print(json.dumps({"status": "complete", "output": str(args.output.resolve()), "song_count": len(songs)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
