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
from types import SimpleNamespace
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.alignment_artifacts import write_alignment_bundle
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
from lyricalign.demo.window_planning import (
    build_silence_aware_window_plan,
    build_strict_silence_boundary_window_plan,
    compress_silence_audio,
    map_compressed_time_to_original,
    project_silence_aware_plan_to_compressed_timeline,
)
from lyricalign.demo.inline_realign import (
    analyze_precommit_trial, attempt_probe_rows, compare_attempt_probes,
    reproduce_segment, stable_segments,
)

SCHEMA_VERSION = "qwen_fa_serial_demo_v7_silence_aware_windows"
WINDOW_POLICY = "silence_aware_global_core_plan_v7"


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

    decoder_kind = str(getattr(args, "decoder_kind", "official"))
    gpu_decoded_classes = None
    gpu_decoder_diagnostic = None
    if decoder_kind in {"gpu_tcn", "gpu_transformer"}:
        runtime = getattr(args, "gpu_decoder_runtime", None)
        if runtime is None:
            raise RuntimeError(f"decoder_kind={decoder_kind} requires a loaded gpu_decoder_runtime")
        expected_architecture = decoder_kind.removeprefix("gpu_")
        if runtime.config.architecture != expected_architecture:
            raise RuntimeError(
                f"decoder checkpoint architecture mismatch: kind={decoder_kind} "
                f"checkpoint={runtime.config.architecture}"
            )
        gpu_decoder_diagnostic = runtime.decode(slot_logits)
        gpu_decoded_classes = gpu_decoder_diagnostic["classes"].detach().cpu()
        gpu_decoder_diagnostic = {
            **gpu_decoder_diagnostic,
            "classes": gpu_decoded_classes,
            "gate": gpu_decoder_diagnostic["gate"].detach().cpu(),
        }
        if int(gpu_decoded_classes.shape[0]) != 2 * len(selected):
            raise RuntimeError("GPU decoder returned the wrong slot count")
    elif decoder_kind not in {"official", "raw"}:
        raise ValueError(f"unknown decoder_kind: {decoder_kind}")

    rows: list[dict[str, Any]] = []
    segment = float(args.timestamp_segment_sec)
    for local_index, (meta, item) in enumerate(zip(selected, decoded, strict=True)):
        start_slot = 2 * local_index
        end_slot = start_slot + 1
        raw_start = int(raw_classes[start_slot]) * segment
        raw_end = int(raw_classes[end_slot]) * segment
        official_fixed_start = float(item["start_time"])
        official_fixed_end = float(item["end_time"])
        gpu_fixed_start = (
            float(int(gpu_decoded_classes[start_slot])) * segment
            if gpu_decoded_classes is not None else None
        )
        gpu_fixed_end = (
            float(int(gpu_decoded_classes[end_slot])) * segment
            if gpu_decoded_classes is not None else None
        )
        if decoder_kind == "official":
            fixed_start, fixed_end = official_fixed_start, official_fixed_end
        elif decoder_kind == "raw":
            fixed_start, fixed_end = raw_start, raw_end
        else:
            fixed_start, fixed_end = float(gpu_fixed_start), float(gpu_fixed_end)
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
                "decoder_kind": decoder_kind,
                "official_fixed_local_start_sec": official_fixed_start,
                "official_fixed_local_end_sec": official_fixed_end,
                "official_fixed_global_start_sec": official_fixed_start + global_audio_offset_sec,
                "official_fixed_global_end_sec": official_fixed_end + global_audio_offset_sec,
                "gpu_fixed_local_start_sec": gpu_fixed_start,
                "gpu_fixed_local_end_sec": gpu_fixed_end,
                "gpu_fixed_global_start_sec": None if gpu_fixed_start is None else gpu_fixed_start + global_audio_offset_sec,
                "gpu_fixed_global_end_sec": None if gpu_fixed_end is None else gpu_fixed_end + global_audio_offset_sec,
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
                "gpu_decoder_start_gate": (
                    None if gpu_decoder_diagnostic is None
                    else float(gpu_decoder_diagnostic["gate"][start_slot])
                ),
                "gpu_decoder_end_gate": (
                    None if gpu_decoder_diagnostic is None
                    else float(gpu_decoder_diagnostic["gate"][end_slot])
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
        "decoder_kind": decoder_kind,
        "gpu_decoder_identity": (
            None if decoder_kind == "official"
            else getattr(getattr(args, "gpu_decoder_runtime", None), "identity", None)
        ),
    }
    return rows, audit


