#!/usr/bin/env python3
"""Run the consolidated decoder/detector/window/realign research suite.

The suite consumes the full manifest and a completed B4 baseline cache.  Pilot
runs may select a small deterministic subset for parameter exploration.  Formal
runs never cap MIR-1K, M4Singer, or prepared test-demo items: every manifest item
contributes to every enabled experiment family, while per-item case caps control
only the number of repeated local perturbations.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
import gc
import hashlib
import json
import math
import statistics
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Sequence
import sys
import time
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "demo"))

import align_qwen_fa_serial_demo as SERIAL
from lyricalign.demo.karaoke import LyricDocument, parse_lyrics_text, normalize_alignment_language
from lyricalign.demo.window_planning import detect_silence_intervals
from lyricalign.demo.realign_diagnostics import structural_summary
from lyricalign.demo.run_state import atomic_json, canonical_hash
from lyricalign.training.qwen_fa_runtime import decode_audio
from lyricalign.research_v6.audio_support import build_audio_profile, support_for_rows, materialize_item_audio, cleanup_item_audio
from lyricalign.research_v6.decoders import DecoderConfig, decode_rows
from lyricalign.research_v6.detector import (
    DetectorConfig,
    LogisticRiskModel,
    StumpBoostRiskModel,
    add_gt_labels,
    binary_metrics,
    event_metrics,
    event_threshold_curve,
    inspect_alignment,
    threshold_curve,
)
from lyricalign.research_v6.metrics import (
    alignment_metrics, aggregate_item_metrics, clustered_bootstrap_macro, grouped_aggregate,
    metric_delta, select_gt_rows, strip_metric_details,
)
from lyricalign.research_v6.experiment_analysis import (
    add_repairability_and_safe_labels, candidate_record as scoped_candidate_record,
    causal_effect, choose_budget_candidates,
    detector_context_from_trace, detector_selection_components, detector_selection_key,
    detector_selection_score, fixed_scope_for_request,
    independent_line_localization, line_localization_metrics, paired_decoder_transition_metrics,
    serial_diagnostics, silence_boundary_diagnostics,
)
from lyricalign.research_v6.requests import AlignmentRequest, CorruptionSpec, apply_corruption, default_corruption_specs
from lyricalign.research_v6.windowing import (
    SilenceInterval,
    apply_time_mapping_to_audio,
    build_dynamic_window_plan,
    build_hard_core_soft_context_plan,
    cap_silence_mapping,
    map_time,
    map_window_plan,
    split_text_chunks,
    text_budget_candidates,
)

PHASES = ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9")
DECODER_NAMES = (
    "raw", "official", "joint_start_end", "topk_sequence", "weighted_isotonic",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_rows(rows: Iterable[dict[str, Any]], stage: str = "selected") -> list[dict[str, Any]]:
    result = []
    for source in sorted(rows, key=lambda row: int(row["global_character_index"])):
        row = dict(source)
        if stage == "selected":
            start = row.get("start_sec", row.get("fixed_global_start_sec"))
            end = row.get("end_sec", row.get("fixed_global_end_sec"))
        elif stage == "raw":
            start, end = row["raw_global_start_sec"], row["raw_global_end_sec"]
        elif stage == "official":
            start, end = row["official_fixed_global_start_sec"], row["official_fixed_global_end_sec"]
        else:
            raise ValueError(stage)
        row["start_sec"] = float(start)
        row["end_sec"] = float(end)
        result.append(row)
    return result


def load_gt(path: str | None) -> list[dict[str, Any]]:
    return [] if not path else read_jsonl(Path(path))


def baseline_path(root: Path, item_id: str, variant: str) -> Path:
    return root / "items" / item_id / "branches" / variant / "alignment.json"


def pilot_selection_eligible(row: dict[str, Any]) -> bool:
    explicit = row.get("pilot_selection_eligible")
    split = str(row.get("split", "")).strip().lower()
    role = str(row.get("selection_role", "")).strip().lower()
    return not (
        explicit is False
        or split in {"test", "heldout"}
        or role in {"heldout", "m4_test"}
    )


def select_items(items: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.item_id:
        selected = [row for row in items if str(row["item_id"]) == args.item_id]
        if not selected:
            raise ValueError(f"item not found in manifest: {args.item_id}")
        if args.mode == "pilot" and not pilot_selection_eligible(selected[0]):
            raise ValueError(
                f"item is not eligible for pilot/freeze selection: {args.item_id} "
                f"split={selected[0].get('split')} role={selected[0].get('selection_role')}"
            )
        return selected
    if args.mode == "formal":
        return items
    # Pilot keeps dataset coverage and duration diversity but never defines the
    # formal population.  Formal always returns every manifest item above.
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for row in items:
        # Pilot/freeze may use train/calibration/development evidence only.
        # Synthetic-long rows retain their source split, so test-derived
        # synthetic items are excluded by the same rule.
        if not pilot_selection_eligible(row):
            continue
        by_dataset.setdefault(str(row.get("dataset")), []).append(row)
    selected: list[dict[str, Any]] = []
    for dataset, rows in sorted(by_dataset.items()):
        rows = sorted(rows, key=lambda row: (float(row.get("duration_sec", 0.0)), str(row["item_id"])))
        cap = max(1, args.pilot_items_per_dataset)
        take = min(cap, len(rows))
        positions = sorted({
            int(round(i * (len(rows) - 1) / max(1, take - 1)))
            for i in range(take)
        })
        selected.extend(rows[position] for position in positions)
    return selected


def serial_args(
    args: argparse.Namespace,
    *,
    plan: dict[str, Any] | None = None,
    backtrack: int = 0,
    injections: list[dict[str, Any]] | None = None,
    initial_state: dict[str, Any] | None = None,
    max_windows: int = 0,
    allow_partial: bool = False,
    minimum_forward_characters: int | None = None,
) -> SimpleNamespace:
    state = dict(initial_state or {})
    return SimpleNamespace(
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
        decoder_top_k=args.decoder_top_k,
        core_sec=args.core_sec,
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
        future_line_padding=1,
        minimum_forward_characters=(
            args.minimum_forward_characters
            if minimum_forward_characters is None else int(minimum_forward_characters)
        ),
        future_character_ratio=args.future_character_ratio,
        max_candidate_expansions=args.max_candidate_expansions,
        boundary_start_tolerance_sec=0.32,
        seam_tolerance_sec=0.16,
        capture_shadow_rows=True,
        capture_attempt_probes=True,
        attempt_probe_max_rows=96,
        stable_segment_min_units=2,
        stable_segment_confidence_quantile=0.50,
        stable_raw_official_tolerance_sec=0.16,
        stable_context_tolerance_sec=0.24,
        stable_prefix_reproduction_tolerance_sec=0.24,
        stable_prefix_minimum_observed_units=2,
        stable_prefix_minimum_observed_ratio=0.50,
        decoder_kind=str(getattr(args, "selected_decoder_name", "official")),
        decoder_beam_size=int(getattr(args, "decoder_beam_size", 96)),
        serial_control_decoder_kind=str(getattr(args, "selected_decoder_name", "official")),
        skip_silent_windows=True,
        silent_active_ratio_max=0.01,
        silent_peak_margin_db=3.0,
        silent_min_sustained_sec=0.40,
        startup_vocal_preroll_sec=2.0,
        startup_minimum_forward_characters=24,
        silence_aware_window_plan=plan is None,
        strict_silence_boundary_plan=False,
        compress_silence_audio=False,
        silence_boundary_min_sec=0.8,
        strong_silence_anchor_sec=1.5,
        silence_boundary_search_sec=6.0,
        leading_silence_min_sec=2.0,
        tail_min_core_sec=18.0,
        minimum_core_sec=12.0,
        gpu_decoder_runtime=None,
        research_infer_cache_root=getattr(args, "_research_serial_cache_root", None),
        research_infer_cache_stats=getattr(args, "_research_serial_cache_stats", None),
        research_model_identity={
            "model": getattr(args, "model", None),
            "revision": getattr(args, "revision", None),
            "checkpoint": str(getattr(args, "r2_checkpoint", "")),
        },
        _precomputed_window_plan=plan,
        next_input_backtrack_units=backtrack,
        research_state_injections=injections or [],
        research_initial_committed_rows=state.get("committed_rows", []),
        research_initial_committed_cursor=state.get("committed_cursor", 0),
        research_initial_input_cursor=state.get("input_cursor", state.get("committed_cursor", 0)),
        research_initial_previous_committed_count=state.get("previous_committed_count", 0),
        research_initial_previous_core_duration=state.get("previous_core_duration", 0.0),
        research_initial_stable_suffix=state.get("previous_stable_suffix"),
        research_max_windows=int(max_windows),
        research_allow_partial_return=bool(allow_partial),
    )


def local_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
        decoder_kind=str(getattr(args, "selected_decoder_name", "official")),
        decoder_top_k=args.decoder_top_k,
        decoder_beam_size=int(getattr(args, "decoder_beam_size", 96)),
        gpu_decoder_runtime=None,
    )


def request_from_trace(item_id: str, trace: dict[str, Any], total_units: int, duration_sec: float) -> AlignmentRequest:
    text_start = int(trace.get("candidate_character_start", trace.get("input_character_start_before", 0)))
    text_end = int(trace.get("candidate_character_end", total_units))
    text_start = max(0, min(total_units - 1, text_start))
    text_end = max(text_start + 1, min(total_units, text_end))
    audio_start = float(trace.get("effective_input_start_sec", trace.get("input_start_sec", 0.0)))
    audio_end = float(trace.get("input_end_sec", duration_sec))
    request = AlignmentRequest(
        item_id=item_id,
        audio_start_sec=max(0.0, audio_start),
        audio_end_sec=min(duration_sec, audio_end),
        ownership_start_sec=float(trace.get("core_start_sec", audio_start)),
        ownership_end_sec=float(trace.get("core_end_sec", audio_end)),
        text_start=text_start,
        text_end=text_end,
        request_role="baseline_window",
        metadata={"window_index": int(trace.get("window_index", -1))},
    )
    request.validate(total_units=total_units, duration_sec=duration_sec)
    return request


def representative_requests(
    item_id: str,
    trace: Sequence[dict[str, Any]],
    *,
    total_units: int,
    duration_sec: float,
    cases_per_item: int,
) -> list[AlignmentRequest]:
    usable = [row for row in trace if not row.get("silent_core_skipped") and row.get("candidate_character_end")]
    if not usable:
        return [AlignmentRequest(item_id, 0.0, duration_sec, 0, total_units, request_role="whole_item")]
    if cases_per_item <= 0 or len(usable) <= cases_per_item:
        chosen = usable
    else:
        # Include the most suspicious window first, then evenly cover the song.
        suspicious = max(
            usable,
            key=lambda row: (
                int(bool((row.get("precommit_diagnostic") or {}).get("triggered"))),
                int(row.get("overlap_compression_collapsed_to_zero_count", 0)),
                int(row.get("committed_character_count", 0)),
            ),
        )
        chosen = [suspicious]
        remaining = [row for row in usable if row is not suspicious]
        while len(chosen) < cases_per_item and remaining:
            position = int(round((len(chosen) - 1) * (len(remaining) - 1) / max(1, cases_per_item - 2)))
            chosen.append(remaining.pop(min(position, len(remaining) - 1)))
    return [request_from_trace(item_id, row, total_units, duration_sec) for row in chosen]


def modified_document(document: LyricDocument, request: AlignmentRequest, spec: CorruptionSpec) -> LyricDocument:
    if spec.replace_units <= 0:
        return document
    characters = list(document.characters)
    count = min(spec.replace_units, request.text_end - request.text_start)
    # Deterministic wrong text from a different part of the same song.  This is
    # preferable to an arbitrary symbol because it simulates plausible wrong
    # cursor/repeated-lyric input while preserving the official tokenizer units.
    source_start = (request.text_end + 7) % max(1, len(characters))
    for offset in range(count):
        target = request.text_start + offset
        source = characters[(source_start + offset) % len(characters)]
        characters[target] = replace(
            characters[target],
            text=source.text,
            display_text=source.display_text or source.text,
            unit_type=source.unit_type,
        )
    return LyricDocument(document.lines, tuple(characters), language=document.language, unit_mode=document.unit_mode)


def run_request(
    *,
    request: AlignmentRequest,
    spec: CorruptionSpec | None,
    audio: np.ndarray,
    document: LyricDocument,
    processor: Any,
    model: Any,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    """Run or reuse one deterministic local inference request.

    The cache is keyed by the *actual* model input, rather than experiment
    labels.  This deliberately merges boundary-clamped corruptions and lets a
    smooth timestamp shift reuse its unshifted forward pass.  The cache stores
    pre-shift rows; the shift is a deterministic post-processing operation.
    """
    start_sample = max(0, int(round(request.audio_start_sec * 16000)))
    end_sample = min(len(audio), int(round(request.audio_end_sec * 16000)))
    if end_sample <= start_sample:
        raise ValueError("empty audio request")
    active_document = modified_document(document, request, spec or CorruptionSpec("none"))
    selected_units = [
        item.text for item in active_document.characters[request.text_start:request.text_end]
    ]
    cache_payload = {
        "schema_version": "research_v6_actual_model_input_cache_v2",
        "audio_identity": getattr(args, "_research_audio_identity", None),
        "audio_samples": [start_sample, end_sample],
        # This offset changes the returned global timestamps, so it remains
        # part of the identity even if rounded samples happen to coincide.
        "global_audio_offset_sec": float(request.audio_start_sec),
        "character_range": [int(request.text_start), int(request.text_end)],
        "alignment_units": selected_units,
        "timestamp_segment_sec": args.timestamp_segment_sec,
        "decoder_top_k": args.decoder_top_k,
        "model": getattr(args, "model", None),
        "revision": getattr(args, "revision", None),
        "checkpoint": str(getattr(args, "r2_checkpoint", "")),
    }
    cache_key = canonical_hash(cache_payload)
    cache_root = getattr(args, "_research_cache_root", None)
    cache_path = None if cache_root is None else Path(cache_root) / f"{cache_key}.json"
    stats = getattr(args, "_research_cache_stats", None)
    if cache_path is not None and cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if stats is not None:
            stats["hits"] = int(stats.get("hits", 0)) + 1
        source_wall_sec = float(payload.get("wall_sec", 0.0))
        args._last_request_meta = {
            "cache_hit": True,
            "cache_key": cache_key,
            "actual_forward_wall_sec": 0.0,
            "estimated_uncached_wall_sec": source_wall_sec,
            # Compatibility alias: this is the estimated uncached cost, not
            # newly consumed wall time on a cache hit.
            "wall_sec": source_wall_sec,
        }
        base_rows = [dict(row) for row in payload["rows"]]
        return apply_smooth_time_shift(base_rows, spec)
    started = time.perf_counter()
    rows, _ = SERIAL.infer_slice(
        processor=processor,
        model=model,
        audio=audio[start_sample:end_sample],
        document=active_document,
        character_start=request.text_start,
        character_end=request.text_end,
        global_audio_offset_sec=request.audio_start_sec,
        args=local_args(args),
    )
    wall_sec = time.perf_counter() - started
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(cache_path, {"schema_version": "research_v6_inference_cache_v1", "identity": cache_payload, "wall_sec": wall_sec, "rows": rows})
    if stats is not None:
        stats["misses"] = int(stats.get("misses", 0)) + 1
        stats["forward_wall_sec"] = float(stats.get("forward_wall_sec", 0.0)) + wall_sec
    args._last_request_meta = {
        "cache_hit": False,
        "cache_key": cache_key,
        "actual_forward_wall_sec": wall_sec,
        "estimated_uncached_wall_sec": wall_sec,
        "wall_sec": wall_sec,
    }
    return apply_smooth_time_shift(rows, spec)


def apply_smooth_time_shift(
    rows: list[dict[str, Any]], spec: CorruptionSpec | None,
) -> list[dict[str, Any]]:
    """Return detached rows after the deterministic E2 timestamp perturbation."""
    result = [dict(row) for row in rows]
    if spec is None or abs(spec.smooth_time_shift_sec) <= 1e-12:
        return result
    for row in result:
        for key in (
            "raw_global_start_sec", "raw_global_end_sec",
            "official_fixed_global_start_sec", "official_fixed_global_end_sec",
            "fixed_global_start_sec", "fixed_global_end_sec",
        ):
            row[key] = float(row[key]) + float(spec.smooth_time_shift_sec)
    return result


def evaluate(
    rows: list[dict[str, Any]], gt: list[dict[str, Any]], *, metric_indices: Iterable[int] | None = None,
) -> dict[str, Any] | None:
    if not gt:
        return None
    selected_gt = gt if metric_indices is None else select_gt_rows(gt, indices=metric_indices)
    return alignment_metrics(canonical_rows(rows), selected_gt)


def candidate_record(
    name: str, rows: list[dict[str, Any]], gt: list[dict[str, Any]], *,
    metric_indices: Iterable[int] | None = None, metric_scope: str = "full_item",
    spliced_rows: list[dict[str, Any]] | None = None, baseline_rows: list[dict[str, Any]] | None = None,
    seams_sec: Sequence[float] = (), extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = canonical_rows(rows)
    return scoped_candidate_record(
        name, canonical, gt, structural=structural_summary(canonical),
        metric_indices=metric_indices, metric_scope=metric_scope,
        spliced_rows=None if spliced_rows is None else canonical_rows(spliced_rows),
        baseline_rows=None if baseline_rows is None else canonical_rows(baseline_rows),
        seams_sec=seams_sec, extra=extra,
    )


def write_alignment(
    path: Path, *, baseline: dict[str, Any], name: str, rows: list[dict[str, Any]],
    gt: list[dict[str, Any]], metadata: dict[str, Any],
    window_trace: Sequence[dict[str, Any]] | None = None, compact_artifacts: bool = False,
) -> None:
    canonical = canonical_rows(rows)
    payload = {
        "schema_version": "alignment_research_candidate_v1",
        "identity": {"name": name, "metadata": metadata},
        "summary": candidate_record(name, canonical, gt),
    }
    if compact_artifacts:
        # Formal runs create many decoder/case candidates.  Their full row and
        # trace payloads are reproducible from the frozen command, baseline,
        # and manifest, while retaining them would scale to multiple TB.
        payload["compact_artifact"] = True
        payload["character_count"] = len(canonical)
        payload["characters_sha256"] = canonical_hash(canonical)
    else:
        payload["lines"] = baseline.get("lines", [])
        payload["characters"] = canonical
        payload["window_trace"] = list(window_trace) if window_trace is not None else baseline.get("window_trace", [])
    atomic_json(path, payload)


def compact_continuation_trace(trace: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep auditable continuation decisions, not repeated model row payloads."""
    bulky = {"processor_units", "shadow_rows", "probe_rows", "rows", "window_trace"}
    def reduce(value: Any, key: str | None = None) -> Any:
        if key in bulky and isinstance(value, (list, tuple)):
            return {"count": len(value), "sha256": canonical_hash(value)}
        if isinstance(value, dict):
            return {name: reduce(child, name) for name, child in value.items()}
        if isinstance(value, list):
            return [reduce(child) for child in value]
        return value
    return [reduce(step) for step in trace]


