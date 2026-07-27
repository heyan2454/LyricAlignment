#!/usr/bin/env python3
"""Run the controlled 2x2 R2 decoder/realign demo experiment.

Branches share one model/checkpoint, one separated-vocal input, one 30-second
window policy, and one raw-argmax serial planning trajectory:

* O0: official timestamp decoder, no realign
* O1: official timestamp decoder, guarded local realign
* R0: raw argmax timestamps, no realign
* R1: raw argmax timestamps, guarded local realign

The raw planner chooses the accepted lyric slice, core ownership, and next-window
cursor once.  Both timestamp decoders are then replayed on exactly those accepted
windows.  This prevents the official decoder's monotonic projection from proving
a bogus boundary by creating a zero-duration prefix or one extremely long unit.
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

import align_qwen_fa_raw_guarded_demo as GUARDED
import align_qwen_fa_serial_demo as SERIAL

from lyricalign.demo.alignment_artifacts import stage_rows, write_alignment_bundle
from lyricalign.demo.karaoke import normalize_alignment_language, parse_lyrics_text
from lyricalign.demo.realign_diagnostics import atomic_json, structural_summary
from lyricalign.training.qwen_fa_runtime import decode_audio

DEFAULT_MODEL = GUARDED.DEFAULT_MODEL
DEFAULT_REVISION = GUARDED.DEFAULT_REVISION
DEFAULT_R2 = GUARDED.DEFAULT_R2

BRANCHES = {
    "official_no_realign": {"decoder_kind": "official", "realign": False, "short": "O0"},
    "official_realign": {"decoder_kind": "official", "realign": True, "short": "O1"},
    "raw_no_realign": {"decoder_kind": "raw", "realign": False, "short": "R0"},
    "raw_realign": {"decoder_kind": "raw", "realign": True, "short": "R1"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist reproducible window decisions without duplicating shadow rows."""
    result: list[dict[str, Any]] = []
    for source in trace:
        row = {key: value for key, value in source.items() if key != "shadow_rows"}
        row["shadow_row_count"] = len(source.get("shadow_rows") or [])
        result.append(row)
    return result


