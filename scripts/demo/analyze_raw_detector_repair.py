#!/usr/bin/env python3
"""Compute GT-backed detector and intervention metrics for raw guarded realignment.

Input is the full evidence/q2 output, not the compact handoff. Metrics are
reported separately for broad detection and actual selected modification.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.alignment_artifacts import stage_rows
from lyricalign.demo.raw_guarded import prf
from lyricalign.demo.realign_diagnostics import atomic_json


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def key(item: str, variant: str, core: float, index: int) -> tuple[str, str, float, int]:
    return item, variant, float(core), int(index)


def max_error(row: dict[str, Any], gt: dict[str, Any]) -> float:
    return max(abs(float(row["start_sec"]) - float(gt["start_sec"])), abs(float(row["end_sec"]) - float(gt["end_sec"])))


def collect_evidence(root: Path) -> tuple[dict[tuple[str, str, float, int], dict[str, Any]], set[tuple[str, str, float, int]], list[dict[str, Any]]]:
    units: dict[tuple[str, str, float, int], dict[str, Any]] = {}
    detected: set[tuple[str, str, float, int]] = set()
    cases: list[dict[str, Any]] = []
    for path in sorted((root / "evidence").glob("core_*s/*/*.json")):
        payload = read_json(path)
        if payload.get("status") != "complete":
            continue
        request = payload["request"]
        item = str(request["item_id"])
        variant = str(request["audio_variant"])
        core = float(request["core_sec"])
        gt = {int(row["character_index"]): row for row in payload["ground_truth"]}
        final = {int(row["global_character_index"]): row for row in stage_rows(payload["characters"], "final")}
        for index, gt_row in gt.items():
            if index not in final:
                continue
            units[key(item, variant, core, index)] = {"prediction": final[index], "gt": gt_row}
        for candidate in payload.get("natural_candidates", []):
            indices = [int(v) for v in candidate.get("character_indices", [])]
            case_keys = [key(item, variant, core, index) for index in indices]
            detected.update(case_keys)
            cases.append({"candidate": candidate, "unit_keys": case_keys})
    return units, detected, cases


def collect_selected(q2_root: Path) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    case_root = q2_root / "q2_natural_realign" / "cases"
    for path in sorted(case_root.glob("*.json")):
        payload = read_json(path)
        selection = payload.get("final_non_gt_selection") or {}
        if not selection.get("selected"):
            continue
        ordinal = selection.get("candidate_ordinal")
        repairs = payload.get("repair_candidates") or []
        if ordinal is None or not (0 <= int(ordinal) < len(repairs)):
            continue
        repair = repairs[int(ordinal)]
        selected.append({"payload": payload, "selection": selection, "repair": repair})
    return selected


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-root", type=Path, required=True)
    p.add_argument("--q2-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--tolerances-sec", nargs="+", type=float, default=[0.08, 0.16, 0.24])
    p.add_argument("--meaningful-change-sec", type=float, default=0.04)
    args = p.parse_args()

    units, detected, cases = collect_evidence(args.baseline_root)
    selections = collect_selected(args.q2_root)
    report: dict[str, Any] = {
        "schema_version": "raw_detector_repair_metrics_v1",
        "baseline_root": str(args.baseline_root.resolve()),
        "q2_root": str(args.q2_root.resolve()),
        "unit_count": len(units),
        "detected_unit_count": len(detected),
        "natural_case_count": len(cases),
        "selected_case_count": len(selections),
        "meaningful_change_sec": args.meaningful_change_sec,
        "by_tolerance": {},
    }

    for tolerance in args.tolerances_sec:
        truth = {unit_key for unit_key, row in units.items() if max_error(row["prediction"], row["gt"]) > tolerance}
        tp = len(detected & truth)
        fp = len(detected - truth)
        fn = len(truth - detected)
        case_tp = case_fp = 0
        trigger_sets: dict[str, set[tuple[str, str, float, int]]] = defaultdict(set)
        for case in cases:
            if any(unit_key in truth for unit_key in case["unit_keys"]):
                case_tp += 1
            else:
                case_fp += 1
            candidate = case["candidate"]
            trigger_sets[f"candidate_type:{candidate.get('candidate_type', 'unknown')}"].update(case["unit_keys"])
            for trigger in (candidate.get("trigger_counts") or {}):
                trigger_sets[f"trigger:{trigger}"].update(case["unit_keys"])

        selected_case_improved = selected_case_worsened = selected_case_neutral = 0
        meaningful_modified = corrected = harmful_correct = modified_correct = improved_error = worsened_error = 0
        false_detected_correct_unmodified = len((detected - truth))
        modified_keys: set[tuple[str, str, float, int]] = set()
        for entry in selections:
            payload = entry["payload"]
            repair = entry["repair"]
            metrics = repair.get("metrics") or {}
            before_mae = (metrics.get("before") or {}).get("boundary_mae_sec")
            after_mae = (metrics.get("after") or {}).get("boundary_mae_sec")
            if before_mae is not None and after_mae is not None:
                delta = float(after_mae) - float(before_mae)
                if delta < -1e-9:
                    selected_case_improved += 1
                elif delta > 1e-9:
                    selected_case_worsened += 1
                else:
                    selected_case_neutral += 1
            item = str(payload["item_id"])
            variant = str(payload["audio_variant"])
            core = float(payload["core_sec"])
            before_rows = {int(row["global_character_index"]): row for row in (payload.get("original_rows", {}).get("final") or [])}
            after_rows = {int(row["global_character_index"]): row for row in (repair.get("changed_rows") or [])}
            gt_rows = {int(row["character_index"]): row for row in (payload.get("ground_truth_rows") or [])}
            for index, after in after_rows.items():
                if index not in before_rows or index not in gt_rows:
                    continue
                before = before_rows[index]
                gt = gt_rows[index]
                change = max(abs(float(after["start_sec"]) - float(before["start_sec"])), abs(float(after["end_sec"]) - float(before["end_sec"])))
                if change < args.meaningful_change_sec - 1e-9:
                    continue
                unit_key = key(item, variant, core, index)
                modified_keys.add(unit_key)
                meaningful_modified += 1
                before_error = max_error(before, gt)
                after_error = max_error(after, gt)
                if before_error > tolerance:
                    if after_error <= tolerance:
                        corrected += 1
                    if after_error < before_error - 1e-9:
                        improved_error += 1
                    elif after_error > before_error + 1e-9:
                        worsened_error += 1
                else:
                    modified_correct += 1
                    if after_error > tolerance or after_error > before_error + 1e-9:
                        harmful_correct += 1
        false_detected_correct_unmodified = len((detected - truth) - modified_keys)
        intervention_fp = meaningful_modified - corrected
        intervention_fn = len(truth) - corrected
        trigger_prf = {}
        for trigger_name, trigger_detected in sorted(trigger_sets.items()):
            trigger_tp = len(trigger_detected & truth)
            trigger_fp = len(trigger_detected - truth)
            trigger_fn = len(truth - trigger_detected)
            trigger_prf[trigger_name] = {
                **prf(trigger_tp, trigger_fp, trigger_fn),
                "detected_unit_count": len(trigger_detected),
            }

        report["by_tolerance"][str(tolerance)] = {
            "error_definition": f"max(onset_abs_error, offset_abs_error) > {tolerance:.3f}s",
            "population": {
                "evaluated_unit_count": len(units),
                "true_error_unit_count": len(truth),
                "true_correct_unit_count": len(units) - len(truth),
                "error_prevalence": len(truth) / len(units) if units else 0.0,
                "detected_unit_count": len(detected),
                "selected_modified_unit_count": len(modified_keys),
            },
            "detector_unit_prf": prf(tp, fp, fn),
            "detector_by_trigger": trigger_prf,
            "detector_case": {
                "true_error_case_count": case_tp,
                "false_alarm_case_count": case_fp,
                "precision": case_tp / (case_tp + case_fp) if case_tp + case_fp else 0.0,
            },
            "correct_units_false_detected_but_unmodified_count": false_detected_correct_unmodified,
            "correct_units_false_detected_and_modified_count": len((detected - truth) & modified_keys),
            "intervention_correction_prf": prf(corrected, intervention_fp, intervention_fn),
            "selected_case_outcome": {
                "improved": selected_case_improved,
                "worsened": selected_case_worsened,
                "neutral": selected_case_neutral,
            },
            "modified_unit_outcome": {
                "meaningfully_modified": meaningful_modified,
                "modified_previously_correct": modified_correct,
                "harmful_modified_previously_correct": harmful_correct,
                "harmful_rate_within_modified_correct": harmful_correct / modified_correct if modified_correct else 0.0,
                "improved_previously_erroneous": improved_error,
                "worsened_previously_erroneous": worsened_error,
                "corrected_to_tolerance": corrected,
            },
        }

    atomic_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