def compact_e8_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove reproducible inference rows from E8 while preserving all metrics."""
    result = {key: value for key, value in payload.items() if key != "cases"}
    cases = []
    for case in payload.get("cases", []):
        reduced = {key: value for key, value in case.items() if key != "candidates"}
        candidates = {}
        for name, candidate in (case.get("candidates") or {}).items():
            compact = {key: value for key, value in candidate.items() if key != "continuation_trace"}
            trace = candidate.get("continuation_trace")
            if trace is not None:
                compact["continuation_trace"] = compact_continuation_trace(trace)
            candidates[name] = compact
        reduced["candidates"] = candidates
        cases.append(reduced)
    result["cases"] = cases
    result["compact_artifact"] = True
    return result


def safe_boundary_candidates(detector_report: dict[str, Any], baseline_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_index = {int(row["global_character_index"]): row for row in baseline_rows}
    result = []
    for feature in detector_report["features"]:
        index = int(feature["global_character_index"])
        source = by_index[index]
        result.append({
            "global_character_index": index,
            "time_sec": float(source.get("fixed_global_end_sec", source.get("end_sec"))),
            # Planning must consume the same risk-gated predicate used by the
            # Detector's safe-boundary decision and evaluation curve.
            "safe_boundary_score": float(feature["safe_boundary_decision_score"]),
            "raw_safe_boundary_score": float(feature["safe_boundary_score"]),
            "risk_score": float(feature["risk_score"]),
            "active_risk_score_key": feature.get("active_risk_score_key", detector_report.get("active_score_key")),
        })
    return result


def synchronize_dynamic_plan(plan: dict[str, Any], baseline_rows: list[dict[str, Any]], offset_units: int) -> dict[str, Any]:
    by_index = {int(row["global_character_index"]): row for row in baseline_rows}
    diagnostics = plan.get("boundary_diagnostics", [])
    windows = [dict(row) for row in plan["windows"]]
    for window_index in range(1, len(windows)):
        diagnostic = diagnostics[window_index - 1] if window_index - 1 < len(diagnostics) else {}
        safe = diagnostic.get("safe_boundary")
        if not safe:
            continue
        index = max(0, int(safe["global_character_index"]) - offset_units)
        row = by_index.get(index)
        if row is None:
            continue
        windows[window_index]["input_start_sec"] = max(
            0.0,
            float(row.get("fixed_global_start_sec", row["official_fixed_global_start_sec"])),
        )
        windows[window_index]["planned_input_character_start"] = index
        windows[window_index]["planned_input_source"] = "detector_safe_boundary_synchronized_audio_and_text"
        windows[window_index]["safe_input_character_index"] = index
        windows[window_index]["safe_input_offset_units"] = offset_units
    result = dict(plan)
    result["windows"] = windows
    result["safe_input_offset_units"] = offset_units
    return result


def remap_rows(rows: list[dict[str, Any]], mapping: Sequence[Any]) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        row = dict(source)
        for key in ("start_sec", "end_sec", "selected_start_sec", "selected_end_sec"):
            if row.get(key) is not None:
                row[key] = map_time(float(row[key]), mapping, direction="transformed_to_original")
        for prefix in ("raw", "official_fixed", "fixed", "control_fixed"):
            for side in ("start", "end"):
                key = f"{prefix}_global_{side}_sec"
                if row.get(key) is not None:
                    row[key] = map_time(float(row[key]), mapping, direction="transformed_to_original")
        result.append(row)
    return result


def remap_trace(trace: list[dict[str, Any]], mapping: Sequence[Any]) -> list[dict[str, Any]]:
    """Recursively restore transformed-clock trace fields to the original clock.

    Serial diagnostics consume window/core/input times as global song times.  A
    silence-capped run therefore must remap its trace together with its character
    rows; otherwise cursor and recovery metrics compare different clocks.
    """
    time_keys = {
        "start_sec", "end_sec", "core_start_sec", "core_end_sec",
        "input_start_sec", "input_end_sec", "effective_input_start_sec",
        "effective_input_end_sec", "nominal_input_start_sec",
        "next_input_boundary_sec", "lookahead_start_sec", "lookahead_end_sec",
        "startup_vocal_onset_sec", "first_sustained_activity_sec",
        "last_sustained_activity_sec",
    }

    def convert(value: Any) -> Any:
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        result: dict[str, Any] = {}
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                result[key] = convert(child)
            elif key in time_keys and isinstance(child, (int, float)) and math.isfinite(float(child)):
                result[key] = map_time(float(child), mapping, direction="transformed_to_original")
            else:
                result[key] = child
        return result

    return [convert(row) for row in trace]


def splice_local_candidate(
    baseline_rows: list[dict[str, Any]], local_rows: list[dict[str, Any]], start: int, end: int,
) -> list[dict[str, Any]]:
    """Replace [start,end] by index without propagating changes outside the case."""
    local_by = {int(row["global_character_index"]): row for row in canonical_rows(local_rows)}
    result = []
    for source in canonical_rows(baseline_rows):
        index = int(source["global_character_index"])
        if start <= index <= end and index in local_by:
            replacement = dict(source)
            replacement["start_sec"] = float(local_by[index]["start_sec"])
            replacement["end_sec"] = float(local_by[index]["end_sec"])
            replacement["realign_source"] = local_by[index].get("research_decoder", "local")
            result.append(replacement)
        else:
            result.append(dict(source))
    return result


def frozen_plan_from_trace(
    trace: Sequence[dict[str, Any]], *, policy: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build an immutable serial plan and keep its source trace rows aligned."""
    windows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for position, row in enumerate(trace):
        if row.get("silent_core_skipped"):
            continue
        windows.append({
            "window_index": int(row.get("window_index", position)),
            "core_start_sec": float(row["core_start_sec"]),
            "core_end_sec": float(row["core_end_sec"]),
            "core_duration_sec": float(row["core_end_sec"] - row["core_start_sec"]),
            "input_start_sec": float(row.get("input_start_sec", row.get("effective_input_start_sec", 0.0))),
            "input_end_sec": float(row["input_end_sec"]),
            "is_final_core": bool(row.get("is_final_core", position == len(trace) - 1)),
            "is_final_region_core": bool(row.get("is_final_region_core", False)),
            "window_plan_policy": policy,
        })
        sources.append(dict(row))
    return {"schema_version": "frozen_baseline_trace_plan_v2", "windows": windows}, sources


def trace_position_for_character(
    source_trace: Sequence[dict[str, Any]], character_index: int,
) -> int | None:
    for position, row in enumerate(source_trace):
        start = row.get("committed_character_start")
        end = row.get("committed_character_end")
        if start is None or end is None:
            continue
        if int(start) <= int(character_index) < int(end):
            return position
    return None


def complete_group_ranges(total_units: int, group_units: int) -> list[tuple[int, int]]:
    if group_units <= 0:
        raise ValueError("group_units must be positive")
    return [
        (start, start + group_units)
        for start in range(0, int(total_units), group_units)
        if start + group_units <= int(total_units)
    ]


