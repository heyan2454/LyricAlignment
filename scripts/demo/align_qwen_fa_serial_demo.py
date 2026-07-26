#!/usr/bin/env python3
"""Create occurrence-aware full and serial-window alignments for one demo song.

R0, R1 and R2 are loaded one at a time.  For each loaded model, mix/full,
mix/windowed, vocal/full and vocal/windowed are completed before the model is
released.  Windowed inference never reads or initializes from the full result.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import (
    LyricDocument,
    build_serial_windows,
    append_strict_core_commits,
    future_character_range,
    parse_lyrics_text,
    repair_monotonic_intervals,
    split_core_commit_prefix,
    next_window_transcript_start,
    normalize_alignment_language,
)
from lyricalign.training.qwen_fa_runtime import decode_audio, move_inputs

SCHEMA_VERSION = "qwen_fa_serial_demo_v6_forward_overlap_compression"
WINDOW_POLICY = "hard_core_forward_overlap_compression_v6"


class SerialWindowAlignmentError(RuntimeError):
    """Windowed alignment failure with a JSON-serializable diagnostic."""

    def __init__(self, message: str, diagnostic: dict[str, Any]):
        super().__init__(message)
        self.diagnostic = diagnostic


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_identity(kind: str, checkpoint: Path | None) -> dict[str, Any]:
    if kind == "raw":
        if checkpoint is not None:
            raise ValueError("raw model must not receive a checkpoint")
        return {"checkpoint_kind": "raw"}
    if checkpoint is None:
        raise ValueError(f"{kind} requires a checkpoint")
    identity: dict[str, Any] = {
        "checkpoint_kind": kind,
        "checkpoint_path": str(checkpoint.resolve()),
    }
    projector = checkpoint / "projector.pt"
    if not projector.is_file():
        raise FileNotFoundError(projector)
    identity["projector_sha256"] = sha256(projector)
    if kind == "lora":
        adapter_model = checkpoint / "adapter" / "adapter_model.safetensors"
        adapter_config = checkpoint / "adapter" / "adapter_config.json"
        if not adapter_model.is_file() or not adapter_config.is_file():
            raise FileNotFoundError(f"incomplete LoRA adapter under {checkpoint / 'adapter'}")
        identity["adapter_model_sha256"] = sha256(adapter_model)
        identity["adapter_config_sha256"] = sha256(adapter_config)
    return identity


def load_model(args: argparse.Namespace, kind: str, checkpoint: Path | None) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor

    kwargs: dict[str, Any] = {
        "revision": args.revision,
        "local_files_only": args.local_files_only or os.environ.get("HF_HUB_OFFLINE") == "1",
    }
    if args.cache_dir:
        kwargs["cache_dir"] = str(args.cache_dir)
    processor = AutoProcessor.from_pretrained(args.model, **kwargs)
    base = AutoModelForTokenClassification.from_pretrained(
        args.model,
        dtype=torch.bfloat16,
        **kwargs,
    )
    if kind == "raw":
        model = base
    elif kind == "projector":
        assert checkpoint is not None
        saved = torch.load(checkpoint / "projector.pt", map_location="cpu", weights_only=True)
        parameters = dict(base.named_parameters())
        missing = sorted(set(saved) - set(parameters))
        if missing:
            raise RuntimeError(f"projector parameters absent from base model: {missing[:5]}")
        for name, value in saved.items():
            parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))
        model = base
    elif kind == "lora":
        from peft import PeftModel

        assert checkpoint is not None
        model = PeftModel.from_pretrained(base, checkpoint / "adapter")
        saved = torch.load(checkpoint / "projector.pt", map_location="cpu", weights_only=True)
        parameters = dict(model.named_parameters())
        missing = sorted(set(saved) - set(parameters))
        if missing:
            raise RuntimeError(f"projector parameters absent from LoRA model: {missing[:5]}")
        for name, value in saved.items():
            parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))
    else:
        raise ValueError(kind)
    return processor, model.to(args.device).eval()


def prepare_pretokenized_aligner_inputs(
    processor: Any,
    *,
    audio: Any,
    alignment_units: list[str],
) -> tuple[Any, list[list[str]]]:
    """Build forced-aligner inputs without tokenizing the transcript twice.

    The lyric parser is the single owner of alignment-unit boundaries.  Each
    unit is inserted as its own text content item, matching the processor's
    post-tokenization chat-template representation.  This is required for
    Japanese because Nagisa may segment a reconstructed slice differently from
    the original visible lyric context.
    """
    if not alignment_units:
        raise ValueError("alignment_units must be non-empty")
    content: list[dict[str, Any]] = [{"type": "audio", "audio": audio}]
    content.extend({"type": "text", "text": unit} for unit in alignment_units)
    conversations = [[{"role": "user", "content": content}]]
    inputs = processor.apply_chat_template(
        conversations,
        tokenize=True,
        return_dict=True,
    )
    return inputs, [list(alignment_units)]


def infer_slice(
    *,
    processor: Any,
    model: Any,
    audio: Any,
    document: LyricDocument,
    character_start: int,
    character_end: int,
    global_audio_offset_sec: float,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import torch

    selected = document.characters[character_start:character_end]
    expected_units = [item.text for item in selected]
    transcript = document.transcript_for_slice(character_start, character_end)
    transcript_policy = "pretokenized_content_items"
    inputs, words = prepare_pretokenized_aligner_inputs(
        processor,
        audio=audio,
        alignment_units=expected_units,
    )
    processor_units = list(words[0])

    batch = move_inputs(inputs, args.device, torch.bfloat16)
    with torch.inference_mode():
        output = model(**batch)
    input_ids = batch["input_ids"][0]
    positions = (input_ids == model.config.timestamp_token_id).nonzero(as_tuple=False).flatten()
    slot_logits = output.logits[0, positions].float()
    if int(slot_logits.shape[0]) != 2 * len(selected):
        raise RuntimeError(
            f"timestamp slots mismatch: slots={slot_logits.shape[0]} units={len(selected)}"
        )
    raw_classes = slot_logits.argmax(dim=-1)
    probabilities = torch.softmax(slot_logits, dim=-1)
    top_values, top_indices = torch.topk(probabilities, k=2, dim=-1)
    entropy = -(probabilities * probabilities.clamp_min(1e-12).log()).sum(dim=-1)
    decoded = processor.decode_forced_alignment(
        output.logits, batch["input_ids"], words, model.config.timestamp_token_id
    )[0]
    if len(decoded) != len(selected):
        raise RuntimeError(f"decode mismatch: decoded={len(decoded)} units={len(selected)}")

    rows: list[dict[str, Any]] = []
    segment = float(args.timestamp_segment_sec)
    for local_index, (meta, item) in enumerate(zip(selected, decoded, strict=True)):
        start_slot = 2 * local_index
        end_slot = start_slot + 1
        raw_start = int(raw_classes[start_slot]) * segment
        raw_end = int(raw_classes[end_slot]) * segment
        fixed_start = float(item["start_time"])
        fixed_end = float(item["end_time"])
        rows.append(
            {
                "global_character_index": meta.global_index,
                "line_index": meta.line_index,
                "index_in_line": meta.index_in_line,
                "character": meta.text,
                "alignment_unit": meta.text,
                "unit_type": meta.unit_type,
                "display_prefix": meta.display_prefix,
                "display_text": meta.display_text or meta.text,
                "display_suffix": meta.display_suffix,
                "raw_local_start_sec": raw_start,
                "raw_local_end_sec": raw_end,
                "raw_global_start_sec": raw_start + global_audio_offset_sec,
                "raw_global_end_sec": raw_end + global_audio_offset_sec,
                "fixed_local_start_sec": fixed_start,
                "fixed_local_end_sec": fixed_end,
                "fixed_global_start_sec": fixed_start + global_audio_offset_sec,
                "fixed_global_end_sec": fixed_end + global_audio_offset_sec,
                "raw_start_top1_probability": float(top_values[start_slot, 0]),
                "raw_end_top1_probability": float(top_values[end_slot, 0]),
                "raw_start_top2_class": int(top_indices[start_slot, 1]),
                "raw_end_top2_class": int(top_indices[end_slot, 1]),
                "raw_start_margin": float(top_values[start_slot, 0] - top_values[start_slot, 1]),
                "raw_end_margin": float(top_values[end_slot, 0] - top_values[end_slot, 1]),
                "raw_start_entropy": float(entropy[start_slot]),
                "raw_end_entropy": float(entropy[end_slot]),
                "raw_boundary_margin_mean": float(
                    (top_values[start_slot, 0] - top_values[start_slot, 1]
                     + top_values[end_slot, 0] - top_values[end_slot, 1]) / 2.0
                ),
            }
        )
    audit = {
        "character_start": character_start,
        "character_end": character_end,
        "character_count": len(selected),
        "alignment_unit_count": len(selected),
        "alignment_unit_mode": document.unit_mode,
        "language": document.language,
        "transcript": transcript,
        "transcript_policy": transcript_policy,
        "processor_units": processor_units,
        "word_count": len(words[0]),
        "timestamp_position_count": int(len(positions)),
        "timestamp_logit_class_count": int(slot_logits.shape[-1]),
        "audio_sample_count": int(len(audio)),
        "audio_duration_sec": float(len(audio) / 16000.0),
    }
    return rows, audit


def decorate_final_rows(rows: list[dict[str, Any]], document: LyricDocument) -> list[dict[str, Any]]:
    by_index = {int(row["global_character_index"]): row for row in rows}
    missing = [item.global_index for item in document.characters if item.global_index not in by_index]
    if missing:
        raise RuntimeError(f"alignment missing {len(missing)} characters, examples={missing[:10]}")
    result: list[dict[str, Any]] = []
    for item in document.characters:
        row = dict(by_index[item.global_index])
        row["character"] = item.text
        row["alignment_unit"] = item.text
        row["unit_type"] = item.unit_type
        row["line_index"] = item.line_index
        row["index_in_line"] = item.index_in_line
        row["display_prefix"] = item.display_prefix
        row["display_text"] = item.display_text or item.text
        row["display_suffix"] = item.display_suffix
        result.append(row)
    return result


def full_alignment(
    processor: Any,
    model: Any,
    audio: Any,
    document: LyricDocument,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, audit = infer_slice(
        processor=processor,
        model=model,
        audio=audio,
        document=document,
        character_start=0,
        character_end=len(document.characters),
        global_audio_offset_sec=0.0,
        args=args,
    )
    selected = []
    for row in rows:
        final = dict(row)
        final["selected_start_sec"] = float(row["fixed_global_start_sec"])
        final["selected_end_sec"] = float(row["fixed_global_end_sec"])
        final["candidate_count"] = 1
        final["inference_source"] = "full"
        selected.append(final)
    repaired = repair_monotonic_intervals(selected, duration_sec=float(len(audio) / 16000.0))
    return decorate_final_rows(repaired, document), [{"mode": "full", **audit}]


def windowed_alignment(
    processor: Any,
    model: Any,
    audio: Any,
    document: LyricDocument,
    args: argparse.Namespace,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run strict serial cores with overlap lyrics used as context only.

    Every 60-second core owns immutable output according to lyric-unit start
    time.  A later window receives lyrics for its 10-second left acoustic
    extension, but already committed units are context-only and can never
    overwrite the preceding core.  New current-window predictions are kept;
    any part that overlaps the frozen prefix is compressed forward to at least
    the previous committed end, without shifting the original end forward.
    """
    duration = float(len(audio) / 16000.0)
    windows = build_serial_windows(
        duration,
        core_sec=args.core_sec,
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
    )
    total_characters = len(document.characters)
    committed_cursor = 0
    input_cursor = 0
    committed_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    previous_committed_count = 0
    previous_core_duration = 0.0

    for window_position, window in enumerate(windows):
        if committed_cursor >= total_characters:
            break
        nominal_input_start = float(window["input_start_sec"])
        input_end = float(window["input_end_sec"])
        core_start = float(window["core_start_sec"])
        core_end = float(window["core_end_sec"])
        final_core = math.isclose(core_end, duration, abs_tol=1e-9)

        # Always retain the nominal acoustic overlap.  Already committed lyrics
        # are re-input only as immutable context.  If the current window places
        # a new lyric before the frozen prefix ends, append_strict_core_commits
        # compresses only the overlapping left part instead of rejecting or
        # rerunning the window.
        has_matched_left_context = core_start <= 0.0 or input_cursor < committed_cursor
        input_variants = [
            {
                "input_start_sec": nominal_input_start,
                "context_policy": (
                    "matched_left_context"
                    if has_matched_left_context
                    else "unmatched_left_context_retained"
                ),
                "trimmed": False,
            }
        ]

        global_rate = total_characters / duration
        recent_rate = (
            previous_committed_count / previous_core_duration
            if previous_committed_count > 0 and previous_core_duration > 0
            else 0.0
        )
        characters_per_second = max(global_rate, recent_rate)
        attempts: list[dict[str, Any]] = []
        accepted_context: list[dict[str, Any]] | None = None
        accepted_committed: list[dict[str, Any]] | None = None
        accepted_lookahead: list[dict[str, Any]] | None = None
        accepted_range: tuple[int, int] | None = None
        accepted_next_input_cursor: int | None = None
        accepted_next_input_cut_character: dict[str, Any] | None = None
        accepted_effective_window: dict[str, Any] | None = None

        next_input_boundary = None
        if not final_core and window_position + 1 < len(windows):
            next_input_boundary = float(windows[window_position + 1]["input_start_sec"])

        for variant_index, variant in enumerate(input_variants):
            input_start = float(variant["input_start_sec"])
            trim_unmatched_left_context = bool(variant["trimmed"])
            effective_window = {
                **window,
                "nominal_input_start_sec": nominal_input_start,
                "input_start_sec": input_start,
                "effective_input_start_sec": input_start,
                "left_context_has_matching_transcript": has_matched_left_context,
                "left_context_trimmed": trim_unmatched_left_context,
                "left_context_trim_reason": None,
                "left_context_policy": str(variant["context_policy"]),
                "left_context_variant_index": variant_index,
            }
            covered_input_sec = max(0.0, input_end - input_start)
            target_count = max(
                args.minimum_forward_characters,
                int(math.ceil(characters_per_second * covered_input_sec * args.future_character_ratio)),
            )
            if final_core:
                target_count = total_characters - input_cursor

            sample_start = int(round(input_start * 16000))
            sample_end = int(round(input_end * 16000))
            for expansion_index in range(args.max_candidate_expansions + 1):
                attempt_index = len(attempts)
                char_start, char_end = future_character_range(
                    document,
                    cursor=input_cursor,
                    target_character_count=max(1, target_count),
                    line_padding=args.future_line_padding,
                )
                if final_core:
                    char_end = total_characters
                rows, audit = infer_slice(
                    processor=processor,
                    model=model,
                    audio=audio[sample_start:sample_end],
                    document=document,
                    character_start=char_start,
                    character_end=char_end,
                    global_audio_offset_sec=input_start,
                    args=args,
                )
                decorated_rows: list[dict[str, Any]] = []
                for row in rows:
                    decorated = dict(row)
                    decorated.update(effective_window)
                    decorated["candidate_character_start"] = char_start
                    decorated["candidate_character_end"] = char_end
                    decorated["inference_source"] = "strict_serial_window_raw"
                    decorated_rows.append(decorated)

                context_rows, core_committed, lookahead = split_core_commit_prefix(
                    decorated_rows,
                    expected_input_character_start=input_cursor,
                    committed_character_start=committed_cursor,
                    core_start_sec=core_start,
                    core_end_sec=core_end,
                    final_core=final_core,
                    start_tolerance_sec=args.boundary_start_tolerance_sec,
                )
                core_boundary_observed = final_core or bool(lookahead) or char_end == total_characters

                next_input_candidate: int | None = total_characters if final_core else None
                next_input_cut_character: dict[str, Any] | None = None
                if next_input_boundary is not None:
                    next_input_candidate, next_input_cut_character = next_window_transcript_start(
                        decorated_rows,
                        input_boundary_sec=next_input_boundary,
                        total_characters=total_characters,
                    )
                    if next_input_candidate is None and char_end == total_characters:
                        next_input_candidate = total_characters
                next_input_boundary_observed = final_core or next_input_candidate is not None
                boundary_observed = core_boundary_observed and next_input_boundary_observed

                attempts.append(
                    {
                        "attempt_index": attempt_index,
                        "expansion_index": expansion_index,
                        "context_variant_index": variant_index,
                        "context_policy": str(variant["context_policy"]),
                        "status": "accepted" if boundary_observed else "expanded",
                        "target_character_count": target_count,
                        "candidate_character_start": char_start,
                        "candidate_character_end": char_end,
                        "context_character_count": len(context_rows),
                        "committed_prefix_count": len(core_committed),
                        "lookahead_count": len(lookahead),
                        "core_boundary_observed": core_boundary_observed,
                        "next_input_boundary_sec": next_input_boundary,
                        "next_input_boundary_observed": next_input_boundary_observed,
                        "next_window_input_character_start": next_input_candidate,
                        "boundary_observed": boundary_observed,
                        **audit,
                    }
                )
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "attempt_completed",
                            "window": effective_window,
                            "committed_cursor": committed_cursor,
                            "input_cursor": input_cursor,
                            "attempts": attempts,
                            "completed_windows": traces,
                        }
                    )
                if boundary_observed:
                    accepted_context = context_rows
                    accepted_committed = core_committed
                    accepted_lookahead = lookahead
                    accepted_range = (char_start, char_end)
                    accepted_next_input_cursor = next_input_candidate
                    accepted_next_input_cut_character = next_input_cut_character
                    accepted_effective_window = effective_window
                    break

                target_count = max(
                    target_count + args.minimum_forward_characters,
                    int(math.ceil(target_count * 1.8)),
                )

            if accepted_effective_window is not None:
                break
            break

        effective_window = accepted_effective_window or effective_window
        input_start = float(effective_window["effective_input_start_sec"])
        trim_unmatched_left_context = bool(
            effective_window["left_context_trimmed"]
        )

        if (
            accepted_context is None
            or accepted_committed is None
            or accepted_lookahead is None
            or accepted_range is None
            or accepted_next_input_cursor is None
        ):
            diagnostic = {
                "kind": "window_boundary_not_observed",
                "window": effective_window,
                "committed_cursor": committed_cursor,
                "input_cursor": input_cursor,
                "attempts": attempts,
                "completed_windows": traces,
            }
            raise SerialWindowAlignmentError(
                f"window {window['window_index']} could not observe the required boundaries "
                f"after {args.max_candidate_expansions + 1} attempts",
                diagnostic,
            )

        committed_cursor_before = committed_cursor
        input_cursor_before = input_cursor
        committed_rows = append_strict_core_commits(
            committed_rows,
            accepted_committed,
            window=effective_window,
            duration_sec=duration,
            seam_tolerance_sec=args.seam_tolerance_sec,
        )
        committed_cursor += len(accepted_committed)
        newly_committed_rows = committed_rows[committed_cursor_before:committed_cursor]
        window_overlap_compressed = [
            row for row in newly_committed_rows if row.get("overlap_compressed")
        ]
        window_overlap_max_sec = max(
            (float(row.get("overlap_compression_sec", 0.0)) for row in window_overlap_compressed),
            default=0.0,
        )
        window_overlap_collapsed_count = sum(
            bool(row.get("overlap_compression_collapsed_to_zero"))
            for row in window_overlap_compressed
        )
        previous_committed_count = len(accepted_committed)
        previous_core_duration = max(core_end - core_start, 1e-9)

        if not final_core:
            if accepted_next_input_cursor > committed_cursor:
                # This is valid only when there is a lyric-free gap covering the
                # remainder of the current core.  The next input still starts at
                # the first character at/after its acoustic boundary, while no
                # uncommitted lyric is silently skipped.
                skipped = accepted_next_input_cursor - committed_cursor
                raise RuntimeError(
                    "next input cursor would skip uncommitted lyrics: "
                    f"committed_cursor={committed_cursor} "
                    f"next_input_cursor={accepted_next_input_cursor} skipped={skipped}"
                )
            input_cursor = accepted_next_input_cursor

        core_boundary_character = None
        if accepted_committed:
            last = accepted_committed[-1]
            if float(last["fixed_global_end_sec"]) > core_end:
                core_boundary_character = {
                    "global_character_index": int(last["global_character_index"]),
                    "character": last["character"],
                    "start_sec": float(last["fixed_global_start_sec"]),
                    "end_sec": float(last["fixed_global_end_sec"]),
                    "crosses_core_end": True,
                    "owned_by_previous_core": True,
                }

        next_uncommitted_character = None
        if committed_cursor < total_characters:
            next_uncommitted_character = {
                "global_character_index": committed_cursor,
                "character": document.characters[committed_cursor].text,
            }
            if accepted_lookahead and int(accepted_lookahead[0]["global_character_index"]) == committed_cursor:
                next_uncommitted_character.update(
                    {
                        "lookahead_start_sec": float(accepted_lookahead[0]["fixed_global_start_sec"]),
                        "lookahead_end_sec": float(accepted_lookahead[0]["fixed_global_end_sec"]),
                    }
                )

        traces.append(
            {
                **effective_window,
                "serial_policy": WINDOW_POLICY,
                "input_character_start_before": input_cursor_before,
                "committed_cursor_before": committed_cursor_before,
                "committed_cursor_after": committed_cursor,
                "candidate_character_start": accepted_range[0],
                "candidate_character_end": accepted_range[1],
                "left_context_character_count": len(accepted_context),
                "committed_character_start": committed_cursor_before,
                "committed_character_end": committed_cursor,
                "committed_character_count": len(accepted_committed),
                "overlap_compressed_character_count": len(window_overlap_compressed),
                "overlap_compression_collapsed_to_zero_count": window_overlap_collapsed_count,
                "overlap_compression_max_sec": window_overlap_max_sec,
                "next_input_boundary_sec": next_input_boundary,
                "next_window_character_start": input_cursor if not final_core else total_characters,
                "next_window_input_character_start": input_cursor if not final_core else total_characters,
                "next_uncommitted_character_start": committed_cursor,
                "input_boundary_cut_character": accepted_next_input_cut_character,
                "core_boundary_character": core_boundary_character,
                "next_uncommitted_character": next_uncommitted_character,
                "attempts": attempts,
            }
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "window_committed",
                    "window": effective_window,
                    "committed_cursor": committed_cursor,
                    "input_cursor": input_cursor,
                    "attempts": attempts,
                    "completed_windows": traces,
                }
            )
        print(
            json.dumps(
                {
                    "window": int(window["window_index"]),
                    "windows_total": len(windows),
                    "core": [core_start, core_end],
                    "nominal_input": [nominal_input_start, input_end],
                    "effective_input": [input_start, input_end],
                    "left_context_trimmed": trim_unmatched_left_context,
                    "characters": [accepted_range[0], accepted_range[1]],
                    "context_characters": [input_cursor_before, committed_cursor_before],
                    "committed": [committed_cursor_before, committed_cursor],
                    "next_input_boundary_sec": next_input_boundary,
                    "next_window_character_start": input_cursor if not final_core else total_characters,
                    "next_uncommitted_character_start": committed_cursor,
                    "input_boundary_cut_character": accepted_next_input_cut_character,
                    "core_boundary_character": core_boundary_character,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    if committed_cursor != total_characters:
        raise RuntimeError(
            f"strict serial alignment ended with uncommitted lyrics: "
            f"cursor={committed_cursor} total={total_characters}"
        )
    return decorate_final_rows(committed_rows, document), traces


def output_is_current(path: Path, request_hash: str) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("identity", {}).get("request_hash") == request_hash


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lyrics", type=Path, required=True)
    parser.add_argument("--mix-audio", type=Path, required=True)
    parser.add_argument("--vocal-audio", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--r1-checkpoint", type=Path, required=True)
    parser.add_argument("--r2-checkpoint", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", type=normalize_alignment_language, default="Chinese")
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--core-sec", type=float, default=60.0)
    parser.add_argument("--left-context-sec", type=float, default=10.0)
    parser.add_argument("--right-context-sec", type=float, default=10.0)
    parser.add_argument("--future-line-padding", type=int, default=1)
    parser.add_argument("--minimum-forward-characters", type=int, default=64)
    parser.add_argument("--future-character-ratio", type=float, default=1.35)
    parser.add_argument("--max-candidate-expansions", type=int, default=4)
    parser.add_argument(
        "--boundary-start-tolerance-sec",
        type=float,
        default=0.32,
        help="legacy compatibility only; v6 does not reject pre-core predictions",
    )
    parser.add_argument(
        "--seam-tolerance-sec",
        type=float,
        default=0.16,
        help="diagnostic legacy threshold only; v6 never limits overlap compression",
    )
    # Accepted only so older launch commands fail soft; strict v2 never backtracks.
    parser.add_argument("--line-padding", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--character-backtrack", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for path in (args.lyrics, args.mix_audio, args.vocal_audio):
        if not path.is_file():
            raise FileNotFoundError(path)
    document = parse_lyrics_text(args.lyrics.read_text(encoding="utf-8-sig"), language=args.language)
    lyrics_identity = {
        "path": str(args.lyrics.resolve()),
        "sha256": sha256(args.lyrics),
        "line_count": len(document.lines),
        "character_count": len(document.characters),
        "alignment_unit_count": len(document.characters),
        "language": document.language,
        "alignment_unit_mode": document.unit_mode,
    }
    audio_inputs = {
        "mix": args.mix_audio,
        "vocal": args.vocal_audio,
    }
    models = [
        ("r0", "raw", None),
        ("r1", "projector", args.r1_checkpoint),
        ("r2", "lora", args.r2_checkpoint),
    ]
    args.out_root.mkdir(parents=True, exist_ok=True)
    atomic_json(
        args.out_root / "lyrics_structure.json",
        {
            "schema_version": SCHEMA_VERSION,
            "identity": lyrics_identity,
            "lines": [line.__dict__ for line in document.lines],
            "characters": [item.__dict__ for item in document.characters],
        },
    )

    for model_name, kind, checkpoint in models:
        checkpoint_info = checkpoint_identity(kind, checkpoint)
        requests: dict[tuple[str, str], tuple[Path, dict[str, Any], str]] = {}
        for audio_name, audio_path in audio_inputs.items():
            audio_info = {
                "path": str(audio_path.resolve()),
                "sha256": sha256(audio_path),
            }
            for mode in ("full", "windowed"):
                request = {
                    "schema_version": SCHEMA_VERSION,
                    "model_name": model_name,
                    "model_id": args.model,
                    "revision": args.revision,
                    "language": document.language,
                    "alignment_unit_mode": document.unit_mode,
                    "checkpoint": checkpoint_info,
                    "lyrics": lyrics_identity,
                    "audio_name": audio_name,
                    "audio": audio_info,
                    "mode": mode,
                    "timestamp_segment_sec": args.timestamp_segment_sec,
                    "window": {
                        "core_sec": args.core_sec,
                        "left_context_sec": args.left_context_sec,
                        "right_context_sec": args.right_context_sec,
                        "policy": WINDOW_POLICY,
                        "future_line_padding": args.future_line_padding,
                        "minimum_forward_characters": args.minimum_forward_characters,
                        "future_character_ratio": args.future_character_ratio,
                        "max_candidate_expansions": args.max_candidate_expansions,
                        "overlap_resolution": "forward_compress_to_previous_committed_end",
                        "allows_zero_duration_after_compression": True,
                        "legacy_boundary_start_tolerance_sec_ignored": args.boundary_start_tolerance_sec,
                        "legacy_seam_tolerance_sec_diagnostic_only": args.seam_tolerance_sec,
                    } if mode == "windowed" else None,
                }
                request_hash = canonical_hash(request)
                out_path = args.out_root / "alignments" / model_name / audio_name / mode / "alignment.json"
                requests[(audio_name, mode)] = (out_path, request, request_hash)
        if not args.force and all(output_is_current(path, request_hash) for path, _, request_hash in requests.values()):
            print(json.dumps({"skip_model": model_name, "reason": "all outputs current"}), flush=True)
            continue

        print(json.dumps({"loading_model": model_name, "checkpoint_kind": kind}), flush=True)
        processor, model = load_model(args, kind, checkpoint)
        try:
            decoded_audio: dict[str, Any] = {}
            for audio_name, audio_path in audio_inputs.items():
                decoded_audio[audio_name] = decode_audio(audio_path)
                for mode in ("full", "windowed"):
                    out_path, request, request_hash = requests[(audio_name, mode)]
                    if not args.force and output_is_current(out_path, request_hash):
                        print(json.dumps({"skip": str(out_path), "reason": "identity match"}), flush=True)
                        continue
                    print(
                        json.dumps(
                            {"model": model_name, "audio": audio_name, "mode": mode, "status": "start"},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if mode == "full":
                        rows, trace = full_alignment(
                            processor, model, decoded_audio[audio_name], document, args
                        )
                    else:
                        rows, trace = windowed_alignment(
                            processor, model, decoded_audio[audio_name], document, args
                        )
                    repaired_count = sum(bool(row.get("cross_window_repaired")) for row in rows)
                    seam_repaired_count = sum(bool(row.get("seam_repaired")) for row in rows)
                    overlap_compressed = [row for row in rows if row.get("overlap_compressed")]
                    overlap_collapsed = [
                        row for row in overlap_compressed
                        if row.get("overlap_compression_collapsed_to_zero")
                    ]
                    overlap_max_sec = max(
                        (float(row.get("overlap_compression_sec", 0.0)) for row in overlap_compressed),
                        default=0.0,
                    )
                    payload = {
                        "schema_version": SCHEMA_VERSION,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "identity": {**request, "request_hash": request_hash},
                        "summary": {
                            "audio_duration_sec": float(len(decoded_audio[audio_name]) / 16000.0),
                            "line_count": len(document.lines),
                            "character_count": len(rows),
                            "alignment_unit_count": len(rows),
                            "language": document.language,
                            "alignment_unit_mode": document.unit_mode,
                            "cross_window_repaired_character_count": repaired_count,
                            "cross_window_repaired_character_rate": repaired_count / len(rows),
                            "seam_repaired_character_count": seam_repaired_count,
                            "seam_repaired_character_rate": seam_repaired_count / len(rows),
                            "overlap_compressed_character_count": len(overlap_compressed),
                            "overlap_compressed_character_rate": len(overlap_compressed) / len(rows),
                            "overlap_compression_collapsed_to_zero_count": len(overlap_collapsed),
                            "overlap_compression_max_sec": overlap_max_sec,
                            "window_policy": WINDOW_POLICY if mode == "windowed" else None,
                            "window_count": len(trace) if mode == "windowed" else 1,
                            "diagnostic_only": True,
                            "uses_full_alignment_as_window_input": False,
                        },
                        "lines": [line.__dict__ for line in document.lines],
                        "characters": rows,
                        "window_trace": trace,
                    }
                    atomic_json(out_path, payload)
                    print(json.dumps({"completed": str(out_path)}, ensure_ascii=False), flush=True)
        finally:
            del model
            del processor
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    atomic_json(
        args.out_root / "alignment_matrix.complete.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "models": [item[0] for item in models],
            "audio_inputs": list(audio_inputs),
            "modes": ["full", "windowed"],
            "expected_alignment_count": 12,
        },
    )


if __name__ == "__main__":
    main()
