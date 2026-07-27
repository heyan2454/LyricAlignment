#!/usr/bin/env python3
"""Run Q1-Q3 demo local-realignment quick experiments.

Quick is a scientific diagnostic stage, not a smoke test.  It produces the
results that will be reviewed before the overnight design is frozen.  A later
smoke must separately validate the frozen overnight launcher.

The entry is resumable at evidence/case granularity.  A failure is recorded and
does not stop later items unless ``--fail-fast`` is supplied.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import math
import os
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.alignment_artifacts import stage_rows
from lyricalign.demo.karaoke import parse_lyrics_text
from lyricalign.demo.raw_guarded import build_runtime_anchor_rows, choose_runtime_anchor_policy, choose_anchor_pair
from lyricalign.demo.realign_diagnostics import (
    TIMESTAMP_STEP_SEC,
    accepted_shadow_rows,
    append_jsonl,
    atomic_json,
    atomic_jsonl,
    bounded_splice,
    build_anchor_rows,
    canonical_hash,
    collect_quick_results,
    compare_two_candidates,
    crop_from_anchors,
    evaluate_rows,
    local_anchor_reproduction,
    mine_natural_candidates,
    non_gt_acceptance,
    oracle_anchor_pair,
    read_json,
    read_jsonl,
    replay_commit_shift,
    scan_anchor_policies,
    select_anchor_pair,
    select_single_repair_candidate,
    stage_from_local_inference,
    stage_rollback_candidate,
    stage_transition_provenance,
    status_is_complete,
    structural_summary,
    utc_now,
    write_csv,
)
from lyricalign.training.qwen_fa_runtime import decode_audio


def load_serial_module() -> Any:
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("lyricalign_serial_demo_quick_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load serial demo module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERIAL = load_serial_module()


def status(out_root: Path, *, phase: str, case_id: str, state: str, **extra: Any) -> None:
    append_jsonl(out_root / "run_status.jsonl", {
        "time": utc_now(), "phase": phase, "case_id": case_id, "status": state, **extra,
    })


def selected_items(subset_root: Path, roles: list[str], item_ids: list[str]) -> list[dict[str, Any]]:
    selection = read_jsonl(subset_root / "selection.jsonl")
    wanted_roles = set(roles)
    rows = [row for row in selection if row.get("selection_role") in wanted_roles]
    if item_ids:
        wanted = set(item_ids)
        rows = [row for row in rows if str(row["item_id"]) in wanted]
    role_order = {role: ordinal for ordinal, role in enumerate(roles)}
    return sorted(rows, key=lambda row: (
        role_order.get(str(row.get("selection_role")), 999),
        row.get("selection_order") is None, row.get("selection_order") or 9999, str(row["item_id"]),
    ))


def audio_path(item_root: Path, variant: str, demucs_model: str) -> Path:
    mapping = {
        "mix": item_root / "audio" / "mix.wav",
        "official_vocal": item_root / "audio" / "official_vocal.wav",
        "spleeter": item_root / "audio" / "spleeter_vocals.wav",
        "demucs": item_root / "audio" / f"demucs_{demucs_model}_vocals.wav",
    }
    return mapping[variant]


def document_and_gt(item_root: Path) -> tuple[Any, list[dict[str, Any]]]:
    document = parse_lyrics_text((item_root / "lyrics.txt").read_text(encoding="utf-8"), language="Chinese")
    gt = sorted(read_jsonl(item_root / "ground_truth.characters.jsonl"), key=lambda row: int(row["character_index"]))
    if len(document.characters) != len(gt):
        raise ValueError(f"lyrics/GT count mismatch: {len(document.characters)} != {len(gt)}")
    for meta, row in zip(document.characters, gt, strict=True):
        expected = row.get("normalized_character") or row.get("character")
        if expected is not None and str(expected) != meta.text:
            raise ValueError(f"lyrics/GT mismatch at {meta.global_index}: {meta.text!r} != {expected!r}")
    return document, gt


def inference_args(args: argparse.Namespace, core_sec: float) -> SimpleNamespace:
    return SimpleNamespace(
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
        core_sec=core_sec,
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
        future_line_padding=args.future_line_padding,
        minimum_forward_characters=args.minimum_forward_characters,
        future_character_ratio=args.future_character_ratio,
        max_candidate_expansions=args.max_candidate_expansions,
        boundary_start_tolerance_sec=args.boundary_start_tolerance_sec,
        seam_tolerance_sec=args.seam_tolerance_sec,
        capture_shadow_rows=True,
        decoder_kind=getattr(args, "decoder_kind", "official"),
        gpu_decoder_runtime=getattr(args, "gpu_decoder_runtime", None),
    )


def evidence_path(out_root: Path, item_id: str, variant: str, core_sec: float) -> Path:
    return out_root / "evidence" / f"core_{core_sec:g}s" / variant / f"{item_id}.json"


def run_evidence(
    args: argparse.Namespace, items: list[dict[str, Any]], processor: Any, model: Any,
    checkpoint_identity: dict[str, Any],
) -> None:
    for selected in items:
        item_id = str(selected["item_id"])
        item_root = args.subset_root / "items" / item_id
        document, gt = document_and_gt(item_root)
        for core_sec in args.core_sec:
            serial_args = inference_args(args, core_sec)
            for variant in args.audio_variants:
                case_id = f"evidence_{item_id}_{variant}_core{core_sec:g}"
                path = evidence_path(args.out_root, item_id, variant, core_sec)
                source_audio = audio_path(item_root, variant, args.demucs_model)
                request = {
                    "schema_version": "demo_realign_quick_evidence_request_v1",
                    "item_id": item_id,
                    "audio_variant": variant,
                    "audio_path": str(source_audio.resolve()),
                    "core_sec": core_sec,
                    "left_context_sec": args.left_context_sec,
                    "right_context_sec": args.right_context_sec,
                    "checkpoint_identity": checkpoint_identity,
                    "model": args.model,
                    "revision": args.revision,
                    "timestamp_segment_sec": args.timestamp_segment_sec,
                    "decoder_kind": args.decoder_kind,
                    "gpu_decoder_checkpoint": (
                        str(args.gpu_decoder_checkpoint.resolve())
                        if args.gpu_decoder_checkpoint is not None else None
                    ),
                    "gpu_decoder_identity": getattr(args, "gpu_decoder_identity", None),
                }
                request_hash = canonical_hash(request)
                if not args.force and path.is_file():
                    try:
                        existing = read_json(path)
                        if existing.get("request_hash") == request_hash and existing.get("status") == "complete":
                            status(args.out_root, phase="evidence", case_id=case_id, state="skipped_identity_match", path=str(path))
                            continue
                    except (OSError, json.JSONDecodeError):
                        pass
                status(args.out_root, phase="evidence", case_id=case_id, state="running", path=str(path))
                started = time.perf_counter()
                try:
                    if not source_audio.is_file():
                        raise FileNotFoundError(source_audio)
                    audio = decode_audio(source_audio)
                    rows, trace = SERIAL.windowed_alignment(processor, model, audio, document, serial_args)
                    shadow = accepted_shadow_rows(trace)
                    candidates = mine_natural_candidates(
                        rows, shadow, item_id=item_id, audio_variant=variant,
                        max_target_units=args.max_target_units,
                        disagreement_peak_threshold_sec=args.disagreement_peak_threshold_sec,
                        timestamp_step_sec=args.timestamp_segment_sec,
                    )
                    for candidate in candidates:
                        candidate["core_sec"] = core_sec
                        candidate["case_id"] = f"{candidate['case_id']}_core{core_sec:g}"
                    anchors = build_anchor_rows(rows, shadow, gt, item_id=item_id, audio_variant=variant)
                    for anchor in anchors:
                        anchor["core_sec"] = core_sec
                    payload = {
                        "schema_version": "demo_realign_quick_evidence_v1",
                        "status": "complete",
                        "created_at": utc_now(),
                        "request_hash": request_hash,
                        "request": request,
                        "item": selected,
                        "audio_duration_sec": len(audio) / 16000.0,
                        "lyrics_path": str((item_root / "lyrics.txt").resolve()),
                        "gt_path": str((item_root / "ground_truth.characters.jsonl").resolve()),
                        "ground_truth": gt,
                        "characters": rows,
                        "stage_transition_provenance": stage_transition_provenance(rows),
                        "window_trace": trace,
                        "shadow_row_count": len(shadow),
                        "natural_candidates": candidates,
                        "anchor_rows": anchors,
                        "runtime": {"wall_sec_including_audio_decode": time.perf_counter() - started},
                    }
                    atomic_json(path, payload)
                    status(args.out_root, phase="evidence", case_id=case_id, state="complete", path=str(path), candidate_count=len(candidates))
                except Exception as exc:
                    failure = {
                        "schema_version": "demo_realign_quick_failure_v1",
                        "status": "failed", "created_at": utc_now(), "request_hash": request_hash,
                        "request": request, "error_type": type(exc).__name__, "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    atomic_json(path.with_suffix(".failure.json"), failure)
                    status(args.out_root, phase="evidence", case_id=case_id, state="failed", error=str(exc), path=str(path.with_suffix('.failure.json')))
                    if args.fail_fast:
                        raise


def load_evidence(args: argparse.Namespace) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for core_sec in args.core_sec:
        for variant in args.audio_variants:
            paths.extend(sorted((args.out_root / "evidence" / f"core_{core_sec:g}s" / variant).glob("*.json")))
    evidence: list[dict[str, Any]] = []
    for path in paths:
        payload = read_json(path)
        if payload.get("status") == "complete":
            payload["evidence_path"] = str(path.resolve())
            evidence.append(payload)
    return evidence


def run_q1(args: argparse.Namespace, evidence: list[dict[str, Any]]) -> None:
    q1 = args.out_root / "q1_anchor_scan"
    anchors: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for item in evidence:
        condition = item["request"]
        for row in item["anchor_rows"]:
            anchors.append({**row, "core_sec": condition["core_sec"], "evidence_path": item["evidence_path"]})
        for row in item["natural_candidates"]:
            candidates.append({**row, "core_sec": condition["core_sec"], "evidence_path": item["evidence_path"]})
    results, shortlist = scan_anchor_policies(
        anchors, candidates, timestamp_step_sec=args.timestamp_segment_sec,
        max_distance_units=args.max_anchor_search_units,
        max_pair_span_units=args.max_anchor_span_units,
        max_pair_span_sec=args.max_anchor_span_sec,
        guard_units=args.anchor_guard_units,
    )
    atomic_jsonl(q1 / "rows.jsonl", anchors)
    atomic_jsonl(q1 / "natural_candidates.jsonl", candidates)
    write_csv(q1 / "precision_coverage.csv", results)
    atomic_json(q1 / "recommended_shortlist.json", {
        "schema_version": "demo_realign_anchor_shortlist_v1", "created_at": utc_now(),
        "shortlist": shortlist,
    })
    aggregate = {
        "schema_version": "demo_realign_anchor_scan_v1", "created_at": utc_now(),
        "evidence_count": len(evidence), "anchor_row_count": len(anchors),
        "natural_candidate_count": len(candidates), "policy_count": len(results),
        "shortlist": shortlist,
        "notes": [
            "Q1 is a quick scientific diagnostic; the shortlist is not a production rule.",
            "GT is used for anchor precision/coverage analysis only.",
        ],
    }
    atomic_json(q1 / "aggregate.json", aggregate)
    status(args.out_root, phase="q1", case_id="q1_anchor_scan", state="complete", anchor_count=len(anchors), candidate_count=len(candidates))


def policy_shortlist(args: argparse.Namespace) -> list[dict[str, Any]]:
    path = args.out_root / "q1_anchor_scan" / "recommended_shortlist.json"
    if not path.is_file():
        return []
    return list(read_json(path).get("shortlist", []))


def anchor_modes_for_case(
    args: argparse.Namespace, evidence: dict[str, Any], candidate: dict[str, Any], shortlist: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any] | None, dict[str, Any], dict[str, Any], list[dict[str, Any]]]]:
    target_start = int(candidate["dependency_character_start"])
    target_end = int(candidate["dependency_character_end"])
    modes: list[tuple[str, dict[str, Any] | None, dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    if args.include_gt_anchor:
        oracle_left, oracle_right = oracle_anchor_pair(evidence["ground_truth"], target_start, target_end, guard_units=args.anchor_guard_units)
        if oracle_left is not None and oracle_right is not None:
            span_units = int(oracle_right["global_character_index"]) - int(oracle_left["global_character_index"]) + 1
            span_sec = float(oracle_right["selected_end_sec"]) - float(oracle_left["selected_start_sec"])
            if span_units <= args.max_anchor_span_units and span_sec <= args.max_anchor_span_sec:
                modes.append(("gt_oracle", None, oracle_left, oracle_right, []))
    if args.runtime_anchor_policy:
        runtime_anchors = build_runtime_anchor_rows(
            evidence["characters"], accepted_shadow_rows(evidence.get("window_trace", []))
        )
        policy = choose_runtime_anchor_policy(
            runtime_anchors,
            margin_quantile=args.runtime_anchor_margin_quantile,
            overlap_tolerance_sec=args.runtime_anchor_overlap_tolerance_sec,
            stability_tolerance_sec=args.runtime_anchor_stability_tolerance_sec,
        )
        left, right, rejected = choose_anchor_pair(
            runtime_anchors, policy, target_start, target_end,
            max_distance_units=args.max_anchor_search_units,
            max_pair_span_units=args.max_anchor_span_units,
            max_pair_span_sec=args.max_anchor_span_sec,
            guard_units=args.anchor_guard_units,
        )
        if left is not None and right is not None:
            modes.append(("runtime_A4", policy, left, right, rejected))
    else:
        anchors = evidence["anchor_rows"]
        for ordinal, policy in enumerate(shortlist[: args.max_automatic_anchor_policies]):
            left, right, rejected = select_anchor_pair(
                anchors, policy, target_start, target_end,
                max_distance_units=args.max_anchor_search_units,
                max_pair_span_units=args.max_anchor_span_units,
                max_pair_span_sec=args.max_anchor_span_sec,
                guard_units=args.anchor_guard_units,
            )
            if left is not None and right is not None:
                role = str(policy.get("shortlist_role") or ("best_automatic" if ordinal == 0 else "strict_automatic"))
                modes.append((role, policy, left, right, rejected))
    return modes


def local_infer(
    *, processor: Any, model: Any, audio: Any, document: Any, serial_args: Any,
    left: dict[str, Any], right: dict[str, Any], audio_duration_sec: float,
    crop_mode: str, padding_sec: float = 0.0, context_units: int = 0,
    context_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    left_index = int(left["global_character_index"])
    right_index = int(right["global_character_index"])
    input_left_index, input_right_index = left_index, right_index
    crop_left, crop_right = left, right
    if crop_mode == "exact_anchor":
        padding_sec = 0.0
    elif crop_mode == "audio_only_padding":
        pass
    elif crop_mode == "matched_context":
        if not context_rows:
            raise ValueError("matched_context requires context_rows")
        by_idx = {int(row["global_character_index"]): row for row in context_rows}
        input_left_index = max(min(by_idx), left_index - context_units)
        input_right_index = min(max(by_idx), right_index + context_units)
        crop_left = by_idx[input_left_index]
        crop_right = by_idx[input_right_index]
        padding_sec = 0.0
    else:
        raise ValueError(crop_mode)
    crop_start, crop_end = crop_from_anchors(
        crop_left, crop_right, padding_sec=padding_sec, audio_duration_sec=audio_duration_sec
    )
    sample_start = int(round(crop_start * 16000))
    sample_end = int(round(crop_end * 16000))
    started = time.perf_counter()
    rows, audit = SERIAL.infer_slice(
        processor=processor, model=model, audio=audio[sample_start:sample_end], document=document,
        character_start=input_left_index, character_end=input_right_index + 1,
        global_audio_offset_sec=crop_start, args=serial_args,
    )
    return {
        "left_index": left_index, "right_index": right_index,
        "input_character_start": input_left_index, "input_character_end": input_right_index,
        "replace_start": left_index + 1, "replace_end": right_index - 1,
        "crop_start_sec": crop_start, "crop_end_sec": crop_end,
        "crop_mode": crop_mode, "padding_sec": padding_sec, "context_units": context_units,
        "context_audit": {
            "text_input_character_start": input_left_index,
            "text_input_character_end": input_right_index,
            "audio_crop_anchor_start_index": int(crop_left["global_character_index"]),
            "audio_crop_anchor_end_index": int(crop_right["global_character_index"]),
            "audio_and_text_context_expanded_together": crop_mode == "matched_context",
            "audio_only_padding": crop_mode == "audio_only_padding",
        },
        "raw_rows": stage_from_local_inference(rows, "local_raw"),
        "decoded_rows": stage_from_local_inference(rows, "local_decoded"),
        "inference_audit": audit, "wall_sec": time.perf_counter() - started,
    }


def repair_candidate_payload(
    *, mode: str, anchor_mode: str, padding_sec: float | None,
    crop_mode: str = "stage_rollback", context_units: int = 0,
    baseline_final: list[dict[str, Any]], candidate_full: list[dict[str, Any]],
    local_rows: list[dict[str, Any]] | None, splice: dict[str, Any],
    target_indices: list[int], replacement_indices: list[int], gt: list[dict[str, Any]],
    acceptance: dict[str, Any] | None = None, anchor_reproduction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_by_index = {int(row["global_character_index"]): row for row in baseline_final}
    after_by_index = {int(row["global_character_index"]): row for row in candidate_full}
    boundary_changes = [
        abs(float(after_by_index[index]["start_sec"]) - float(before_by_index[index]["start_sec"]))
        for index in replacement_indices if index in before_by_index and index in after_by_index
    ] + [
        abs(float(after_by_index[index]["end_sec"]) - float(before_by_index[index]["end_sec"]))
        for index in replacement_indices if index in before_by_index and index in after_by_index
    ]
    return {
        "mode": mode, "anchor_mode": anchor_mode, "padding_sec": padding_sec,
        "crop_mode": crop_mode, "context_units": context_units,
        "target_indices": target_indices, "replacement_indices": replacement_indices,
        "local_rows": local_rows,
        "changed_rows": [row for row in candidate_full if int(row["global_character_index"]) in set(replacement_indices)],
        "splice": splice, "anchor_reproduction": anchor_reproduction,
        "acceptance": acceptance,
        "modification_summary": {
            "changed_boundary_count": sum(value > 1e-9 for value in boundary_changes),
            "boundary_change_abs_sec": {
                "count": len(boundary_changes),
                "mean": sum(boundary_changes) / len(boundary_changes) if boundary_changes else None,
                "max": max(boundary_changes, default=None),
            },
        },
        "metrics": {
            "before": evaluate_rows(baseline_final, gt, target_indices),
            "after": evaluate_rows(candidate_full, gt, target_indices),
            "replacement_before": evaluate_rows(baseline_final, gt, replacement_indices),
            "replacement_after": evaluate_rows(candidate_full, gt, replacement_indices),
            "whole_song_before": evaluate_rows(baseline_final, gt),
            "whole_song_after": evaluate_rows(candidate_full, gt),
        },
    }


def run_q2_case(
    args: argparse.Namespace, evidence: dict[str, Any], candidate: dict[str, Any],
    processor: Any, model: Any, shortlist: list[dict[str, Any]],
) -> dict[str, Any]:
    item_id = str(evidence["request"]["item_id"])
    item_root = args.subset_root / "items" / item_id
    document, gt = document_and_gt(item_root)
    source_audio = Path(evidence["request"]["audio_path"])
    audio = decode_audio(source_audio)
    serial_args = inference_args(args, float(evidence["request"]["core_sec"]))
    baseline_rows = evidence["characters"]
    baseline_final = stage_rows(baseline_rows, "final")
    context_rows = stage_rows(baseline_rows, "selected")
    target_indices = list(range(int(candidate["dependency_character_start"]), int(candidate["dependency_character_end"]) + 1))
    repair_candidates: list[dict[str, Any]] = []

    # Existing-stage recovery baselines: no new model call. Expand left to
    # include any predecessor whose final end would immediately compress the
    # restored stage back to the old result.
    for stage in ("raw", "processor_decoded", "selected"):
        rollback_rows, rollback_splice = stage_rollback_candidate(
            baseline_rows, stage, target_indices[0], target_indices[-1],
            max_predecessor_units=args.rollback_predecessor_units,
        )
        rollback_acceptance = non_gt_acceptance(baseline_final, rollback_rows, target_indices)
        rollback_replacement_indices = list(range(
            int(rollback_splice.get("effective_replace_start", target_indices[0])),
            int(rollback_splice.get("effective_replace_end", target_indices[-1])) + 1,
        ))
        repair_candidates.append(repair_candidate_payload(
            mode=f"{stage}_rollback_bounded_remerge", anchor_mode="none", padding_sec=None,
            crop_mode="stage_rollback", baseline_final=baseline_final, candidate_full=rollback_rows,
            local_rows=None, splice=rollback_splice, target_indices=target_indices,
            replacement_indices=rollback_replacement_indices, gt=gt, acceptance=rollback_acceptance,
        ))

    local_trials: list[dict[str, Any]] = []
    for anchor_mode, policy, left, right, rejected in anchor_modes_for_case(args, evidence, candidate, shortlist):
        if args.q2_trial_profile == "exact":
            trial_specs = [("exact_anchor", 0.0, 0)]
        elif args.q2_trial_profile == "plus2":
            trial_specs = [("matched_context", 0.0, 2)]
        elif args.q2_trial_profile == "plus4":
            trial_specs = [("matched_context", 0.0, 4)]
        elif args.q2_trial_profile == "exact_plus2":
            trial_specs = [("exact_anchor", 0.0, 0), ("matched_context", 0.0, 2)]
        elif args.q2_trial_profile == "all":
            trial_specs = [("exact_anchor", 0.0, 0)]
            trial_specs.extend(("audio_only_padding", float(padding), 0) for padding in args.padding_sec)
            trial_specs.extend(("matched_context", 0.0, int(units)) for units in args.matched_context_units)
        else:
            raise ValueError(args.q2_trial_profile)
        for crop_mode, padding, context_units in trial_specs:
            trial = local_infer(
                processor=processor, model=model, audio=audio, document=document, serial_args=serial_args,
                left=left, right=right, audio_duration_sec=len(audio) / 16000.0,
                crop_mode=crop_mode, padding_sec=padding, context_units=context_units,
                context_rows=context_rows,
            )
            trial.update({
                "anchor_mode": anchor_mode, "anchor_policy": policy,
                "left_anchor": left, "right_anchor": right,
                "rejected_anchor_candidates": rejected,
            })
            local_trials.append(trial)
            replacement_indices = list(range(trial["replace_start"], trial["replace_end"] + 1))
            for stage_name, local_rows in (("local_raw", trial["raw_rows"]), ("local_decoded", trial["decoded_rows"])):
                anchor_reproduction = local_anchor_reproduction(local_rows, left, right)
                # bounded remerge is the primary usable result; direct trust is retained as a mechanism check.
                for remerge, suffix in ((True, "bounded_remerge"), (False, "direct_trust_diagnostic")):
                    candidate_full, splice = bounded_splice(
                        baseline_final, local_rows, replace_start=trial["replace_start"],
                        replace_end=trial["replace_end"], remerge=remerge,
                    )
                    acceptance = non_gt_acceptance(
                        baseline_final, candidate_full, target_indices,
                        anchor_reproduction_max_sec=anchor_reproduction.get("max_error_sec"),
                    )
                    repair_candidates.append(repair_candidate_payload(
                        mode=f"{stage_name}_{suffix}", anchor_mode=anchor_mode, padding_sec=padding,
                        crop_mode=crop_mode, context_units=context_units,
                        baseline_final=baseline_final, candidate_full=candidate_full, local_rows=local_rows,
                        splice=splice, target_indices=target_indices, replacement_indices=replacement_indices,
                        gt=gt, acceptance=acceptance, anchor_reproduction=anchor_reproduction,
                    ))

    # Compare equivalent outputs from different input contexts.
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trial in local_trials:
        grouped[(trial["anchor_mode"], "raw")].append(trial)
        grouped[(trial["anchor_mode"], "decoded")].append(trial)
    consensus: list[dict[str, Any]] = []
    for (anchor_mode, stage), trials in grouped.items():
        if len(trials) < 2:
            continue
        base = next((row for row in trials if row["crop_mode"] == "exact_anchor"), trials[0])
        for other in trials:
            if other is base:
                continue
            rows_a = base["raw_rows" if stage == "raw" else "decoded_rows"]
            rows_b = other["raw_rows" if stage == "raw" else "decoded_rows"]
            indices = range(int(base["replace_start"]), int(base["replace_end"]) + 1)
            consensus.append({
                "anchor_mode": anchor_mode, "stage": stage,
                "left_crop_mode": base["crop_mode"], "right_crop_mode": other["crop_mode"],
                "right_padding_sec": other["padding_sec"], "right_context_units": other["context_units"],
                "comparison": compare_two_candidates(rows_a, rows_b, indices),
            })

    final_selection = select_single_repair_candidate(
        repair_candidates,
        require_context_agreement=args.q2_require_context_agreement,
        context_agreement_tolerance_sec=args.selection_consensus_tolerance_sec,
        excluded_anchor_modes=("gt_oracle", "gt_oracle_fallback"),
    )
    return {
        "schema_version": "demo_realign_q2_case_v2_1", "status": "complete", "created_at": utc_now(),
        "case_id": candidate["case_id"], "family": "natural", "item_id": item_id,
        "audio_variant": evidence["request"]["audio_variant"], "core_sec": evidence["request"]["core_sec"],
        "evidence_path": evidence["evidence_path"], "source_candidate": candidate,
        "original_rows": {
            stage: [row for row in stage_rows(baseline_rows, stage) if int(row["global_character_index"]) in target_indices]
            for stage in ("raw", "processor_decoded", "selected", "final")
        },
        "stage_transition_provenance": [
            row for row in evidence.get("stage_transition_provenance", [])
            if int(row["global_character_index"]) in target_indices
        ],
        "ground_truth_rows": [row for row in gt if int(row["character_index"]) in target_indices],
        "local_trials": local_trials, "repair_candidates": repair_candidates,
        "context_consensus": consensus, "final_non_gt_selection": final_selection,
    }


def load_external_q2_plan(path: Path | None) -> dict[tuple[str, str, float], list[dict[str, Any]]]:
    if path is None:
        return {}
    grouped: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(path):
        key = (str(row["item_id"]), str(row["audio_variant"]), float(row["core_sec"]))
        grouped[key].append(row)
    return grouped


def external_candidate(row: dict[str, Any]) -> dict[str, Any]:
    start = int(row["target_start"])
    end = int(row["target_end"])
    if start < 0 or end < start:
        raise ValueError(f"invalid external q2 span: {row}")
    return {
        "case_id": str(row.get("case_id") or row.get("pair_id")),
        "pair_id": str(row.get("pair_id") or row.get("case_id")),
        "candidate_type": "external_decoder_union",
        "observed_character_start": start,
        "observed_character_end": end,
        "dependency_character_start": start,
        "dependency_character_end": end,
        "character_indices": list(range(start, end + 1)),
        "target_unit_count": end - start + 1,
        "trigger_counts": dict(row.get("trigger_counts") or {}),
        "trigger_flags_by_index": dict(row.get("trigger_flags_by_index") or {}),
        "constraint_dependency_trace": list(row.get("constraint_dependency_trace") or []),
        "severity_score": float(row.get("severity_score") or 0.0),
        "source_decoders": list(row.get("source_decoders") or []),
        "funnel_stage": row.get("funnel_stage"),
    }


def run_q2(
    args: argparse.Namespace, evidence: list[dict[str, Any]], processor: Any, model: Any,
) -> None:
    shortlist = policy_shortlist(args)
    out_dir = args.out_root / "q2_natural_realign" / "cases"
    requested = 0
    completed = 0
    refreshed_candidate_rows: list[dict[str, Any]] = []
    external_plan = load_external_q2_plan(args.q2_case_plan)
    for item in evidence:
        evidence_key = (
            str(item["request"]["item_id"]),
            str(item["request"]["audio_variant"]),
            float(item["request"]["core_sec"]),
        )
        if external_plan:
            refreshed_candidates = [external_candidate(row) for row in external_plan.get(evidence_key, [])]
        else:
            shadow = accepted_shadow_rows(item.get("window_trace", []))
            refreshed_candidates = mine_natural_candidates(
                item["characters"], shadow,
                item_id=str(item["request"]["item_id"]),
                audio_variant=str(item["request"]["audio_variant"]),
                max_target_units=args.max_target_units,
                disagreement_peak_threshold_sec=args.disagreement_peak_threshold_sec,
                timestamp_step_sec=args.timestamp_segment_sec,
            )
            for candidate in refreshed_candidates:
                candidate["core_sec"] = float(item["request"]["core_sec"])
                candidate["case_id"] = f"{candidate['case_id']}_core{float(item['request']['core_sec']):g}"
        for candidate in refreshed_candidates:
            candidate["core_sec"] = float(item["request"]["core_sec"])
            refreshed_candidate_rows.append({**candidate, "evidence_path": item["evidence_path"]})
        for candidate in refreshed_candidates:
            requested += 1
            case_id = str(candidate["case_id"])
            path = out_dir / f"{case_id}.json"
            request = {
                "case_id": case_id, "evidence_request_hash": item["request_hash"],
                "shortlist_policy_ids": [row.get("policy_id") for row in shortlist[:2]],
                "padding_sec": args.padding_sec,
                "matched_context_units": args.matched_context_units,
                "anchor_limits": [args.anchor_guard_units, args.max_anchor_span_units, args.max_anchor_span_sec],
                "candidate_limits": [args.max_target_units, args.disagreement_peak_threshold_sec],
                "quick_revision": "2.1",
                "decoder_kind": args.decoder_kind,
                "q2_trial_profile": args.q2_trial_profile,
                "q2_require_context_agreement": args.q2_require_context_agreement,
                "rollback_predecessor_units": args.rollback_predecessor_units,
                "selection_consensus_tolerance_sec": args.selection_consensus_tolerance_sec,
                "excluded_automatic_anchor_modes": ["gt_oracle", "gt_oracle_fallback"],
            }
            request_hash = canonical_hash(request)
            status_path = path.with_suffix(".status.json")
            if not args.force and status_is_complete(status_path, request_hash) and path.is_file():
                status(args.out_root, phase="q2", case_id=case_id, state="skipped_identity_match", path=str(path))
                completed += 1
                continue
            status(args.out_root, phase="q2", case_id=case_id, state="running", path=str(path))
            atomic_json(status_path, {"request_hash": request_hash, "status": "running", "updated_at": utc_now()})
            try:
                payload = run_q2_case(args, item, candidate, processor, model, shortlist)
                payload["request_hash"] = request_hash
                payload["request"] = request
                atomic_json(path, payload)
                atomic_json(status_path, {"request_hash": request_hash, "status": "complete", "updated_at": utc_now()})
                status(args.out_root, phase="q2", case_id=case_id, state="complete", path=str(path), repair_candidate_count=len(payload["repair_candidates"]))
                completed += 1
            except Exception as exc:
                failure = {"request_hash": request_hash, "status": "failed", "updated_at": utc_now(), "error": str(exc), "traceback": traceback.format_exc()}
                atomic_json(status_path, failure)
                atomic_json(path.with_suffix(".failure.json"), failure)
                status(args.out_root, phase="q2", case_id=case_id, state="failed", error=str(exc), path=str(path.with_suffix('.failure.json')))
                if args.fail_fast:
                    raise
    atomic_jsonl(args.out_root / "q2_natural_realign" / "refreshed_natural_candidates.jsonl", refreshed_candidate_rows)
    comparison = summarize_case_directory(out_dir)
    comparison.update({
        "schema_version": "demo_realign_q2_comparison_v2_1",
        "requested_case_count": requested,
        "completed_case_count": completed,
        "refreshed_candidate_count": len(refreshed_candidate_rows),
        "selector": {
            "ground_truth_anchor_modes_excluded": True,
            "requires_second_reasonable_input_agreement": args.q2_require_context_agreement,
            "agreement_tolerance_sec": args.selection_consensus_tolerance_sec,
            "trial_profile": args.q2_trial_profile,
            "decoder_kind": args.decoder_kind,
        },
    })
    atomic_json(args.out_root / "q2_natural_realign" / "comparison.json", comparison)
    write_q2_trace(args.out_root / "q2_natural_realign" / "trace.md", comparison, out_dir)


def seam_records(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in evidence.get("window_trace", [])[1:]:
        committed = int(window.get("committed_cursor_before", 0))
        if committed <= 0 or committed >= len(evidence["characters"]) - 2:
            continue
        rows.append({
            "window_index": int(window["window_index"]),
            "seam_index": committed - 1,
            "target_start": committed,
            "target_end": min(committed + 3, len(evidence["characters"]) - 2),
            "window": window,
        })
    return rows


def automatic_anchor_for_span(
    args: argparse.Namespace, evidence: dict[str, Any], shortlist: list[dict[str, Any]], start: int, end: int
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any] | None] | None:
    for ordinal, policy in enumerate(shortlist[:2]):
        left, right, _ = select_anchor_pair(
            evidence["anchor_rows"], policy, start, end,
            max_distance_units=args.max_anchor_search_units,
            max_pair_span_units=args.max_anchor_span_units,
            max_pair_span_sec=args.max_anchor_span_sec,
            guard_units=args.anchor_guard_units,
        )
        if left is not None and right is not None:
            return ("best_automatic" if ordinal == 0 else "strict_automatic", left, right, policy)
    # Ground-truth anchors are analysis-only and must never be used by an
    # automatic repair path.
    return None


def q3_local_repairs(
    args: argparse.Namespace, evidence: dict[str, Any], baseline_or_perturbed: list[dict[str, Any]],
    target_start: int, target_end: int, processor: Any, model: Any, shortlist: list[dict[str, Any]],
    *, force_repair: bool = False,
) -> list[dict[str, Any]]:
    anchor = automatic_anchor_for_span(args, evidence, shortlist, target_start, target_end)
    if anchor is None:
        return []
    anchor_mode, left, right, policy = anchor
    item_id = str(evidence["request"]["item_id"])
    item_root = args.subset_root / "items" / item_id
    document, gt = document_and_gt(item_root)
    audio = decode_audio(Path(evidence["request"]["audio_path"]))
    serial_args = inference_args(args, float(evidence["request"]["core_sec"]))
    target_indices = list(range(target_start, target_end + 1))
    context_rows = stage_rows(evidence["characters"], "selected")
    repairs: list[dict[str, Any]] = []
    specs = [("exact_anchor", 0.0, 0), ("audio_only_padding", 0.5, 0)]
    specs.extend(("matched_context", 0.0, int(units)) for units in args.matched_context_units[:1])
    for crop_mode, padding, context_units in specs:
        trial = local_infer(
            processor=processor, model=model, audio=audio, document=document, serial_args=serial_args,
            left=left, right=right, audio_duration_sec=len(audio) / 16000.0,
            crop_mode=crop_mode, padding_sec=padding, context_units=context_units, context_rows=context_rows,
        )
        replacement_indices = list(range(trial["replace_start"], trial["replace_end"] + 1))
        for stage_name, local_rows in (("local_raw", trial["raw_rows"]), ("local_decoded", trial["decoded_rows"])):
            anchor_reproduction = local_anchor_reproduction(local_rows, left, right)
            candidate_full, splice = bounded_splice(
                baseline_or_perturbed, local_rows, replace_start=trial["replace_start"],
                replace_end=trial["replace_end"], remerge=True,
            )
            acceptance = non_gt_acceptance(
                baseline_or_perturbed, candidate_full, target_indices,
                anchor_reproduction_max_sec=anchor_reproduction.get("max_error_sec"),
            )
            repairs.append(repair_candidate_payload(
                mode=f"{stage_name}_bounded_remerge", anchor_mode=anchor_mode, padding_sec=padding,
                crop_mode=crop_mode, context_units=context_units,
                baseline_final=baseline_or_perturbed, candidate_full=candidate_full, local_rows=local_rows,
                splice=splice, target_indices=target_indices, replacement_indices=replacement_indices,
                gt=gt, acceptance=acceptance, anchor_reproduction=anchor_reproduction,
            ) | {"forced_repair_control": force_repair, "anchor_policy": policy})
    return repairs


def _injection_effectiveness(
    baseline: list[dict[str, Any]], perturbed: list[dict[str, Any]], target_indices: list[int],
    threshold_sec: float = TIMESTAMP_STEP_SEC,
) -> dict[str, Any]:
    before = {int(row["global_character_index"]): row for row in baseline}
    after = {int(row["global_character_index"]): row for row in perturbed}
    differences: list[float] = []
    missing = []
    for index in target_indices:
        if index not in before or index not in after:
            missing.append(index)
            continue
        differences.extend((
            abs(float(after[index]["start_sec"]) - float(before[index]["start_sec"])),
            abs(float(after[index]["end_sec"]) - float(before[index]["end_sec"])),
        ))
    maximum = max(differences, default=0.0)
    return {
        "effective": bool(missing) or maximum >= threshold_sec - 1e-9,
        "threshold_sec": threshold_sec, "missing_indices": missing,
        "boundary_difference_count": len(differences),
        "mean_boundary_difference_sec": sum(differences) / len(differences) if differences else None,
        "max_boundary_difference_sec": maximum,
    }


def _remap_source_timings(
    baseline: list[dict[str, Any]], target_indices: list[int], shift_units: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    indexed = {int(row["global_character_index"]): dict(row) for row in baseline}
    replacement = []
    mapping = []
    for target in target_indices:
        source = target + shift_units
        if source not in indexed:
            continue
        row = dict(indexed[source])
        row["global_character_index"] = target
        row["character"] = indexed[target].get("character")
        row["injection_type"] = "wrong_global_character_mapping"
        row["injection_source_character_index"] = source
        replacement.append(row)
        mapping.append({"target_index": target, "source_index": source})
    if len(replacement) != len(target_indices):
        raise ValueError("wrong-global-mapping source range falls outside the song")
    perturbed, splice = bounded_splice(
        baseline, replacement, replace_start=target_indices[0], replace_end=target_indices[-1], remerge=True
    )
    return perturbed, {"mapping": mapping, "splice": splice}


def forced_clean_control_selection(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose one deterministic local candidate while bypassing safety gates.

    This is a diagnostic harm upper bound only. It excludes direct-trust and GT
    anchors, prefers exact-anchor/local-raw bounded remerge, and then chooses the
    smallest mean boundary movement. No anomaly-reduction or context-agreement
    requirement is applied.
    """
    eligible: list[tuple[tuple[int, int, float, int], int, dict[str, Any]]] = []
    for ordinal, candidate in enumerate(candidates):
        if "direct_trust" in str(candidate.get("mode", "")):
            continue
        if str(candidate.get("anchor_mode")) in {"gt_oracle", "gt_oracle_fallback"}:
            continue
        if not (candidate.get("splice") or {}).get("valid"):
            continue
        crop_priority = 0 if candidate.get("crop_mode") == "exact_anchor" else 1
        stage_priority = 0 if str(candidate.get("mode", "")).startswith("local_raw") else 1
        mean_change = ((candidate.get("modification_summary") or {}).get("boundary_change_abs_sec") or {}).get("mean")
        eligible.append(((crop_priority, stage_priority, float(mean_change or 0.0), ordinal), ordinal, candidate))
    if not eligible:
        return {
            "selected": False,
            "decision": "keep_baseline",
            "reason": "forced_clean_control_has_no_structurally_spliceable_candidate",
            "forced_write_back_control": True,
        }
    _, ordinal, candidate = min(eligible, key=lambda row: row[0])
    return {
        "selected": True,
        "decision": "replace",
        "reason": "forced_clean_control_bypasses_anomaly_and_agreement_gates",
        "forced_write_back_control": True,
        "candidate_ordinal": ordinal,
        "mode": candidate.get("mode"),
        "anchor_mode": candidate.get("anchor_mode"),
        "crop_mode": candidate.get("crop_mode"),
        "context_units": candidate.get("context_units"),
    }