def propagate_realign_candidate(
    *,
    seed_rows: list[dict[str, Any]],
    target_end_index: int,
    trace: Sequence[dict[str, Any]],
    processor: Any,
    model: Any,
    audio: Any,
    document: LyricDocument,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Continue true serial inference from a locally replaced prefix.

    The candidate replaces the target span, becomes immutable prefix state, and
    every remaining unit is inferred again under the frozen baseline window
    plan.  This makes E8 downstream metrics measure causal serial propagation
    instead of static splice invariance.
    """
    plan, source_trace = frozen_plan_from_trace(
        trace, policy="E8_realign_continuation_frozen_baseline_plan_v1",
    )
    position = trace_position_for_character(source_trace, target_end_index)
    if position is None:
        raise RuntimeError(
            f"target character {target_end_index} is not owned by a non-silent baseline window"
        )
    committed_cursor = int(target_end_index) + 1
    prefix = [
        dict(row) for row in canonical_rows(seed_rows)
        if int(row["global_character_index"]) < committed_cursor
    ]
    if len(prefix) != committed_cursor:
        raise RuntimeError(
            "E8 continuation prefix is incomplete: "
            f"expected={committed_cursor} actual={len(prefix)}"
        )
    current = source_trace[position]
    input_cursor = min(
        committed_cursor,
        int(current.get("input_character_start_before", committed_cursor)),
    )
    previous = source_trace[position - 1] if position > 0 else None
    initial_state = {
        "committed_rows": prefix,
        "committed_cursor": committed_cursor,
        "input_cursor": input_cursor,
        "previous_committed_count": int(previous.get("committed_character_count", 0)) if previous else 0,
        "previous_core_duration": (
            float(previous.get("core_end_sec", 0.0)) - float(previous.get("core_start_sec", 0.0))
            if previous else 0.0
        ),
        "previous_stable_suffix": previous.get("stable_suffix_candidate") if previous else None,
    }
    tail_plan = {
        **plan,
        "schema_version": "E8_realign_continuation_plan_v1",
        "windows": [dict(row) for row in plan["windows"][position:]],
        "source_window_position": position,
        "target_end_index": int(target_end_index),
    }
    rows, continuation_trace = SERIAL.windowed_alignment(
        processor,
        model,
        audio,
        document,
        serial_args(args, plan=tail_plan, initial_state=initial_state),
    )
    metadata = {
        "status": "complete",
        "source_window_position": position,
        "source_window_index": current.get("window_index"),
        "initial_committed_cursor": committed_cursor,
        "initial_input_cursor": input_cursor,
        "rerun_window_count": len(continuation_trace),
        "tail_plan": tail_plan,
    }
    return rows, continuation_trace, metadata


def _beam_structural_count(summary: dict[str, Any]) -> int:
    return sum(
        int(summary.get(key, 0) or 0)
        for key in (
            "negative_duration_count", "zero_duration_count",
            "inter_unit_overlap_count", "start_regression_count", "invalid_interval_count",
        )
    )


def _beam_rank_key(state: dict[str, Any]) -> tuple[Any, ...]:
    cumulative = state["cumulative"]
    evidence_count = max(1, int(cumulative.get("risk_evidence_count", 0)))
    mean_risk = float(cumulative.get("risk_score_sum", math.inf)) / evidence_count
    return (
        int(cumulative.get("fallback_count", 0)),
        int(cumulative.get("current_progress_deficit_units", 0)),
        int(cumulative.get("risk_span_count", 0)),
        int(cumulative.get("structural_anomaly_count", 0)),
        float(cumulative.get("maximum_risk_score", math.inf)),
        mean_risk,
        int(cumulative.get("attempt_count", 0)),
        int(cumulative.get("branch_complexity", 0)),
        str(state.get("path_id", "")),
    )


def _beam_state_identity(state: dict[str, Any]) -> tuple[Any, ...]:
    tail = canonical_rows(state.get("committed_rows") or [])[-8:]
    timing = tuple(
        (
            int(row["global_character_index"]),
            round(float(row["start_sec"]), 4),
            round(float(row["end_sec"]), 4),
        )
        for row in tail
    )
    return (
        int(state.get("committed_cursor", 0)),
        int(state.get("input_cursor", 0)),
        int(state.get("previous_committed_count", 0)),
        round(float(state.get("previous_core_duration", 0.0)), 4),
        canonical_hash(state.get("previous_stable_suffix")),
        timing,
    )


def run_cursor_window_beam(
    *,
    baseline_rows: list[dict[str, Any]],
    baseline_trace: Sequence[dict[str, Any]],
    processor: Any,
    model: Any,
    audio: Any,
    document: LyricDocument,
    audio_profile: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run an actual cross-window beam with model-backed hypotheses.

    Up to ``system_beam_width`` states are carried into the next window.  Each
    state owns its committed prefix, lyric cursor, previous-end state (through
    the prefix), and text-budget policy.  Pruning is lexicographic and does not
    use GT.
    """
    plan, source_trace = frozen_plan_from_trace(
        baseline_trace, policy="E9_cursor_window_beam_frozen_baseline_plan_v1",
    )
    if len(plan.get("windows", [])) < 2:
        # E9 evaluates cross-window cursor/state propagation.  A one-window
        # item has no such transition, so a beam run would only duplicate local
        # inference without testing the stated mechanism.
        return {
            "schema_version": "E9_actual_cursor_window_beam_v1",
            "not_applicable": True,
            "not_applicable_reason": "requires_at_least_two_windows",
            "beam_width": 0,
            "branch_specs": [],
            "window_records": [],
            "final_states": [],
            "selected_state": None,
            "multi_hypothesis_window_count": 0,
            "fallback_window_count": 0,
        }
    width = max(1, int(args.system_beam_width))
    branch_specs = [
        {
            "name": "nominal",
            "cursor_delta": 0,
            "input_start_delta_sec": 0.0,
            "extra_forward_characters": 0,
            "complexity": 0,
        },
        {
            "name": "cursor_window_backtrack",
            "cursor_delta": -abs(int(args.system_beam_cursor_backtrack_units)),
            "input_start_delta_sec": -abs(float(args.system_beam_window_backtrack_sec)),
            "extra_forward_characters": 0,
            "complexity": 1,
        },
        {
            "name": "wider_text_budget",
            "cursor_delta": 0,
            "input_start_delta_sec": 0.0,
            "extra_forward_characters": abs(int(args.system_beam_extra_forward_characters)),
            "complexity": 1,
        },
    ][:width]
    states: list[dict[str, Any]] = [{
        "path_id": "root",
        "committed_rows": [],
        "committed_cursor": 0,
        "input_cursor": 0,
        "previous_committed_count": 0,
        "previous_core_duration": 0.0,
        "previous_stable_suffix": None,
        "path": [],
        "cumulative": {
            "fallback_count": 0,
            "risk_span_count": 0,
            "structural_anomaly_count": 0,
            "maximum_risk_score": 0.0,
            "risk_score_sum": 0.0,
            "risk_evidence_count": 0,
            "current_progress_deficit_units": 0,
            "attempt_count": 0,
            "branch_complexity": 0,
        },
    }]
    window_records: list[dict[str, Any]] = []
    total_units = len(document.characters)
    baseline_canonical = canonical_rows(baseline_rows)

    for window_position, (window, source_row) in enumerate(zip(plan["windows"], source_trace, strict=True)):
        expansions: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for parent in states:
            if int(parent["committed_cursor"]) >= total_units:
                expansions.append(dict(parent))
                continue
            for branch in branch_specs:
                branch_window = dict(window)
                branch_window["input_start_sec"] = max(
                    0.0,
                    float(branch_window["input_start_sec"]) + float(branch["input_start_delta_sec"]),
                )
                branch_window["window_plan_policy"] = (
                    "E9_actual_cursor_window_text_budget_beam_v1"
                )
                input_cursor = max(
                    0,
                    min(
                        total_units - 1,
                        int(parent["input_cursor"]) + int(branch["cursor_delta"]),
                    ),
                )
                initial_state = {
                    "committed_rows": parent["committed_rows"],
                    "committed_cursor": parent["committed_cursor"],
                    "input_cursor": input_cursor,
                    "previous_committed_count": parent["previous_committed_count"],
                    "previous_core_duration": parent["previous_core_duration"],
                    "previous_stable_suffix": parent.get("previous_stable_suffix"),
                }
                one_window_plan = {
                    "schema_version": "E9_single_window_beam_step_v1",
                    "windows": [branch_window],
                    "source_window_position": window_position,
                }
                try:
                    rows, step_trace = SERIAL.windowed_alignment(
                        processor,
                        model,
                        audio,
                        document,
                        serial_args(
                            args,
                            plan=one_window_plan,
                            initial_state=initial_state,
                            max_windows=1,
                            allow_partial=True,
                            minimum_forward_characters=(
                                int(args.minimum_forward_characters)
                                + int(branch["extra_forward_characters"])
                            ),
                        ),
                    )
                    if not step_trace:
                        raise RuntimeError("beam step produced no trace row")
                    last = step_trace[-1]
                    next_cursor = int(last.get("committed_cursor_after", len(rows)))
                    next_input = int(last.get("next_window_input_character_start", next_cursor))
                    if next_cursor <= int(parent["committed_cursor"]):
                        raise RuntimeError(
                            "beam hypothesis made no forward progress in the current window: "
                            f"before={parent['committed_cursor']} after={next_cursor}"
                        )
                    newly_committed = [
                        row for row in rows
                        if int(row["global_character_index"]) >= int(parent["committed_cursor"])
                    ]
                    support = support_for_rows(canonical_rows(newly_committed), audio_profile) if newly_committed else {}
                    detector = inspect_alignment(
                        newly_committed,
                        config=DetectorConfig(cross_input_tolerance_sec=args.detector_tolerance_sec),
                        audio_support_by_index=support,
                        risk_model=args.frozen_detector_model,
                        active_threshold=(
                            args.detector_model_threshold
                            if args.frozen_detector_model is not None
                            else args.detector_risk_threshold
                        ),
                        active_safe_threshold=args.detector_safe_threshold,
                        active_safe_boundary_score_threshold=getattr(args, "dynamic_safe_score", 0.25),
                        detector_name=args.selected_detector_name,
                    ) if newly_committed else {"features": [], "risk_spans": []}
                    selection = detector_selection_components(detector)
                    structure = structural_summary(canonical_rows(newly_committed)) if newly_committed else {}
                    cumulative = dict(parent["cumulative"])
                    cumulative["risk_span_count"] += int(selection["risk_span_count"] if math.isfinite(float(selection["risk_span_count"])) else 1_000_000)
                    cumulative["structural_anomaly_count"] += _beam_structural_count(structure)
                    cumulative["maximum_risk_score"] = max(
                        float(cumulative["maximum_risk_score"]),
                        float(selection["maximum_risk_score"] if math.isfinite(float(selection["maximum_risk_score"])) else 1_000_000.0),
                    )
                    finite_mean_risk = (
                        float(selection["mean_risk_score"])
                        if math.isfinite(float(selection["mean_risk_score"]))
                        else 1_000_000.0
                    )
                    risk_evidence_count = max(1, len(detector.get("features") or []))
                    cumulative["risk_score_sum"] += finite_mean_risk * risk_evidence_count
                    cumulative["risk_evidence_count"] += risk_evidence_count
                    expected_cursor = int(source_row.get("committed_cursor_after", next_cursor))
                    cumulative["current_progress_deficit_units"] = max(0, expected_cursor - next_cursor)
                    cumulative["attempt_count"] += len(last.get("attempts") or [])
                    cumulative["branch_complexity"] += int(branch["complexity"])
                    path_id = f"{parent['path_id']}/{window_position}:{branch['name']}"
                    child = {
                        "path_id": path_id,
                        "committed_rows": rows,
                        "committed_cursor": next_cursor,
                        "input_cursor": next_input,
                        "previous_committed_count": int(last.get("committed_character_count", 0)),
                        "previous_core_duration": float(last.get("core_end_sec", 0.0)) - float(last.get("core_start_sec", 0.0)),
                        "previous_stable_suffix": last.get("stable_suffix_candidate"),
                        "path": parent["path"] + [{
                            "window_position": window_position,
                            "window_index": window.get("window_index"),
                            "branch": branch,
                            "committed_cursor_before": parent["committed_cursor"],
                            "committed_cursor_after": next_cursor,
                            "input_cursor_before": input_cursor,
                            "input_cursor_after": next_input,
                            "detector_selection_components": selection,
                            "structural": structure,
                            "attempt_count": len(last.get("attempts") or []),
                        }],
                        "cumulative": cumulative,
                    }
                    child["rank_key"] = list(_beam_rank_key(child)[:-1])
                    expansions.append(child)
                except Exception as exc:
                    failures.append({
                        "parent_path_id": parent["path_id"],
                        "branch": branch,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

        used_baseline_fallback = False
        if not expansions:
            used_baseline_fallback = True
            committed_end = int(
                source_row.get(
                    "committed_cursor_after",
                    source_row.get("committed_character_end", 0),
                )
            )
            fallback_rows = [
                dict(row) for row in baseline_canonical
                if int(row["global_character_index"]) < committed_end
            ]
            best_parent = min(states, key=_beam_rank_key)
            prior_fallbacks = int(best_parent["cumulative"].get("fallback_count", 0))
            fallback = {
                "path_id": f"{best_parent['path_id']}/{window_position}:baseline_fallback",
                "committed_rows": fallback_rows,
                "committed_cursor": committed_end,
                "input_cursor": int(source_row.get("next_window_input_character_start", committed_end)),
                "previous_committed_count": int(source_row.get("committed_character_count", 0)),
                "previous_core_duration": float(source_row.get("core_end_sec", 0.0)) - float(source_row.get("core_start_sec", 0.0)),
                "previous_stable_suffix": source_row.get("stable_suffix_candidate"),
                "path": best_parent["path"] + [{
                    "window_position": window_position,
                    "window_index": window.get("window_index"),
                    "branch": {"name": "baseline_fallback"},
                    "reason": "all_model_backed_beam_expansions_failed",
                    "baseline_reset": True,
                }],
                # The rows reset to the baseline prefix, so risk/structure
                # evidence also restarts. The fallback count remains cumulative
                # to make degraded search provenance explicit.
                "cumulative": {
                    "fallback_count": prior_fallbacks + 1,
                    "risk_span_count": 0,
                    "structural_anomaly_count": 0,
                    "maximum_risk_score": 0.0,
                    "risk_score_sum": 0.0,
                    "risk_evidence_count": 0,
                    "current_progress_deficit_units": 0,
                    "attempt_count": 0,
                    "branch_complexity": 0,
                },
            }
            fallback["rank_key"] = list(_beam_rank_key(fallback)[:-1])
            expansions = [fallback]

        deduplicated: dict[tuple[Any, ...], dict[str, Any]] = {}
        for state in expansions:
            identity = _beam_state_identity(state)
            existing = deduplicated.get(identity)
            if existing is None or _beam_rank_key(state) < _beam_rank_key(existing):
                deduplicated[identity] = state
        ordered = sorted(deduplicated.values(), key=_beam_rank_key)
        states = ordered[:width]
        window_records.append({
            "window_position": window_position,
            "window_index": window.get("window_index"),
            "expanded_hypothesis_count": len(expansions),
            "deduplicated_hypothesis_count": len(ordered),
            "failed_expansion_count": len(failures),
            "failures": failures,
            "survivor_count": len(states),
            "survivors": [{
                "path_id": state["path_id"],
                "committed_cursor": state["committed_cursor"],
                "input_cursor": state["input_cursor"],
                "rank_key": state["rank_key"],
            } for state in states],
            "carried_multiple_hypotheses": len(states) > 1,
            "baseline_fallback_used": used_baseline_fallback,
        })

    final_states = sorted(states, key=_beam_rank_key)
    return {
        "schema_version": "E9_actual_cursor_window_beam_v1",
        "beam_width": width,
        "branch_specs": branch_specs,
        "selection_policy": (
            "lexicographic: fallback count, current progress deficit, risk-span count, "
            "structural anomalies, maximum risk, cumulative mean risk, attempts, branch complexity"
        ),
        "window_records": window_records,
        "final_states": final_states,
        "selected_state": final_states[0] if final_states else None,
        "multi_hypothesis_window_count": sum(
            row["carried_multiple_hypotheses"] for row in window_records
        ),
        "fallback_window_count": sum(row["baseline_fallback_used"] for row in window_records),
    }


def gt_cursor(gt: list[dict[str, Any]], time_sec: float, total_units: int) -> int:
    for row in gt:
        index = int(row.get("character_index", row.get("global_character_index")))
        if float(row["start_sec"]) >= time_sec - 1e-9:
            return index
    return total_units


def run_item(
    *, item: dict[str, Any], args: argparse.Namespace, processor: Any | None, model: Any | None,
) -> dict[str, Any]:
    item_id = str(item["item_id"])
    item_root = args.out_root / "items" / item_id
    item_root.mkdir(parents=True, exist_ok=True)
    args._research_cache_root = item_root / "inference_cache"
    args._research_cache_stats = {"hits": 0, "misses": 0, "forward_wall_sec": 0.0}
    args._research_serial_cache_root = item_root / "serial_inference_cache"
    args._research_serial_cache_stats = {"hits": 0, "misses": 0}
    baseline_file = baseline_path(args.baseline_root, item_id, args.baseline_variant)
    if not baseline_file.is_file():
        raise FileNotFoundError(f"baseline missing: {baseline_file}")
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    baseline_rows = list(baseline["characters"])
    trace = list(baseline.get("window_trace", []))
    gt = load_gt(item.get("gt_path"))
    lyrics_path = Path(item["lyrics_path"])
    audio_path, lazy_audio_owned = materialize_item_audio(item)
    language = normalize_alignment_language(str(item.get("language") or args.language))
    document = parse_lyrics_text(lyrics_path.read_text(encoding="utf-8-sig"), language=language)
    audio = decode_audio(audio_path)
    duration_sec = len(audio) / 16000.0
    if len(document.characters) != len(baseline_rows):
        raise ValueError(f"{item_id}: baseline/document unit mismatch")

    requested_phases = set(args.phases)
    phases = set(requested_phases)
    summary: dict[str, Any] = {
        "item_id": item_id,
        "dataset": item.get("dataset"),
        "profile": item.get("profile"),
        "split": item.get("split"),
        "selection_role": item.get("selection_role"),
        "training_exposure": bool(item.get("training_exposure", False)),
        "source_song_id": item.get("source_song_id") or item.get("song_id") or item.get("source_item_id") or item_id,
        "synthetic": bool(item.get("synthetic", False)),
        "synthetic_seams_sec": list(item.get("synthetic_seams_sec") or item.get("join_points_sec") or []),
        "language": language,
        "unit_count": len(document.characters),
        "duration_sec": duration_sec,
        "baseline_path": str(baseline_file),
        "frozen_decoder": str(getattr(args, "selected_decoder_name", "official")),
        "phases": {},
        "resumed_phases": [],
    }
    if args.resume:
        phase_files = {
            "E2": "E2_corruptions.json", "E3": "E3_decoder_hybrid.json",
            "E4": "E4_text_budget_and_chunks.json", "E5": "E5_dynamic_windows.json",
            "E6": "E6_silence.json", "E7": "E7_serial_propagation.json",
            "E8": "E8_realign.json", "E9": "E9_system_pilots.json",
        }
        for phase, filename in phase_files.items():
            path = item_root / filename
            if phase not in phases or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            phase_summary = payload.get("_phase_summary")
            if phase_summary is None:
                continue
            summary["phases"][phase] = {**phase_summary, "resumed": True}
            summary["resumed_phases"].append(phase)
            phases.remove(phase)

    decoder_outputs: dict[str, list[dict[str, Any]]] = {}
    if {"E0", "E1", "E3", "E8"} & phases:
        for name in DECODER_NAMES:
            config = DecoderConfig(
                name=name,
                timestamp_step_sec=args.timestamp_segment_sec,
                top_k=args.decoder_top_k,
                beam_size=args.decoder_beam_size,
            )
            decoder_outputs[name] = decode_rows(baseline_rows, config)
        raw_decoder_rows = decoder_outputs["raw"]
        decoder_records = []
        for name, rows in decoder_outputs.items():
            extra = {}
            if gt:
                extra["paired_transition_from_raw"] = paired_decoder_transition_metrics(
                    raw_decoder_rows, rows, gt, tolerance_sec=args.detector_tolerance_sec,
                )
            decoder_records.append(candidate_record(
                name, rows, gt, seams_sec=summary["synthetic_seams_sec"], extra=extra,
            ))
        atomic_json(item_root / "E0_decoder_reanalysis.json", {
            "schema_version": "E0_decoder_reanalysis_v1",
            "candidates": decoder_records,
        })
        for name, rows in decoder_outputs.items():
            write_alignment(
                item_root / "experimental_alignments" / f"decoder_{name}" / "alignment.json",
                baseline=baseline, name=f"decoder_{name}", rows=rows, gt=gt,
                metadata={"phase": "E0/E3", "decoder": name}, compact_artifacts=args.compact_artifacts,
            )
        summary["phases"]["E0"] = {"candidate_count": len(decoder_records), "candidates": decoder_records}

    # A non-official frozen decoder must be applied before ownership splitting
    # and cursor updates.  Re-running the frozen baseline plan here establishes
    # the actual formal route used by E1 and all downstream experiments.  The
    # original B4 cache remains the fair, shared evidence source for E0 decoder
    # comparison above.
    if args.mode == "formal" and args.selected_decoder_name != "official":
        if processor is None or model is None:
            raise RuntimeError("non-official frozen decoder requires model-backed formal baseline rerun")
        frozen_route_plan, _ = frozen_plan_from_trace(
            trace, policy="formal_frozen_decoder_baseline_plan_v1",
        )
        route_started = time.perf_counter()
        route_recovery = None
        try:
            baseline_rows, trace = SERIAL.windowed_alignment(
                processor, model, audio, document, serial_args(args, plan=frozen_route_plan),
            )
        except (RuntimeError, SERIAL.SerialWindowAlignmentError) as first_exc:
            retry_args = serial_args(args, plan=frozen_route_plan)
            retry_args.max_candidate_expansions = max(16, int(args.max_candidate_expansions) * 3)
            try:
                baseline_rows, trace = SERIAL.windowed_alignment(
                    processor, model, audio, document, retry_args,
                )
                route_recovery = {"status": "expanded_retry", "initial_error": str(first_exc)}
            except (RuntimeError, SERIAL.SerialWindowAlignmentError) as retry_exc:
                # Keep the frozen decoder active for downstream phases even
                # when serial boundary observation is infeasible.  This is an
                # explicit B4-plan fallback, not a silent official-decoder run.
                config = DecoderConfig(
                    name=args.selected_decoder_name,
                    timestamp_step_sec=args.timestamp_segment_sec,
                    top_k=args.decoder_top_k,
                    beam_size=args.decoder_beam_size,
                )
                baseline_rows = decode_rows(baseline_rows, config)
                route_recovery = {
                    "status": "B4_plan_decoder_fallback",
                    "initial_error": str(first_exc), "retry_error": str(retry_exc),
                }
        route_wall_sec = time.perf_counter() - route_started
        baseline_indices = [
            int(row["global_character_index"]) for row in canonical_rows(baseline_rows)
        ]
        if baseline_indices != list(range(len(document.characters))):
            raise RuntimeError(
                "frozen decoder formal baseline was incomplete: "
                f"decoder={args.selected_decoder_name} indices={baseline_indices[:8]}... "
                f"rows={len(baseline_rows)} expected={len(document.characters)}"
            )
        write_alignment(
            item_root / "frozen_decoder_baseline" / "alignment.json",
            baseline=baseline,
            name=f"frozen_decoder_baseline_{args.selected_decoder_name}",
            rows=baseline_rows,
            gt=gt,
            metadata={
                "phase": "formal_frozen_decoder_baseline",
                "decoder": args.selected_decoder_name,
                "decoder_applied_before_serial_commit": True,
                "source_baseline_variant": args.baseline_variant,
            },
            window_trace=trace, compact_artifacts=args.compact_artifacts,
        )
        summary["frozen_decoder_route"] = {
            "decoder": args.selected_decoder_name,
            "source": "model_backed_serial_rerun_under_frozen_baseline_plan" if route_recovery is None else route_recovery["status"],
            "recovery": route_recovery,
            "decoder_applied_before_serial_commit": True,
            "window_count": len(trace),
            "wall_sec": route_wall_sec,
        }
    else:
        summary["frozen_decoder_route"] = {
            "decoder": args.selected_decoder_name,
            "source": "existing_official_B4_serial_baseline",
            "decoder_applied_before_serial_commit": True,
            "window_count": len(trace),
        }

    detector_report: dict[str, Any] | None = None
    audio_profile: dict[str, Any] | None = None
    detector_input_candidates: list[list[dict[str, Any]]] = []
    detector_window_candidates: list[list[dict[str, Any]]] = []
    detector_cursor_disagreement: dict[int, float] = {}
    if {"E1", "E2", "E3", "E5", "E8", "E9"} & phases:
        audio_profile = build_audio_profile(audio)
        support = support_for_rows(canonical_rows(baseline_rows), audio_profile)
        detector_input_candidates, detector_window_candidates, detector_cursor_disagreement = detector_context_from_trace(trace)
        detector_report = inspect_alignment(
            baseline_rows,
            config=DetectorConfig(
                error_tolerance_sec=args.detector_tolerance_sec,
                risk_threshold=args.detector_risk_threshold,
                safe_threshold=args.detector_safe_threshold,
                cross_input_tolerance_sec=args.detector_tolerance_sec,
            ),
            input_candidates=detector_input_candidates,
            window_candidates=detector_window_candidates,
            audio_support_by_index=support,
            cursor_disagreement_by_index=detector_cursor_disagreement,
            risk_model=args.frozen_detector_model,
            active_threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
            active_safe_threshold=args.detector_safe_threshold,
            active_safe_boundary_score_threshold=getattr(args, "dynamic_safe_score", 0.25),
            detector_name=args.selected_detector_name,
        )
        detector_report["features"] = add_gt_labels(
            detector_report["features"], gt, canonical_rows(baseline_rows),
            tolerance_sec=args.detector_tolerance_sec,
        ) if gt else detector_report["features"]
        if gt:
            detector_report["features"] = add_repairability_and_safe_labels(
                detector_report["features"], gt, canonical_rows(baseline_rows),
                {
                    name: canonical_rows(rows) for name, rows in decoder_outputs.items()
                    if name in {"joint_start_end", "topk_sequence", "weighted_isotonic"}
                },
                tolerance_sec=args.detector_tolerance_sec,
            )
        detector_report["rule_threshold_curve"] = (
            threshold_curve(detector_report["features"], score_key="rule_risk_score") if gt else []
        )
        detector_report["active_threshold_curve"] = (
            threshold_curve(detector_report["features"], score_key=detector_report["active_score_key"]) if gt else []
        )
        detector_report["rule_event_threshold_curve"] = (
            event_threshold_curve(detector_report["features"], score_key="rule_risk_score") if gt else []
        )
        detector_report["active_event_threshold_curve"] = (
            event_threshold_curve(detector_report["features"], score_key=detector_report["active_score_key"]) if gt else []
        )
        detector_report["repairable_threshold_curve"] = (
            threshold_curve(
                detector_report["features"], score_key=detector_report["active_score_key"], label_key="gt_repairable"
            ) if gt else []
        )
        detector_report["safe_boundary_threshold_curve"] = (
            threshold_curve(
                detector_report["features"], score_key="safe_boundary_decision_score", label_key="gt_safe_boundary"
            ) if gt else []
        )
        detector_report["evidence_sources"] = {
            "input_candidate_sets": len(detector_input_candidates),
            "window_candidate_sets": len(detector_window_candidates),
            "cursor_disagreement_indices": len(detector_cursor_disagreement),
            "audio_support_indices": len(support),
        }
        atomic_json(item_root / "E1_detector.json", detector_report)
        summary["phases"]["E1"] = {
            "selected_detector": detector_report["selected_detector"],
            "active_score_key": detector_report["active_score_key"],
            "active_risk_threshold": detector_report["active_risk_threshold"],
            "risk_span_count": len(detector_report["risk_spans"]),
            "safe_boundary_count": len(detector_report["safe_boundaries"]),
            "gt_available": bool(gt),
            "evidence_sources": detector_report["evidence_sources"],
        }

    local_requests = representative_requests(
        item_id, trace, total_units=len(document.characters), duration_sec=duration_sec,
        cases_per_item=args.cases_per_item,
    )

    if "E2" in phases:
        if processor is None or model is None:
            raise RuntimeError("E2 requires model inference")
        if audio_profile is None:
            audio_profile = build_audio_profile(audio)
        specs = default_corruption_specs()
        if args.mode == "pilot":
            # One moderate corruption per category in pilot; formal runs all.
            seen = set(); pilot_specs = []
            for spec in specs:
                if spec.category not in seen:
                    seen.add(spec.category); pilot_specs.append(spec)
            specs = pilot_specs
        records = []
        for case_index, request in enumerate(local_requests):
            evaluation_indices = fixed_scope_for_request(request, gt)
            baseline_local = run_request(
                request=request, spec=None, audio=audio, document=document,
                processor=processor, model=model, args=args,
            )
            baseline_common = canonical_rows(baseline_local)
            baseline_support = support_for_rows(baseline_common, audio_profile)
            clean_report = inspect_alignment(
                baseline_local,
                config=DetectorConfig(cross_input_tolerance_sec=args.detector_tolerance_sec),
                input_candidates=[baseline_common], audio_support_by_index=baseline_support,
                risk_model=args.frozen_detector_model,
                active_threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
                active_safe_threshold=args.detector_safe_threshold,
                active_safe_boundary_score_threshold=getattr(args, "dynamic_safe_score", 0.25),
                detector_name=args.selected_detector_name,
            )
            if gt:
                clean_report["features"] = add_gt_labels(
                    clean_report["features"], select_gt_rows(gt, indices=evaluation_indices), baseline_common,
                    tolerance_sec=args.detector_tolerance_sec,
                )
            for spec in specs:
                corrupted_request = apply_corruption(
                    request, spec, total_units=len(document.characters), duration_sec=duration_sec,
                )
                rows = run_request(
                    request=corrupted_request, spec=spec, audio=audio, document=document,
                    processor=processor, model=model, args=args,
                )
                canonical_corrupted = canonical_rows(rows)
                common_indices = sorted(
                    set(int(row["global_character_index"]) for row in baseline_common)
                    & set(int(row["global_character_index"]) for row in canonical_corrupted)
                )
                by_base = {int(row["global_character_index"]): row for row in baseline_common}
                by_new = {int(row["global_character_index"]): row for row in canonical_corrupted}
                spread = [
                    max(
                        abs(float(by_base[index]["start_sec"]) - float(by_new[index]["start_sec"])),
                        abs(float(by_base[index]["end_sec"]) - float(by_new[index]["end_sec"])),
                    )
                    for index in common_indices
                ]
                corrupted_support = support_for_rows(canonical_corrupted, audio_profile)
                report = inspect_alignment(
                    rows,
                    config=DetectorConfig(cross_input_tolerance_sec=args.detector_tolerance_sec),
                    input_candidates=[baseline_common, canonical_corrupted],
                    audio_support_by_index=corrupted_support,
                    risk_model=args.frozen_detector_model,
                    active_threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
                    active_safe_threshold=args.detector_safe_threshold,
                active_safe_boundary_score_threshold=getattr(args, "dynamic_safe_score", 0.25),
                detector_name=args.selected_detector_name,
                )
                detection = None
                if gt:
                    report["features"] = add_gt_labels(
                        report["features"], select_gt_rows(gt, indices=evaluation_indices), canonical_corrupted,
                        tolerance_sec=args.detector_tolerance_sec,
                    )
                    detection = binary_metrics(
                        report["features"], score_key="risk_score", label_key="gt_error",
                        threshold=float(report["active_risk_threshold"]),
                    )
                    event_detection = event_metrics(
                        report["features"], score_key="risk_score", label_key="gt_error",
                        threshold=float(report["active_risk_threshold"]),
                    )
                else:
                    event_detection = None
                records.append({
                    "case_index": case_index,
                    "request": request.to_dict(),
                    "evaluation_indices": evaluation_indices,
                    "corruption": spec.to_dict(),
                    "corrupted_request": corrupted_request.to_dict(),
                    "common_unit_count": len(common_indices),
                    "median_boundary_change_sec": float(np.median(spread)) if spread else None,
                    "max_boundary_change_sec": max(spread, default=None),
                    "detector": {
                        "selected_detector": report["selected_detector"],
                        "active_score_key": report["active_score_key"],
                        "active_risk_threshold": report["active_risk_threshold"],
                        "risk_spans": report["risk_spans"],
                        "risk_span_count": len(report["risk_spans"]),
                        "binary_metrics": detection,
                        "event_metrics": event_detection,
                        "clean_risk_span_count": len(clean_report["risk_spans"]),
                    },
                    "candidate": candidate_record(
                        spec.name, rows, gt, metric_indices=evaluation_indices,
                        metric_scope="fixed_local_ownership",
                    ),
                })
        payload = {
            "schema_version": "E2_corruption_suite_v2", "case_count": len(records),
            "detector_name": args.selected_detector_name, "records": records,
            "_phase_summary": {"record_count": len(records), "corruption_categories": sorted({row["corruption"]["category"] for row in records})},
        }
        atomic_json(item_root / "E2_corruptions.json", payload)
        summary["phases"]["E2"] = payload["_phase_summary"]

    if "E3" in phases:
        if detector_report is None:
            raise RuntimeError("E3 requires detector report")
        span_sets: dict[str, list[tuple[int, int]]] = {
            "detector": [
                (int(row["character_start"]), int(row["character_end"]))
                for row in detector_report.get("risk_spans", [])
            ]
        }
        if gt:
            official = decoder_outputs.get("official") or decode_rows(baseline_rows, DecoderConfig(name="official"))
            details = alignment_metrics(official, gt)["details"]
            hard = [int(row["character_index"]) for row in details if float(row["max_abs_error_sec"]) > args.detector_tolerance_sec]
            oracle_spans: list[tuple[int, int]] = []
            if hard:
                span_start = previous = hard[0]
                for index in hard[1:]:
                    if index <= previous + 1:
                        previous = index
                    else:
                        oracle_spans.append((span_start, previous)); span_start = previous = index
                oracle_spans.append((span_start, previous))
            span_sets["oracle"] = oracle_spans
        records = []
        for span_source, spans in span_sets.items():
            if not spans:
                records.append({
                    "span_source": span_source, "status": "not_applicable",
                    "reason": "no_risk_spans", "spans": [], "candidates": [],
                })
                continue
            candidates = []
            for method in ("local_weighted_isotonic", "local_topk_sequence"):
                rows = decode_rows(
                    baseline_rows,
                    DecoderConfig(
                        name=method, local_spans=tuple(spans), top_k=args.decoder_top_k,
                        beam_size=args.decoder_beam_size, timestamp_step_sec=args.timestamp_segment_sec,
                    ),
                )
                record = candidate_record(method, rows, gt, metric_scope="full_item_hybrid")
                candidates.append(record)
                write_alignment(
                    item_root / "experimental_alignments" / f"decoder_{span_source}_{method}" / "alignment.json",
                    baseline=baseline, name=f"{span_source}_{method}", rows=rows, gt=gt,
                    metadata={"phase": "E3", "span_source": span_source, "spans": spans}, compact_artifacts=args.compact_artifacts,
                )
            records.append({
                "span_source": span_source, "status": "complete",
                "spans": [{"character_start": a, "character_end": b} for a, b in spans],
                "candidates": candidates,
            })
        payload = {
            "schema_version": "E3_decoder_hybrid_v2",
            "detector_name": detector_report["selected_detector"],
            "records": records,
            "_phase_summary": {
                "span_sources": {row["span_source"]: len(row.get("spans", [])) for row in records},
                "candidate_count": sum(len(row.get("candidates", [])) for row in records),
            },
        }
        atomic_json(item_root / "E3_decoder_hybrid.json", payload)
        summary["phases"]["E3"] = payload["_phase_summary"]

    if "E4" in phases:
        if processor is None or model is None:
            raise RuntimeError("E4 requires model inference")
        if audio_profile is None:
            audio_profile = build_audio_profile(audio)
        records = []
        for case_index, request in enumerate(local_requests):
            base_length = request.text_end - request.text_start
            evaluation_indices = fixed_scope_for_request(request, gt)
            required_end = max(evaluation_indices, default=request.text_end - 1) + 1
            amounts = sorted({
                max(1, int(round(base_length * ratio))) for ratio in (0.50, 0.75, 1.0, 1.25, 1.50)
            } | set(text_budget_candidates(base_length, maximum=len(document.characters) - request.text_start)))
            raw_candidates = []
            candidate_rows: list[list[dict[str, Any]]] = []
            for amount in amounts:
                adjusted = request.derive(
                    text_end=min(len(document.characters), request.text_start + amount),
                    request_role=f"text_budget_{amount}",
                )
                rows = run_request(
                    request=adjusted, spec=None, audio=audio, document=document,
                    processor=processor, model=model, args=args,
                )
                inference_meta = dict(getattr(args, "_last_request_meta", {}))
                canonical = canonical_rows(rows)
                candidate_rows.append(canonical)
                raw_candidates.append((amount, adjusted, rows, canonical, inference_meta))
            candidates = []
            for amount, adjusted, rows, canonical, inference_meta in raw_candidates:
                support = support_for_rows(canonical, audio_profile)
                report = inspect_alignment(
                    rows,
                    config=DetectorConfig(cross_input_tolerance_sec=args.detector_tolerance_sec),
                    input_candidates=candidate_rows, audio_support_by_index=support,
                    risk_model=args.frozen_detector_model,
                    active_threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
                    active_safe_threshold=args.detector_safe_threshold,
                active_safe_boundary_score_threshold=getattr(args, "dynamic_safe_score", 0.25),
                detector_name=args.selected_detector_name,
                )
                selection_components = detector_selection_components(report)
                score = detector_selection_score(report)
                candidates.append({
                    "amount": amount,
                    "amount_ratio_vs_baseline": amount / max(1, base_length),
                    "request": adjusted.to_dict(),
                    "coverage_relation": "future_only_removed_or_added" if adjusted.text_end >= required_end else "core_target_truncated",
                    "detector_selection_score": score,
                    "detector_selection_components": selection_components,
                    "detector_report": {
                        "selected_detector": report["selected_detector"],
                        "active_score_key": report["active_score_key"],
                        "risk_spans": report["risk_spans"],
                        "risk_span_count": len(report["risk_spans"]),
                    },
                    "inference": inference_meta,
                    "candidate": candidate_record(
                        str(amount), rows, gt, metric_indices=evaluation_indices,
                        metric_scope="fixed_local_ownership",
                    ),
                })
            records.append({
                "case_index": case_index, "baseline_request": request.to_dict(),
                "evaluation_indices": evaluation_indices,
                "candidates": candidates,
                "selection_results": choose_budget_candidates(candidates),
            })
        # 96 vs 3x32 family.  All candidates use the same [start,end) local GT
        # scope; chunk seams and inference cost are reported explicitly.
        chunk_records = []
        total = len(document.characters)
        for start_index, end_index in complete_group_ranges(total, 96):
            source_times = {
                int(row.get("character_index", row.get("global_character_index"))): (float(row["start_sec"]), float(row["end_sec"]))
                for row in (gt if gt else canonical_rows(baseline_rows))
            }
            if start_index not in source_times or end_index - 1 not in source_times:
                continue
            local_indices = list(range(start_index, end_index))
            whole = AlignmentRequest(
                item_id, max(0.0, source_times[start_index][0] - 0.5), min(duration_sec, source_times[end_index - 1][1] + 0.5),
                start_index, end_index, request_role="chunk_whole_96",
            )
            whole_rows = run_request(request=whole, spec=None, audio=audio, document=document, processor=processor, model=model, args=args)
            whole_meta = dict(getattr(args, "_last_request_meta", {}))
            whole_record = candidate_record("1x96", whole_rows, gt, metric_indices=local_indices, metric_scope="fixed_96_unit_group")
            whole_audio_sec = whole.audio_end_sec - whole.audio_start_sec
            whole_estimated_wall = float(whole_meta.get("estimated_uncached_wall_sec", whole_meta.get("wall_sec", 0.0)))
            whole_actual_wall = float(whole_meta.get("actual_forward_wall_sec", whole_estimated_wall))
            whole_record["inference"] = {
                **whole_meta, "call_count": 1, "audio_requested_sec": whole_audio_sec,
                "actual_forward_wall_sec": whole_actual_wall,
                "estimated_uncached_wall_sec": whole_estimated_wall,
                "actual_rtf": whole_actual_wall / max(1e-9, whole_audio_sec),
                "estimated_uncached_rtf": whole_estimated_wall / max(1e-9, whole_audio_sec),
                # Compatibility alias used by existing reports.
                "rtf": whole_estimated_wall / max(1e-9, whole_audio_sec),
            }
            chunk_variants = {}
            for overlap in (0, 4, 8):
                merged: list[dict[str, Any]] = []
                call_meta = []
                seam_indices: set[int] = set()
                chunks = split_text_chunks(start_index, end_index, chunk_units=32 + overlap, overlap_units=overlap, commit_units=32)
                for chunk_position, chunk in enumerate(chunks):
                    cstart, cend = chunk["text_start"], chunk["text_end"]
                    audio_start = max(0.0, source_times[cstart][0] - 0.5)
                    audio_end = min(duration_sec, source_times[cend - 1][1] + 0.5)
                    chunk_request = AlignmentRequest(item_id, audio_start, audio_end, cstart, cend, request_role=f"chunk_32_overlap_{overlap}")
                    rows = run_request(request=chunk_request, spec=None, audio=audio, document=document, processor=processor, model=model, args=args)
                    call_meta.append({**dict(getattr(args, "_last_request_meta", {})), "audio_requested_sec": audio_end - audio_start})
                    commit_start, commit_end = chunk["commit_start"], chunk["commit_end"]
                    merged.extend(row for row in rows if commit_start <= int(row["global_character_index"]) < commit_end)
                    if chunk_position + 1 < len(chunks):
                        for index in range(max(start_index, commit_end - 1), min(end_index, commit_end + 2)):
                            seam_indices.add(index)
                record = candidate_record(
                    f"3x32_overlap_{overlap}", merged, gt, metric_indices=local_indices,
                    metric_scope="fixed_96_unit_group",
                )
                requested_audio_sec = sum(float(row["audio_requested_sec"]) for row in call_meta)
                actual_wall_sec = sum(
                    float(row.get("actual_forward_wall_sec", row.get("wall_sec", 0.0)))
                    for row in call_meta
                )
                estimated_wall_sec = sum(
                    float(row.get("estimated_uncached_wall_sec", row.get("wall_sec", 0.0)))
                    for row in call_meta
                )
                record["inference"] = {
                    "call_count": len(call_meta),
                    "cache_hit_count": sum(int(row.get("cache_hit", False)) for row in call_meta),
                    "actual_forward_wall_sec": actual_wall_sec,
                    "estimated_uncached_wall_sec": estimated_wall_sec,
                    "audio_requested_sec": requested_audio_sec,
                    "actual_rtf": actual_wall_sec / max(1e-9, requested_audio_sec),
                    "estimated_uncached_rtf": estimated_wall_sec / max(1e-9, requested_audio_sec),
                    "rtf": estimated_wall_sec / max(1e-9, requested_audio_sec),
                }
                if gt and seam_indices:
                    record["chunk_seam_metrics"] = strip_metric_details(alignment_metrics(canonical_rows(merged), select_gt_rows(gt, indices=seam_indices)))
                    record["chunk_seam_indices"] = sorted(seam_indices)
                chunk_variants[str(overlap)] = record
            chunk_records.append({
                "character_start": start_index, "character_end": end_index,
                "localization_source": "GT" if gt else "baseline_pseudo",
                "whole": whole_record, "chunks": chunk_variants,
            })
            if args.mode == "pilot" or args.max_chunk_groups_per_item == 1:
                break
            if args.max_chunk_groups_per_item > 0 and len(chunk_records) >= args.max_chunk_groups_per_item:
                break
        payload = {
            "schema_version": "E4_text_budget_and_chunks_v2",
            "budget_cases": records, "chunk_cases": chunk_records,
            "_phase_summary": {"budget_case_count": len(records), "chunk_case_count": len(chunk_records)},
        }
        atomic_json(item_root / "E4_text_budget_and_chunks.json", payload)
        summary["phases"]["E4"] = payload["_phase_summary"]

    if "E5" in phases:
        if processor is None or model is None or detector_report is None:
            raise RuntimeError("E5 requires model and detector")
        safe = safe_boundary_candidates(detector_report, baseline_rows)
        base_plan = build_dynamic_window_plan(
            duration_sec=duration_sec, target_core_sec=args.core_sec,
            left_context_sec=args.left_context_sec, right_context_sec=args.right_context_sec,
            safe_boundaries=safe, search_before_sec=args.dynamic_search_sec,
            search_after_sec=args.dynamic_search_sec, minimum_score=args.dynamic_safe_score,
        )
        variants = []
        applicable = len(base_plan.get("windows", [])) >= 2
        if applicable:
            for offset in (0, 2, 4):
                plan = synchronize_dynamic_plan(base_plan, baseline_rows, offset)
                execution_error = None
                try:
                    rows, dynamic_trace = SERIAL.windowed_alignment(
                        processor, model, audio, document, serial_args(args, plan=plan),
                    )
                except (RuntimeError, SERIAL.SerialWindowAlignmentError) as exc:
                    # A detector-chosen plan can still be infeasible for a
                    # particular utterance.  Preserve the item and report the
                    # infeasibility explicitly; never let it erase all other
                    # formal phases for that item.
                    rows, dynamic_trace = baseline_rows, trace
                    execution_error = {"type": type(exc).__name__, "message": str(exc), "fallback": "B4_frozen_route"}
                name = f"dynamic_safe_minus{offset}"
                diagnostics = serial_diagnostics(
                    canonical_rows(rows), dynamic_trace, gt, tolerance_sec=args.detector_tolerance_sec,
                    seams_sec=summary["synthetic_seams_sec"],
                )
                movements = []
                for diagnostic in plan.get("boundary_diagnostics", []):
                    movements.append(float(diagnostic["selected_sec"]) - float(diagnostic["nominal_sec"]))
                record = candidate_record(
                    name, rows, gt, seams_sec=summary["synthetic_seams_sec"],
                    extra={
                        "window_count": len(dynamic_trace),
                        "execution_error": execution_error,
                        "serial_diagnostics": diagnostics,
                        "boundary_movement_sec": movements,
                        "boundary_movement_mean_abs_sec": statistics.fmean(abs(value) for value in movements) if movements else 0.0,
                        "nominal_fallback_count": sum(row.get("source") == "nominal_fallback" for row in plan.get("boundary_diagnostics", [])),
                        "planned_cursor_application_count": sum(bool(row.get("planned_input_cursor_applied")) for row in dynamic_trace),
                    },
                )
                variants.append(record)
                write_alignment(
                    item_root / "experimental_alignments" / name / "alignment.json",
                    baseline=baseline, name=name, rows=rows, gt=gt,
                    metadata={"phase": "E5", "plan": plan, "serial_diagnostics": diagnostics}, compact_artifacts=args.compact_artifacts,
                )
        payload = {
            "schema_version": "E5_dynamic_windows_v3", "base_plan": base_plan,
            "applicable": applicable,
            "not_applicable_reason": None if applicable else "fewer_than_two_windows",
            "detector": {
                "selected_detector": detector_report["selected_detector"],
                "active_score_key": detector_report["active_score_key"],
                "active_risk_threshold": detector_report["active_risk_threshold"],
            },
            "variants": variants,
            "_phase_summary": {
                "variant_count": len(variants), "safe_boundary_count": len(safe),
                "applicable": applicable, "window_count": len(base_plan.get("windows", [])),
            },
        }
        atomic_json(item_root / "E5_dynamic_windows.json", payload)
        summary["phases"]["E5"] = payload["_phase_summary"]

    if "E6" in phases:
        if processor is None or model is None:
            raise RuntimeError("E6 requires model")
        activity = SERIAL.build_vocal_activity_profile(audio)
        silence_rows = detect_silence_intervals(
            activity, duration_sec=duration_sec, min_silence_sec=0.8, strong_silence_sec=1.5,
        )
        silences = [SilenceInterval(float(row["start_sec"]), float(row["end_sec"])) for row in silence_rows]
        variants = []
        baseline_canonical = canonical_rows(baseline_rows)
        variants.append(candidate_record(
            "S0_baseline", baseline_rows, gt, seams_sec=summary["synthetic_seams_sec"],
            extra={
                "silence_boundary_diagnostics": silence_boundary_diagnostics(baseline_canonical, gt, silence_rows),
                "serial_diagnostics": serial_diagnostics(baseline_canonical, trace, gt, tolerance_sec=args.detector_tolerance_sec, seams_sec=summary["synthetic_seams_sec"]),
            },
        ))
        hard_plan = None
        if silences:
            hard_plan = build_hard_core_soft_context_plan(
                duration_sec=duration_sec, silences=silences, target_core_sec=args.core_sec,
                left_context_sec=args.left_context_sec, right_lookahead_sec=args.silence_lookahead_sec,
            )
            if hard_plan["windows"]:
                rows, hard_trace = SERIAL.windowed_alignment(processor, model, audio, document, serial_args(args, plan=hard_plan))
                canonical = canonical_rows(rows)
                variants.append(candidate_record(
                    "S1_hard_core_full_context", rows, gt, seams_sec=summary["synthetic_seams_sec"],
                    extra={
                        "silence_boundary_diagnostics": silence_boundary_diagnostics(canonical, gt, silence_rows),
                        "serial_diagnostics": serial_diagnostics(canonical, hard_trace, gt, tolerance_sec=args.detector_tolerance_sec, seams_sec=summary["synthetic_seams_sec"]),
                    },
                ))
                write_alignment(item_root / "experimental_alignments" / "S1_hard_core_full_context" / "alignment.json", baseline=baseline, name="S1_hard_core_full_context", rows=rows, gt=gt, metadata={"phase": "E6", "plan": hard_plan}, compact_artifacts=args.compact_artifacts)
            for cap in (4.0, 1.5, 0.4):
                mapping = cap_silence_mapping(duration_sec=duration_sec, silences=silences, cap_sec=cap)
                transformed_audio = apply_time_mapping_to_audio(audio, mapping)
                transformed_plan = map_window_plan(hard_plan, mapping, direction="original_to_transformed")
                rows, transformed_trace = SERIAL.windowed_alignment(
                    processor, model, transformed_audio, document, serial_args(args, plan=transformed_plan),
                )
                rows = remap_rows(rows, mapping)
                restored_trace = remap_trace(transformed_trace, mapping)
                name = "S_history_cap_0p4s" if abs(cap - 0.4) < 1e-9 else f"S_cap_{str(cap).replace('.', 'p')}s"
                canonical = canonical_rows(rows)
                variants.append(candidate_record(
                    name, rows, gt, seams_sec=summary["synthetic_seams_sec"],
                    extra={
                        "silence_cap_sec": cap,
                        "silence_boundary_diagnostics": silence_boundary_diagnostics(canonical, gt, silence_rows),
                        "serial_diagnostics": serial_diagnostics(canonical, restored_trace, gt, tolerance_sec=args.detector_tolerance_sec, seams_sec=summary["synthetic_seams_sec"]),
                    },
                ))
                write_alignment(item_root / "experimental_alignments" / name / "alignment.json", baseline=baseline, name=name, rows=rows, gt=gt, metadata={"phase": "E6", "cap_sec": cap, "mapping": [segment.to_dict() for segment in mapping], "plan": transformed_plan}, compact_artifacts=args.compact_artifacts)
        payload = {
            "schema_version": "E6_silence_v3", "silence_intervals": silence_rows,
            "applicable": bool(silences),
            "not_applicable_reason": None if silences else "no_detected_silence",
            "hard_core_soft_context_plan": hard_plan, "variants": variants,
            "_phase_summary": {"silence_count": len(silences), "variant_count": len(variants), "applicable": bool(silences)},
        }
        atomic_json(item_root / "E6_silence.json", payload)
        summary["phases"]["E6"] = payload["_phase_summary"]

    if "E7" in phases:
        if processor is None or model is None:
            raise RuntimeError("E7 requires model")
        windows = []
        for position, row in enumerate(trace):
            if row.get("silent_core_skipped"):
                continue
            windows.append({
                "window_index": int(row.get("window_index", position)),
                "core_start_sec": float(row["core_start_sec"]),
                "core_end_sec": float(row["core_end_sec"]),
                "core_duration_sec": float(row["core_end_sec"] - row["core_start_sec"]),
                "input_start_sec": float(row.get("input_start_sec", row.get("effective_input_start_sec", 0.0))),
                "input_end_sec": float(row["input_end_sec"]),
                "is_final_core": bool(row.get("is_final_core", position == len(trace) - 1)),
                "window_plan_policy": "frozen_baseline_trace_for_state_injection",
            })
        frozen_plan = {"schema_version": "frozen_baseline_trace_plan_v1", "windows": windows}
        records = []
        if len(windows) < 2:
            payload = {
                "schema_version": "E7_serial_propagation_v2", "frozen_plan": frozen_plan,
                "applicable": False, "not_applicable_reason": "fewer_than_two_non_silent_windows",
                "records": [], "_phase_summary": {"record_count": 0, "applicable": False},
            }
        else:
            injection_window = min(args.injection_window_index, len(windows) - 2)
            intervention_time = float(windows[injection_window]["core_start_sec"])
            injection_specs = []
            for value in (-8, -4, -2, 2, 4, 8): injection_specs.append(("cursor_units", float(value)))
            for value in (-1.6, -0.8, -0.4, 0.4, 0.8, 1.6): injection_specs.append(("previous_end_sec", value))
            for value in (-5.0, -2.0, 2.0, 5.0): injection_specs.append(("core_boundary_sec", value))
            if args.mode == "pilot": injection_specs = injection_specs[::3]
            for kind, value in injection_specs:
                injections = [] if kind == "core_boundary_sec" else [{"window_index": injection_window, "kind": kind, "value": value}]
                active_plan = frozen_plan
                if kind == "core_boundary_sec" and injection_window + 1 < len(windows):
                    shifted = [dict(row) for row in windows]
                    lower = shifted[injection_window]["core_start_sec"] + 1.0
                    upper = shifted[injection_window + 1]["core_end_sec"] - 1.0
                    boundary = min(upper, max(lower, shifted[injection_window]["core_end_sec"] + value))
                    shifted[injection_window]["core_end_sec"] = boundary
                    shifted[injection_window]["core_duration_sec"] = boundary - shifted[injection_window]["core_start_sec"]
                    shifted[injection_window + 1]["core_start_sec"] = boundary
                    shifted[injection_window + 1]["core_duration_sec"] = shifted[injection_window + 1]["core_end_sec"] - boundary
                    active_plan = {**frozen_plan, "windows": shifted, "injected_core_boundary": {"window_index": injection_window, "delta_sec": value}}
                try:
                    rows, injected_trace = SERIAL.windowed_alignment(
                        processor, model, audio, document, serial_args(args, plan=active_plan, injections=injections),
                    )
                    predict = candidate_record(f"{kind}_{value:+}", rows, gt)
                    predict["causal_effect"] = causal_effect(canonical_rows(baseline_rows), canonical_rows(rows), gt, intervention_time_sec=intervention_time)
                    status = "complete"
                except Exception as exc:
                    predict = {"error": f"{type(exc).__name__}: {exc}"}; injected_trace = []; status = "failed"; rows = []
                resets = {}
                if gt and injection_window + 1 < len(windows):
                    reset_time = float(windows[injection_window + 1]["input_start_sec"])
                    reset_cursor = gt_cursor(gt, reset_time, len(document.characters))
                    preceding = [row for row in gt if float(row["end_sec"]) <= reset_time + 1e-9]
                    reset_end = max((float(row["end_sec"]) for row in preceding), default=0.0)
                    reset_variants = {
                        "text_reset": [{"window_index": injection_window + 1, "kind": "cursor_set", "value": reset_cursor}],
                        "time_reset": [{"window_index": injection_window + 1, "kind": "previous_end_set", "value": reset_end}],
                        "full_reset": [
                            {"window_index": injection_window + 1, "kind": "cursor_set", "value": reset_cursor},
                            {"window_index": injection_window + 1, "kind": "previous_end_set", "value": reset_end},
                        ],
                    }
                    for reset_name, reset_tail in reset_variants.items():
                        try:
                            reset_rows, reset_trace = SERIAL.windowed_alignment(
                                processor, model, audio, document, serial_args(args, plan=active_plan, injections=injections + reset_tail),
                            )
                            reset_record = candidate_record(f"{kind}_{value:+}_{reset_name}", reset_rows, gt)
                            reset_record["causal_effect"] = causal_effect(canonical_rows(baseline_rows), canonical_rows(reset_rows), gt, intervention_time_sec=reset_time)
                            if rows:
                                reset_record["recovery_vs_injected"] = metric_delta(
                                    reset_record["causal_effect"].get("changed_post_metrics"),
                                    predict["causal_effect"].get("changed_post_metrics"),
                                )
                            reset_record["completed_window_count"] = len(reset_trace)
                            resets[reset_name] = reset_record
                        except Exception as exc:
                            resets[reset_name] = {"error": f"{type(exc).__name__}: {exc}"}
                records.append({
                    "kind": kind, "value": value, "window_index": injection_window,
                    "intervention_time_sec": intervention_time,
                    "status": status, "predict_state": predict, "resets": resets,
                    "completed_window_count": len(injected_trace),
                })
            payload = {
                "schema_version": "E7_serial_propagation_v2", "frozen_plan": frozen_plan,
                "applicable": True, "records": records,
                "_phase_summary": {
                    "record_count": len(records), "applicable": True,
                    "complete_count": sum(row["status"] == "complete" for row in records),
                },
            }
        atomic_json(item_root / "E7_serial_propagation.json", payload)
        summary["phases"]["E7"] = payload["_phase_summary"]

    if "E8" in phases:
        if processor is None or model is None or detector_report is None:
            raise RuntimeError("E8 requires model and detector")
        if audio_profile is None:
            audio_profile = build_audio_profile(audio)
        risk_spans = detector_report["risk_spans"]
        cases = []
        baseline_canonical = canonical_rows(baseline_rows)
        baseline_full_metrics = strip_metric_details(alignment_metrics(baseline_canonical, gt)) if gt else None
        for case_index, span in enumerate(risk_spans):
            start_index = int(span["character_start"]); end_index = int(span["character_end"])
            target_indices = list(range(start_index, end_index + 1))
            left = max(0, start_index - args.realign_context_units)
            right = min(len(document.characters), end_index + 1 + args.realign_context_units)
            baseline_by = {int(row["global_character_index"]): row for row in baseline_rows}
            if left not in baseline_by or right - 1 not in baseline_by:
                continue
            request = AlignmentRequest(
                item_id,
                max(0.0, float(baseline_by[left]["fixed_global_start_sec"]) - 0.5),
                min(duration_sec, float(baseline_by[right - 1]["fixed_global_end_sec"]) + 0.5),
                left, right, request_role="detector_realign", metadata={"target_span": [start_index, end_index]},
            )
            local = run_request(request=request, spec=None, audio=audio, document=document, processor=processor, model=model, args=args)
            alternate_left = max(0, left - args.realign_context_units)
            alternate_right = min(len(document.characters), right + args.realign_context_units)
            alternate_request = AlignmentRequest(
                item_id,
                max(0.0, float(baseline_by[alternate_left]["fixed_global_start_sec"]) - 0.75),
                min(duration_sec, float(baseline_by[alternate_right - 1]["fixed_global_end_sec"]) + 0.75),
                alternate_left, alternate_right, request_role="detector_realign_alternate_context",
                metadata={"target_span": [start_index, end_index], "alternate_of": request.to_dict()},
            )
            alternate_local = run_request(request=alternate_request, spec=None, audio=audio, document=document, processor=processor, model=model, args=args)
            candidate_inputs = {
                "raw": (local, "primary", "raw"),
                "official": (local, "primary", "official"),
                "joint_start_end": (local, "primary", "joint_start_end"),
                "topk_sequence": (local, "primary", "topk_sequence"),
                "alternate_official": (alternate_local, "alternate_context", "official"),
                "alternate_topk_sequence": (alternate_local, "alternate_context", "topk_sequence"),
            }
            candidates = {}
            case_root = item_root / "realign_cases" / f"case_{case_index:04d}"
            target_gt = select_gt_rows(gt, indices=target_indices) if gt else []
            baseline_target_metrics = strip_metric_details(alignment_metrics(baseline_canonical, target_gt)) if target_gt else None
            baseline_target_full = alignment_metrics(baseline_canonical, target_gt) if target_gt else None
            baseline_target_clean = None if baseline_target_full is None else (
                float(baseline_target_full.get("coverage") or 0.0) >= 1.0 - 1e-12
                and all(
                    float(row["max_abs_error_sec"]) <= args.detector_tolerance_sec
                    for row in baseline_target_full["details"]
                )
            )
            downstream_gt = select_gt_rows(gt, start_index=end_index + 1) if gt else []
            baseline_downstream_metrics = strip_metric_details(alignment_metrics(baseline_canonical, downstream_gt)) if downstream_gt else None
            for name, (input_rows, input_variant, decoder_name) in candidate_inputs.items():
                rows = decode_rows(input_rows, DecoderConfig(
                    name=decoder_name, top_k=args.decoder_top_k, beam_size=args.decoder_beam_size,
                    timestamp_step_sec=args.timestamp_segment_sec,
                ))
                static_spliced_rows = splice_local_candidate(baseline_rows, rows, start_index, end_index)
                propagation_error = None
                continuation_trace: list[dict[str, Any]] = []
                candidate_serial_trace: list[dict[str, Any]] = []
                continuation_metadata: dict[str, Any]
                try:
                    full_rows, continuation_trace, continuation_metadata = propagate_realign_candidate(
                        seed_rows=static_spliced_rows,
                        target_end_index=end_index,
                        trace=trace,
                        processor=processor,
                        model=model,
                        audio=audio,
                        document=document,
                        args=args,
                    )
                    _, non_silent_source_trace = frozen_plan_from_trace(
                        trace, policy="E8_candidate_trace_materialization_v1",
                    )
                    source_position = int(continuation_metadata["source_window_position"])
                    candidate_serial_trace = (
                        non_silent_source_trace[:source_position] + continuation_trace
                    )
                except Exception as exc:
                    # Preserve the candidate and local evidence even when its
                    # serial continuation fails.  It remains visible but is not
                    # eligible for automatic selection.
                    full_rows = static_spliced_rows
                    propagation_error = f"{type(exc).__name__}: {exc}"
                    continuation_metadata = {
                        "status": "failed",
                        "error": propagation_error,
                        "rerun_window_count": 0,
                    }
                full_support = support_for_rows(canonical_rows(full_rows), audio_profile)
                continuation_inputs, continuation_windows, continuation_cursor = (
                    detector_context_from_trace(candidate_serial_trace)
                    if candidate_serial_trace else ([], [], {})
                )
                candidate_detector = inspect_alignment(
                    full_rows,
                    config=DetectorConfig(cross_input_tolerance_sec=args.detector_tolerance_sec),
                    # A repaired candidate is judged using evidence generated by
                    # its own serial continuation. Divergence from the baseline
                    # is not itself risk.
                    input_candidates=[canonical_rows(full_rows)] + continuation_inputs,
                    window_candidates=continuation_windows,
                    audio_support_by_index=full_support,
                    cursor_disagreement_by_index=continuation_cursor,
                    risk_model=args.frozen_detector_model,
                    active_threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
                    active_safe_threshold=args.detector_safe_threshold,
                active_safe_boundary_score_threshold=getattr(args, "dynamic_safe_score", 0.25),
                detector_name=args.selected_detector_name,
                )
                selection_components = detector_selection_components(candidate_detector)
                propagated_downstream_metrics = (
                    strip_metric_details(alignment_metrics(full_rows, downstream_gt))
                    if downstream_gt and propagation_error is None else None
                )
                static_downstream_metrics = (
                    strip_metric_details(alignment_metrics(static_spliced_rows, downstream_gt))
                    if downstream_gt else None
                )
                record = candidate_record(
                    name, rows, gt, metric_indices=target_indices, metric_scope="detector_target_span",
                    spliced_rows=(full_rows if propagation_error is None else None),
                    baseline_rows=(baseline_rows if propagation_error is None else None),
                    extra={
                        "request_variant": input_variant,
                        "decoder_name": decoder_name,
                        "detector_selection_score": detector_selection_score(candidate_detector),
                        "detector_selection_components": selection_components,
                        "eligible_for_selection": propagation_error is None,
                        "propagation": continuation_metadata,
                        "continuation_trace": continuation_trace,
                        "serial_trace_prefix_window_count": max(
                            0, len(candidate_serial_trace) - len(continuation_trace)
                        ),
                        "post_propagation_risk_span_count": len(candidate_detector["risk_spans"]),
                        "post_propagation_risk_spans": candidate_detector["risk_spans"],
                        "static_splice_full_metrics": (
                            strip_metric_details(alignment_metrics(static_spliced_rows, gt)) if gt else None
                        ),
                        "static_splice_downstream_metrics": static_downstream_metrics,
                        "downstream_metrics": propagated_downstream_metrics,
                        "downstream_delta_vs_baseline": metric_delta(
                            propagated_downstream_metrics,
                            baseline_downstream_metrics,
                        ),
                        "downstream_delta_vs_static_splice": metric_delta(
                            propagated_downstream_metrics,
                            static_downstream_metrics,
                        ),
                    },
                )
                candidates[name] = record
                write_alignment(
                    case_root / name / "alignment.json", baseline=baseline,
                    name=f"E8_case_{case_index:04d}_{name}", rows=full_rows, gt=gt,
                    metadata={
                        "phase": "E8", "case_index": case_index,
                        "target_span": [start_index, end_index],
                        "request": request.to_dict(),
                        "propagation_status": continuation_metadata.get("status"),
                        "alignment_content": (
                            "serial_continuation" if propagation_error is None
                            else "static_splice_diagnostic_after_continuation_failure"
                        ),
                    },
                    window_trace=candidate_serial_trace, compact_artifacts=args.compact_artifacts,
                )
            eligible_candidates = {
                key: value for key, value in candidates.items()
                if value.get("eligible_for_selection")
            }
            selected_name = min(
                eligible_candidates,
                key=lambda key: (
                    detector_selection_key(eligible_candidates[key]["detector_selection_components"]),
                    key,
                ),
            ) if eligible_candidates else None
            oracle_name = None
            if gt and eligible_candidates:
                oracle_name = min(
                    eligible_candidates,
                    key=lambda key: (
                        float(eligible_candidates[key]["spliced_full_metrics"]["all_penalized_boundary_mae_sec"]),
                        -float(eligible_candidates[key]["spliced_full_metrics"].get("coverage") or 0.0),
                        key,
                    ),
                )
            selected = candidates.get(selected_name) if selected_name else None
            selected_delta = None if selected is None else selected.get("spliced_delta_vs_baseline")
            selected_improved = None
            clean_harm = None
            if selected_delta and selected_delta.get("all_penalized_boundary_mae_sec") is not None:
                delta = float(selected_delta["all_penalized_boundary_mae_sec"])
                selected_improved = delta < -1e-12
                clean_harm = delta > 1e-12
            cases.append({
                "case_index": case_index, "span": span, "target_indices": target_indices,
                "request": request.to_dict(), "alternate_request": alternate_request.to_dict(),
                "case_root": str(case_root),
                "baseline_target_metrics": baseline_target_metrics,
                "baseline_target_clean": baseline_target_clean,
                "baseline_full_metrics": baseline_full_metrics, "candidates": candidates,
                "selection": {
                    "selected_candidate": selected_name, "oracle_candidate": oracle_name,
                    "selected_matches_oracle": None if oracle_name is None else selected_name == oracle_name,
                    "selected_improved_full_mae": selected_improved,
                    "selected_harm_full_mae": clean_harm,
                    "selected_clean_harm": clean_harm if baseline_target_clean is True else None,
                },
            })
            if args.max_realign_cases_per_item > 0 and len(cases) >= args.max_realign_cases_per_item:
                break
        payload = {
            "schema_version": "E8_realign_v4_success_conditioned_serial_continuation",
            "detector": {
                "selected_detector": detector_report["selected_detector"],
                "active_score_key": detector_report["active_score_key"],
                "active_risk_threshold": detector_report["active_risk_threshold"],
            },
            "cases": cases,
            "_phase_summary": {
                "case_count": len(cases),
                "candidate_propagation_failure_count": sum(
                    candidate.get("propagation", {}).get("status") == "failed"
                    for row in cases for candidate in row["candidates"].values()
                ),
                "candidate_propagation_complete_count": sum(
                    candidate.get("propagation", {}).get("status") == "complete"
                    for row in cases for candidate in row["candidates"].values()
                ),
                "selected_improvement_count": sum(row["selection"].get("selected_improved_full_mae") is True for row in cases),
                "selected_clean_harm_count": sum(row["selection"].get("selected_clean_harm") is True for row in cases),
                "oracle_match_count": sum(row["selection"].get("selected_matches_oracle") is True for row in cases),
            },
        }
        atomic_json(
            item_root / "E8_realign.json",
            compact_e8_payload(payload) if args.compact_artifacts else payload,
        )
        summary["phases"]["E8"] = payload["_phase_summary"]

    if "E9" in phases:
        if processor is None or model is None:
            raise RuntimeError("E9 actual cursor/window beam requires model inference")
        if audio_profile is None:
            audio_profile = build_audio_profile(audio)
        beam_result = run_cursor_window_beam(
            baseline_rows=baseline_rows,
            baseline_trace=trace,
            processor=processor,
            model=model,
            audio=audio,
            document=document,
            audio_profile=audio_profile,
            args=args,
        )
        final_records = []
        serializable_final_states = []
        baseline_full = strip_metric_details(alignment_metrics(canonical_rows(baseline_rows), gt)) if gt else None
        for rank, state in enumerate(beam_result["final_states"], start=1):
            rows = canonical_rows(state["committed_rows"])
            metrics = strip_metric_details(alignment_metrics(rows, gt)) if gt else None
            record = {
                "rank": rank,
                "path_id": state["path_id"],
                "complete": int(state["committed_cursor"]) == len(document.characters),
                "committed_cursor": int(state["committed_cursor"]),
                "input_cursor": int(state["input_cursor"]),
                "rank_key": state.get("rank_key"),
                "cumulative": state["cumulative"],
                "path": state["path"],
                "metrics": metrics,
                "delta_vs_baseline": metric_delta(metrics, baseline_full),
            }
            final_records.append(record)
            serializable_final_states.append(record)
            write_alignment(
                item_root / "E9_beam" / f"rank_{rank:02d}" / "alignment.json",
                baseline=baseline,
                name=f"E9_beam_rank_{rank:02d}",
                rows=rows,
                gt=gt,
                metadata={
                    "phase": "E9", "path_id": state["path_id"], "rank": rank,
                    "beam_path": state["path"],
                },
                window_trace=[], compact_artifacts=args.compact_artifacts,
            )
        selected = final_records[0] if final_records else None
        oracle_rank = None
        if gt and final_records:
            oracle = min(
                final_records,
                key=lambda row: (
                    float((row.get("metrics") or {}).get("all_penalized_boundary_mae_sec", math.inf)),
                    -float((row.get("metrics") or {}).get("coverage") or 0.0),
                    int(row["rank"]),
                ),
            )
            oracle_rank = int(oracle["rank"])
        line_spans = independent_line_localization(document, audio_profile, duration_sec)
        line_metrics = line_localization_metrics(line_spans, document, gt)
        payload = {
            "schema_version": "E9_system_pilots_v3_actual_cross_window_beam",
            "applicability": {
                "applicable": not bool(beam_result.get("not_applicable", False)),
                "reason": beam_result.get("not_applicable_reason"),
            },
            "cursor_window_beam": {
                key: value for key, value in beam_result.items()
                if key not in {"final_states", "selected_state"}
            },
            "final_hypotheses": serializable_final_states,
            "cursor_window_beam_summary": {
                "window_count": len(beam_result["window_records"]),
                "beam_width": beam_result["beam_width"],
                "multi_hypothesis_window_count": beam_result["multi_hypothesis_window_count"],
                "fallback_window_count": beam_result["fallback_window_count"],
                "final_hypothesis_count": len(final_records),
                "complete_final_hypothesis_count": sum(row["complete"] for row in final_records),
                "selected_complete": None if selected is None else selected["complete"],
                "selected_path_id": None if selected is None else selected["path_id"],
                "selected_metrics": None if selected is None else selected["metrics"],
                "selected_delta_vs_baseline": None if selected is None else selected["delta_vs_baseline"],
                "final_beam_oracle_rank": oracle_rank,
                "selected_matches_final_beam_oracle": None if oracle_rank is None else oracle_rank == 1,
            },
            "line_level_coarse_localization": line_spans,
            "line_level_metrics": line_metrics,
            "line_localizer_independent_of_character_alignment": True,
            "_phase_summary": {
                "applicable": not bool(beam_result.get("not_applicable", False)),
                "not_applicable_reason": beam_result.get("not_applicable_reason"),
                "beam_window_count": len(beam_result["window_records"]),
                "beam_width": beam_result["beam_width"],
                "multi_hypothesis_window_count": beam_result["multi_hypothesis_window_count"],
                "fallback_window_count": beam_result["fallback_window_count"],
                "selected_complete": None if selected is None else selected["complete"],
                "selected_delta_mae_sec": None if selected is None else (selected.get("delta_vs_baseline") or {}).get("all_penalized_boundary_mae_sec"),
                "selected_matches_final_beam_oracle": None if oracle_rank is None else oracle_rank == 1,
                "line_count": len(line_spans),
                "line_boundary_mae_sec": line_metrics.get("boundary_mae_sec"),
            },
        }
        atomic_json(item_root / "E9_system_pilots.json", payload)
        summary["phases"]["E9"] = payload["_phase_summary"]

    summary["inference_cache"] = dict(args._research_cache_stats)
    summary["serial_inference_cache"] = dict(args._research_serial_cache_stats)
    summary["identity"] = {
        "baseline_sha256": sha256(baseline_file),
        "lyrics_sha256": sha256(lyrics_path),
        "audio_path": str(audio_path),
        "gt_path": item.get("gt_path"),
        "request_hash": canonical_hash({
            "item": item, "phases": sorted(requested_phases), "mode": args.mode,
            "parameters": {
                key: (sorted(value) if isinstance(value, set) else str(value) if isinstance(value, Path) else value)
                for key, value in vars(args).items()
                if key not in {"frozen_detector_model", "frozen_payload"} and not key.startswith("_")
            },
        }),
    }
    atomic_json(item_root / "item_summary.json", summary)
    if args.compact_artifacts:
        # Inference cache is useful only during the current item; every entry
        # is deterministically regenerable and must not accumulate over formal.
        for cache_root in (args._research_cache_root, args._research_serial_cache_root):
            if cache_root.is_dir():
                for cache_file in cache_root.glob("*.json"):
                    cache_file.unlink()
                cache_root.rmdir()
    cleanup_item_audio(audio_path, lazy_audio_owned)
    return summary


def _mean(values: Iterable[Any]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return statistics.fmean(usable) if usable else None


def summarize_e8_downstream_effects(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if row.get("propagation_status") == "complete"]
    return {
        "candidate_propagation_complete_count": len(complete),
        "candidate_propagation_failure_count": sum(
            row.get("propagation_status") == "failed" for row in rows
        ),
        "downstream_effect_conditioning": "propagation_status == complete",
        "downstream_mae_delta_mean_sec": _mean(
            row.get("downstream_mae_delta") for row in complete
        ),
        "downstream_coverage_delta_mean": _mean(
            row.get("downstream_coverage_delta") for row in complete
        ),
    }


def _detector_group_split(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("source_song_id") or row.get("item_id")), []).append(row)
    keys = sorted(groups, key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
    if len(keys) < 2:
        # A single-song smoke/pilot cannot form a leakage-free split.  Continue
        # with an explicitly degraded overlapping fit/calibration set so the
        # pipeline can still produce a final, lower-evidence result.
        only = [row for key in keys for row in groups[key]]
        return only, only, {
            "split_unit": "source_song_id",
            "train_group_count": len(keys),
            "calibration_group_count": len(keys),
            "train_unit_count": len(only),
            "calibration_unit_count": len(only),
            "calibration_group_ids": keys,
            "degraded": True,
            "degraded_reason": "fewer_than_two_source_song_groups; fit and calibration overlap",
        }
    calibration_count = max(1, int(round(0.30 * len(keys))))
    calibration_keys = set(keys[-calibration_count:])
    train = [row for key in keys if key not in calibration_keys for row in groups[key]]
    calibration = [row for key in keys if key in calibration_keys for row in groups[key]]
    return train, calibration, {
        "split_unit": "source_song_id", "train_group_count": len(keys) - calibration_count,
        "calibration_group_count": calibration_count,
        "train_unit_count": len(train), "calibration_unit_count": len(calibration),
        "calibration_group_ids": sorted(calibration_keys),
    }


def _cluster_bootstrap_detector(
    rows: list[dict[str, Any]], *, score_key: str, label_key: str, threshold: float,
    samples: int = 1000, seed: int = 20260731,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get(label_key) is not None:
            grouped[str(row.get("source_song_id") or row.get("item_id"))].append(row)
    keys = sorted(grouped)
    if not keys:
        return {"cluster_count": 0, "unit_count": 0}
    point = binary_metrics(rows, score_key=score_key, label_key=label_key, threshold=threshold)
    if len(keys) == 1 or samples <= 0:
        return {"cluster_count": len(keys), "unit_count": sum(len(grouped[key]) for key in keys), "point": point, "ci95": {}}
    import random
    rng = random.Random(seed)
    estimates: dict[str, list[float]] = defaultdict(list)
    for _ in range(int(samples)):
        draw = [key for _ in keys for key in [keys[rng.randrange(len(keys))]]]
        sampled = [dict(row) for key in draw for row in grouped[key]]
        metrics = binary_metrics(sampled, score_key=score_key, label_key=label_key, threshold=threshold)
        for metric in ("precision", "recall", "f1", "false_positive_rate"):
            if metrics.get(metric) is not None:
                estimates[metric].append(float(metrics[metric]))
    ci95 = {}
    for metric, values in estimates.items():
        values.sort()
        ci95[metric] = [
            values[max(0, int(0.025 * len(values)) - 1)],
            values[min(len(values) - 1, int(0.975 * len(values)))],
        ]
    return {
        "cluster_count": len(keys), "unit_count": sum(len(grouped[key]) for key in keys),
        "point": point, "ci95": ci95, "bootstrap_samples": samples, "seed": seed,
        "cluster_key": "source_song_id",
    }


def aggregate(args: argparse.Namespace, items: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    decoder_items: list[dict[str, Any]] = []
    detector_rows: list[dict[str, Any]] = []
    phase_payloads: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {phase: [] for phase in PHASES[2:]}
    for item in items:
        metadata = {
            "item_id": item["item_id"], "dataset": item.get("dataset"), "profile": item.get("profile"),
            "split": item.get("split"), "selection_role": item.get("selection_role"),
            "training_exposure": item.get("training_exposure"),
            "source_song_id": item.get("source_song_id") or item["item_id"],
            "synthetic": item.get("synthetic"),
        }
        for candidate in item.get("phases", {}).get("E0", {}).get("candidates", []):
            if candidate.get("metrics"):
                decoder_items.append({
                    **metadata, "decoder": candidate["name"], "metrics": candidate["metrics"],
                    "structural": candidate.get("structural") or {},
                    "seam": candidate.get("seam_stratified_metrics"),
                    "paired_transition_from_raw": candidate.get("paired_transition_from_raw"),
                })
        detector_path = args.out_root / "items" / item["item_id"] / "E1_detector.json"
        if detector_path.is_file():
            detector_payload = json.loads(detector_path.read_text(encoding="utf-8"))
            for row in detector_payload.get("features", []):
                if row.get("gt_error") is not None:
                    detector_rows.append({**row, **metadata})
        filenames = {
            "E2": "E2_corruptions.json", "E3": "E3_decoder_hybrid.json",
            "E4": "E4_text_budget_and_chunks.json", "E5": "E5_dynamic_windows.json",
            "E6": "E6_silence.json", "E7": "E7_serial_propagation.json",
            "E8": "E8_realign.json", "E9": "E9_system_pilots.json",
        }
        for phase, filename in filenames.items():
            path = args.out_root / "items" / item["item_id"] / filename
            if path.is_file():
                phase_payloads[phase].append((metadata, json.loads(path.read_text(encoding="utf-8"))))

    decoder_groups: dict[str, Any] = {}
    for name in DECODER_NAMES:
        rows = [row for row in decoder_items if row["decoder"] == name]
        seam_near = [{**row, "metrics": row["seam"]["near"]} for row in rows if row.get("seam") and row["seam"].get("near")]
        seam_far = [{**row, "metrics": row["seam"]["far"]} for row in rows if row.get("seam") and row["seam"].get("far")]
        decoder_groups[name] = {
            "all": aggregate_item_metrics(rows),
            "main_generalization_nontraining": aggregate_item_metrics(
                [row for row in rows if not bool(row.get("training_exposure"))]
            ),
            "by_dataset": grouped_aggregate(rows, ["dataset"]),
            "by_dataset_split": grouped_aggregate(rows, ["dataset", "split"]),
            "by_selection_role": grouped_aggregate(rows, ["dataset", "selection_role"]),
            "by_training_exposure": grouped_aggregate(rows, ["training_exposure"]),
            "source_song_cluster_bootstrap": clustered_bootstrap_macro(rows, cluster_key="source_song_id"),
            "seam_near": aggregate_item_metrics(seam_near),
            "seam_far": aggregate_item_metrics(seam_far),
            "paired_transition_from_raw": {
                "raw_correct_harm_rate_macro": _mean(
                    (row.get("paired_transition_from_raw") or {}).get("raw_correct_harm_rate") for row in rows
                ),
                "raw_error_repair_rate_macro": _mean(
                    (row.get("paired_transition_from_raw") or {}).get("raw_error_repair_rate") for row in rows
                ),
                "movement_mean_sec_macro": _mean(
                    (row.get("paired_transition_from_raw") or {}).get("movement_mean_sec") for row in rows
                ),
            },
            "structural_macro": {
                key: _mean((row.get("structural") or {}).get(key) for row in rows)
                for key in (
                    "negative_duration_count", "zero_duration_count",
                    "inter_unit_overlap_count", "start_regression_count", "invalid_interval_count",
                )
            },
        }

    detector_summary: dict[str, Any] = {"labelled_unit_count": len(detector_rows)}
    models_payload: dict[str, Any] = {}
    if detector_rows and args.mode == "pilot":
        train_rows, calibration_rows, split_summary = _detector_group_split(detector_rows)
        logistic = LogisticRiskModel.fit(train_rows)
        stump = StumpBoostRiskModel.fit(train_rows)
        for row in train_rows + calibration_rows:
            row["logistic_score"] = logistic.predict_score(row)
            row["stump_score"] = stump.predict_score(row)
        detector_summary.update({
            "data_split": split_summary,
            "rule_threshold_curve": threshold_curve(calibration_rows, score_key="rule_risk_score"),
            "logistic_threshold_curve": threshold_curve(calibration_rows, score_key="logistic_score"),
            "stump_threshold_curve": threshold_curve(calibration_rows, score_key="stump_score"),
            "rule_event_threshold_curve": event_threshold_curve(calibration_rows, score_key="rule_risk_score"),
            "logistic_event_threshold_curve": event_threshold_curve(calibration_rows, score_key="logistic_score"),
            "stump_event_threshold_curve": event_threshold_curve(calibration_rows, score_key="stump_score"),
            "rule_repairable_threshold_curve": threshold_curve(calibration_rows, score_key="rule_risk_score", label_key="gt_repairable"),
            "logistic_repairable_threshold_curve": threshold_curve(calibration_rows, score_key="logistic_score", label_key="gt_repairable"),
            "stump_repairable_threshold_curve": threshold_curve(calibration_rows, score_key="stump_score", label_key="gt_repairable"),
            "safe_boundary_threshold_curve": threshold_curve(calibration_rows, score_key="safe_boundary_decision_score", label_key="gt_safe_boundary"),
            "train_diagnostics": {
                "rule": threshold_curve(train_rows, score_key="rule_risk_score"),
                "logistic": threshold_curve(train_rows, score_key="logistic_score"),
                "stump": threshold_curve(train_rows, score_key="stump_score"),
            },
        })
        models_payload = {"logistic": logistic.to_dict(), "stump_boost": stump.to_dict()}
        atomic_json(args.out_root / "detector_models.json", {
            "schema_version": "detector_models_bundle_v2", "training_split": split_summary, **models_payload,
        })
    elif detector_rows:
        detector_summary["formal_evaluation"] = {
            "selected_detector": args.selected_detector_name,
            "active_score_key": "learned_risk_score" if args.frozen_detector_model is not None else "rule_risk_score",
            "fixed_threshold": args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold,
            "binary_metrics": binary_metrics(
                detector_rows, score_key=("learned_risk_score" if args.frozen_detector_model is not None else "rule_risk_score"),
                label_key="gt_error", threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
            ),
            "event_metrics": event_metrics(
                detector_rows, score_key=("learned_risk_score" if args.frozen_detector_model is not None else "rule_risk_score"),
                label_key="gt_error", threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
            ),
            "repairable_binary_metrics": binary_metrics(
                detector_rows, score_key=("learned_risk_score" if args.frozen_detector_model is not None else "rule_risk_score"),
                label_key="gt_repairable", threshold=args.repairable_score_threshold,
            ),
            "safe_boundary_binary_metrics": binary_metrics(
                detector_rows, score_key="safe_boundary_decision_score", label_key="gt_safe_boundary",
                threshold=args.dynamic_safe_score,
            ),
            "source_song_cluster_bootstrap": _cluster_bootstrap_detector(
                detector_rows,
                score_key=("learned_risk_score" if args.frozen_detector_model is not None else "rule_risk_score"),
                label_key="gt_error",
                threshold=(args.detector_model_threshold if args.frozen_detector_model is not None else args.detector_risk_threshold),
            ),
            "threshold_curve_diagnostic_only_not_for_selection": threshold_curve(
                detector_rows, score_key=("learned_risk_score" if args.frozen_detector_model is not None else "rule_risk_score")
            ),
        }

    experiment_summary: dict[str, Any] = {}
    # E2 corruption detection and local alignment, grouped by corruption type.
    e2_rows = []
    for metadata, payload in phase_payloads["E2"]:
        for record in payload.get("records", []):
            e2_rows.append({**metadata, "category": record["corruption"]["category"], "name": record["corruption"]["name"], "metrics": record["candidate"].get("metrics"), "detector": record.get("detector", {})})
    experiment_summary["E2"] = {
        "record_count": len(e2_rows),
        "alignment_by_category": grouped_aggregate(e2_rows, ["category"]),
        "alignment_by_corruption": grouped_aggregate(e2_rows, ["category", "name"]),
        "detector_micro": {
            key: sum(int((row.get("detector", {}).get("binary_metrics") or {}).get(key, 0)) for row in e2_rows)
            for key in ("tp", "fp", "fn", "tn")
        },
        "event_micro": {
            key: sum(int((row.get("detector", {}).get("event_metrics") or {}).get(key, 0)) for row in e2_rows)
            for key in ("tp", "fp", "fn")
        },
        "clean_risk_span_mean": _mean(row.get("detector", {}).get("clean_risk_span_count") for row in e2_rows),
    }
    counts = experiment_summary["E2"]["detector_micro"]
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    experiment_summary["E2"]["detector_micro"].update({"precision": precision, "recall": recall, "f1": None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)})
    event_counts = experiment_summary["E2"]["event_micro"]
    event_precision = event_counts["tp"] / (event_counts["tp"] + event_counts["fp"]) if event_counts["tp"] + event_counts["fp"] else None
    event_recall = event_counts["tp"] / (event_counts["tp"] + event_counts["fn"]) if event_counts["tp"] + event_counts["fn"] else None
    experiment_summary["E2"]["event_micro"].update({
        "precision": event_precision, "recall": event_recall,
        "f1": None if event_precision is None or event_recall is None or event_precision + event_recall == 0 else 2 * event_precision * event_recall / (event_precision + event_recall),
    })

    e3_rows = []
    for metadata, payload in phase_payloads["E3"]:
        for record in payload.get("records", []):
            for candidate in record.get("candidates", []):
                e3_rows.append({**metadata, "span_source": record["span_source"], "method": candidate["name"], "metrics": candidate.get("metrics")})
    experiment_summary["E3"] = {"candidate_count": len(e3_rows), "by_span_source_method": grouped_aggregate(e3_rows, ["span_source", "method"])}

    e4_budget = []; e4_selectors: dict[str, list[dict[str, Any]]] = defaultdict(list); e4_chunks = []
    for metadata, payload in phase_payloads["E4"]:
        for case in payload.get("budget_cases", []):
            for candidate in case.get("candidates", []):
                e4_budget.append({**metadata, "amount_ratio": candidate.get("amount_ratio_vs_baseline"), "coverage_relation": candidate.get("coverage_relation"), "metrics": candidate["candidate"].get("metrics")})
            for selector, selected in (case.get("selection_results") or {}).items():
                if selected and selected.get("metrics"):
                    e4_selectors[selector].append({**metadata, "metrics": selected["metrics"]})
        for case in payload.get("chunk_cases", []):
            whole = case.get("whole") or {}
            if whole.get("metrics"):
                e4_chunks.append({**metadata, "method": "1x96", "metrics": whole["metrics"], "calls": 1, "rtf": (whole.get("inference") or {}).get("rtf")})
            for overlap, candidate in (case.get("chunks") or {}).items():
                e4_chunks.append({**metadata, "method": f"3x32_overlap_{overlap}", "metrics": candidate.get("metrics"), "calls": (candidate.get("inference") or {}).get("call_count"), "rtf": (candidate.get("inference") or {}).get("rtf")})
    experiment_summary["E4"] = {
        "budget_by_ratio_and_relation": grouped_aggregate(e4_budget, ["amount_ratio", "coverage_relation"]),
        "selectors": {name: aggregate_item_metrics(rows) for name, rows in e4_selectors.items()},
        "chunks": grouped_aggregate(e4_chunks, ["method"]),
        "chunk_cost": {method: {"mean_calls": _mean(row.get("calls") for row in e4_chunks if row["method"] == method), "mean_rtf": _mean(row.get("rtf") for row in e4_chunks if row["method"] == method)} for method in sorted({row["method"] for row in e4_chunks})},
    }

    serial_phase_rows: dict[str, list[dict[str, Any]]] = {"E5": [], "E6": []}
    silence_boundary_rows: list[dict[str, Any]] = []
    for phase, variant_key in (("E5", "variants"), ("E6", "variants")):
        rows = serial_phase_rows[phase]
        for metadata, phase_payload in phase_payloads[phase]:
            for candidate in phase_payload.get(variant_key, []):
                serial = candidate.get("serial_diagnostics") or {}
                failure = serial.get("first_failure_recovery") or {}
                seam = serial.get("seam_metrics") or {}
                rows.append({
                    **metadata, "variant": candidate["name"], "metrics": candidate.get("metrics"),
                    "cursor_mae": serial.get("cursor_distance_mean_abs_units"),
                    "cursor_max": serial.get("cursor_distance_max_abs_units"),
                    "missing": serial.get("missing_unit_count"),
                    "extra": serial.get("prediction_extra_unit_count"),
                    "first_failure_index": failure.get("first_failure_character_index"),
                    "recovery_distance": failure.get("recovery_character_distance"),
                    "persistent_failure": failure.get("persistent_failure"),
                    "seam_near_mae": ((seam.get("near") or {}).get("all_penalized_boundary_mae_sec")),
                    "seam_far_mae": ((seam.get("far") or {}).get("all_penalized_boundary_mae_sec")),
                    "boundary_movement_mean_abs_sec": candidate.get("boundary_movement_mean_abs_sec"),
                    "nominal_fallback_count": candidate.get("nominal_fallback_count"),
                    "planned_cursor_application_count": candidate.get("planned_cursor_application_count"),
                    "applicable": phase_payload.get("applicable", True),
                })
                if phase == "E6":
                    boundary_report = candidate.get("silence_boundary_diagnostics") or {}
                    for boundary in boundary_report.get("boundaries", []):
                        duration = float(boundary.get("duration_sec", 0.0))
                        if duration < 1.5:
                            duration_bin = "0.8_to_1.5s"
                        elif duration < 4.0:
                            duration_bin = "1.5_to_4s"
                        elif duration < 10.0:
                            duration_bin = "4_to_10s"
                        else:
                            duration_bin = "10s_plus"
                        silence_boundary_rows.append({
                            **metadata, "variant": candidate["name"], "duration_bin": duration_bin,
                            "duration_sec": duration,
                            "before_mae": (boundary.get("before") or {}).get("boundary_mae_sec"),
                            "after_mae": (boundary.get("after") or {}).get("boundary_mae_sec"),
                            "before_missing": (boundary.get("before") or {}).get("missing"),
                            "after_missing": (boundary.get("after") or {}).get("missing"),
                        })
        variants = sorted({row["variant"] for row in rows})
        experiment_summary[phase] = {
            "by_variant": grouped_aggregate(rows, ["variant"]),
            "serial_diagnostics_by_variant": {
                name: {
                    "cursor_distance_mean_abs_units": _mean(row.get("cursor_mae") for row in rows if row["variant"] == name),
                    "cursor_distance_max_abs_units_mean": _mean(row.get("cursor_max") for row in rows if row["variant"] == name),
                    "missing_unit_count_mean": _mean(row.get("missing") for row in rows if row["variant"] == name),
                    "extra_unit_count_mean": _mean(row.get("extra") for row in rows if row["variant"] == name),
                    "recovery_character_distance_mean": _mean(row.get("recovery_distance") for row in rows if row["variant"] == name),
                    "persistent_failure_rate": _mean(float(row["persistent_failure"]) for row in rows if row["variant"] == name and row.get("persistent_failure") is not None),
                    "seam_near_mae_sec": _mean(row.get("seam_near_mae") for row in rows if row["variant"] == name),
                    "seam_far_mae_sec": _mean(row.get("seam_far_mae") for row in rows if row["variant"] == name),
                    "boundary_movement_mean_abs_sec": _mean(row.get("boundary_movement_mean_abs_sec") for row in rows if row["variant"] == name),
                    "nominal_fallback_count_mean": _mean(row.get("nominal_fallback_count") for row in rows if row["variant"] == name),
                    "planned_cursor_application_count_mean": _mean(row.get("planned_cursor_application_count") for row in rows if row["variant"] == name),
                }
                for name in variants
            },
            "applicable_item_count": sum(bool(payload.get("applicable", True)) for _, payload in phase_payloads[phase]),
            "not_applicable_item_count": sum(not bool(payload.get("applicable", True)) for _, payload in phase_payloads[phase]),
        }
    silence_groups = {}
    for variant, duration_bin in sorted({(row["variant"], row["duration_bin"]) for row in silence_boundary_rows}):
        selected = [row for row in silence_boundary_rows if row["variant"] == variant and row["duration_bin"] == duration_bin]
        silence_groups[f"{variant}|{duration_bin}"] = {
            "variant": variant, "duration_bin": duration_bin, "boundary_count": len(selected),
            "duration_mean_sec": _mean(row.get("duration_sec") for row in selected),
            "before_boundary_mae_sec": _mean(row.get("before_mae") for row in selected),
            "after_boundary_mae_sec": _mean(row.get("after_mae") for row in selected),
            "before_missing_mean": _mean(row.get("before_missing") for row in selected),
            "after_missing_mean": _mean(row.get("after_missing") for row in selected),
        }
    experiment_summary["E6"]["silence_boundary_by_variant_and_duration"] = silence_groups

    e7_effects = []
    e7_resets = []
    for metadata, phase_payload in phase_payloads["E7"]:
        for record in phase_payload.get("records", []):
            effect = (record.get("predict_state") or {}).get("causal_effect") or {}
            delta = effect.get("delta_vs_baseline") or {}
            base_row = {
                **metadata, "kind": record.get("kind"), "value": record.get("value"),
                "mae_delta": delta.get("all_penalized_boundary_mae_sec"),
                "coverage_delta": delta.get("coverage"), "status": record.get("status"),
            }
            e7_effects.append(base_row)
            for reset_name, reset in (record.get("resets") or {}).items():
                recovery = (reset or {}).get("recovery_vs_injected") or {}
                e7_resets.append({
                    **base_row, "reset": reset_name,
                    "recovery_mae_delta": recovery.get("all_penalized_boundary_mae_sec"),
                    "recovery_coverage_delta": recovery.get("coverage"),
                    "reset_complete": bool(reset) and "error" not in reset,
                })
    kinds = sorted({row["kind"] for row in e7_effects})
    experiment_summary["E7"] = {
        "record_count": len(e7_effects),
        "by_injection_kind": {
            kind: {
                "mean_post_mae_delta_sec": _mean(row.get("mae_delta") for row in e7_effects if row["kind"] == kind),
                "mean_coverage_delta": _mean(row.get("coverage_delta") for row in e7_effects if row["kind"] == kind),
                "complete_count": sum(row["status"] == "complete" for row in e7_effects if row["kind"] == kind),
                "persistent_degradation_rate": _mean(
                    float(row["mae_delta"] > 0.0) for row in e7_effects
                    if row["kind"] == kind and row.get("mae_delta") is not None
                ),
            }
            for kind in kinds
        },
        "reset_recovery": {
            reset: {
                "mean_mae_change_vs_injected_sec": _mean(row.get("recovery_mae_delta") for row in e7_resets if row["reset"] == reset),
                "mean_coverage_change_vs_injected": _mean(row.get("recovery_coverage_delta") for row in e7_resets if row["reset"] == reset),
                "recovery_rate": _mean(
                    float(row["recovery_mae_delta"] < 0.0) for row in e7_resets
                    if row["reset"] == reset and row.get("recovery_mae_delta") is not None
                ),
                "complete_count": sum(row["reset_complete"] for row in e7_resets if row["reset"] == reset),
            }
            for reset in sorted({row["reset"] for row in e7_resets})
        },
        "causal_cascade_supported_rate": _mean(
            float(
                row.get("mae_delta") is not None and row["mae_delta"] > 0.0
                and any(
                    reset_row.get("recovery_mae_delta") is not None and reset_row["recovery_mae_delta"] < 0.0
                    for reset_row in e7_resets
                    if reset_row["item_id"] == row["item_id"] and reset_row["kind"] == row["kind"] and reset_row["value"] == row["value"]
                )
            )
            for row in e7_effects if row.get("mae_delta") is not None
        ),
    }

    e8_candidates = []; e8_selections = []
    for metadata, phase_payload in phase_payloads["E8"]:
        for case in phase_payload.get("cases", []):
            for name, candidate in (case.get("candidates") or {}).items():
                downstream_delta = candidate.get("downstream_delta_vs_baseline") or {}
                e8_candidates.append({
                    **metadata, "candidate": name, "request_variant": candidate.get("request_variant"),
                    "metrics": candidate.get("metrics"), "spliced_metrics": candidate.get("spliced_full_metrics"),
                    "propagation_status": (candidate.get("propagation") or {}).get("status"),
                    "downstream_mae_delta": downstream_delta.get("all_penalized_boundary_mae_sec"),
                    "downstream_coverage_delta": downstream_delta.get("coverage"),
                })
            e8_selections.append({
                **metadata, "baseline_target_clean": case.get("baseline_target_clean"),
                **(case.get("selection") or {}),
            })
    experiment_summary["E8"] = {
        "local_by_candidate": grouped_aggregate(e8_candidates, ["candidate"]),
        "spliced_full_by_candidate": grouped_aggregate([{**row, "metrics": row.get("spliced_metrics")} for row in e8_candidates if row.get("spliced_metrics")], ["candidate"]),
        "case_count": len(e8_selections),
        "clean_case_count": sum(row.get("baseline_target_clean") is True for row in e8_selections),
        "selected_improvement_rate": _mean(float(row.get("selected_improved_full_mae")) for row in e8_selections if row.get("selected_improved_full_mae") is not None),
        "selected_harm_rate": _mean(float(row.get("selected_harm_full_mae")) for row in e8_selections if row.get("selected_harm_full_mae") is not None),
        "selected_clean_harm_rate": _mean(float(row.get("selected_clean_harm")) for row in e8_selections if row.get("selected_clean_harm") is not None),
        "oracle_match_rate": _mean(float(row.get("selected_matches_oracle")) for row in e8_selections if row.get("selected_matches_oracle") is not None),
        **summarize_e8_downstream_effects(e8_candidates),
        "candidate_propagation_failure_rate": _mean(
            float(row.get("propagation_status") == "failed") for row in e8_candidates
        ),
        "alternate_input_candidate_count": sum(row.get("request_variant") == "alternate_context" for row in e8_candidates),
    }

    e9 = []
    for metadata, payload in phase_payloads["E9"]:
        beam_summary = payload.get("cursor_window_beam_summary") or {}
        selected_delta = beam_summary.get("selected_delta_vs_baseline") or {}
        e9.append({
            **metadata,
            "beam_width": beam_summary.get("beam_width"),
            "multi_hypothesis_windows": beam_summary.get("multi_hypothesis_window_count"),
            "fallback_windows": beam_summary.get("fallback_window_count"),
            "selected_complete": beam_summary.get("selected_complete"),
            "selected_matches_oracle": beam_summary.get("selected_matches_final_beam_oracle"),
            "selected_mae_delta": selected_delta.get("all_penalized_boundary_mae_sec"),
            "line_mae": (payload.get("line_level_metrics") or {}).get("boundary_mae_sec"),
        })
    experiment_summary["E9"] = {
        "item_count": len(e9),
        "beam_width_mean": _mean(row.get("beam_width") for row in e9),
        "multi_hypothesis_window_count_mean": _mean(row.get("multi_hypothesis_windows") for row in e9),
        "fallback_window_count_mean": _mean(row.get("fallback_windows") for row in e9),
        "selected_complete_rate": _mean(
            float(row["selected_complete"]) for row in e9
            if row.get("selected_complete") is not None
        ),
        "selected_matches_final_beam_oracle_rate": _mean(
            float(row.get("selected_matches_oracle")) for row in e9
            if row.get("selected_matches_oracle") is not None
        ),
        "selected_mae_delta_mean_sec": _mean(row.get("selected_mae_delta") for row in e9),
        "line_boundary_mae_sec": _mean(row.get("line_mae") for row in e9),
    }

    payload = {
        "schema_version": "alignment_research_suite_summary_v3_frozen_decoder_route",
        "mode": args.mode, "manifest": str(args.manifest),
        "manifest_item_count": len(read_jsonl(args.manifest)),
        "selected_item_count": len(items) + len(failures),
        "completed_item_count": len(items), "failed_item_count": len(failures),
        "full_data_policy": "formal consumes every manifest item; no dataset item cap",
        "case_execution_policy": {
            "cases_per_item": int(args.cases_per_item),
            "max_chunk_groups_per_item": int(args.max_chunk_groups_per_item),
            "max_realign_cases_per_item": int(args.max_realign_cases_per_item),
            "zero_means_unlimited": True,
            "case_level_subsampling": any(
                int(value) > 0 for value in (
                    args.cases_per_item, args.max_chunk_groups_per_item, args.max_realign_cases_per_item
                )
            ),
        },
        "phases": sorted(args.phases), "decoder_summary": decoder_groups,
        "frozen_decoder_execution": {
            "selected_decoder": str(getattr(args, "selected_decoder_name", "official")),
            "formal_serial_commit_policy": "decoder applied per model window before ownership split and cursor update",
            "item_count": len(items),
            "route_source_counts": {
                source: sum(
                    (item.get("frozen_decoder_route") or {}).get("source") == source
                    for item in items
                )
                for source in sorted({
                    str((item.get("frozen_decoder_route") or {}).get("source"))
                    for item in items
                    if (item.get("frozen_decoder_route") or {}).get("source") is not None
                })
            },
            "model_backed_rerun_wall_sec": sum(
                float((item.get("frozen_decoder_route") or {}).get("wall_sec", 0.0))
                for item in items
            ),
        },
        "detector_summary": detector_summary, "detector_models": models_payload,
        "experiment_summary": experiment_summary,
        "inference_cache_summary": {
            "hits": sum(int(item.get("inference_cache", {}).get("hits", 0)) for item in items),
            "misses": sum(int(item.get("inference_cache", {}).get("misses", 0)) for item in items),
            "forward_wall_sec": sum(float(item.get("inference_cache", {}).get("forward_wall_sec", 0.0)) for item in items),
        },
        "items": items, "failures": failures,
    }
    atomic_json(args.out_root / "research_summary.json", payload)
    atomic_json(args.out_root / "complete.json", {"status": "complete" if not failures else "partial_failure", **payload})
    return payload


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("pilot", "formal"), required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--baseline-root", type=Path, required=True)
    p.add_argument("--baseline-variant", default="B4_60_silence_official")
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--model")
    p.add_argument("--revision")
    p.add_argument("--r2-checkpoint", type=Path)
    p.add_argument("--device", default="cuda")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--local-files-only", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--language", default="Chinese")
    p.add_argument("--phases", default=",".join(PHASES))
    p.add_argument("--item-id")
    p.add_argument("--pilot-items-per-dataset", type=int, default=2)
    p.add_argument("--cases-per-item", type=int, default=0, help="0 means all eligible windows; smoke wrapper overrides to 1")
    p.add_argument("--max-chunk-groups-per-item", type=int, default=0, help="0 means all complete 96-unit groups")
    p.add_argument("--max-realign-cases-per-item", type=int, default=0, help="0 means all detector risk spans")
    p.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    p.add_argument("--decoder-top-k", type=int, default=8)
    p.add_argument("--decoder-beam-size", type=int, default=96)
    p.add_argument("--detector-tolerance-sec", type=float, default=0.16)
    p.add_argument("--detector-risk-threshold", type=float, default=1.0, help="rule-score threshold when no learned detector is frozen")
    p.add_argument("--detector-model-threshold", type=float, default=0.5, help="probability threshold for a frozen learned detector")
    p.add_argument("--detector-safe-threshold", type=float, default=0.25)
    p.add_argument("--repairable-score-threshold", type=float, default=0.5)
    p.add_argument("--core-sec", type=float, default=60.0)
    p.add_argument("--left-context-sec", type=float, default=10.0)
    p.add_argument("--right-context-sec", type=float, default=10.0)
    p.add_argument("--minimum-forward-characters", type=int, default=64)
    p.add_argument("--future-character-ratio", type=float, default=1.35)
    p.add_argument("--max-candidate-expansions", type=int, default=4)
    p.add_argument("--dynamic-search-sec", type=float, default=10.0)
    p.add_argument("--dynamic-safe-score", type=float, default=0.25)
    p.add_argument("--silence-lookahead-sec", type=float, default=8.0)
    p.add_argument("--injection-window-index", type=int, default=1)
    p.add_argument("--realign-context-units", type=int, default=4)
    p.add_argument("--system-beam-width", type=int, default=3)
    p.add_argument("--system-beam-cursor-backtrack-units", type=int, default=2)
    p.add_argument("--system-beam-window-backtrack-sec", type=float, default=2.0)
    p.add_argument("--system-beam-extra-forward-characters", type=int, default=32)
    p.add_argument("--frozen-params", type=Path, help="pilot-frozen detector/decoder parameters for formal evaluation")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--compact-artifacts", action="store_true", help="store metrics and hashes, not reproducible candidate rows/traces/cache")
    return p


def main() -> int:
    args = parser().parse_args()
    args.manifest = args.manifest.expanduser().resolve()
    args.baseline_root = args.baseline_root.expanduser().resolve()
    args.out_root = args.out_root.expanduser().resolve()
    args.out_root.mkdir(parents=True, exist_ok=True)
    args.frozen_payload = {}
    args.frozen_detector_model = None
    args.selected_detector_name = "rule"
    args.selected_decoder_name = "official"
    if args.frozen_params is not None:
        args.frozen_params = args.frozen_params.expanduser().resolve()
        args.frozen_payload = json.loads(args.frozen_params.read_text(encoding="utf-8"))
        args.selected_detector_name = str(args.frozen_payload.get("selected_detector") or "rule")
        args.selected_decoder_name = str(args.frozen_payload.get("selected_decoder") or "official")
        if args.selected_decoder_name not in DECODER_NAMES:
            raise ValueError(f"unknown frozen decoder: {args.selected_decoder_name}")
        selected_threshold = args.frozen_payload.get("selected_detector_threshold") or {}
        if selected_threshold.get("threshold") is not None:
            args.detector_model_threshold = float(selected_threshold["threshold"])
        detector_model = args.frozen_payload.get("detector_model")
        if detector_model:
            schema = detector_model.get("schema_version")
            if schema == "logistic_risk_model_v1":
                args.frozen_detector_model = LogisticRiskModel.from_dict(detector_model)
            elif schema == "stump_boost_risk_model_v1":
                args.frozen_detector_model = StumpBoostRiskModel(
                    float(detector_model["base_score"]), float(detector_model["learning_rate"]),
                    [__import__("lyricalign.research_v6.detector", fromlist=["DecisionStump"]).DecisionStump(**row) for row in detector_model["stumps"]],
                )
            else:
                raise ValueError(f"unknown frozen detector model: {schema}")
        recommended = args.frozen_payload.get("recommended_parameters", {})
        for key, value in recommended.items():
            if hasattr(args, key):
                setattr(args, key, value)
    if float(args.dynamic_safe_score) <= 0.0:
        raise ValueError("--dynamic-safe-score must be positive so risk-gated zero scores remain rejected")
    args.phases = {value.strip() for value in str(args.phases).split(",") if value.strip()}
    unknown = args.phases - set(PHASES)
    if unknown:
        raise ValueError(f"unknown phases: {sorted(unknown)}")
    items = select_items(read_jsonl(args.manifest), args)
    requires_model = bool(args.phases - {"E0", "E1", "E3"}) or (
        args.mode == "formal" and args.selected_decoder_name != "official"
    )
    processor = model = None
    if requires_model:
        if not args.model or not args.revision or args.r2_checkpoint is None:
            raise ValueError("enabled phases require --model, --revision and --r2-checkpoint")
        load_args = SimpleNamespace(
            model=args.model, revision=args.revision, local_files_only=args.local_files_only,
            cache_dir=args.cache_dir, device=args.device,
        )
        processor, model = SERIAL.load_model(load_args, "lora", args.r2_checkpoint.resolve())
    summaries = []
    failures = []
    status_path = args.out_root / "run_status.jsonl"
    try:
        for ordinal, item in enumerate(items, 1):
            item_id = str(item["item_id"])
            summary_path = args.out_root / "items" / item_id / "item_summary.json"
            if args.resume and summary_path.is_file():
                try:
                    existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing_summary = None
                existing_phases = set((existing_summary or {}).get("phases", {}))
                if existing_summary is not None and set(args.phases).issubset(existing_phases):
                    summaries.append(existing_summary)
                    continue
                # Missing phases are recovered by run_item's phase-level resume.
            with status_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"status": "running", "item": f"{ordinal}/{len(items)}", "item_id": item_id}, ensure_ascii=False) + "\n")
            print(json.dumps({"stage": "research", "status": "item_start", "item": f"{ordinal}/{len(items)}", "item_id": item_id}, ensure_ascii=False), flush=True)
            started = time.perf_counter()
            try:
                summary = run_item(item=item, args=args, processor=processor, model=model)
                summary["wall_sec"] = time.perf_counter() - started
                atomic_json(summary_path, summary)
                summaries.append(summary)
                print(json.dumps({"stage": "research", "status": "item_complete", "item_id": item_id}, ensure_ascii=False), flush=True)
            except Exception as exc:
                failure = {"item_id": item_id, "error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()}
                failures.append(failure)
                atomic_json(args.out_root / "items" / item_id / "failure.json", failure)
                print(json.dumps({"stage": "research", "status": "item_failed", "item_id": item_id, "error": str(exc)}, ensure_ascii=False), flush=True)
                if args.fail_fast:
                    raise
    finally:
        if model is not None:
            del model, processor
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available(): torch.cuda.empty_cache()
            except ImportError:
                pass
    aggregate(args, summaries, failures)
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
