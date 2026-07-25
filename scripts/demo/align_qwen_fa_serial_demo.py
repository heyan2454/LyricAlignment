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
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import (
    LyricDocument,
    build_serial_windows,
    candidate_character_range,
    merge_window_candidates,
    parse_lyrics_text,
    repair_monotonic_intervals,
)
from lyricalign.training.qwen_fa_runtime import decode_audio, move_inputs

SCHEMA_VERSION = "qwen_fa_serial_demo_v1"


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
    transcript = "".join(item.text for item in selected)
    inputs, words = processor.prepare_forced_aligner_inputs(
        audio=[audio], transcript=[transcript], language=args.language
    )
    batch = move_inputs(inputs, args.device, torch.bfloat16)
    with torch.inference_mode():
        output = model(**batch)
    input_ids = batch["input_ids"][0]
    positions = (input_ids == model.config.timestamp_token_id).nonzero(as_tuple=False).flatten()
    slot_logits = output.logits[0, positions].float()
    if int(slot_logits.shape[0]) != 2 * len(selected):
        raise RuntimeError(
            f"timestamp slots mismatch: slots={slot_logits.shape[0]} characters={len(selected)}"
        )
    raw_classes = slot_logits.argmax(dim=-1)
    probabilities = torch.softmax(slot_logits, dim=-1)
    top_values, top_indices = torch.topk(probabilities, k=2, dim=-1)
    entropy = -(probabilities * probabilities.clamp_min(1e-12).log()).sum(dim=-1)
    decoded = processor.decode_forced_alignment(
        output.logits, batch["input_ids"], words, model.config.timestamp_token_id
    )[0]
    if len(decoded) != len(selected):
        raise RuntimeError(f"decode mismatch: decoded={len(decoded)} characters={len(selected)}")

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
        "transcript": transcript,
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
        row["line_index"] = item.line_index
        row["index_in_line"] = item.index_in_line
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    duration = float(len(audio) / 16000.0)
    windows = build_serial_windows(
        duration,
        core_sec=args.core_sec,
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
    )
    cursor = 0
    candidates: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for window in windows:
        input_start = float(window["input_start_sec"])
        input_end = float(window["input_end_sec"])
        core_start = float(window["core_start_sec"])
        core_end = float(window["core_end_sec"])
        char_start, char_end = candidate_character_range(
            document,
            duration_sec=duration,
            input_start_sec=input_start,
            input_end_sec=input_end,
            cursor=cursor,
            line_padding=args.line_padding,
            character_backtrack=args.character_backtrack,
            minimum_forward_characters=args.minimum_forward_characters,
        )
        sample_start = int(round(input_start * 16000))
        sample_end = int(round(input_end * 16000))
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
        committed: list[int] = []
        for row in rows:
            decorated = dict(row)
            decorated.update(window)
            decorated["candidate_character_start"] = char_start
            decorated["candidate_character_end"] = char_end
            decorated["inference_source"] = "serial_window"
            midpoint = (
                float(decorated["fixed_global_start_sec"])
                + float(decorated["fixed_global_end_sec"])
            ) / 2.0
            if core_start <= midpoint < core_end or (
                math.isclose(core_end, duration) and midpoint <= core_end
            ):
                committed.append(int(decorated["global_character_index"]))
            candidates.append(decorated)
        cursor_before = cursor
        if committed:
            cursor = max(cursor, max(committed) + 1)
        traces.append(
            {
                **window,
                "cursor_before": cursor_before,
                "cursor_after": cursor,
                "candidate_character_start": char_start,
                "candidate_character_end": char_end,
                "committed_character_count": len(set(committed)),
                **audit,
            }
        )
        print(
            json.dumps(
                {
                    "window": int(window["window_index"]),
                    "windows_total": len(windows),
                    "core": [core_start, core_end],
                    "input": [input_start, input_end],
                    "characters": [char_start, char_end],
                    "cursor": cursor,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    merged = merge_window_candidates(candidates, duration_sec=duration)
    return decorate_final_rows(merged, document), traces


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
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--core-sec", type=float, default=60.0)
    parser.add_argument("--left-context-sec", type=float, default=15.0)
    parser.add_argument("--right-context-sec", type=float, default=15.0)
    parser.add_argument("--line-padding", type=int, default=2)
    parser.add_argument("--character-backtrack", type=int, default=24)
    parser.add_argument("--minimum-forward-characters", type=int, default=48)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for path in (args.lyrics, args.mix_audio, args.vocal_audio):
        if not path.is_file():
            raise FileNotFoundError(path)
    document = parse_lyrics_text(args.lyrics.read_text(encoding="utf-8-sig"))
    lyrics_identity = {
        "path": str(args.lyrics.resolve()),
        "sha256": sha256(args.lyrics),
        "line_count": len(document.lines),
        "character_count": len(document.characters),
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
                        "line_padding": args.line_padding,
                        "character_backtrack": args.character_backtrack,
                        "minimum_forward_characters": args.minimum_forward_characters,
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
                    payload = {
                        "schema_version": SCHEMA_VERSION,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "identity": {**request, "request_hash": request_hash},
                        "summary": {
                            "audio_duration_sec": float(len(decoded_audio[audio_name]) / 16000.0),
                            "line_count": len(document.lines),
                            "character_count": len(rows),
                            "cross_window_repaired_character_count": repaired_count,
                            "cross_window_repaired_character_rate": repaired_count / len(rows),
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