def project_rows_for_decoder(
    rows: list[dict[str, Any]], decoder_kind: str,
) -> list[dict[str, Any]]:
    """Project saved multi-decoder boundaries into ``fixed_*`` fields.

    Serial ownership and the user-visible timestamp decoder are separate
    experimental variables.  In particular, a raw-argmax branch may reuse the
    official decoder's window ownership/cursor trajectory while committing raw
    timestamps.  This helper performs only that projection; it does not change
    the raw/official evidence retained on each row.
    """
    if decoder_kind in {"same", "output"}:
        return [dict(row) for row in rows]
    if decoder_kind not in {"official", "raw"}:
        raise ValueError(f"unsupported serial control decoder: {decoder_kind}")
    result: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        if decoder_kind == "official":
            local_start = row["official_fixed_local_start_sec"]
            local_end = row["official_fixed_local_end_sec"]
            global_start = row["official_fixed_global_start_sec"]
            global_end = row["official_fixed_global_end_sec"]
        else:
            local_start = row["raw_local_start_sec"]
            local_end = row["raw_local_end_sec"]
            global_start = row["raw_global_start_sec"]
            global_end = row["raw_global_end_sec"]
        row["fixed_local_start_sec"] = float(local_start)
        row["fixed_local_end_sec"] = float(local_end)
        row["fixed_global_start_sec"] = float(global_start)
        row["fixed_global_end_sec"] = float(global_end)
        row["serial_control_decoder_kind"] = decoder_kind
        result.append(row)
    return result


def build_vocal_activity_profile(
    audio: Any, *, sample_rate: int = 16000, frame_sec: float = 0.04,
    hop_sec: float = 0.02, sustained_window_sec: float = 0.80,
    sustained_fraction: float = 0.30,
) -> dict[str, Any]:
    """Build a song-adaptive vocal activity profile.

    In addition to frame energy, this records *sustained* activity.  The latter
    is used for long intros/instrumental cores so isolated separator leakage
    does not make an otherwise empty core eligible for lyric commitment.
    """
    import numpy as np

    values = np.asarray(audio, dtype=np.float32)
    frame = max(1, int(round(frame_sec * sample_rate)))
    hop = max(1, int(round(hop_sec * sample_rate)))
    if len(values) < frame:
        values = np.pad(values, (0, frame - len(values)))
    count = 1 + (len(values) - frame) // hop
    starts = np.arange(count, dtype=np.int64) * hop
    squared = np.square(values.astype(np.float64, copy=False))
    cumulative = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(squared)))
    sums = cumulative[starts + frame] - cumulative[starts]
    rms = np.sqrt(sums / frame + 1e-12)
    db = 20.0 * np.log10(rms + 1e-12)
    q20 = float(np.quantile(db, 0.20))
    q90 = float(np.quantile(db, 0.90))
    if q90 < -70.0:
        threshold = -65.0
    else:
        threshold = float(min(-35.0, q90 - 6.0, max(-55.0, q20 + 10.0)))
    reliable_threshold = float(max(threshold, q90 - 12.0))
    active = db >= reliable_threshold
    sustained_frames = max(1, int(round(sustained_window_sec / hop_sec)))
    kernel = np.ones(sustained_frames, dtype=np.float64)
    rolling = np.convolve(active.astype(np.float64), kernel, mode="same") / sustained_frames
    sustained = rolling >= float(sustained_fraction)
    indices = np.flatnonzero(sustained)
    first_sustained = None if len(indices) == 0 else float(indices[0] * hop_sec)
    return {
        "frame_sec": float(frame_sec),
        "hop_sec": float(hop_sec),
        "sample_rate": int(sample_rate),
        "frame_db": db,
        "active": active,
        "sustained": sustained,
        "threshold_db": threshold,
        "reliable_threshold_db": reliable_threshold,
        "song_q20_db": q20,
        "song_q90_db": q90,
        "first_sustained_activity_sec": first_sustained,
        "sustained_window_sec": float(sustained_window_sec),
        "sustained_fraction": float(sustained_fraction),
    }


