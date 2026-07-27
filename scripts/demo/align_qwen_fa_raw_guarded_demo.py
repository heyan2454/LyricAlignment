#!/usr/bin/env python3
"""Standalone R2 demo: raw timestamp baseline plus conservative local realignment.

The production path never uses ground truth. It detects broad structural/cross-
window anomalies, but modifies a region only when exact-anchor and +2 lyric-
context inferences agree within tolerance and the bounded splice reduces the
non-GT anomaly score without introducing overlap/negative duration.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "demo"))

import align_qwen_fa_serial_demo as SERIAL
import run_demo_realign_quick as QUICK

from lyricalign.demo.alignment_artifacts import stage_rows, write_alignment_bundle
from lyricalign.demo.karaoke import normalize_alignment_language, parse_lyrics_text
from lyricalign.demo.raw_guarded import (
    agreement_between_trials,
    build_runtime_anchor_rows,
    choose_anchor_pair,
    choose_runtime_anchor_policy,
    nonoverlapping_candidates,
)
from lyricalign.demo.realign_diagnostics import (
    accepted_shadow_rows,
    atomic_json,
    bounded_splice,
    local_anchor_reproduction,
    mine_natural_candidates,
    non_gt_acceptance,
    structural_summary,
)
from lyricalign.training.qwen_fa_runtime import decode_audio

DEFAULT_MODEL = "/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064"
DEFAULT_REVISION = "c07281df297b9905d24a508279258cccf987a064"
DEFAULT_R2 = "/root/autodl-tmp/AST_storage/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"
DEFAULT_OUT = "/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics/raw_guarded_demo_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serial_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
        core_sec=args.core_sec,
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
        future_line_padding=args.future_line_padding,
        minimum_forward_characters=args.minimum_forward_characters,
        future_character_ratio=args.future_character_ratio,
        max_candidate_expansions=args.max_candidate_expansions,
        boundary_start_tolerance_sec=args.boundary_start_tolerance_sec,
        seam_tolerance_sec=args.seam_tolerance_sec,
        capture_shadow_rows=True,
        decoder_kind="raw",
        gpu_decoder_runtime=None,
    )


def max_boundary_change(before: list[dict[str, Any]], after: list[dict[str, Any]], indices: list[int]) -> float:
    a = {int(row["global_character_index"]): row for row in before}
    b = {int(row["global_character_index"]): row for row in after}
    values: list[float] = []
    for index in indices:
        if index not in a or index not in b:
            continue
        values.extend((
            abs(float(a[index]["start_sec"]) - float(b[index]["start_sec"])),
            abs(float(a[index]["end_sec"]) - float(b[index]["end_sec"])),
        ))
    return max(values, default=0.0)


def run_guarded_realign(
    *, args: argparse.Namespace, processor: Any, model: Any, audio: Any,
    document: Any, baseline_rows: list[dict[str, Any]], trace: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    shadow = accepted_shadow_rows(trace)
    candidates = mine_natural_candidates(
        baseline_rows,
        shadow,
        item_id=args.item_id,
        audio_variant=args.audio_variant,
        max_target_units=args.max_target_units,
        disagreement_peak_threshold_sec=args.disagreement_peak_threshold_sec,
        timestamp_step_sec=args.timestamp_segment_sec,
    )
    candidates = nonoverlapping_candidates(candidates)
    anchor_rows = build_runtime_anchor_rows(baseline_rows, shadow)
    policy = choose_runtime_anchor_policy(
        anchor_rows,
        margin_quantile=args.anchor_margin_quantile,
        overlap_tolerance_sec=args.anchor_overlap_tolerance_sec,
        stability_tolerance_sec=args.anchor_stability_tolerance_sec,
    )
    current = stage_rows(baseline_rows, "final")
    decisions: list[dict[str, Any]] = []
    sargs = serial_args(args)
    duration = len(audio) / 16000.0

    for candidate in candidates:
        target_start = int(candidate["dependency_character_start"])
        target_end = int(candidate["dependency_character_end"])
        target_indices = list(range(target_start, target_end + 1))
        left, right, rejected = choose_anchor_pair(
            anchor_rows, policy, target_start, target_end,
            max_distance_units=args.max_anchor_search_units,
            max_pair_span_units=args.max_anchor_span_units,
            max_pair_span_sec=args.max_anchor_span_sec,
            guard_units=args.anchor_guard_units,
        )
        decision: dict[str, Any] = {
            "case_id": candidate["case_id"],
            "source_candidate": candidate,
            "target_indices": target_indices,
            "selected": False,
            "anchor_rejections": rejected,
        }
        if left is None or right is None:
            decision["reason"] = "no_conservative_anchor_pair"
            decisions.append(decision)
            continue

        exact = QUICK.local_infer(
            processor=processor, model=model, audio=audio, document=document, serial_args=sargs,
            left=left, right=right, audio_duration_sec=duration,
            crop_mode="exact_anchor", padding_sec=0.0, context_units=0,
            context_rows=stage_rows(baseline_rows, "selected"),
        )
        plus2 = QUICK.local_infer(
            processor=processor, model=model, audio=audio, document=document, serial_args=sargs,
            left=left, right=right, audio_duration_sec=duration,
            crop_mode="matched_context", padding_sec=0.0, context_units=2,
            context_rows=stage_rows(baseline_rows, "selected"),
        )
        replacement_indices = list(range(int(exact["replace_start"]), int(exact["replace_end"]) + 1))
        agreement = agreement_between_trials(
            exact["raw_rows"], plus2["raw_rows"], target_indices,
            tolerance_sec=args.context_agreement_tolerance_sec,
        )
        exact_full, exact_splice = bounded_splice(
            current, exact["raw_rows"],
            replace_start=int(exact["replace_start"]), replace_end=int(exact["replace_end"]), remerge=True,
        )
        acceptance = non_gt_acceptance(
            current, exact_full, target_indices,
            anchor_reproduction_max_sec=local_anchor_reproduction(exact["raw_rows"], left, right).get("max_error_sec"),
            tolerance_sec=args.anchor_reproduction_tolerance_sec,
        )
        change_max = max_boundary_change(current, exact_full, replacement_indices)
        decision.update({
            "left_anchor": left,
            "right_anchor": right,
            "exact": {"crop": [exact["crop_start_sec"], exact["crop_end_sec"]], "wall_sec": exact["wall_sec"]},
            "plus2": {"crop": [plus2["crop_start_sec"], plus2["crop_end_sec"]], "wall_sec": plus2["wall_sec"]},
            "context_agreement": agreement,
            "acceptance": acceptance,
            "splice": exact_splice,
            "max_boundary_change_sec": change_max,
        })
        if not agreement["supported"]:
            decision["reason"] = "exact_plus2_disagreement"
        elif not acceptance.get("accepted"):
            decision["reason"] = "non_gt_safety_gate_rejected"
        elif not exact_splice.get("valid"):
            decision["reason"] = "invalid_bounded_splice"
        elif change_max > args.max_repair_boundary_change_sec + 1e-9:
            decision["reason"] = "repair_change_exceeds_cap"
        else:
            current = exact_full
            decision["selected"] = True
            decision["reason"] = "exact_supported_by_plus2_and_anomaly_reduced"
        decisions.append(decision)

    return current, {
        "schema_version": "qwen_fa_raw_guarded_realign_v1",
        "created_at": utc_now(),
        "candidate_count": len(candidates),
        "selected_repair_count": sum(bool(row["selected"]) for row in decisions),
        "anchor_policy": policy,
        "decisions": decisions,
        "final_structural": structural_summary(current),
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--lyrics", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True, help="Prefer Demucs lead-vocal audio")
    p.add_argument("--out-root", type=Path, default=Path(os.environ.get("RAW_GUARDED_OUT_ROOT", DEFAULT_OUT)))
    p.add_argument("--item-id", default="demo")
    p.add_argument("--audio-variant", default="demucs")
    p.add_argument("--model", default=os.environ.get("MODEL_SOURCE", DEFAULT_MODEL))
    p.add_argument("--revision", default=os.environ.get("MODEL_REVISION", DEFAULT_REVISION))
    p.add_argument("--r2-checkpoint", type=Path, default=Path(os.environ.get("R2_CHECKPOINT", DEFAULT_R2)))
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--language", type=normalize_alignment_language, default="Chinese")
    p.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    p.add_argument("--core-sec", type=float, default=30.0)
    p.add_argument("--left-context-sec", type=float, default=10.0)
    p.add_argument("--right-context-sec", type=float, default=10.0)
    p.add_argument("--future-line-padding", type=int, default=1)
    p.add_argument("--minimum-forward-characters", type=int, default=64)
    p.add_argument("--future-character-ratio", type=float, default=1.35)
    p.add_argument("--max-candidate-expansions", type=int, default=4)
    p.add_argument("--boundary-start-tolerance-sec", type=float, default=0.32)
    p.add_argument("--seam-tolerance-sec", type=float, default=0.16)
    p.add_argument("--max-target-units", type=int, default=8)
    p.add_argument("--disagreement-peak-threshold-sec", type=float, default=0.24)
    p.add_argument("--anchor-margin-quantile", type=float, default=0.75)
    p.add_argument("--anchor-overlap-tolerance-sec", type=float, default=0.16)
    p.add_argument("--anchor-stability-tolerance-sec", type=float, default=0.08)
    p.add_argument("--anchor-guard-units", type=int, default=1)
    p.add_argument("--max-anchor-search-units", type=int, default=16)
    p.add_argument("--max-anchor-span-units", type=int, default=16)
    p.add_argument("--max-anchor-span-sec", type=float, default=12.0)
    p.add_argument("--context-agreement-tolerance-sec", type=float, default=0.16)
    p.add_argument("--anchor-reproduction-tolerance-sec", type=float, default=0.16)
    p.add_argument("--max-repair-boundary-change-sec", type=float, default=0.80)
    p.add_argument("--disable-realign", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    for path in (args.lyrics, args.audio, args.r2_checkpoint):
        if not path.exists():
            raise FileNotFoundError(path)
    args.lyrics = args.lyrics.resolve()
    args.audio = args.audio.resolve()
    args.r2_checkpoint = args.r2_checkpoint.resolve()
    args.out_root = args.out_root.resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)

    checkpoint = SERIAL.checkpoint_identity("lora", args.r2_checkpoint)
    request = {
        "schema_version": "qwen_fa_raw_guarded_demo_request_v2",
        "lyrics": str(args.lyrics),
        "lyrics_sha256": SERIAL.sha256(args.lyrics),
        "audio": str(args.audio),
        "audio_sha256": SERIAL.sha256(args.audio),
        "model": str(args.model),
        "revision": args.revision,
        "checkpoint": checkpoint,
        "language": args.language,
        "timestamp_segment_sec": args.timestamp_segment_sec,
        "window": {
            "core_sec": args.core_sec,
            "left_context_sec": args.left_context_sec,
            "right_context_sec": args.right_context_sec,
            "future_line_padding": args.future_line_padding,
            "minimum_forward_characters": args.minimum_forward_characters,
            "future_character_ratio": args.future_character_ratio,
            "max_candidate_expansions": args.max_candidate_expansions,
            "boundary_start_tolerance_sec": args.boundary_start_tolerance_sec,
            "seam_tolerance_sec": args.seam_tolerance_sec,
        },
        "realign": {
            "enabled": not args.disable_realign,
            "max_target_units": args.max_target_units,
            "disagreement_peak_threshold_sec": args.disagreement_peak_threshold_sec,
            "anchor_margin_quantile": args.anchor_margin_quantile,
            "context_agreement_tolerance_sec": args.context_agreement_tolerance_sec,
            "anchor_reproduction_tolerance_sec": args.anchor_reproduction_tolerance_sec,
            "max_repair_boundary_change_sec": args.max_repair_boundary_change_sec,
            "contexts": ["exact", "matched_plus2_audio_and_text"],
        },
    }
    request_hash = SERIAL.canonical_hash(request)
    complete_path = args.out_root / "complete.json"
    final_path = args.out_root / "alignment.json"
    baseline_path = args.out_root / "baseline_raw" / "alignment.json"
    if not args.force and complete_path.is_file() and final_path.is_file() and baseline_path.is_file():
        try:
            previous = json.loads(complete_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if previous.get("status") == "complete" and previous.get("request_hash") == request_hash:
            print(json.dumps({
                "status": "skipped_identity_match",
                "out_root": str(args.out_root),
                "request_hash": request_hash,
            }, ensure_ascii=False), flush=True)
            return 0

    document = parse_lyrics_text(args.lyrics.read_text(encoding="utf-8-sig"), language=args.language)
    audio = decode_audio(args.audio)
    load_args = SimpleNamespace(
        model=str(args.model), revision=args.revision, local_files_only=args.local_files_only,
        cache_dir=args.cache_dir, device=args.device,
    )
    processor, model = SERIAL.load_model(load_args, "lora", args.r2_checkpoint)
    try:
        baseline_rows, trace = SERIAL.windowed_alignment(
            processor, model, audio, document, serial_args(args)
        )
        baseline_payload = {
            "schema_version": "qwen_fa_raw_guarded_demo_v1",
            "created_at": utc_now(),
            "identity": {
                "request_hash": SERIAL.canonical_hash({"request_hash": request_hash, "artifact": "baseline_raw"}),
                "pipeline_request_hash": request_hash,
                "request": request,
                "model": str(args.model), "revision": args.revision,
                "r2_checkpoint": str(args.r2_checkpoint),
                "timestamp_decoder": "raw", "realign_enabled": not args.disable_realign,
                "realign_contexts": ["exact", "matched_plus2_audio_and_text"],
            },
            "summary": {
                "audio_duration_sec": len(audio) / 16000.0,
                "character_count": len(baseline_rows),
                "window_count": len(trace),
                "timestamp_decoder": "raw",
            },
            "lines": [line.__dict__ for line in document.lines],
            "characters": baseline_rows,
            "window_trace": trace,
        }
        write_alignment_bundle(args.out_root / "baseline_raw" / "alignment.json", baseline_payload)
        if args.disable_realign:
            final_rows = stage_rows(baseline_rows, "final")
            diagnostics = {"candidate_count": 0, "selected_repair_count": 0, "disabled": True}
        else:
            final_rows, diagnostics = run_guarded_realign(
                args=args, processor=processor, model=model, audio=audio, document=document,
                baseline_rows=baseline_rows, trace=trace,
            )
        final_payload = {
            **baseline_payload,
            "created_at": utc_now(),
            "identity": {
                **baseline_payload["identity"],
                "request_hash": SERIAL.canonical_hash({"request_hash": request_hash, "artifact": "guarded_final"}),
                "artifact": "guarded_final",
            },
            "summary": {
                **baseline_payload["summary"],
                "selected_repair_count": diagnostics.get("selected_repair_count", 0),
                "candidate_count": diagnostics.get("candidate_count", 0),
                "guarded_realign": not args.disable_realign,
            },
            "characters": final_rows,
            "raw_guarded_realign": diagnostics,
        }
        artifact = write_alignment_bundle(args.out_root / "alignment.json", final_payload)
        atomic_json(args.out_root / "raw_guarded_realign.json", diagnostics)
        atomic_json(args.out_root / "complete.json", {
            "status": "complete", "created_at": utc_now(),
            "request_hash": request_hash,
            "request": request,
            "alignment": str((args.out_root / "alignment.json").resolve()),
            "quality": artifact["quality"],
            "candidate_count": diagnostics.get("candidate_count", 0),
            "selected_repair_count": diagnostics.get("selected_repair_count", 0),
        })
        print(json.dumps({
            "status": "complete", "out_root": str(args.out_root.resolve()),
            "candidate_count": diagnostics.get("candidate_count", 0),
            "selected_repair_count": diagnostics.get("selected_repair_count", 0),
            "request_hash": request_hash,
        }, ensure_ascii=False), flush=True)
    finally:
        del model, processor
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
