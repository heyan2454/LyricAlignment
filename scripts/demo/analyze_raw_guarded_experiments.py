#!/usr/bin/env python3
"""Analyze E0-E4 raw/guarded experiments from full MIR-1K evidence.

The analyzer never reruns Qwen. It keeps detector quality, intervention safety,
and candidate oracle headroom separate. Song-level rows are retained so later
confidence intervals can use songs rather than treating correlated characters
as independent samples.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.alignment_artifacts import stage_rows
from lyricalign.demo.raw_guarded import prf
from lyricalign.demo.realign_diagnostics import (
    atomic_json,
    repair_context_agreement,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def key(item: str, variant: str, core: float, index: int) -> tuple[str, str, float, int]:
    return item, variant, float(core), int(index)


def max_error(row: dict[str, Any], gt: dict[str, Any]) -> float:
    return max(
        abs(float(row["start_sec"]) - float(gt["start_sec"])),
        abs(float(row["end_sec"]) - float(gt["end_sec"])),
    )


def iter_evidence(root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    for path in sorted((root / "evidence").glob("core_*s/*/*.json")):
        payload = read_json(path)
        if payload.get("status") == "complete":
            yield path, payload


def iter_q2_cases(root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    directory = root / "q2_natural_realign" / "cases"
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        if payload.get("status") == "complete":
            yield path, payload


def _stable_recovery(errors: Sequence[bool], start: int, stable_units: int) -> int | None:
    for cursor in range(start + 1, len(errors)):
        if cursor + stable_units <= len(errors) and not any(errors[cursor:cursor + stable_units]):
            return cursor
    return None


def _cursor_counts(trace: Sequence[dict[str, Any]]) -> dict[str, int]:
    starts: list[int] = []
    for row in trace:
        value = row.get("next_window_input_character_start")
        if value is None:
            value = row.get("input_character_start_before")
        if value is not None:
            starts.append(int(value))
    repeats = sum(right <= left for left, right in zip(starts, starts[1:]))
    large_jumps = sum(right - left > 128 for left, right in zip(starts, starts[1:]))
    return {
        "cursor_observation_count": len(starts),
        "non_forward_or_repeat_count": repeats,
        "large_forward_jump_count": large_jumps,
    }


def e0_census(root: Path, tolerances: Sequence[float], stable_units: int) -> dict[str, Any]:
    songs: list[dict[str, Any]] = []
    totals = {str(t): {"units": 0, "errors": 0} for t in tolerances}
    for path, payload in iter_evidence(root):
        request = payload["request"]
        item = str(request["item_id"])
        variant = str(request["audio_variant"])
        core = float(request["core_sec"])
        gt = {int(row["character_index"]): row for row in payload["ground_truth"]}
        final = sorted(stage_rows(payload["characters"], "final"), key=lambda row: int(row["global_character_index"]))
        evaluated = [(row, gt[int(row["global_character_index"])]) for row in final if int(row["global_character_index"]) in gt]
        row_errors = [max_error(row, ref) for row, ref in evaluated]
        tolerance_rows: dict[str, Any] = {}
        for tolerance in tolerances:
            flags = [value > tolerance for value in row_errors]
            first = next((i for i, value in enumerate(flags) if value), None)
            recovery = _stable_recovery(flags, first, stable_units) if first is not None else None
            first_index = int(evaluated[first][0]["global_character_index"]) if first is not None else None
            recovery_index = int(evaluated[recovery][0]["global_character_index"]) if recovery is not None else None
            recovery_sec = None
            if first is not None and recovery is not None:
                recovery_sec = max(0.0, float(evaluated[recovery][1]["start_sec"]) - float(evaluated[first][1]["start_sec"]))
            count = sum(flags)
            totals[str(tolerance)]["units"] += len(flags)
            totals[str(tolerance)]["errors"] += count
            tolerance_rows[str(tolerance)] = {
                "error_count": count,
                "error_rate": count / len(flags) if flags else 0.0,
                "first_error_character_index": first_index,
                "recovery_character_index": recovery_index,
                "recovery_units": None if first_index is None or recovery_index is None else recovery_index - first_index,
                "recovery_sec": recovery_sec,
            }
        zero = sum(float(row["end_sec"]) <= float(row["start_sec"]) + 1e-9 for row in final)
        negative = sum(float(row["end_sec"]) < float(row["start_sec"]) - 1e-9 for row in final)
        overlaps = sum(
            float(right["start_sec"]) < float(left["end_sec"]) - 1e-9
            for left, right in zip(final, final[1:])
        )
        compressed = sum(bool(row.get("overlap_compressed")) for row in final)
        songs.append({
            "evidence_path": str(path),
            "item_id": item,
            "audio_variant": variant,
            "core_sec": core,
            "unit_count": len(evaluated),
            "duration_sec": payload.get("audio_duration_sec"),
            "tolerances": tolerance_rows,
            "structural": {
                "zero_duration_count": zero,
                "negative_duration_count": negative,
                "inter_unit_overlap_count": overlaps,
                "overlap_compressed_count": compressed,
            },
            "cursor": _cursor_counts(payload.get("window_trace") or []),
        })
    for tolerance in tolerances:
        row = totals[str(tolerance)]
        row["error_rate"] = row["errors"] / row["units"] if row["units"] else 0.0
    return {
        "schema_version": "raw_guarded_e0_census_v1",
        "stable_recovery_units": stable_units,
        "totals": totals,
        "songs": songs,
    }


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def collect_detection(root: Path) -> tuple[
    dict[tuple[str, str, float, int], dict[str, Any]],
    dict[str, set[tuple[str, str, float, int]]],
    set[tuple[str, str, float, int]],
    dict[str, float | None],
]:
    units: dict[tuple[str, str, float, int], dict[str, Any]] = {}
    triggers: dict[str, set[tuple[str, str, float, int]]] = defaultdict(set)
    detected: set[tuple[str, str, float, int]] = set()
    for _, payload in iter_evidence(root):
        request = payload["request"]
        item, variant, core = str(request["item_id"]), str(request["audio_variant"]), float(request["core_sec"])
        gt = {int(row["character_index"]): row for row in payload["ground_truth"]}
        final = {int(row["global_character_index"]): row for row in stage_rows(payload["characters"], "final")}
        for index, ref in gt.items():
            if index in final:
                units[key(item, variant, core, index)] = {"prediction": final[index], "gt": ref}
        for candidate in payload.get("natural_candidates") or []:
            keys = {key(item, variant, core, int(index)) for index in candidate.get("character_indices") or []}
            detected.update(keys)
            triggers[f"candidate_type:{candidate.get('candidate_type', 'unknown')}"] |= keys
            for name in (candidate.get("trigger_counts") or {}):
                triggers[f"trigger:{name}"] |= keys

    feature_rows: dict[tuple[str, str, float, int], dict[str, float]] = {}
    for unit_key, row in units.items():
        prediction = row["prediction"]
        margins = [prediction.get("raw_start_margin"), prediction.get("raw_end_margin")]
        probabilities = [prediction.get("raw_start_top1_probability"), prediction.get("raw_end_top1_probability")]
        entropies = [prediction.get("raw_start_entropy"), prediction.get("raw_end_entropy")]
        feature: dict[str, float] = {}
        if any(value is not None for value in margins):
            feature["margin_min"] = min(float(value) for value in margins if value is not None)
        if any(value is not None for value in probabilities):
            feature["probability_min"] = min(float(value) for value in probabilities if value is not None)
        if any(value is not None for value in entropies):
            feature["entropy_max"] = max(float(value) for value in entropies if value is not None)
        feature_rows[unit_key] = feature

    thresholds: dict[str, float | None] = {}
    for q in (0.10, 0.25):
        label = int(q * 100)
        margin_threshold = _quantile([row["margin_min"] for row in feature_rows.values() if "margin_min" in row], q)
        probability_threshold = _quantile([row["probability_min"] for row in feature_rows.values() if "probability_min" in row], q)
        entropy_threshold = _quantile([row["entropy_max"] for row in feature_rows.values() if "entropy_max" in row], 1.0 - q)
        thresholds[f"margin_bottom_{label}pct"] = margin_threshold
        thresholds[f"probability_bottom_{label}pct"] = probability_threshold
        thresholds[f"entropy_top_{label}pct"] = entropy_threshold
        if margin_threshold is not None:
            triggers[f"confidence:margin_bottom_{label}pct"] = {
                unit_key for unit_key, row in feature_rows.items()
                if row.get("margin_min") is not None and row["margin_min"] <= margin_threshold + 1e-12
            }
        if probability_threshold is not None:
            triggers[f"confidence:probability_bottom_{label}pct"] = {
                unit_key for unit_key, row in feature_rows.items()
                if row.get("probability_min") is not None and row["probability_min"] <= probability_threshold + 1e-12
            }
        if entropy_threshold is not None:
            triggers[f"confidence:entropy_top_{label}pct"] = {
                unit_key for unit_key, row in feature_rows.items()
                if row.get("entropy_max") is not None and row["entropy_max"] >= entropy_threshold - 1e-12
            }
    return units, triggers, detected, thresholds


def e1_trigger_ablation(root: Path, tolerances: Sequence[float]) -> dict[str, Any]:
    units, triggers, detected, confidence_thresholds = collect_detection(root)
    result: dict[str, Any] = {
        "schema_version": "raw_guarded_e1_trigger_ablation_v1",
        "unit_count": len(units),
        "detected_unit_count": len(detected),
        "confidence_thresholds": confidence_thresholds,
        "by_tolerance": {},
    }
    for tolerance in tolerances:
        truth = {unit_key for unit_key, row in units.items() if max_error(row["prediction"], row["gt"]) > tolerance}
        rows: dict[str, Any] = {}
        for name, selected in sorted(triggers.items()):
            tp_set = selected & truth
            other_tp = set().union(*(value & truth for key_name, value in triggers.items() if key_name != name)) if len(triggers) > 1 else set()
            rows[name] = {
                **prf(len(tp_set), len(selected - truth), len(truth - selected)),
                "detected_unit_count": len(selected),
                "unique_true_positive_count": len(tp_set - other_tp),
            }
        remaining = set(truth)
        cumulative: set[tuple[str, str, float, int]] = set()
        greedy: list[dict[str, Any]] = []
        unused = set(triggers)
        while unused:
            name = max(unused, key=lambda candidate: (len((triggers[candidate] & remaining)), -len(triggers[candidate] - truth), candidate))
            newly = triggers[name] & remaining
            cumulative |= triggers[name]
            remaining -= newly
            metric = prf(len(cumulative & truth), len(cumulative - truth), len(truth - cumulative))
            greedy.append({"trigger": name, "new_true_positive_count": len(newly), **metric})
            unused.remove(name)
        result["by_tolerance"][str(tolerance)] = {
            "true_error_unit_count": len(truth),
            "all_detector": prf(len(detected & truth), len(detected - truth), len(truth - detected)),
            "triggers": rows,
            "greedy_cumulative_order": greedy,
        }
    return result


def _candidate_delta(candidate: dict[str, Any]) -> float | None:
    before = ((candidate.get("metrics") or {}).get("before") or {}).get("boundary_mae_sec")
    after = ((candidate.get("metrics") or {}).get("after") or {}).get("boundary_mae_sec")
    if before is None or after is None:
        return None
    return float(after) - float(before)


def _eligible_base(candidate: dict[str, Any]) -> bool:
    if candidate.get("crop_mode") != "exact_anchor":
        return False
    if "direct_trust" in str(candidate.get("mode", "")):
        return False
    if str(candidate.get("anchor_mode")) in {"gt_oracle", "gt_oracle_fallback"}:
        return False
    splice = candidate.get("splice") or {}
    acceptance = candidate.get("acceptance") or {}
    before = (acceptance.get("before_anomaly") or {}).get("score")
    after = (acceptance.get("after_anomaly") or {}).get("score")
    structural = acceptance.get("structural") or {}
    anchor_error = (candidate.get("anchor_reproduction") or {}).get("max_error_sec")
    return bool(
        splice.get("valid")
        and before is not None and after is not None and float(after) < float(before)
        and int(structural.get("negative_duration_count", 0)) == 0
        and int(structural.get("inter_unit_overlap_count", 0)) == 0
        and (anchor_error is None or float(anchor_error) <= 0.16 + 1e-9)
    )


def _select_for_config(candidates: Sequence[dict[str, Any]], config: str, agreement_tolerance: float, change_cap: float) -> int | None:
    eligible: list[tuple[tuple[float, float, int], int]] = []
    for ordinal, candidate in enumerate(candidates):
        if not _eligible_base(candidate):
            continue
        if config in {"C_exact_plus2_agreement", "D_agreement_plus_change_cap"}:
            agreement = repair_context_agreement(candidates, ordinal, tolerance_sec=agreement_tolerance)
            if not agreement.get("supported"):
                continue
        change = ((candidate.get("modification_summary") or {}).get("boundary_change_abs_sec") or {}).get("max")
        if config == "D_agreement_plus_change_cap" and (change is None or float(change) > change_cap + 1e-9):
            continue
        after_score = (((candidate.get("acceptance") or {}).get("after_anomaly") or {}).get("score"))
        mean_change = ((candidate.get("modification_summary") or {}).get("boundary_change_abs_sec") or {}).get("mean")
        eligible.append(((float(after_score), float(mean_change or 0.0), ordinal), ordinal))
    return min(eligible)[1] if eligible else None


def _selected_unit_outcome(case: dict[str, Any], candidate: dict[str, Any], tolerance: float, meaningful_change: float) -> dict[str, int]:
    before = {int(row["global_character_index"]): row for row in ((case.get("original_rows") or {}).get("final") or [])}
    after = {int(row["global_character_index"]): row for row in (candidate.get("changed_rows") or [])}
    gt = {int(row["character_index"]): row for row in (case.get("ground_truth_rows") or [])}
    outcome = defaultdict(int)
    for index, changed in after.items():
        if index not in before or index not in gt:
            continue
        movement = max(abs(float(changed["start_sec"]) - float(before[index]["start_sec"])), abs(float(changed["end_sec"]) - float(before[index]["end_sec"])))
        if movement < meaningful_change - 1e-9:
            continue
        outcome["meaningfully_modified"] += 1
        before_error = max_error(before[index], gt[index])
        after_error = max_error(changed, gt[index])
        if before_error <= tolerance:
            outcome["modified_previously_correct"] += 1
            if after_error > tolerance or after_error > before_error + 1e-9:
                outcome["harmful_modified_previously_correct"] += 1
        else:
            if after_error < before_error - 1e-9:
                outcome["improved_previously_erroneous"] += 1
            elif after_error > before_error + 1e-9:
                outcome["worsened_previously_erroneous"] += 1
            if after_error <= tolerance:
                outcome["corrected_to_tolerance"] += 1
    return dict(outcome)


def _summarize_selected_entries(
    entries: Sequence[tuple[dict[str, Any], dict[str, Any]]],
    tolerance: float,
    meaningful_change: float,
) -> dict[str, Any]:
    improved = worsened = neutral = 0
    deltas: list[float] = []
    unit_totals: defaultdict[str, int] = defaultdict(int)
    modified_keys: set[tuple[str, str, float, int]] = set()
    modified_observations = 0
    for case, candidate in entries:
        delta = _candidate_delta(candidate)
        if delta is not None:
            deltas.append(delta)
            if delta < -1e-9:
                improved += 1
            elif delta > 1e-9:
                worsened += 1
            else:
                neutral += 1
        outcome = _selected_unit_outcome(case, candidate, tolerance, meaningful_change)
        for name, count in outcome.items():
            unit_totals[name] += count
        before = {int(row["global_character_index"]): row for row in ((case.get("original_rows") or {}).get("final") or [])}
        for row in candidate.get("changed_rows") or []:
            index = int(row["global_character_index"])
            if index not in before:
                continue
            movement = max(
                abs(float(row["start_sec"]) - float(before[index]["start_sec"])),
                abs(float(row["end_sec"]) - float(before[index]["end_sec"])),
            )
            if movement >= meaningful_change - 1e-9:
                modified_observations += 1
                modified_keys.add(key(str(case["item_id"]), str(case["audio_variant"]), float(case["core_sec"]), index))
    return {
        "selected_case_count": len(entries),
        "improved_case_count": improved,
        "worsened_case_count": worsened,
        "neutral_case_count": neutral,
        "mean_boundary_mae_delta_sec": sum(deltas) / len(deltas) if deltas else None,
        "min_boundary_mae_delta_sec": min(deltas, default=None),
        "max_boundary_mae_delta_sec": max(deltas, default=None),
        "modified_unit_outcome": dict(unit_totals),
        "meaningful_modified_observation_count": modified_observations,
        "unique_meaningfully_modified_unit_count": len(modified_keys),
        "duplicate_modified_observation_count": modified_observations - len(modified_keys),
    }


def _nonoverlap_entries(
    entries: Sequence[tuple[dict[str, Any], dict[str, Any]]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    grouped: dict[tuple[str, str, float], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for case, candidate in entries:
        grouped[(str(case["item_id"]), str(case["audio_variant"]), float(case["core_sec"]))].append((case, candidate))
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in grouped.values():
        occupied: set[int] = set()
        ordered = sorted(
            group,
            key=lambda entry: (
                -float((entry[0].get("source_candidate") or {}).get("severity_score", 0.0)),
                int((entry[0].get("source_candidate") or {}).get("dependency_character_start", 0)),
                str(entry[0].get("case_id", "")),
            ),
        )
        for case, candidate in ordered:
            source = case.get("source_candidate") or {}
            start = int(source.get("dependency_character_start", min(candidate.get("target_indices") or [0])))
            end = int(source.get("dependency_character_end", max(candidate.get("target_indices") or [start])))
            span = set(range(start, end + 1))
            if span & occupied:
                continue
            occupied |= span
            selected.append((case, candidate))
    return selected


def e2_guard_ablation(
    root: Path, tolerances: Sequence[float], agreement_tolerance: float, change_cap: float,
    meaningful_change: float, agreement_sweep: Sequence[float] = (0.08, 0.16, 0.24),
    change_cap_sweep: Sequence[float] = (0.24, 0.48, 0.80),
) -> dict[str, Any]:
    cases = [payload for _, payload in iter_q2_cases(root)]
    configs = ["A_keep_baseline", "B_exact_structural_gate", "C_exact_plus2_agreement", "D_agreement_plus_change_cap"]
    result: dict[str, Any] = {
        "schema_version": "raw_guarded_e2_guard_ablation_v2_nonoverlap",
        "case_count": len(cases),
        "agreement_tolerance_sec": agreement_tolerance,
        "change_cap_sec": change_cap,
        "note": (
            "independent_case_evaluation can double-count overlapping candidates; "
            "global_nonoverlap_replay mirrors the production severity-first non-overlap policy"
        ),
        "by_tolerance": {},
    }
    selected_by_config: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for config in configs:
        entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if config != "A_keep_baseline":
            for case in cases:
                candidates = case.get("repair_candidates") or []
                ordinal = _select_for_config(candidates, config, agreement_tolerance, change_cap)
                if ordinal is not None:
                    entries.append((case, candidates[ordinal]))
        selected_by_config[config] = entries
    for tolerance in tolerances:
        config_rows: dict[str, Any] = {}
        for config in configs:
            independent = _summarize_selected_entries(selected_by_config[config], tolerance, meaningful_change)
            global_entries = _nonoverlap_entries(selected_by_config[config])
            global_summary = _summarize_selected_entries(global_entries, tolerance, meaningful_change)
            config_rows[config] = {
                **global_summary,
                "independent_case_evaluation": independent,
                "global_nonoverlap_replay": global_summary,
            }
        result["by_tolerance"][str(tolerance)] = config_rows

    primary_tolerance = 0.16 if any(abs(value - 0.16) < 1e-9 for value in tolerances) else float(tolerances[0])
    agreement_rows: dict[str, Any] = {}
    for value in agreement_sweep:
        entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for case in cases:
            candidates = case.get("repair_candidates") or []
            ordinal = _select_for_config(candidates, "C_exact_plus2_agreement", float(value), change_cap)
            if ordinal is not None:
                entries.append((case, candidates[ordinal]))
        agreement_rows[str(value)] = _summarize_selected_entries(
            _nonoverlap_entries(entries), primary_tolerance, meaningful_change
        )
    cap_rows: dict[str, Any] = {}
    for value in change_cap_sweep:
        entries = []
        for case in cases:
            candidates = case.get("repair_candidates") or []
            ordinal = _select_for_config(candidates, "D_agreement_plus_change_cap", agreement_tolerance, float(value))
            if ordinal is not None:
                entries.append((case, candidates[ordinal]))
        cap_rows[str(value)] = _summarize_selected_entries(
            _nonoverlap_entries(entries), primary_tolerance, meaningful_change
        )
    result["one_dimensional_sensitivity"] = {
        "primary_error_tolerance_sec": primary_tolerance,
        "agreement_tolerance_sweep": agreement_rows,
        "boundary_change_cap_sweep": cap_rows,
        "note": "one-dimensional offline sweeps; no additional Qwen inference and no full Cartesian grid",
    }
    return result


def e3_oracle(root: Path) -> dict[str, Any]:
    cases = [payload for _, payload in iter_q2_cases(root)]
    rows: dict[str, dict[str, Any]] = {}
    modes = {
        "exact": lambda c: c.get("crop_mode") == "exact_anchor",
        "matched_plus2": lambda c: c.get("crop_mode") == "matched_context" and int(c.get("context_units") or 0) == 2,
        "best_exact_or_plus2": lambda c: c.get("crop_mode") == "exact_anchor" or (c.get("crop_mode") == "matched_context" and int(c.get("context_units") or 0) == 2),
    }
    for mode, predicate in modes.items():
        improved = worsened = available = 0
        deltas: list[float] = []
        for case in cases:
            candidates = [candidate for candidate in (case.get("repair_candidates") or []) if predicate(candidate) and "direct_trust" not in str(candidate.get("mode", ""))]
            candidate_deltas = [value for value in (_candidate_delta(candidate) for candidate in candidates) if value is not None]
            if not candidate_deltas:
                continue
            available += 1
            best = min(candidate_deltas)
            deltas.append(best)
            if best < -1e-9: improved += 1
            elif best > 1e-9: worsened += 1
        rows[mode] = {
            "available_case_count": available,
            "oracle_improved_case_count": improved,
            "oracle_worsened_case_count": worsened,
            "oracle_improvement_rate": improved / available if available else 0.0,
            "mean_best_delta_sec": sum(deltas) / len(deltas) if deltas else None,
        }
    automatic_improved = automatic_worsened = automatic_selected = 0
    for case in cases:
        selection = case.get("final_non_gt_selection") or {}
        if not selection.get("selected"):
            continue
        ordinal = selection.get("candidate_ordinal")
        candidates = case.get("repair_candidates") or []
        if ordinal is None or not (0 <= int(ordinal) < len(candidates)):
            continue
        automatic_selected += 1
        delta = _candidate_delta(candidates[int(ordinal)])
        if delta is not None and delta < -1e-9: automatic_improved += 1
        elif delta is not None and delta > 1e-9: automatic_worsened += 1
    return {
        "schema_version": "raw_guarded_e3_oracle_v1",
        "case_count": len(cases),
        "oracle": rows,
        "automatic": {
            "selected_case_count": automatic_selected,
            "improved_case_count": automatic_improved,
            "worsened_case_count": automatic_worsened,
        },
    }


def e4_clean_control(root: Path) -> dict[str, Any]:
    directory = root / "q3_injection_matrix" / "cases"
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        if payload.get("status") == "complete" and str(payload.get("family", "")).startswith("clean_"):
            families[str(payload["family"])].append(payload)
    result: dict[str, Any] = {"schema_version": "raw_guarded_e4_clean_control_v1", "families": {}}
    for family, cases in sorted(families.items()):
        selected = improved = worsened = neutral = 0
        deltas: list[float] = []
        for case in cases:
            selection = case.get("final_non_gt_selection") or {}
            if not selection.get("selected"):
                continue
            candidates = case.get("repair_candidates") or []
            ordinal = selection.get("candidate_ordinal")
            if ordinal is None or not (0 <= int(ordinal) < len(candidates)):
                continue
            selected += 1
            delta = _candidate_delta(candidates[int(ordinal)])
            if delta is None: continue
            deltas.append(delta)
            if delta < -1e-9: improved += 1
            elif delta > 1e-9: worsened += 1
            else: neutral += 1
        result["families"][family] = {
            "case_count": len(cases),
            "selected_case_count": selected,
            "improved_case_count": improved,
            "worsened_case_count": worsened,
            "neutral_case_count": neutral,
            "mean_boundary_mae_delta_sec": sum(deltas) / len(deltas) if deltas else None,
        }
    return result


def markdown_summary(parts: dict[str, Any]) -> str:
    e0, e1, e2, e3, e4 = (parts[name] for name in ("e0", "e1", "e2", "e3", "e4"))
    lines = [
        "# Raw + guarded experiment suite summary", "",
        "This report keeps broad detection and actual write-back separate.", "",
        "## E0 — raw baseline census", "",
    ]
    for tolerance, row in e0["totals"].items():
        lines.append(f"- tolerance `{float(tolerance)*1000:.0f} ms`: {row['errors']}/{row['units']} errors ({row['error_rate']:.2%})")
    lines += ["", "## E1 — detector", ""]
    for tolerance, row in e1["by_tolerance"].items():
        metric = row["all_detector"]
        lines.append(f"- `{float(tolerance)*1000:.0f} ms`: P={metric['precision']:.3f}, R={metric['recall']:.3f}, F1={metric['f1']:.3f}")
    lines += ["", "## E2 — guard ablation (160 ms)", ""]
    primary = e2["by_tolerance"].get("0.16") or next(iter(e2["by_tolerance"].values()), {})
    for name, row in primary.items():
        lines.append(f"- `{name}`: selected={row['selected_case_count']}, improved={row['improved_case_count']}, worsened={row['worsened_case_count']}, mean delta={row['mean_boundary_mae_delta_sec']}")
    lines += ["", "## E3 — oracle headroom", ""]
    for name, row in e3["oracle"].items():
        lines.append(f"- `{name}`: oracle improvement {row['oracle_improved_case_count']}/{row['available_case_count']} ({row['oracle_improvement_rate']:.1%})")
    lines += ["", "## E4 — clean controls", ""]
    if e4["families"]:
        for name, row in e4["families"].items():
            lines.append(f"- `{name}`: selected={row['selected_case_count']}/{row['case_count']}, worsened={row['worsened_case_count']}")
    else:
        lines.append("- no completed clean-control cases found")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="full evidence/q2/q3 experiment root")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--tolerances-sec", nargs="+", type=float, default=[0.08, 0.16, 0.24])
    parser.add_argument("--stable-recovery-units", type=int, default=3)
    parser.add_argument("--agreement-tolerance-sec", type=float, default=0.16)
    parser.add_argument("--max-repair-boundary-change-sec", type=float, default=0.80)
    parser.add_argument("--meaningful-change-sec", type=float, default=0.04)
    args = parser.parse_args()
    if args.stable_recovery_units < 1:
        raise ValueError("--stable-recovery-units must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    parts = {
        "e0": e0_census(args.root, args.tolerances_sec, args.stable_recovery_units),
        "e1": e1_trigger_ablation(args.root, args.tolerances_sec),
        "e2": e2_guard_ablation(args.root, args.tolerances_sec, args.agreement_tolerance_sec, args.max_repair_boundary_change_sec, args.meaningful_change_sec),
        "e3": e3_oracle(args.root),
        "e4": e4_clean_control(args.root),
    }
    names = {
        "e0": "e0_raw_baseline_census.json",
        "e1": "e1_detector_trigger_ablation.json",
        "e2": "e2_guard_ablation.json",
        "e3": "e3_repair_oracle.json",
        "e4": "e4_clean_control.json",
    }
    for key_name, filename in names.items():
        atomic_json(args.out_dir / filename, parts[key_name])
    summary = {"schema_version": "raw_guarded_experiment_suite_v1", **parts}
    atomic_json(args.out_dir / "experiment_suite_summary.json", summary)
    (args.out_dir / "experiment_suite_summary.md").write_text(markdown_summary(parts), encoding="utf-8")
    print(json.dumps({"status": "complete", "out_dir": str(args.out_dir.resolve()), "files": list(names.values()) + ["experiment_suite_summary.json", "experiment_suite_summary.md"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