def vocal_activity_for_interval(
    profile: dict[str, Any], start_sec: float, end_sec: float,
) -> dict[str, Any]:
    import numpy as np

    db = np.asarray(profile["frame_db"])
    active_all = np.asarray(profile["active"], dtype=bool)
    sustained_all = np.asarray(profile["sustained"], dtype=bool)
    hop = float(profile["hop_sec"])
    first = max(0, int(math.floor(start_sec / hop)))
    last = min(len(db), max(first + 1, int(math.ceil(end_sec / hop))))
    selected = db[first:last]
    active = active_all[first:last]
    sustained = sustained_all[first:last]
    sustained_indices = np.flatnonzero(sustained)
    first_sustained = None
    if len(sustained_indices):
        first_sustained = float((first + int(sustained_indices[0])) * hop)
    return {
        "start_sec": float(start_sec),
        "end_sec": float(end_sec),
        "frame_count": int(len(selected)),
        "active_frame_count": int(active.sum()),
        "active_ratio": float(active.mean()) if len(selected) else 0.0,
        "active_duration_sec": float(active.sum() * hop),
        "sustained_frame_count": int(sustained.sum()),
        "sustained_active_ratio": float(sustained.mean()) if len(selected) else 0.0,
        "sustained_active_duration_sec": float(sustained.sum() * hop),
        "first_sustained_activity_sec": first_sustained,
        "peak_db": float(selected.max()) if len(selected) else -math.inf,
        "q95_db": float(np.quantile(selected, 0.95)) if len(selected) else -math.inf,
        "threshold_db": float(profile["threshold_db"]),
        "reliable_threshold_db": float(profile["reliable_threshold_db"]),
    }


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