def trajectory_projection(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact the shared planner decisions independently of timestamp values."""
    fields = (
        "window_index", "status", "silent_core_skipped",
        "input_character_start_before", "committed_cursor_before", "committed_cursor_after",
        "candidate_character_start", "candidate_character_end",
        "committed_character_start", "committed_character_end",
        "next_window_input_character_start", "next_uncommitted_character_start",
    )
    projected: list[dict[str, Any]] = []
    for row in trace:
        item = {field: row.get(field) for field in fields}
        item["attempts"] = [
            {
                "status": attempt.get("status"),
                "candidate_character_start": attempt.get("candidate_character_start"),
                "candidate_character_end": attempt.get("candidate_character_end"),
                "committed_prefix_count": attempt.get("committed_prefix_count"),
                "next_window_input_character_start": attempt.get("next_window_input_character_start"),
            }
            for attempt in row.get("attempts", [])
        ]
        projected.append(item)
    return projected



def project_trace_for_decoder(
    trace: list[dict[str, Any]], decoder_kind: str,
) -> list[dict[str, Any]]:
    """Project accepted-window shadow rows while preserving planner decisions."""
    result: list[dict[str, Any]] = []
    for source in trace:
        row = dict(source)
        shadow = [dict(item) for item in source.get("shadow_rows") or []]
        row["shadow_rows"] = SERIAL.project_rows_for_decoder(shadow, decoder_kind)
        row["planner_decoder_kind"] = "raw"
        row["output_decoder_kind"] = decoder_kind
        row["serial_control_decoder_kind"] = "raw_shared_planner"
        result.append(row)
    return result


def replay_decoder_on_shared_trace(
    trace: list[dict[str, Any]], *, decoder_kind: str, document: Any,
    duration_sec: float, seam_tolerance_sec: float,
) -> list[dict[str, Any]]:
    """Build one whole-song output from a fixed accepted-window trajectory.

    Candidate text, ownership, and cursor movement are already frozen in
    ``trace``.  Only the timestamp decoder fields are changed here.
    """
    committed: list[dict[str, Any]] = []
    for window in trace:
        if bool(window.get("silent_core_skipped")):
            continue
        first = int(window.get("committed_character_start", 0))
        last = int(window.get("committed_character_end", first))
        if last <= first:
            continue
        shadow = window.get("shadow_rows") or []
        by_index = {int(row["global_character_index"]): dict(row) for row in shadow}
        missing = [index for index in range(first, last) if index not in by_index]
        if missing:
            raise RuntimeError(
                f"shared planner trace missing committed rows for decoder={decoder_kind}: "
                f"window={window.get('window_index')} examples={missing[:8]}"
            )
        selected = [by_index[index] for index in range(first, last)]
        projected = SERIAL.project_rows_for_decoder(selected, decoder_kind)
        committed = SERIAL.append_strict_core_commits(
            committed, projected, window=window, duration_sec=duration_sec,
            seam_tolerance_sec=seam_tolerance_sec,
        )
    if len(committed) != len(document.characters):
        raise RuntimeError(
            "shared planner replay ended with incomplete lyrics: "
            f"decoder={decoder_kind} committed={len(committed)} total={len(document.characters)}"
        )
    return SERIAL.decorate_final_rows(committed, document)

def branch_args(args: argparse.Namespace, decoder_kind: str) -> SimpleNamespace:
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
        decoder_kind=decoder_kind,
        serial_control_decoder_kind="same",
        skip_silent_windows=True,
        silent_active_ratio_max=args.silent_active_ratio_max,
        silent_peak_margin_db=args.silent_peak_margin_db,
        silent_min_sustained_sec=args.silent_min_sustained_sec,
        startup_vocal_preroll_sec=args.startup_vocal_preroll_sec,
        startup_minimum_forward_characters=args.startup_minimum_forward_characters,
        silence_aware_window_plan=args.silence_aware_window_plan,
        silence_boundary_min_sec=args.silence_boundary_min_sec,
        strong_silence_anchor_sec=args.strong_silence_anchor_sec,
        silence_boundary_search_sec=args.silence_boundary_search_sec,
        leading_silence_min_sec=args.leading_silence_min_sec,
        tail_min_core_sec=args.tail_min_core_sec,
        minimum_core_sec=args.minimum_core_sec,
        gpu_decoder_runtime=None,
        item_id=args.item_id,
        audio_variant=args.audio_variant,
        max_target_units=args.max_target_units,
        disagreement_peak_threshold_sec=args.disagreement_peak_threshold_sec,
        anchor_margin_quantile=args.anchor_margin_quantile,
        anchor_overlap_tolerance_sec=args.anchor_overlap_tolerance_sec,
        anchor_stability_tolerance_sec=args.anchor_stability_tolerance_sec,
        anchor_guard_units=args.anchor_guard_units,
        max_anchor_search_units=args.max_anchor_search_units,
        max_anchor_span_units=args.max_anchor_span_units,
        max_anchor_span_sec=args.max_anchor_span_sec,
        context_agreement_tolerance_sec=args.context_agreement_tolerance_sec,
        anchor_reproduction_tolerance_sec=args.anchor_reproduction_tolerance_sec,
        max_repair_boundary_change_sec=args.max_repair_boundary_change_sec,
        local_projection=args.local_projection,
        local_minimum_duration_sec=args.local_minimum_duration_sec,
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lyrics", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True, help="separated vocal used for all four branches")
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--item-id", default="demo")
    p.add_argument("--audio-variant", default="vocal")
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
    p.add_argument("--silent-active-ratio-max", type=float, default=0.01)
    p.add_argument("--silent-peak-margin-db", type=float, default=3.0)
    p.add_argument("--silent-min-sustained-sec", type=float, default=0.40)
    p.add_argument("--startup-vocal-preroll-sec", type=float, default=2.0)
    p.add_argument("--startup-minimum-forward-characters", type=int, default=24)
    p.add_argument("--silence-aware-window-plan", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--silence-boundary-min-sec", type=float, default=0.8)
    p.add_argument("--strong-silence-anchor-sec", type=float, default=1.5)
    p.add_argument("--silence-boundary-search-sec", type=float, default=6.0)
    p.add_argument("--leading-silence-min-sec", type=float, default=2.0)
    p.add_argument("--tail-min-core-sec", type=float, default=18.0)
    p.add_argument("--minimum-core-sec", type=float, default=12.0)
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
    p.add_argument("--local-projection", choices=("isotonic", "forward"), default="isotonic")
    p.add_argument(
        "--local-minimum-duration-sec", type=float, default=0.0,
        help="kept at zero until a separate gap-repair policy is justified",
    )
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
        "schema_version": "qwen_fa_decoder_realign_comparison_request_v1",
        "lyrics": {"path": str(args.lyrics), "sha256": SERIAL.sha256(args.lyrics)},
        "audio": {"path": str(args.audio), "sha256": SERIAL.sha256(args.audio), "role": "vocal_inference"},
        "model": str(args.model),
        "revision": args.revision,
        "checkpoint": checkpoint,
        "language": args.language,
        "window": {
            "core_sec": args.core_sec,
            "left_context_sec": args.left_context_sec,
            "right_context_sec": args.right_context_sec,
            "skip_silent_windows": True,
            "silent_active_ratio_max": args.silent_active_ratio_max,
            "silent_peak_margin_db": args.silent_peak_margin_db,
            "silent_min_sustained_sec": args.silent_min_sustained_sec,
            "startup_vocal_preroll_sec": args.startup_vocal_preroll_sec,
            "startup_minimum_forward_characters": args.startup_minimum_forward_characters,
            "silence_aware_window_plan": args.silence_aware_window_plan,
            "silence_boundary_min_sec": args.silence_boundary_min_sec,
            "strong_silence_anchor_sec": args.strong_silence_anchor_sec,
            "silence_boundary_search_sec": args.silence_boundary_search_sec,
            "leading_silence_min_sec": args.leading_silence_min_sec,
            "tail_min_core_sec": args.tail_min_core_sec,
            "minimum_core_sec": args.minimum_core_sec,
        },
        "design": {
            "baseline": "R2 + official timestamp decoder + 30s core",
            "alternative_decoder": "raw timestamp argmax",
            "serial_planner_decoder": "raw argmax shared by all four branches",
            "window_planner": "whole-song silence-aware 30s target with short-tail redistribution",
            "serial_control_decoder": "shared accepted windows, ownership, and lyric cursor",
            "branches": BRANCHES,
            "realign_local_stage": "branch decoder output",
            "replacement_constraint": args.local_projection,
            "whole_song_second_compression": False,
            "gap_repair_enabled": False,
        },
    }
    request_hash = SERIAL.canonical_hash(request)
    complete_path = args.out_root / "complete.json"
    if not args.force and complete_path.is_file():
        try:
            previous = json.loads(complete_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if previous.get("status") == "complete" and previous.get("request_hash") == request_hash:
            print(json.dumps({"status": "skipped_identity_match", "out_root": str(args.out_root)}))
            return 0

    document = parse_lyrics_text(args.lyrics.read_text(encoding="utf-8-sig"), language=args.language)
    audio = decode_audio(args.audio)
    load_args = SimpleNamespace(
        model=str(args.model), revision=args.revision, local_files_only=args.local_files_only,
        cache_dir=args.cache_dir, device=args.device,
    )
    processor, model = SERIAL.load_model(load_args, "lora", args.r2_checkpoint)
    results: dict[str, Any] = {}
    baseline_memory: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    try:
        # Plan the serial path once with raw argmax.  In an empty introductory
        # core, raw can legitimately commit zero units; the previous official
        # planner instead expanded the transcript until a pathological decoded
        # span falsely crossed the boundary and advanced the lyric cursor.
        planner_args = branch_args(args, "raw")
        _planner_rows, planner_trace = SERIAL.windowed_alignment(
            processor, model, audio, document, planner_args
        )
        duration_sec = len(audio) / 16000.0
        window_plan = getattr(planner_args, "generated_window_plan", None)
        if window_plan is None:
            raise RuntimeError("silence-aware planner did not expose generated_window_plan")
        window_plan_hash = SERIAL.canonical_hash(window_plan)
        atomic_json(args.out_root / "window_plan.json", {**window_plan, "window_plan_hash": window_plan_hash})
        shared_trajectory = trajectory_projection(planner_trace)
        shared_trajectory_hash = SERIAL.canonical_hash(shared_trajectory)

        for decoder_kind in ("official", "raw"):
            decoder_trace = project_trace_for_decoder(planner_trace, decoder_kind)
            rows = replay_decoder_on_shared_trace(
                decoder_trace, decoder_kind=decoder_kind, document=document,
                duration_sec=duration_sec, seam_tolerance_sec=args.seam_tolerance_sec,
            )
            baseline_memory[decoder_kind] = (rows, decoder_trace)

        trajectory_match = True
        trajectory_hashes = {
            "official": shared_trajectory_hash,
            "raw": shared_trajectory_hash,
            "shared_raw_planner": shared_trajectory_hash,
        }

        for branch_name, spec in BRANCHES.items():
            decoder_kind = str(spec["decoder_kind"])
            baseline_rows, trace = baseline_memory[decoder_kind]
            bargs = branch_args(args, decoder_kind)
            bargs.serial_control_decoder_kind = "raw"
            bargs.silence_intervals = window_plan.get("silence_intervals", [])
            if bool(spec["realign"]):
                final_rows, diagnostics = GUARDED.run_guarded_realign(
                    args=bargs, processor=processor, model=model, audio=audio, document=document,
                    baseline_rows=baseline_rows, trace=trace,
                )
            else:
                final_rows = stage_rows(baseline_rows, "final")
                diagnostics = {
                    "disabled": True,
                    "candidate_count": 0,
                    "selected_repair_count": 0,
                    "final_structural": structural_summary(final_rows),
                }

            branch_request_hash = SERIAL.canonical_hash({
                "pipeline_request_hash": request_hash,
                "branch": branch_name,
            })
            payload = {
                "schema_version": "qwen_fa_decoder_realign_branch_v1",
                "created_at": utc_now(),
                "identity": {
                    "request_hash": branch_request_hash,
                    "pipeline_request_hash": request_hash,
                    "branch": branch_name,
                    "branch_short": spec["short"],
                    "decoder_kind": decoder_kind,
                    "serial_control_decoder_kind": "raw_shared_planner",
                    "planner_decoder_kind": "raw",
                    "realign_enabled": bool(spec["realign"]),
                    "trajectory_hash": shared_trajectory_hash,
                    "window_plan_hash": window_plan_hash,
                    "request": request,
                },
                "summary": {
                    "audio_duration_sec": duration_sec,
                    "character_count": len(final_rows),
                    "window_count": len(trace),
                    "silent_window_skip_count": sum(bool(row.get("silent_core_skipped")) for row in trace),
                    "planned_window_count": len(window_plan.get("windows", [])),
                    "leading_silence_skipped_sec": (
                        None if window_plan.get("leading_silence_skipped") is None
                        else window_plan["leading_silence_skipped"].get("duration_sec")
                    ),
                    "tail_adjustment": window_plan.get("tail_adjustment"),
                    "candidate_count": diagnostics.get("candidate_count", 0),
                    "selected_repair_count": diagnostics.get("selected_repair_count", 0),
                    "structural": structural_summary(final_rows),
                },
                "lines": [line.__dict__ for line in document.lines],
                "characters": final_rows,
                "window_trace": compact_trace(trace) if not bool(spec["realign"]) else [],
                "window_trace_reference_branch": (
                    None if not bool(spec["realign"])
                    else f"{decoder_kind}_no_realign"
                ),
                "realign": diagnostics,
            }
            branch_path = args.out_root / "branches" / branch_name / "alignment.json"
            artifact = write_alignment_bundle(branch_path, payload)
            atomic_json(args.out_root / "branches" / branch_name / "realign.json", diagnostics)
            results[branch_name] = {
                "branch": branch_name,
                "short": spec["short"],
                "decoder_kind": decoder_kind,
                "planner_decoder_kind": "raw",
                "realign": bool(spec["realign"]),
                "alignment": str(branch_path),
                "quality": artifact["quality"],
                "summary": payload["summary"],
            }

        manifest = {
            "schema_version": "qwen_fa_decoder_realign_comparison_manifest_v1",
            "created_at": utc_now(),
            "request_hash": request_hash,
            "request": request,
            "trajectory_match": trajectory_match,
            "trajectory_hashes": trajectory_hashes,
            "window_plan": str(args.out_root / "window_plan.json"),
            "window_plan_hash": window_plan_hash,
            "branches": results,
        }
        atomic_json(args.out_root / "comparison_manifest.json", manifest)
        atomic_json(complete_path, {"status": "complete", **manifest})
        print(json.dumps({
            "status": "complete", "out_root": str(args.out_root),
            "trajectory_match": trajectory_match,
            "trajectory_hashes": trajectory_hashes,
            "branches": {name: row["summary"] for name, row in results.items()},
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