def run_q3_case(
    args: argparse.Namespace, evidence: dict[str, Any], seam: dict[str, Any], condition: dict[str, Any],
    processor: Any, model: Any, shortlist: list[dict[str, Any]],
) -> dict[str, Any]:
    item_id = str(evidence["request"]["item_id"])
    item_root = args.subset_root / "items" / item_id
    document, gt = document_and_gt(item_root)
    baseline = stage_rows(evidence["characters"], "final")
    target_start = int(seam["target_start"])
    target_end = int(seam["target_end"])
    target_indices = list(range(target_start, target_end + 1))
    family = str(condition["family"])
    perturbed = baseline
    injection: dict[str, Any] = {"condition": condition}

    if family == "commit_shift":
        perturbed, replay = replay_commit_shift(baseline, int(seam["seam_index"]), float(condition["shift_sec"]))
        injection["replay"] = replay
        affected = replay["affected_indices"]
        if affected:
            target_start, target_end = min(affected), max(affected)
            target_indices = list(range(target_start, target_end + 1))
    elif family == "wrong_global_mapping":
        perturbed, replay = _remap_source_timings(baseline, target_indices, int(condition["units"]))
        injection["replay"] = replay
    elif family == "wrong_lyrics_range":
        window = seam["window"]
        baseline_start = int(window["input_character_start_before"])
        baseline_end = int(window["candidate_character_end"])
        width = baseline_end - baseline_start
        shifted_start = max(0, min(len(document.characters) - width, baseline_start + int(condition["units"])))
        shifted_end = shifted_start + width
        source_audio = decode_audio(Path(evidence["request"]["audio_path"]))
        input_start = float(window["input_start_sec"])
        input_end = float(window["input_end_sec"])
        serial_args = inference_args(args, float(evidence["request"]["core_sec"]))
        rows, audit = SERIAL.infer_slice(
            processor=processor, model=model,
            audio=source_audio[int(round(input_start * 16000)):int(round(input_end * 16000))],
            document=document, character_start=shifted_start, character_end=shifted_end,
            global_audio_offset_sec=input_start, args=serial_args,
        )
        decoded = stage_from_local_inference(rows, "local_decoded")
        decoded_ordered = sorted(decoded, key=lambda row: int(row["global_character_index"]))
        positional_offset = target_start - baseline_start
        selected_wrong = decoded_ordered[positional_offset:positional_offset + len(target_indices)]
        if len(selected_wrong) != len(target_indices):
            raise ValueError("wrong-lyrics-range inference did not return enough target-position rows")
        replacement = []
        mapping = []
        baseline_by_index = {int(row["global_character_index"]): row for row in baseline}
        for target, source in zip(target_indices, selected_wrong, strict=True):
            row = dict(source)
            wrong_index = int(source["global_character_index"])
            row["global_character_index"] = target
            row["character"] = baseline_by_index[target].get("character")
            row["injection_type"] = "wrong_lyrics_range_prediction"
            row["wrong_lyrics_character_index"] = wrong_index
            replacement.append(row)
            mapping.append({"target_index": target, "wrong_lyrics_index": wrong_index})
        perturbed, splice = bounded_splice(
            baseline, replacement, replace_start=target_start, replace_end=target_end, remerge=True
        )
        injection.update({
            "baseline_input_character_start": baseline_start, "baseline_input_character_end": baseline_end,
            "shifted_input_character_start": shifted_start, "shifted_input_character_end": shifted_end,
            "mapping": mapping, "splice": splice, "inference_audit": audit,
        })
    elif family in {"clean_detector", "clean_forced_repair"}:
        pass
    else:
        raise ValueError(family)

    effectiveness = _injection_effectiveness(baseline, perturbed, target_indices) if family not in {"clean_detector", "clean_forced_repair"} else {
        "effective": False, "reason": "clean_control"
    }
    detector = {
        "known_injected": family not in {"clean_detector", "clean_forced_repair"},
        "structural": structural_summary(perturbed),
        "injection_effectiveness": effectiveness,
        "baseline_target": evaluate_rows(baseline, gt, target_indices),
        "perturbed_target": evaluate_rows(perturbed, gt, target_indices),
    }
    repairs = q3_local_repairs(
        args, evidence, perturbed, target_start, target_end, processor, model, shortlist,
        force_repair=(family == "clean_forced_repair"),
    ) if family != "clean_detector" else []
    if family == "clean_forced_repair":
        final_selection = forced_clean_control_selection(repairs)
    else:
        final_selection = select_single_repair_candidate(
            repairs,
            require_context_agreement=False,
            excluded_anchor_modes=("gt_oracle", "gt_oracle_fallback"),
        )
    return {
        "schema_version": "demo_realign_q3_case_v2", "status": "complete", "created_at": utc_now(),
        "case_id": condition["case_id"], "family": family, "item_id": item_id,
        "audio_variant": evidence["request"]["audio_variant"], "core_sec": evidence["request"]["core_sec"],
        "evidence_path": evidence["evidence_path"], "seam": seam, "target_indices": target_indices,
        "injection": injection, "detector": detector, "repair_candidates": repairs,
        "final_non_gt_selection": final_selection,
    }


