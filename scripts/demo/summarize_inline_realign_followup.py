#!/usr/bin/env python3
"""Summarize follow-up inline-realign experiments into compact JSON and Markdown.

The summary intentionally keeps automatic detection, GT-oracle experiments,
window-assistance trials, and constructed incomplete outputs separate. This
prevents oracle or validation-only artifacts from being reported as automatic
production gains.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_mean(values: Iterable[Any]) -> float | None:
    materialized = [value for item in values if (value := finite(item)) is not None]
    return statistics.fmean(materialized) if materialized else None


def safe_median(values: Iterable[Any]) -> float | None:
    materialized = [value for item in values if (value := finite(item)) is not None]
    return statistics.median(materialized) if materialized else None


def safe_max(values: Iterable[Any]) -> float | None:
    materialized = [value for item in values if (value := finite(item)) is not None]
    return max(materialized) if materialized else None


def percentile(values: Iterable[Any], quantile: float) -> float | None:
    materialized = sorted(value for item in values if (value := finite(item)) is not None)
    if not materialized:
        return None
    if len(materialized) == 1:
        return materialized[0]
    position = (len(materialized) - 1) * quantile
    lower = int(math.floor(position)); upper = int(math.ceil(position))
    if lower == upper:
        return materialized[lower]
    fraction = position - lower
    return materialized[lower] * (1.0 - fraction) + materialized[upper] * fraction


def counter_dict(counter: collections.Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def rows_by_index(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["global_character_index"]): row
        for row in payload.get("characters", [])
        if row.get("global_character_index") is not None
    }


def compare_branches(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rows = rows_by_index(left); right_rows = rows_by_index(right)
    common = sorted(set(left_rows) & set(right_rows))
    timing_changed = 0; owner_changed = 0; movements: list[float] = []
    for index in common:
        a = left_rows[index]; b = right_rows[index]
        local = [
            abs(float(a.get("start_sec", 0.0)) - float(b.get("start_sec", 0.0))),
            abs(float(a.get("end_sec", 0.0)) - float(b.get("end_sec", 0.0))),
        ]
        movements.extend(local)
        timing_changed += max(local) > 1e-9
        owner_changed += a.get("owner_window_index") != b.get("owner_window_index")
    left_gt = (left.get("summary") or {}).get("gt") or {}
    right_gt = (right.get("summary") or {}).get("gt") or {}
    left_mae = finite(left_gt.get("boundary_mae_sec")); right_mae = finite(right_gt.get("boundary_mae_sec"))
    return {
        "common_character_count": len(common),
        "timing_changed_character_count": timing_changed,
        "owner_changed_character_count": owner_changed,
        "max_boundary_movement_sec": max(movements, default=None),
        "median_boundary_movement_sec": statistics.median(movements) if movements else None,
        "b3_minus_b2_boundary_mae_sec": (
            None if left_mae is None or right_mae is None else right_mae - left_mae
        ),
    }


def summarize(root: Path) -> dict[str, Any]:
    experiment = read_json(root / "experiment_summary.json")
    manifest_rows: list[dict[str, Any]] = []
    manifest_path = root / "experiment_manifest.jsonl"
    if manifest_path.is_file():
        manifest_rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    datasets = collections.Counter(str(row.get("dataset", "unknown")) for row in manifest_rows)
    profiles = collections.Counter(str(row.get("profile", "unknown")) for row in manifest_rows)
    roles = collections.Counter(str(row.get("selection_role", "unknown")) for row in manifest_rows)

    shadow_reasons: collections.Counter[str] = collections.Counter()
    shadow_sources: collections.Counter[str] = collections.Counter()
    automatic_reasons: collections.Counter[str] = collections.Counter()
    oracle_reasons: collections.Counter[str] = collections.Counter()
    planner_item_rows: list[dict[str, Any]] = []
    stable_input_error_before: list[float] = []
    stable_input_error_after: list[float] = []
    stable_commit_error_before: list[float] = []
    stable_commit_error_after: list[float] = []
    expansion_movements: list[float] = []
    expansion_variant_rows: list[dict[str, Any]] = []
    item_rows: list[dict[str, Any]] = []

    totals: collections.Counter[str] = collections.Counter()
    incomplete_remaining: list[int] = []

    for item_root in sorted(path for path in (root / "items").glob("*") if path.is_dir()):
        item_summary = read_json(item_root / "item_summary.json")
        item_id = item_root.name
        dataset = str(item_summary.get("dataset", "unknown"))
        b2_path = item_root / "branches" / "B2_30_silence_official" / "alignment.json"
        b3_path = item_root / "branches" / "B3_30_silence_raw_control" / "alignment.json"
        b2 = read_json(b2_path); b3 = read_json(b3_path)
        planner = (b2.get("planner_divergence") or {}) if b2 else {}
        if planner:
            totals["planner_evaluated_windows"] += int(planner.get("evaluated_window_count", 0))
            totals["planner_diverged_windows"] += int(planner.get("diverged_window_count", 0))
            if int(planner.get("diverged_window_count", 0)) > 0:
                totals["planner_diverged_items"] += 1
            comparison = compare_branches(b2, b3) if b3 else None
            planner_item_rows.append({
                "item_id": item_id,
                "dataset": dataset,
                "evaluated_window_count": int(planner.get("evaluated_window_count", 0)),
                "diverged_window_count": int(planner.get("diverged_window_count", 0)),
                "first_divergence_window": planner.get("first_divergence_window"),
                "b3_was_run": bool(b3),
                "b2_b3_comparison": comparison,
            })

        shadow = read_json(item_root / "inline_realign_shadow.json")
        if shadow:
            totals["shadow_candidate_count"] += int(shadow.get("candidate_count", 0))
            totals["automatic_candidate_count"] += int(shadow.get("automatic_candidate_count", 0))
            totals["gt_oracle_candidate_count"] += int(shadow.get("gt_oracle_candidate_count", 0))
            totals["local_inference_attempted_count"] += int(shadow.get("local_inference_attempted_count", 0))
            totals["would_write_count"] += int(shadow.get("would_write_count", 0))
            for decision in shadow.get("decisions", []):
                reason = str(decision.get("reason", "unknown"))
                source = str((decision.get("trigger") or {}).get("candidate_source", decision.get("candidate_source", "unknown")))
                shadow_reasons[reason] += 1; shadow_sources[source] += 1
                (oracle_reasons if source == "gt_oracle" else automatic_reasons)[reason] += 1
                totals["gt_improved_count"] += bool(decision.get("gt_improved"))
                totals["context_agreement_supported_count"] += bool((decision.get("context_agreement") or {}).get("supported"))

        assistance = read_json(item_root / "stable_window_assistance.json")
        if assistance:
            totals["stable_transition_count"] += int(assistance.get("transition_count", 0))
            totals["stable_prefix_available_count"] += int(assistance.get("prefix_available_count", 0))
            totals["stable_informative_cursor_change_count"] += int(assistance.get("informative_cursor_change_count", 0))
            totals["stable_reproduced_count"] += int(assistance.get("reproduced_count", 0))
            for transition in assistance.get("transitions", []):
                ideal_input = transition.get("gt_ideal_input_cursor")
                baseline_input = transition.get("baseline_input_cursor")
                stable_input = transition.get("stable_prefix_input_cursor")
                if ideal_input is not None and baseline_input is not None:
                    stable_input_error_before.append(abs(int(baseline_input) - int(ideal_input)))
                if ideal_input is not None and stable_input is not None:
                    stable_input_error_after.append(abs(int(stable_input) - int(ideal_input)))
                    if baseline_input is not None:
                        before = abs(int(baseline_input) - int(ideal_input)); after = abs(int(stable_input) - int(ideal_input))
                        totals["stable_input_improved_count"] += after < before
                        totals["stable_input_worsened_count"] += after > before
                        totals["stable_input_equal_count"] += after == before
                ideal_commit = transition.get("gt_ideal_commit_cursor")
                baseline_commit = transition.get("baseline_commit_cursor")
                stable_commit = transition.get("stable_safe_commit_cursor")
                if ideal_commit is not None and baseline_commit is not None:
                    stable_commit_error_before.append(abs(int(baseline_commit) - int(ideal_commit)))
                if ideal_commit is not None and stable_commit is not None:
                    stable_commit_error_after.append(abs(int(stable_commit) - int(ideal_commit)))
                    if baseline_commit is not None:
                        before = abs(int(baseline_commit) - int(ideal_commit)); after = abs(int(stable_commit) - int(ideal_commit))
                        totals["stable_commit_improved_count"] += after < before
                        totals["stable_commit_worsened_count"] += after > before
                        totals["stable_commit_equal_count"] += after == before

        assistance_trials = read_json(item_root / "stable_window_assistance_trials.json")
        if assistance_trials:
            totals["stable_trial_count"] += int(assistance_trials.get("trial_count", 0))
            totals["stable_successful_trial_count"] += int(assistance_trials.get("successful_trial_count", 0))
            for trial in assistance_trials.get("trials", []):
                totals["stable_rerun_reproduced_count"] += bool((trial.get("rerun_prefix_reproduction") or {}).get("supported"))

        expansion = read_json(item_root / "forced_expansion_trials.json")
        if expansion:
            totals["expansion_window_count"] += int(expansion.get("window_count", 0))
            totals["expansion_variant_run_count"] += int(expansion.get("variant_run_count", 0))
            for window in expansion.get("windows", []):
                for variant in window.get("variants", []):
                    status = str(variant.get("status", "unknown"))
                    totals[f"expansion_status_{status}"] += 1
                    movement = finite((variant.get("movement") or {}).get("max_boundary_movement_sec"))
                    if movement is not None:
                        expansion_movements.append(movement)
                        totals["expansion_movement_gt_016_count"] += movement > 0.16
                        totals["expansion_movement_gt_024_count"] += movement > 0.24
                    expansion_variant_rows.append({
                        "item_id": item_id,
                        "dataset": dataset,
                        "window_index": window.get("window_index"),
                        "ratio": variant.get("ratio"),
                        "status": status,
                        "max_boundary_movement_sec": movement,
                        "zero_duration_count": (variant.get("structural") or {}).get("zero_duration_count"),
                        "boundary_mae_sec": (variant.get("gt") or {}).get("boundary_mae_sec"),
                    })

        incomplete = read_json(item_root / "incomplete_guard" / "alignment.json")
        if incomplete:
            totals["incomplete_guard_count"] += 1
            remaining = int((incomplete.get("summary") or {}).get("remaining_character_count", 0))
            incomplete_remaining.append(remaining)

        b2_summary = (b2.get("summary") or {}) if b2 else {}
        stable_gt = b2_summary.get("stable_segment_gt") or {}
        item_rows.append({
            "item_id": item_id,
            "dataset": dataset,
            "profile": item_summary.get("profile"),
            "selection_role": item_summary.get("selection_role"),
            "character_count": b2_summary.get("character_count"),
            "window_count": b2_summary.get("window_count"),
            "gt_boundary_mae_sec": (b2_summary.get("gt") or {}).get("boundary_mae_sec"),
            "stable_segment_count": b2_summary.get("stable_segment_count"),
            "stable_character_count": stable_gt.get("stable_unit_count"),
            "stable_gt_boundary_mae_sec": stable_gt.get("boundary_mae_sec") if isinstance(stable_gt, dict) else None,
            "planner_diverged_window_count": planner.get("diverged_window_count") if planner else None,
            "automatic_candidate_count": shadow.get("automatic_candidate_count") if shadow else None,
            "gt_oracle_candidate_count": shadow.get("gt_oracle_candidate_count") if shadow else None,
            "local_inference_attempted_count": shadow.get("local_inference_attempted_count") if shadow else None,
            "would_write_count": shadow.get("would_write_count") if shadow else None,
            "incomplete_remaining_character_count": remaining if incomplete else None,
        })

    render = read_json(root / "demo_render_summary.json")
    result = {
        "schema_version": "inline_realign_followup_analysis_summary_v1",
        "created_at": utc_now(),
        "input_root": str(root),
        "experiment_status": {
            "manifest_item_count": len(manifest_rows),
            "completed_item_count": int(experiment.get("completed_item_count", 0)),
            "failed_item_count": int(experiment.get("failed_item_count", 0)),
            "dataset_counts": counter_dict(datasets),
            "profile_counts": counter_dict(profiles),
            "selection_role_counts": counter_dict(roles),
        },
        "automatic_and_oracle_realign": {
            "candidate_count": totals["shadow_candidate_count"],
            "automatic_candidate_count": totals["automatic_candidate_count"],
            "gt_oracle_candidate_count": totals["gt_oracle_candidate_count"],
            "local_inference_attempted_count": totals["local_inference_attempted_count"],
            "would_write_count": totals["would_write_count"],
            "gt_improved_count": totals["gt_improved_count"],
            "context_agreement_supported_count": totals["context_agreement_supported_count"],
            "candidate_source_counts": counter_dict(shadow_sources),
            "all_decision_reason_counts": counter_dict(shadow_reasons),
            "automatic_reason_counts": counter_dict(automatic_reasons),
            "gt_oracle_reason_counts": counter_dict(oracle_reasons),
        },
        "stable_window_assistance": {
            "transition_count": totals["stable_transition_count"],
            "prefix_available_count": totals["stable_prefix_available_count"],
            "informative_cursor_change_count": totals["stable_informative_cursor_change_count"],
            "prefix_reproduced_count": totals["stable_reproduced_count"],
            "active_trial_count": totals["stable_trial_count"],
            "successful_active_trial_count": totals["stable_successful_trial_count"],
            "rerun_prefix_reproduced_count": totals["stable_rerun_reproduced_count"],
            "input_cursor_gt_comparison": {
                "paired_improved_count": totals["stable_input_improved_count"],
                "paired_equal_count": totals["stable_input_equal_count"],
                "paired_worsened_count": totals["stable_input_worsened_count"],
                "baseline_absolute_error_mean_characters": safe_mean(stable_input_error_before),
                "stable_absolute_error_mean_characters": safe_mean(stable_input_error_after),
                "baseline_absolute_error_median_characters": safe_median(stable_input_error_before),
                "stable_absolute_error_median_characters": safe_median(stable_input_error_after),
            },
            "safe_commit_gt_comparison": {
                "paired_improved_count": totals["stable_commit_improved_count"],
                "paired_equal_count": totals["stable_commit_equal_count"],
                "paired_worsened_count": totals["stable_commit_worsened_count"],
                "baseline_absolute_error_mean_characters": safe_mean(stable_commit_error_before),
                "stable_absolute_error_mean_characters": safe_mean(stable_commit_error_after),
                "baseline_absolute_error_median_characters": safe_median(stable_commit_error_before),
                "stable_absolute_error_median_characters": safe_median(stable_commit_error_after),
            },
        },
        "forced_future_text_expansion": {
            "window_count": totals["expansion_window_count"],
            "variant_run_count": totals["expansion_variant_run_count"],
            "complete_run_count": totals["expansion_status_complete"],
            "failed_run_count": totals["expansion_status_failed"],
            "movement_supported_count": len(expansion_movements),
            "movement_gt_0_16_count": totals["expansion_movement_gt_016_count"],
            "movement_gt_0_24_count": totals["expansion_movement_gt_024_count"],
            "max_boundary_movement_sec": safe_max(expansion_movements),
            "median_max_boundary_movement_sec": safe_median(expansion_movements),
            "p90_max_boundary_movement_sec": percentile(expansion_movements, 0.90),
            "variants": expansion_variant_rows,
        },
        "planner_divergence": {
            "evaluated_window_count": totals["planner_evaluated_windows"],
            "diverged_window_count": totals["planner_diverged_windows"],
            "diverged_item_count": totals["planner_diverged_items"],
            "items": planner_item_rows,
        },
        "incomplete_guard": {
            "output_count": totals["incomplete_guard_count"],
            "remaining_character_count_total": sum(incomplete_remaining),
            "remaining_character_count_median": safe_median(incomplete_remaining),
        },
        "demo_render": render,
        "items": item_rows,
        "interpretation_limits": [
            "Automatic detector candidates and GT-oracle candidates are reported separately.",
            "GT-oracle improvement measures local-realign capability, not automatic production performance.",
            "Stable-window suggestions are experimental until paired reruns and GT comparisons support them.",
            "Constructed incomplete outputs validate fail-closed behavior and are not automatic incomplete detections.",
            "Demo items without GT support structural and listening conclusions only.",
            "M4Singer synthetic-long results must remain separate from natural MIR-1K and Demo results.",
        ],
    }
    return result


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(payload: dict[str, Any]) -> str:
    status = payload["experiment_status"]
    shadow = payload["automatic_and_oracle_realign"]
    stable = payload["stable_window_assistance"]
    expansion = payload["forced_future_text_expansion"]
    planner = payload["planner_divergence"]
    incomplete = payload["incomplete_guard"]
    render = payload.get("demo_render") or {}
    lines = [
        "# Inline Realign Follow-up Result Summary",
        "",
        f"Generated: `{payload['created_at']}`",
        "",
        "## Coverage",
        "",
        f"- Manifest items: {status['manifest_item_count']}",
        f"- Completed / failed: {status['completed_item_count']} / {status['failed_item_count']}",
        f"- Datasets: `{json.dumps(status['dataset_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Automatic detector and GT-oracle local realign",
        "",
        "| quantity | count |",
        "|---|---:|",
        f"| automatic candidates | {shadow['automatic_candidate_count']} |",
        f"| GT-oracle candidates | {shadow['gt_oracle_candidate_count']} |",
        f"| local inference attempted | {shadow['local_inference_attempted_count']} |",
        f"| context agreement supported | {shadow['context_agreement_supported_count']} |",
        f"| GT improved | {shadow['gt_improved_count']} |",
        f"| shadow would write | {shadow['would_write_count']} |",
        "",
        "Decision reasons:",
        "",
        f"`{json.dumps(shadow['all_decision_reason_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Stable segments assisting window boundaries",
        "",
        "| quantity | value |",
        "|---|---:|",
        f"| transitions | {stable['transition_count']} |",
        f"| stable prefix available | {stable['prefix_available_count']} |",
        f"| cursor suggestion differs from baseline | {stable['informative_cursor_change_count']} |",
        f"| prefix reproduced in captured next window | {stable['prefix_reproduced_count']} |",
        f"| active reruns / successful | {stable['active_trial_count']} / {stable['successful_active_trial_count']} |",
        f"| active rerun prefix reproduced | {stable['rerun_prefix_reproduced_count']} |",
        "",
        "Input cursor absolute error to GT (characters):",
        "",
        f"- baseline mean / median: {fmt(stable['input_cursor_gt_comparison']['baseline_absolute_error_mean_characters'])} / {fmt(stable['input_cursor_gt_comparison']['baseline_absolute_error_median_characters'])}",
        f"- stable suggestion mean / median: {fmt(stable['input_cursor_gt_comparison']['stable_absolute_error_mean_characters'])} / {fmt(stable['input_cursor_gt_comparison']['stable_absolute_error_median_characters'])}",
        f"- paired improved / equal / worsened: {stable['input_cursor_gt_comparison']['paired_improved_count']} / {stable['input_cursor_gt_comparison']['paired_equal_count']} / {stable['input_cursor_gt_comparison']['paired_worsened_count']}",
        "",
        "## Forced future-text expansion",
        "",
        f"- windows / runs: {expansion['window_count']} / {expansion['variant_run_count']}",
        f"- complete / failed: {expansion['complete_run_count']} / {expansion['failed_run_count']}",
        f"- median / p90 / maximum boundary movement: {fmt(expansion['median_max_boundary_movement_sec'])} / {fmt(expansion['p90_max_boundary_movement_sec'])} / {fmt(expansion['max_boundary_movement_sec'])} seconds",
        f"- movement >0.16s / >0.24s: {expansion['movement_gt_0_16_count']} / {expansion['movement_gt_0_24_count']}",
        "",
        "## Raw/official planner divergence",
        "",
        f"- evaluated windows: {planner['evaluated_window_count']}",
        f"- diverged windows / items: {planner['diverged_window_count']} / {planner['diverged_item_count']}",
        "",
        "## Fail-closed incomplete outputs",
        "",
        f"- outputs: {incomplete['output_count']}",
        f"- total remaining characters: {incomplete['remaining_character_count_total']}",
        "",
        "## Demo rendering",
        "",
        f"- requested after all alignment: `{bool(render)}`",
        f"- rendered / failed: {render.get('rendered_item_count', render.get('rendered_count', 0))} / {render.get('failed_item_count', render.get('failed_count', 0))}",
        "",
        "## Interpretation limits",
        "",
    ]
    lines.extend(f"- {text}" for text in payload["interpretation_limits"])
    lines.append("")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input_root", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--markdown-output", type=Path)
    return p


def main() -> int:
    args = parser().parse_args()
    root = args.input_root.expanduser().resolve()
    if not (root / "experiment_summary.json").is_file():
        raise FileNotFoundError(root / "experiment_summary.json")
    output = (args.output or root / "followup_analysis_summary.json").expanduser().resolve()
    markdown = (args.markdown_output or root / "followup_analysis_summary.md").expanduser().resolve()
    payload = summarize(root)
    write_json(output, payload)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    temporary = markdown.with_suffix(markdown.suffix + ".tmp")
    temporary.write_text(render_markdown(payload), encoding="utf-8")
    temporary.replace(markdown)
    print(json.dumps({
        "status": "complete", "output": str(output), "markdown_output": str(markdown),
        "completed_item_count": payload["experiment_status"]["completed_item_count"],
        "failed_item_count": payload["experiment_status"]["failed_item_count"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