def _remap_compressed_alignment(
    rows: list[dict[str, Any]], traces: list[dict[str, Any]], mapping: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map compressed-timeline outputs back to the original song clock.

    Start-like fields use the post-silence side of a splice and end-like fields
    use the pre-silence side.  The conversion is recursive so audit rows,
    candidate probes, stable segments and boundary diagnostics remain on the
    same original clock as final characters.
    """
    start_time_keys = {
        "start_sec", "raw_global_start_sec", "official_fixed_global_start_sec",
        "fixed_global_start_sec", "selected_start_sec", "core_start_sec",
        "input_start_sec", "effective_input_start_sec",
        "nominal_input_start_sec", "next_input_boundary_sec",
        "lookahead_start_sec", "startup_vocal_onset_sec",
        "first_sustained_activity_sec",
    }
    end_time_keys = {
        "end_sec", "raw_global_end_sec", "official_fixed_global_end_sec",
        "fixed_global_end_sec", "selected_end_sec", "core_end_sec",
        "input_end_sec", "effective_input_end_sec", "lookahead_end_sec",
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
                continue
            if key in start_time_keys and isinstance(child, (int, float)) and math.isfinite(float(child)):
                result[f"compressed_{key}"] = float(child)
                result[key] = map_compressed_time_to_original(
                    float(child), mapping, boundary_side="right",
                )
                continue
            if key in end_time_keys and isinstance(child, (int, float)) and math.isfinite(float(child)):
                result[f"compressed_{key}"] = float(child)
                result[key] = map_compressed_time_to_original(
                    float(child), mapping, boundary_side="left",
                )
                continue
            result[key] = child
        result["silence_compressed_diagnostic"] = True
        return result

    mapped_rows = convert(rows)
    mapped_trace = convert(traces)
    for trace in mapped_trace:
        trace["silence_compression_mapping"] = mapping
        trace["window_plan_policy"] = "silence_compressed_with_original_snap_v2"
    return mapped_rows, mapped_trace


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
    compress_mode = bool(getattr(args, "compress_silence_audio", False))
    if compress_mode and not bool(getattr(args, "_silence_compression_inner", False)):
        activity_profile = build_vocal_activity_profile(audio)
        original_plan = build_silence_aware_window_plan(
            duration,
            activity_profile,
            target_core_sec=float(args.core_sec),
            left_context_sec=float(args.left_context_sec),
            right_context_sec=float(args.right_context_sec),
            min_silence_sec=float(getattr(args, "silence_boundary_min_sec", 0.8)),
            strong_silence_sec=float(getattr(args, "strong_silence_anchor_sec", 1.5)),
            boundary_search_sec=float(getattr(args, "silence_boundary_search_sec", 6.0)),
            leading_silence_min_sec=float(getattr(args, "leading_silence_min_sec", 2.0)),
            tail_min_core_sec=float(getattr(args, "tail_min_core_sec", 18.0)),
            minimum_core_sec=float(getattr(args, "minimum_core_sec", 12.0)),
        )
        compressed_audio, mapping = compress_silence_audio(
            audio, activity_profile,
            min_silence_sec=float(getattr(args, "silence_boundary_min_sec", 0.8)),
            strong_silence_sec=float(getattr(args, "strong_silence_anchor_sec", 1.5)),
            remove_silence_sec=float(getattr(args, "silence_compression_min_sec", getattr(args, "strong_silence_anchor_sec", 1.5))),
            keep_edge_padding_sec=float(getattr(args, "silence_compression_padding_sec", 0.20)),
        )
        compressed_plan = project_silence_aware_plan_to_compressed_timeline(
            original_plan, mapping,
        )
        inner_args = SimpleNamespace(**vars(args))
        inner_args.compress_silence_audio = False
        inner_args._silence_compression_inner = True
        inner_args.silence_aware_window_plan = False
        inner_args.strict_silence_boundary_plan = False
        inner_args._precomputed_window_plan = compressed_plan
        rows, traces = windowed_alignment(
            processor, model, compressed_audio, document, inner_args, progress_callback=progress_callback,
        )
        mapped_rows, mapped_traces = _remap_compressed_alignment(rows, traces, mapping)
        setattr(args, "generated_silence_compression_mapping", mapping)
        setattr(args, "generated_window_plan", {
            **original_plan,
            "schema_version": "silence_compressed_original_clock_plan_v2",
            "policy": "original_silence_snap_with_compressed_audio_input",
            "compressed_window_plan": compressed_plan,
            "silence_compression_mapping": mapping,
        })
        return mapped_rows, mapped_traces

    precomputed_window_plan = getattr(args, "_precomputed_window_plan", None)
    use_silence_plan = bool(getattr(args, "silence_aware_window_plan", False))
    use_strict_silence_plan = bool(getattr(args, "strict_silence_boundary_plan", False))
    need_activity = (
        bool(getattr(args, "skip_silent_windows", False))
        or use_silence_plan
        or use_strict_silence_plan
    )
    activity_profile = build_vocal_activity_profile(audio) if need_activity else None
    window_plan = None
    if precomputed_window_plan is not None:
        window_plan = dict(precomputed_window_plan)
        windows = list(window_plan.get("windows") or [])
        if not windows:
            raise RuntimeError("precomputed window plan contains no windows")
        setattr(args, "generated_window_plan", window_plan)
    elif use_strict_silence_plan:
        assert activity_profile is not None
        window_plan = build_strict_silence_boundary_window_plan(
            duration,
            activity_profile,
            target_core_sec=float(args.core_sec),
            left_context_sec=float(args.left_context_sec),
            right_context_sec=float(args.right_context_sec),
            min_silence_sec=float(getattr(args, "silence_boundary_min_sec", 0.8)),
            strong_silence_sec=float(getattr(args, "strong_silence_anchor_sec", 1.5)),
            strict_silence_sec=float(getattr(args, "strict_silence_boundary_sec", getattr(args, "strong_silence_anchor_sec", 1.5))),
            tail_min_core_sec=float(getattr(args, "tail_min_core_sec", 18.0)),
            minimum_core_sec=float(getattr(args, "minimum_core_sec", 12.0)),
        )
        windows = list(window_plan["windows"])
        setattr(args, "generated_window_plan", window_plan)
    elif use_silence_plan:
        assert activity_profile is not None
        window_plan = build_silence_aware_window_plan(
            duration,
            activity_profile,
            target_core_sec=float(args.core_sec),
            left_context_sec=float(args.left_context_sec),
            right_context_sec=float(args.right_context_sec),
            min_silence_sec=float(getattr(args, "silence_boundary_min_sec", 0.8)),
            strong_silence_sec=float(getattr(args, "strong_silence_anchor_sec", 1.5)),
            boundary_search_sec=float(getattr(args, "silence_boundary_search_sec", 6.0)),
            leading_silence_min_sec=float(getattr(args, "leading_silence_min_sec", 2.0)),
            tail_min_core_sec=float(getattr(args, "tail_min_core_sec", 18.0)),
            minimum_core_sec=float(getattr(args, "minimum_core_sec", 12.0)),
        )
        windows = list(window_plan["windows"])
        setattr(args, "generated_window_plan", window_plan)
    else:
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
    control_decoder_kind = str(getattr(args, "serial_control_decoder_kind", "same"))
    skip_silent_windows = bool(getattr(args, "skip_silent_windows", False))
    silent_active_ratio_max = float(getattr(args, "silent_active_ratio_max", 0.01))
    silent_peak_margin_db = float(getattr(args, "silent_peak_margin_db", 3.0))
    silent_min_sustained_sec = float(getattr(args, "silent_min_sustained_sec", 0.40))
    startup_vocal_preroll_sec = float(getattr(args, "startup_vocal_preroll_sec", 2.0))
    startup_minimum_forward_characters = int(
        getattr(args, "startup_minimum_forward_characters", 24)
    )
    # Activity may already have been built for the global window plan.
    if activity_profile is None and skip_silent_windows:
        activity_profile = build_vocal_activity_profile(audio)
    alignment_span_sec = (
        float(window_plan["active_span_duration_sec"])
        if window_plan is not None else duration
    )
    capture_attempt_probes = bool(getattr(args, "capture_attempt_probes", False))
    attempt_probe_max_rows = int(getattr(args, "attempt_probe_max_rows", 48))
    stable_segment_min_units = int(getattr(args, "stable_segment_min_units", 2))
    stable_segment_confidence_quantile = float(
        getattr(args, "stable_segment_confidence_quantile", 0.50)
    )
    stable_raw_official_tolerance_sec = float(
        getattr(args, "stable_raw_official_tolerance_sec", 0.16)
    )
    stable_context_tolerance_sec = float(
        getattr(args, "stable_context_tolerance_sec", 0.24)
    )
    stable_prefix_reproduction_tolerance_sec = float(
        getattr(args, "stable_prefix_reproduction_tolerance_sec", 0.24)
    )
    stable_prefix_minimum_observed_units = int(
        getattr(args, "stable_prefix_minimum_observed_units", 2)
    )
    stable_prefix_minimum_observed_ratio = float(
        getattr(args, "stable_prefix_minimum_observed_ratio", 0.50)
    )
    previous_stable_suffix: dict[str, Any] | None = None

    for window_position, window in enumerate(windows):
        if committed_cursor >= total_characters:
            break
        nominal_input_start = float(window["input_start_sec"])
        input_end = float(window["input_end_sec"])
        core_start = float(window["core_start_sec"])
        core_end = float(window["core_end_sec"])
        final_core = bool(window.get("is_final_core", math.isclose(core_end, duration, abs_tol=1e-9)))
        final_region_core = bool(window.get("is_final_region_core", False))

        activity = None
        if activity_profile is not None:
            activity = vocal_activity_for_interval(activity_profile, core_start, core_end)
            essentially_silent = (
                activity["sustained_active_duration_sec"] < silent_min_sustained_sec
                and (
                    activity["active_ratio"] <= silent_active_ratio_max + 1e-12
                    or activity["peak_db"]
                    <= activity["reliable_threshold_db"] + silent_peak_margin_db + 1e-12
                )
            )
            # Never skip the final core while lyrics remain; doing so would hide
            # an incomplete alignment instead of surfacing it.
            if essentially_silent and not final_core:
                trace = {
                    **window,
                    "serial_policy": WINDOW_POLICY,
                    "status": "skipped_silent_core",
                    "silent_core_skipped": True,
                    "vocal_activity": activity,
                    "input_character_start_before": input_cursor,
                    "committed_cursor_before": committed_cursor,
                    "committed_cursor_after": committed_cursor,
                    "next_window_character_start": input_cursor,
                    "next_uncommitted_character_start": committed_cursor,
                    "attempts": [],
                }
                traces.append(trace)
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "silent_window_skipped",
                            "window": window,
                            "committed_cursor": committed_cursor,
                            "input_cursor": input_cursor,
                            "completed_windows": traces,
                        }
                    )
                print(
                    json.dumps(
                        {
                            "window": int(window["window_index"]),
                            "windows_total": len(windows),
                            "core": [core_start, core_end],
                            "status": "skipped_silent_core",
                            "vocal_activity": activity,
                            "committed_cursor": committed_cursor,
                            "input_cursor": input_cursor,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue

        # Always retain the nominal acoustic overlap.  Already committed lyrics
        # are re-input only as immutable context.  If the current window places
        # a new lyric before the frozen prefix ends, append_strict_core_commits
        # compresses only the overlapping left part instead of rejecting or
        # rerunning the window.
        has_matched_left_context = core_start <= 0.0 or input_cursor < committed_cursor
        startup_trimmed_start = nominal_input_start
        startup_onset = None
        if activity_profile is not None and committed_cursor == 0:
            startup_onset = activity_profile.get("first_sustained_activity_sec")
            if startup_onset is not None and float(startup_onset) < input_end:
                startup_trimmed_start = max(
                    nominal_input_start,
                    float(startup_onset) - startup_vocal_preroll_sec,
                )
        input_variants = [
            {
                "input_start_sec": startup_trimmed_start,
                "context_policy": (
                    "startup_silence_trimmed"
                    if startup_trimmed_start > nominal_input_start + 1e-9
                    else (
                        "matched_left_context"
                        if has_matched_left_context
                        else "unmatched_left_context_retained"
                    )
                ),
                "trimmed": startup_trimmed_start > nominal_input_start + 1e-9,
            }
        ]

        global_rate = total_characters / max(alignment_span_sec, 1e-9)
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
        accepted_shadow_rows: list[dict[str, Any]] | None = None
        accepted_control_committed: list[dict[str, Any]] | None = None

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
                "startup_vocal_onset_sec": startup_onset,
            }
            covered_input_sec = max(0.0, input_end - input_start)
            budget_support_sec = covered_input_sec
            input_activity = None
            if activity_profile is not None:
                input_activity = vocal_activity_for_interval(activity_profile, input_start, input_end)
                # Estimate transcript demand from vocal-supporting time, not from
                # a long instrumental prefix. Candidate expansion remains the
                # recovery path when this conservative first estimate is small.
                budget_support_sec = min(
                    covered_input_sec,
                    max(0.0, float(input_activity["sustained_active_duration_sec"])),
                )
            minimum_target = (
                startup_minimum_forward_characters
                if committed_cursor == 0
                else int(args.minimum_forward_characters)
            )
            target_count = max(
                minimum_target,
                int(math.ceil(characters_per_second * budget_support_sec * args.future_character_ratio)),
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
                    decorated["inference_source"] = "strict_serial_window"
                    decorated["timestamp_decoder"] = str(getattr(args, "decoder_kind", "official"))
                    decorated_rows.append(decorated)

                control_rows = project_rows_for_decoder(decorated_rows, control_decoder_kind)

                control_context_rows, control_core_committed, control_lookahead = split_core_commit_prefix(
                    control_rows,
                    expected_input_character_start=input_cursor,
                    committed_character_start=committed_cursor,
                    core_start_sec=core_start,
                    core_end_sec=core_end,
                    final_core=final_core,
                    start_tolerance_sec=args.boundary_start_tolerance_sec,
                )
                by_output_index = {
                    int(row["global_character_index"]): row for row in decorated_rows
                }
                context_rows = [
                    by_output_index[int(row["global_character_index"])]
                    for row in control_context_rows
                ]
                core_committed = [
                    by_output_index[int(row["global_character_index"])]
                    for row in control_core_committed
                ]
                lookahead = [
                    by_output_index[int(row["global_character_index"])]
                    for row in control_lookahead
                ]
                # A hard-silence region ends before the next region's acoustic
                # input begins, so the current inference cannot observe that
                # future input boundary.  At such a boundary the only causal and
                # transcript-consistent cursor is the cursor immediately after
                # the rows committed from this region.
                core_boundary_observed = (
                    final_core or final_region_core or bool(lookahead)
                    or char_end == total_characters
                )

                if final_core:
                    next_input_candidate: int | None = total_characters
                elif final_region_core:
                    next_input_candidate = committed_cursor + len(control_core_committed)
                else:
                    next_input_candidate = None
                next_input_cut_character: dict[str, Any] | None = None
                if next_input_boundary is not None and not final_region_core:
                    next_input_candidate, next_input_cut_character = next_window_transcript_start(
                        control_rows,
                        input_boundary_sec=next_input_boundary,
                        total_characters=total_characters,
                    )
                    if next_input_candidate is None and char_end == total_characters:
                        next_input_candidate = total_characters
                next_input_boundary_observed = (
                    final_core or final_region_core or next_input_candidate is not None
                )
                boundary_observed = core_boundary_observed and next_input_boundary_observed

                probe_rows = (
                    attempt_probe_rows(
                        control_rows,
                        core_end_sec=core_end,
                        next_input_boundary_sec=next_input_boundary,
                        max_rows=attempt_probe_max_rows,
                    )
                    if capture_attempt_probes else []
                )
                attempts.append(
                    {
                        "attempt_index": attempt_index,
                        "expansion_index": expansion_index,
                        "context_variant_index": variant_index,
                        "context_policy": str(variant["context_policy"]),
                        "status": "accepted" if boundary_observed else "expanded",
                        "target_character_count": target_count,
                        "budget_support_sec": budget_support_sec,
                        "input_vocal_activity": input_activity,
                        "candidate_character_start": char_start,
                        "candidate_character_end": char_end,
                        "context_character_count": len(context_rows),
                        "committed_prefix_count": len(core_committed),
                        "lookahead_count": len(lookahead),
                        "core_boundary_observed": core_boundary_observed,
                        "final_region_core": final_region_core,
                        "strict_boundary_cursor_policy": (
                            "continue_from_committed_cursor_after_region"
                            if final_region_core and not final_core else None
                        ),
                        "next_input_boundary_sec": next_input_boundary,
                        "next_input_boundary_observed": next_input_boundary_observed,
                        "next_window_input_character_start": next_input_candidate,
                        "boundary_observed": boundary_observed,
                        "output_decoder_kind": str(getattr(args, "decoder_kind", "official")),
                        "serial_control_decoder_kind": control_decoder_kind,
                        **({"probe_rows": probe_rows} if capture_attempt_probes else {}),
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
                    accepted_control_committed = control_core_committed
                    if bool(getattr(args, "capture_shadow_rows", False)):
                        control_by_index = {
                            int(row["global_character_index"]): row for row in control_rows
                        }
                        accepted_shadow_rows = []
                        for source in decorated_rows:
                            row = dict(source)
                            control = control_by_index[int(row["global_character_index"])]
                            row["control_fixed_global_start_sec"] = float(control["fixed_global_start_sec"])
                            row["control_fixed_global_end_sec"] = float(control["fixed_global_end_sec"])
                            row["serial_control_decoder_kind"] = control_decoder_kind
                            accepted_shadow_rows.append(row)
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
            or accepted_control_committed is None
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
        stable_prefix_reproduction = reproduce_segment(
            previous_stable_suffix,
            accepted_shadow_rows or accepted_committed,
            tolerance_sec=stable_prefix_reproduction_tolerance_sec,
            minimum_observed_units=stable_prefix_minimum_observed_units,
            minimum_observed_ratio=stable_prefix_minimum_observed_ratio,
        )
        trial_committed_rows = append_strict_core_commits(
            committed_rows,
            accepted_committed,
            window=effective_window,
            duration_sec=duration,
            seam_tolerance_sec=args.seam_tolerance_sec,
        )
        precommit_diagnostic = analyze_precommit_trial(
            existing_rows=committed_rows,
            candidate_rows=accepted_committed,
            all_candidate_rows=accepted_shadow_rows or accepted_committed,
            trial_rows=trial_committed_rows,
            window=effective_window,
            vocal_activity=activity,
            uncommitted_character_index=committed_cursor,
        )
        expansion_stability = compare_attempt_probes(attempts)
        committed_rows = trial_committed_rows
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
        window_stable_segments = stable_segments(
            newly_committed_rows,
            accepted_shadow_rows or accepted_committed,
            window_indices={int(window["window_index"])},
            min_units=stable_segment_min_units,
            confidence_quantile=stable_segment_confidence_quantile,
            raw_official_tolerance_sec=stable_raw_official_tolerance_sec,
            repeated_context_tolerance_sec=stable_context_tolerance_sec,
        )
        previous_stable_suffix = (
            max(window_stable_segments, key=lambda row: int(row["character_end"]))
            if window_stable_segments else None
        )

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
        if accepted_control_committed:
            last = accepted_control_committed[-1]
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
                "output_decoder_kind": str(getattr(args, "decoder_kind", "official")),
                "serial_control_decoder_kind": control_decoder_kind,
                "silent_core_skipped": False,
                "vocal_activity": activity,
                "precommit_diagnostic": precommit_diagnostic,
                "attempt_expansion_stability": expansion_stability,
                "stable_prefix_reproduction": stable_prefix_reproduction,
                "stable_suffix_candidate": previous_stable_suffix,
                "stable_segment_count": len(window_stable_segments),
                **({"shadow_rows": accepted_shadow_rows or []} if bool(getattr(args, "capture_shadow_rows", False)) else {}),
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
                    "window_plan_policy": window.get("window_plan_policy"),
                    "core_duration_sec": window.get("core_duration_sec", core_end - core_start),
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
    parser.add_argument("--decoder-kind", choices=("raw", "official", "gpu_tcn", "gpu_transformer"), default="official")
    parser.add_argument(
        "--serial-control-decoder-kind", choices=("same", "official", "raw"), default="same",
        help="decoder used only for core ownership and the next-window lyric cursor",
    )
    parser.add_argument("--gpu-decoder-checkpoint", type=Path)
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
    parser.add_argument(
        "--capture-shadow-rows", action="store_true",
        help="retain all accepted-window candidate rows in window_trace for quick diagnostics",
    )
    parser.add_argument(
        "--capture-attempt-probes", action="store_true",
        help="retain compact boundary probes for candidate-text expansion stability",
    )
    parser.add_argument("--attempt-probe-max-rows", type=int, default=48)
    parser.add_argument("--stable-segment-min-units", type=int, default=2)
    parser.add_argument("--stable-segment-confidence-quantile", type=float, default=0.50)
    parser.add_argument("--stable-raw-official-tolerance-sec", type=float, default=0.16)
    parser.add_argument("--stable-context-tolerance-sec", type=float, default=0.24)
    parser.add_argument("--stable-prefix-reproduction-tolerance-sec", type=float, default=0.24)
    parser.add_argument(
        "--skip-silent-windows", action=argparse.BooleanOptionalAction, default=False,
        help="skip non-final cores that are essentially silent in the vocal stem",
    )
    parser.add_argument("--silent-active-ratio-max", type=float, default=0.01)
    parser.add_argument("--silent-peak-margin-db", type=float, default=3.0)
    parser.add_argument("--silent-min-sustained-sec", type=float, default=0.40)
    parser.add_argument("--startup-vocal-preroll-sec", type=float, default=2.0)
    parser.add_argument("--startup-minimum-forward-characters", type=int, default=24)
    parser.add_argument(
        "--silence-aware-window-plan", action=argparse.BooleanOptionalAction, default=False,
        help="plan the whole song around sustained silence before serial inference",
    )
    parser.add_argument("--silence-boundary-min-sec", type=float, default=0.8)
    parser.add_argument("--strong-silence-anchor-sec", type=float, default=1.5)
    parser.add_argument("--strict-silence-boundary-plan", action="store_true",
                        help="split model inputs at long strong-silence intervals; no window crosses the boundary")
    parser.add_argument("--strict-silence-boundary-sec", type=float, default=1.5)
    parser.add_argument("--compress-silence-audio", action="store_true",
                        help="diagnostic: remove long silence interiors, align compressed audio, then map timestamps back")
    parser.add_argument("--silence-compression-min-sec", type=float, default=1.5)
    parser.add_argument("--silence-compression-padding-sec", type=float, default=0.20)
    parser.add_argument("--silence-boundary-search-sec", type=float, default=6.0)
    parser.add_argument("--leading-silence-min-sec", type=float, default=2.0)
    parser.add_argument("--tail-min-core-sec", type=float, default=18.0)
    parser.add_argument("--minimum-core-sec", type=float, default=12.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
    (args.out_root / "alignment_matrix.complete.json").unlink(missing_ok=True)
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
                    "decoder": {
                        "kind": args.decoder_kind,
                        "serial_control_kind": args.serial_control_decoder_kind,
                        "gpu_checkpoint": (
                            None if args.gpu_decoder_checkpoint is None
                            else str(args.gpu_decoder_checkpoint.resolve())
                        ),
                    },
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
                        "skip_silent_windows": args.skip_silent_windows,
                        "silence_aware_window_plan": args.silence_aware_window_plan,
                        "silence_boundary_min_sec": args.silence_boundary_min_sec,
                        "strong_silence_anchor_sec": args.strong_silence_anchor_sec,
                        "silence_boundary_search_sec": args.silence_boundary_search_sec,
                        "leading_silence_min_sec": args.leading_silence_min_sec,
                        "tail_min_core_sec": args.tail_min_core_sec,
                        "minimum_core_sec": args.minimum_core_sec,
                        "silent_active_ratio_max": args.silent_active_ratio_max,
                        "silent_peak_margin_db": args.silent_peak_margin_db,
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
                    progress_output = out_path.with_name("alignment.progress.json")
                    failure_output = out_path.with_name("alignment.failure.json")
                    out_path.unlink(missing_ok=True)
                    failure_output.unlink(missing_ok=True)

                    def write_progress(state: dict[str, Any]) -> None:
                        atomic_json(
                            progress_output,
                            {
                                "schema_version": "qwen_fa_alignment_progress_v1",
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                                "identity": {**request, "request_hash": request_hash},
                                "state": state,
                            },
                        )

                    write_progress({"event": "alignment_started", "mode": mode})
                    try:
                        if mode == "full":
                            rows, trace = full_alignment(
                                processor, model, decoded_audio[audio_name], document, args
                            )
                        else:
                            rows, trace = windowed_alignment(
                                processor, model, decoded_audio[audio_name], document, args,
                                progress_callback=write_progress,
                            )
                    except Exception as exc:
                        latest_progress = None
                        try:
                            latest_progress = json.loads(progress_output.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            pass
                        atomic_json(
                            failure_output,
                            {
                                "schema_version": "qwen_fa_alignment_failure_v1",
                                "created_at": datetime.now(timezone.utc).isoformat(),
                                "identity": {**request, "request_hash": request_hash},
                                "error": {
                                    "type": type(exc).__name__,
                                    "message": str(exc),
                                    "diagnostic": getattr(exc, "diagnostic", None),
                                },
                                "latest_progress": latest_progress,
                            },
                        )
                        raise
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
                    artifact_result = write_alignment_bundle(out_path, payload)
                    progress_output.unlink(missing_ok=True)
                    failure_output.unlink(missing_ok=True)
                    print(
                        json.dumps(
                            {
                                "completed": str(out_path),
                                "quality_status": artifact_result["quality"]["status"],
                                "artifacts": artifact_result["paths"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
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