def q3_plan(args: argparse.Namespace, evidence: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    preferred: dict[str, dict[str, Any]] = {}
    for item in evidence:
        item_id = str(item["request"]["item_id"])
        score = (item["request"]["audio_variant"] == "demucs", float(item["request"]["core_sec"]) == min(args.core_sec))
        current = preferred.get(item_id)
        if current is None:
            preferred[item_id] = item
        else:
            current_score = (current["request"]["audio_variant"] == "demucs", float(current["request"]["core_sec"]) == min(args.core_sec))
            if score > current_score:
                preferred[item_id] = item
    resolved: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    selected_song_count = 0
    for item_id in sorted(preferred):
        item = preferred[item_id]
        seams = seam_records(item)[: args.q3_seams_per_song]
        if not seams:
            continue
        selected_song_count += 1
        for seam in seams:
            base = f"{item_id}_w{seam['window_index']:02d}"
            conditions = [
                {"case_id": f"{base}_mapping_minus4", "family": "wrong_global_mapping", "units": -4},
                {"case_id": f"{base}_mapping_plus4", "family": "wrong_global_mapping", "units": 4},
                {"case_id": f"{base}_lyrics_minus2", "family": "wrong_lyrics_range", "units": -2},
                {"case_id": f"{base}_lyrics_plus2", "family": "wrong_lyrics_range", "units": 2},
                {"case_id": f"{base}_lyrics_minus4", "family": "wrong_lyrics_range", "units": -4},
                {"case_id": f"{base}_lyrics_plus4", "family": "wrong_lyrics_range", "units": 4},
                {"case_id": f"{base}_commit_plus0p24", "family": "commit_shift", "shift_sec": 0.24},
                {"case_id": f"{base}_commit_plus0p48", "family": "commit_shift", "shift_sec": 0.48},
                {"case_id": f"{base}_commit_plus0p96", "family": "commit_shift", "shift_sec": 0.96},
                {"case_id": f"{base}_clean_detector", "family": "clean_detector"},
                {"case_id": f"{base}_clean_forced_repair", "family": "clean_forced_repair"},
            ]
            resolved.extend((item, seam, condition) for condition in conditions)
        if selected_song_count >= args.q3_song_count:
            break
    return resolved


def run_q3(
    args: argparse.Namespace, evidence: list[dict[str, Any]], processor: Any, model: Any,
) -> None:
    shortlist = policy_shortlist(args)
    plan = q3_plan(args, evidence)
    plan_rows = [
        {"evidence_path": item["evidence_path"], "item_id": item["request"]["item_id"], "seam": seam, "condition": condition}
        for item, seam, condition in plan
    ]
    atomic_json(args.out_root / "q3_injection_matrix" / "plan.resolved.json", {
        "schema_version": "demo_realign_q3_plan_v2", "created_at": utc_now(),
        "requested_song_count": args.q3_song_count, "requested_seams_per_song": args.q3_seams_per_song,
        "resolved_case_count": len(plan_rows), "cases": plan_rows,
    })
    out_dir = args.out_root / "q3_injection_matrix" / "cases"
    for item, seam, condition in plan:
        case_id = str(condition["case_id"])
        path = out_dir / f"{case_id}.json"
        request = {
            "case": condition, "evidence_request_hash": item["request_hash"],
            "shortlist_policy_ids": [row.get("policy_id") for row in shortlist[:2]],
            "padding_sec": args.padding_sec,
            "matched_context_units": args.matched_context_units,
            "anchor_limits": [args.anchor_guard_units, args.max_anchor_span_units, args.max_anchor_span_sec],
        }
        request_hash = canonical_hash(request)
        status_path = path.with_suffix(".status.json")
        if not args.force and status_is_complete(status_path, request_hash) and path.is_file():
            status(args.out_root, phase="q3", case_id=case_id, state="skipped_identity_match", path=str(path))
            continue
        status(args.out_root, phase="q3", case_id=case_id, state="running", path=str(path))
        atomic_json(status_path, {"request_hash": request_hash, "status": "running", "updated_at": utc_now()})
        try:
            payload = run_q3_case(args, item, seam, condition, processor, model, shortlist)
            payload["request_hash"] = request_hash
            payload["request"] = request
            atomic_json(path, payload)
            atomic_json(status_path, {"request_hash": request_hash, "status": "complete", "updated_at": utc_now()})
            status(args.out_root, phase="q3", case_id=case_id, state="complete", path=str(path), repair_candidate_count=len(payload["repair_candidates"]))
        except Exception as exc:
            failure = {"request_hash": request_hash, "status": "failed", "updated_at": utc_now(), "error": str(exc), "traceback": traceback.format_exc()}
            atomic_json(status_path, failure)
            atomic_json(path.with_suffix(".failure.json"), failure)
            status(args.out_root, phase="q3", case_id=case_id, state="failed", error=str(exc), path=str(path.with_suffix('.failure.json')))
            if args.fail_fast:
                raise
    q3_summary = summarize_case_directory(out_dir)
    atomic_json(args.out_root / "q3_injection_matrix" / "detector_summary.json", summarize_q3_detector(out_dir))
    atomic_json(args.out_root / "q3_injection_matrix" / "repair_summary.json", q3_summary)
    atomic_jsonl(args.out_root / "q3_injection_matrix" / "cases.jsonl", plan_rows)
    failures = [read_json(path) for path in sorted(out_dir.glob("*.failure.json"))]
    atomic_jsonl(args.out_root / "q3_injection_matrix" / "failures.jsonl", failures)


def summarize_case_directory(directory: Path) -> dict[str, Any]:
    cases = []
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        if payload.get("status") == "complete":
            cases.append(payload)
    repair_candidates = [candidate for case in cases for candidate in case.get("repair_candidates", [])]
    deltas = []
    for candidate in repair_candidates:
        before = candidate.get("metrics", {}).get("before", {}).get("boundary_mae_sec")
        after = candidate.get("metrics", {}).get("after", {}).get("boundary_mae_sec")
        if before is not None and after is not None:
            deltas.append(float(after) - float(before))
    selected_cases = [case for case in cases if case.get("final_non_gt_selection", {}).get("selected")]
    return {
        "schema_version": "demo_realign_case_summary_v2", "created_at": utc_now(),
        "case_count": len(cases), "repair_candidate_count": len(repair_candidates),
        "case_with_selected_repair_count": len(selected_cases),
        "non_gt_accept_count": sum(bool(row.get("acceptance", {}).get("accepted")) for row in repair_candidates),
        "structurally_valid_count": sum(bool(row.get("splice", {}).get("valid")) for row in repair_candidates),
        "improved_boundary_mae_count": sum(value < 0 for value in deltas),
        "worsened_boundary_mae_count": sum(value > 0 for value in deltas),
        "delta_boundary_mae_sec": {
            "count": len(deltas), "mean": sum(deltas) / len(deltas) if deltas else None,
            "min": min(deltas, default=None), "max": max(deltas, default=None),
        },
    }


def summarize_q3_detector(directory: Path) -> dict[str, Any]:
    families = Counter()
    injected = clean = effective = ineffective = 0
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        if path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(path)
        family = str(payload.get("family"))
        families[family] += 1
        detector = payload.get("detector", {})
        if detector.get("known_injected"):
            injected += 1
            if detector.get("injection_effectiveness", {}).get("effective"):
                effective += 1
            else:
                ineffective += 1
        else:
            clean += 1
    return {
        "schema_version": "demo_realign_q3_detector_summary_v2", "created_at": utc_now(),
        "case_count_by_family": dict(sorted(families.items())),
        "injected_case_count": injected, "effective_injected_case_count": effective,
        "ineffective_injected_case_count": ineffective, "clean_case_count": clean,
        "note": "Ineffective injections are retained for debugging but must not enter repair-success rates.",
    }


def write_q2_trace(path: Path, summary: dict[str, Any], case_directory: Path) -> None:
    lines = [
        "# Q2 natural-candidate quick trace",
        "",
        "This quick stage automatically mined structural collapse/conflict candidates without GT.",
        "GT was used only after candidate creation for repair evaluation.",
        "",
        f"- requested cases: {summary.get('requested_case_count', 0)}",
        f"- completed cases: {summary.get('completed_case_count', 0)}",
        f"- repair candidates: {summary.get('repair_candidate_count', 0)}",
        f"- improved boundary-MAE candidates: {summary.get('improved_boundary_mae_count', 0)}",
        f"- worsened boundary-MAE candidates: {summary.get('worsened_boundary_mae_count', 0)}",
        "",
        "The dependency chain below identifies the previous committed end that supplied a",
        "compression floor. It does not assert that the predecessor is GT-wrong.",
        "",
    ]
    for case_path in sorted(case_directory.glob("*.json")) if case_directory.exists() else []:
        if case_path.name.endswith((".status.json", ".failure.json")):
            continue
        payload = read_json(case_path)
        source = payload.get("source_candidate", {})
        lines.extend([
            f"## {payload.get('case_id')}",
            "",
            f"- item/audio/core: `{payload.get('item_id')}` / `{payload.get('audio_variant')}` / `{payload.get('core_sec')}`",
            f"- observed span: `{source.get('observed_character_start')}..{source.get('observed_character_end')}`",
            f"- dependency span: `{source.get('dependency_character_start')}..{source.get('dependency_character_end')}`",
            f"- triggers: `{json.dumps(source.get('trigger_counts', {}), ensure_ascii=False, sort_keys=True)}`",
            "",
        ])
        trace = source.get("constraint_dependency_trace", [])
        if trace:
            for step in trace:
                lines.append(
                    f"- `{step.get('dependency_index')}` -> `{step.get('affected_index')}`: "
                    f"floor `{step.get('compression_floor_sec')}` s"
                )
        else:
            lines.append("- no forward-compression predecessor was required for this candidate")
        repair_candidates = payload.get("repair_candidates", [])
        ranked = []
        for candidate in repair_candidates:
            before = candidate.get("metrics", {}).get("before", {}).get("boundary_mae_sec")
            after = candidate.get("metrics", {}).get("after", {}).get("boundary_mae_sec")
            if before is None or after is None:
                continue
            ranked.append((float(after) - float(before), candidate))
        if ranked:
            delta, best = min(ranked, key=lambda item: item[0])
            lines.extend([
                "",
                f"- best observed target boundary-MAE delta: `{delta:+.6f}` s",
                f"- best mode: `{best.get('anchor_mode')}/{best.get('mode')}/padding={best.get('padding_sec')}`",
                f"- non-GT accepted: `{best.get('acceptance', {}).get('accepted')}`",
            ])
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_plan(args: argparse.Namespace, items: list[dict[str, Any]], checkpoint_identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "demo_realign_quick_plan_v2_1", "created_at": utc_now(),
        "stage_semantics": {
            "quick": "scientific diagnostic whose reviewed results may change overnight design",
            "smoke": "separate post-design execution check before launching frozen overnight",
            "overnight": "not implemented or launched by this quick entry",
        },
        "phases": args.phase, "subset_root": str(args.subset_root.resolve()),
        "out_root": str(args.out_root.resolve()), "roles": args.roles,
        "items": [str(row["item_id"]) for row in items],
        "item_roles": {str(row["item_id"]): row.get("selection_role") for row in items},
        "audio_variants": args.audio_variants, "core_sec": args.core_sec,
        "audio_only_padding_sec": args.padding_sec,
        "matched_context_units": args.matched_context_units,
        "selection": {
            "ground_truth_anchor_modes_excluded": True,
            "requires_second_reasonable_input_agreement": args.q2_require_context_agreement,
            "agreement_tolerance_sec": args.selection_consensus_tolerance_sec,
            "trial_profile": args.q2_trial_profile,
            "decoder_kind": args.decoder_kind,
        },
        "rollback_predecessor_units": args.rollback_predecessor_units,
        "natural_candidate_limits": {
            "max_target_units": args.max_target_units,
            "disagreement_peak_threshold_sec": args.disagreement_peak_threshold_sec,
        },
        "anchor_limits": {
            "guard_units": args.anchor_guard_units,
            "max_search_units_each_side": args.max_anchor_search_units,
            "max_pair_span_units": args.max_anchor_span_units,
            "max_pair_span_sec": args.max_anchor_span_sec,
        },
        "model": args.model, "revision": args.revision,
        "decoder": {
            "kind": args.decoder_kind,
            "gpu_checkpoint": None if args.gpu_decoder_checkpoint is None else str(args.gpu_decoder_checkpoint.resolve()),
        },
        "q2_execution": {
            "trial_profile": args.q2_trial_profile,
            "case_plan": None if args.q2_case_plan is None else str(args.q2_case_plan.resolve()),
            "require_context_agreement": args.q2_require_context_agreement,
            "include_gt_anchor": args.include_gt_anchor,
            "max_automatic_anchor_policies": args.max_automatic_anchor_policies,
        },
        "checkpoint_identity": checkpoint_identity,
        "q3": {"song_count": args.q3_song_count, "seams_per_song": args.q3_seams_per_song},
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--subset-root", type=Path, required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--phase", nargs="+", choices=("evidence", "q1", "q2", "q3", "collect", "all"), default=["all"])
    p.add_argument(
        "--roles", nargs="+", choices=("development", "quick_v2_extra", "heldout", "spare"),
        default=["development", "quick_v2_extra"],
    )
    p.add_argument("--role", choices=("development", "quick_v2_extra", "heldout", "spare"), help=argparse.SUPPRESS)
    p.add_argument("--item-id", action="append", default=[])
    p.add_argument("--audio-variants", nargs="+", choices=("demucs", "official_vocal", "spleeter", "mix"), default=["demucs", "official_vocal"])
    p.add_argument("--core-sec", nargs="+", type=float, default=[30.0])
    p.add_argument("--padding-sec", nargs="+", type=float, default=[0.5, 1.5], help="audio-only padding controls")
    p.add_argument("--matched-context-units", nargs="+", type=int, default=[2, 4])
    p.add_argument("--selection-consensus-tolerance-sec", type=float, default=0.16)
    p.add_argument("--rollback-predecessor-units", type=int, default=4)
    p.add_argument("--max-target-units", type=int, default=8)
    p.add_argument("--disagreement-peak-threshold-sec", type=float, default=0.24)
    p.add_argument("--anchor-guard-units", type=int, default=1)
    p.add_argument("--max-anchor-search-units", type=int, default=16)
    p.add_argument("--max-anchor-span-units", type=int, default=16)
    p.add_argument("--max-anchor-span-sec", type=float, default=12.0)
    p.add_argument("--model-kind", choices=("raw", "projector", "lora"), default="lora")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--model", default=os.environ.get("MODEL_SOURCE") or os.environ.get("MODEL_ID", "Qwen/Qwen3-ForcedAligner-0.6B-hf"))
    p.add_argument("--revision", default=os.environ.get("MODEL_REVISION", "c07281df297b9905d24a508279258cccf987a064"))
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action="store_true", default=os.environ.get("HF_HUB_OFFLINE") == "1")
    p.add_argument("--device", default="cuda")
    p.add_argument("--decoder-kind", choices=("raw", "official", "gpu_tcn", "gpu_transformer"), default="official")
    p.add_argument("--gpu-decoder-checkpoint", type=Path)
    p.add_argument("--q2-case-plan", type=Path, help="External decoder-union/escalation plan JSONL")
    p.add_argument("--q2-trial-profile", choices=("exact", "plus2", "plus4", "exact_plus2", "all"), default="all")
    p.add_argument("--q2-require-context-agreement", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--include-gt-anchor", action="store_true")
    p.add_argument("--max-automatic-anchor-policies", type=int, default=2)
    p.add_argument("--runtime-anchor-policy", action="store_true", help="Use the no-GT conservative A4 runtime anchor policy")
    p.add_argument("--runtime-anchor-margin-quantile", type=float, default=0.75)
    p.add_argument("--runtime-anchor-overlap-tolerance-sec", type=float, default=0.16)
    p.add_argument("--runtime-anchor-stability-tolerance-sec", type=float, default=0.08)
    p.add_argument("--timestamp-segment-sec", type=float, default=TIMESTAMP_STEP_SEC)
    p.add_argument("--demucs-model", default="htdemucs_ft")
    p.add_argument("--left-context-sec", type=float, default=10.0)
    p.add_argument("--right-context-sec", type=float, default=10.0)
    p.add_argument("--future-line-padding", type=int, default=1)
    p.add_argument("--minimum-forward-characters", type=int, default=64)
    p.add_argument("--future-character-ratio", type=float, default=1.35)
    p.add_argument("--max-candidate-expansions", type=int, default=4)
    p.add_argument("--boundary-start-tolerance-sec", type=float, default=0.32)
    p.add_argument("--seam-tolerance-sec", type=float, default=0.16)
    p.add_argument("--q3-song-count", type=int, default=6)
    p.add_argument("--q3-seams-per-song", type=int, default=2)
    p.add_argument("--force", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    return p


def validate_anchor_policy_args(args: argparse.Namespace) -> None:
    if args.max_automatic_anchor_policies < 0:
        raise ValueError("--max-automatic-anchor-policies must be non-negative")
    if (
        args.max_automatic_anchor_policies == 0
        and not args.runtime_anchor_policy
        and not args.include_gt_anchor
    ):
        raise ValueError(
            "--max-automatic-anchor-policies=0 requires --runtime-anchor-policy "
            "or --include-gt-anchor"
        )


def main() -> int:
    args = parser().parse_args()
    args.subset_root = args.subset_root.resolve()
    args.out_root = args.out_root.resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)
    validate_anchor_policy_args(args)
    args.gpu_decoder_runtime = None
    args.gpu_decoder_identity = None
    if args.decoder_kind in {"gpu_tcn", "gpu_transformer"}:
        if args.gpu_decoder_checkpoint is None:
            raise ValueError(f"--decoder-kind {args.decoder_kind} requires --gpu-decoder-checkpoint")
        from lyricalign.demo.gpu_boundary_decoder import GpuBoundaryDecoderRuntime
        args.gpu_decoder_runtime = GpuBoundaryDecoderRuntime(
            args.gpu_decoder_checkpoint.resolve(), device=args.device
        )
        args.gpu_decoder_identity = args.gpu_decoder_runtime.identity
    phases = set(args.phase)
    if "all" in phases:
        phases = {"evidence", "q1", "q2", "q3", "collect"}
    if args.role:
        args.roles = [args.role]
    items = selected_items(args.subset_root, args.roles, args.item_id)
    if not items:
        raise ValueError("no selected items")
    checkpoint = args.checkpoint.resolve() if args.checkpoint else None
    checkpoint_identity = SERIAL.checkpoint_identity(args.model_kind, checkpoint)
    plan = build_plan(args, items, checkpoint_identity)
    atomic_json(args.out_root / "plan.json", plan)
    atomic_json(args.out_root / "resolved_inputs.json", {
        "created_at": utc_now(), "subset_selection": items,
        "item_roots": [str((args.subset_root / 'items' / str(row['item_id'])).resolve()) for row in items],
    })

    processor = model = None
    needs_model = bool(phases & {"evidence", "q2", "q3"})
    try:
        if needs_model:
            processor, model = SERIAL.load_model(args, args.model_kind, checkpoint)
        if "evidence" in phases:
            run_evidence(args, items, processor, model, checkpoint_identity)
        evidence = load_evidence(args)
        if "q1" in phases:
            if not evidence:
                raise RuntimeError("Q1 requires completed evidence; run --phase evidence first")
            run_q1(args, evidence)
        if "q2" in phases:
            if not evidence:
                raise RuntimeError("Q2 requires completed evidence")
            run_q2(args, evidence, processor, model)
        if "q3" in phases:
            if not evidence:
                raise RuntimeError("Q3 requires completed evidence")
            run_q3(args, evidence, processor, model)
        if "collect" in phases:
            summary, failures = collect_quick_results(args.out_root)
            print(json.dumps({"summary": summary, "failures": failures}, ensure_ascii=False, sort_keys=True))
    finally:
        if model is not None:
            del model
        if processor is not None:
            del processor
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
