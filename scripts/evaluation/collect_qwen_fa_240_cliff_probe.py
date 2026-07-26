#!/usr/bin/env python3
"""Collect a minimal, controlled diagnostic for the Qwen FA ~240 s collapse.

The probe has two complementary parts:

1. A single-segment prefix-silence sweep around the suspected cliff.
2. Three equal-total-length A/B controls.  B starts at the same absolute time
   in all controls, while A starts at 0, 180, or 240 seconds:

   - late_A:  silence(240) + A + B
   - mid_A:   silence(180) + A + silence(60) + B
   - early_A: A + silence(240) + B

All three controls therefore have total duration 240 + dur(A) + dur(B), and B
starts at 240 + dur(A).  This separates target position from total length and
also tests whether valid singing after 240 seconds is generally unusable.

This script performs no training.  The generated variants are diagnostic-only
and must not be used for checkpoint selection or benchmark reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "qwen_fa_immediate_collector", HERE / "collect_qwen_fa_immediate_diagnostics.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load collect_qwen_fa_immediate_diagnostics.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def parse_float_list(text: str) -> list[float]:
    values = [float(part.strip()) for part in text.split(",") if part.strip()]
    if not values:
        raise ValueError("empty offset list")
    if any(value < 0 for value in values):
        raise ValueError("offsets must be non-negative")
    return values


def stable_rank(seed: int, item_id: str) -> str:
    return hashlib.sha256(f"{seed}:{item_id}".encode("utf-8")).hexdigest()


def select_pair(
    records: list[dict[str, Any]],
    by_item: dict[str, list[dict[str, Any]]],
    audio_root: Path,
    *,
    split: str,
    min_duration: float,
    max_duration: float,
    min_characters: int,
    max_characters: int,
    seed: int,
    a_item_id: str | None,
    b_item_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for row in records:
        item_id = str(row["item_id"])
        if split and row.get("split") != split:
            continue
        refs = by_item.get(item_id)
        if not refs:
            continue
        duration = float(row["duration_sec"])
        characters = len(refs)
        audio_path = audio_root / str(row["audio_relpath"])
        if not (min_duration <= duration <= max_duration):
            continue
        if not (min_characters <= characters <= max_characters):
            continue
        if not audio_path.is_file():
            continue
        candidates.append(
            {
                **row,
                "item_id": item_id,
                "resolved_audio_path": str(audio_path),
                "resolved_character_count": characters,
                "stable_rank": stable_rank(seed, item_id),
            }
        )
    if len(candidates) < 2:
        raise RuntimeError(
            "fewer than two eligible A/B candidates; loosen duration or character constraints"
        )
    candidates.sort(key=lambda row: (row["stable_rank"], row["item_id"]))
    by_id = {str(row["item_id"]): row for row in candidates}
    if a_item_id:
        if a_item_id not in by_id:
            raise ValueError(f"explicit A item is not eligible: {a_item_id}")
        a = by_id[a_item_id]
    else:
        a = candidates[0]
    if b_item_id:
        if b_item_id not in by_id:
            raise ValueError(f"explicit B item is not eligible: {b_item_id}")
        b = by_id[b_item_id]
    else:
        pool = [
            row
            for row in candidates
            if row["item_id"] != a["item_id"] and row.get("song_id") != a.get("song_id")
        ]
        if not pool:
            pool = [row for row in candidates if row["item_id"] != a["item_id"]]
        target_duration = float(a["duration_sec"])
        pool.sort(
            key=lambda row: (
                abs(float(row["duration_sec"]) - target_duration),
                row["stable_rank"],
                row["item_id"],
            )
        )
        b = pool[0]
    if a["item_id"] == b["item_id"]:
        raise RuntimeError("A and B must be distinct")
    return a, b, candidates


def read_audio(path: Path) -> np.ndarray:
    audio = collector.decode_audio(path)
    if audio.ndim != 1:
        raise RuntimeError(f"expected mono audio: {path} shape={audio.shape}")
    if not np.isfinite(audio).all():
        raise RuntimeError(f"non-finite audio: {path}")
    return np.asarray(audio, dtype=np.float32)


def silence(seconds: float, sample_rate: int = 16000) -> np.ndarray:
    return np.zeros(int(round(seconds * sample_rate)), dtype=np.float32)


def write_audio(path: Path, pieces: Iterable[np.ndarray], sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return
    arrays = [np.asarray(piece, dtype=np.float32) for piece in pieces]
    audio = np.concatenate(arrays) if arrays else np.zeros(0, dtype=np.float32)
    temporary = path.with_suffix(".tmp.wav")
    sf.write(temporary, audio, sample_rate, subtype="PCM_16")
    temporary.replace(path)


def shifted_segment_refs(
    refs: list[dict[str, Any]],
    *,
    start_sec: float,
    role: str,
    source_item_id: str,
    output_start_index: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for local_index, row in enumerate(refs):
        copied = dict(row)
        copied["reference_source_item_id"] = source_item_id
        copied["source_character_index"] = int(row["character_index"])
        copied["segment_role"] = role
        copied["character_index"] = output_start_index + local_index
        copied["start_sec"] = float(row["start_sec"]) + start_sec
        copied["end_sec"] = float(row["end_sec"]) + start_sec
        result.append(copied)
    return result


def config_probe(processor: Any, model: Any) -> dict[str, Any]:
    keywords = (
        "max_position",
        "max_source",
        "max_length",
        "sliding",
        "rope",
        "window",
        "timestamp",
        "duration",
        "chunk",
        "position",
    )
    matches: dict[str, Any] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                # Hugging Face configs may contain non-string dictionary keys,
                # such as integer layer indices.
                key_text = str(key)
                child_path = f"{path}.{key_text}"
                if any(keyword in key_text.lower() for keyword in keywords):
                    try:
                        json.dumps(child)
                        matches[child_path] = child
                    except TypeError:
                        matches[child_path] = repr(child)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(model.config.to_dict(), "model.config")
    processor_matches: dict[str, Any] = {}
    for name in sorted(dir(processor)):
        if name.startswith("_") or not any(keyword in name.lower() for keyword in keywords):
            continue
        try:
            value = getattr(processor, name)
        except Exception:
            continue
        if callable(value):
            continue
        try:
            json.dumps(value)
            processor_matches[name] = value
        except TypeError:
            processor_matches[name] = repr(value)
    return {
        "schema_version": "qwen_fa_240_cliff_config_probe_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_class": type(model).__name__,
        "timestamp_token_id": int(model.config.timestamp_token_id),
        "model_config_matches": matches,
        "processor_matches": processor_matches,
    }


def make_variant_id(condition: str, a_id: str, b_id: str | None = None) -> str:
    suffix = f":{a_id}" if b_id is None else f":{a_id}:{b_id}"
    return f"cliff240:{condition}{suffix}"


def build_variants(
    *,
    out_dir: Path,
    a: dict[str, Any],
    b: dict[str, Any],
    a_refs: list[dict[str, Any]],
    b_refs: list[dict[str, Any]],
    offsets: list[float],
    late_start_sec: float,
    mid_start_sec: float,
) -> list[dict[str, Any]]:
    audio_dir = out_dir / "derived_audio"
    a_audio = read_audio(Path(a["resolved_audio_path"]))
    b_audio = read_audio(Path(b["resolved_audio_path"]))
    a_duration = a_audio.size / 16000.0
    b_duration = b_audio.size / 16000.0
    a_transcript = str(a["lyrics_normalized"])
    b_transcript = str(b["lyrics_normalized"])
    variants: list[dict[str, Any]] = []

    for offset in offsets:
        condition = f"shift_{offset:.3f}"
        variant_id = make_variant_id(condition, str(a["item_id"]))
        path = audio_dir / f"{hashlib.sha256(variant_id.encode()).hexdigest()[:20]}.wav"
        write_audio(path, [silence(offset), a_audio])
        refs = shifted_segment_refs(
            a_refs,
            start_sec=offset,
            role="A",
            source_item_id=str(a["item_id"]),
            output_start_index=0,
        )
        variants.append(
            {
                "variant_item_id": variant_id,
                "source_item_id": str(a["item_id"]),
                "song_id": a.get("song_id"),
                "audio_path": path,
                "transcript": a_transcript,
                "refs": refs,
                "offset_sec": offset,
                "variant_kind": "shift_cliff_sweep",
                "probe_condition": condition,
                "join_points_sec": [offset] if offset > 0 else [],
                "duration_sec": offset + a_duration,
            }
        )

    gap = late_start_sec - mid_start_sec
    if gap < 0:
        raise ValueError("late start must be at or after mid start")
    b_start = late_start_sec + a_duration
    total_duration = b_start + b_duration
    controls = [
        (
            "equal_total_late_A",
            [silence(late_start_sec), a_audio, b_audio],
            late_start_sec,
            [late_start_sec, b_start],
        ),
        (
            "equal_total_mid_A",
            [silence(mid_start_sec), a_audio, silence(gap), b_audio],
            mid_start_sec,
            [mid_start_sec, mid_start_sec + a_duration, b_start],
        ),
        (
            "equal_total_early_A",
            [a_audio, silence(late_start_sec), b_audio],
            0.0,
            [a_duration, b_start],
        ),
    ]
    for condition, pieces, a_start, joins in controls:
        variant_id = make_variant_id(condition, str(a["item_id"]), str(b["item_id"]))
        path = audio_dir / f"{hashlib.sha256(variant_id.encode()).hexdigest()[:20]}.wav"
        write_audio(path, pieces)
        refs_a = shifted_segment_refs(
            a_refs,
            start_sec=a_start,
            role="A",
            source_item_id=str(a["item_id"]),
            output_start_index=0,
        )
        refs_b = shifted_segment_refs(
            b_refs,
            start_sec=b_start,
            role="B",
            source_item_id=str(b["item_id"]),
            output_start_index=len(refs_a),
        )
        variants.append(
            {
                "variant_item_id": variant_id,
                "source_item_id": f"A={a['item_id']}|B={b['item_id']}",
                "song_id": f"A={a.get('song_id')}|B={b.get('song_id')}",
                "audio_path": path,
                "transcript": a_transcript + b_transcript,
                "refs": refs_a + refs_b,
                "offset_sec": a_start,
                "variant_kind": "equal_total_control",
                "probe_condition": condition,
                "join_points_sec": joins,
                "duration_sec": total_duration,
            }
        )
    return variants


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-kind", choices=("raw", "projector", "lora"), required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--a-item-id")
    parser.add_argument("--b-item-id")
    parser.add_argument("--selection-seed", type=int, default=20260725)
    parser.add_argument("--min-duration", type=float, default=5.0)
    parser.add_argument("--max-duration", type=float, default=15.0)
    parser.add_argument("--min-characters", type=int, default=15)
    parser.add_argument("--max-characters", type=int, default=40)
    parser.add_argument(
        "--shift-offsets",
        default="0,120,180,220,228,232,234,236,238,240,242,245",
    )
    parser.add_argument("--late-start-sec", type=float, default=240.0)
    parser.add_argument("--mid-start-sec", type=float, default=180.0)
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    if args.out_dir.exists() and all(
        (args.out_dir / name).is_file()
        for name in (
            "identity.json",
            "selection.json",
            "config_probe.json",
            "diagnostic_rows.jsonl",
            "item_summary.jsonl",
            "input_audit.jsonl",
        )
    ):
        print(json.dumps({"status": "already_complete", "out_dir": str(args.out_dir)}))
        return
    if args.out_dir.exists():
        archive = args.out_dir.with_name(args.out_dir.name + ".incomplete")
        counter = 0
        while archive.exists():
            counter += 1
            archive = args.out_dir.with_name(args.out_dir.name + f".incomplete.{counter}")
        args.out_dir.rename(archive)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    records = collector.read_jsonl(args.labels)
    by_item = collector.group_characters(args.characters)
    a, b, candidates = select_pair(
        records,
        by_item,
        args.audio_root,
        split=args.split,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        min_characters=args.min_characters,
        max_characters=args.max_characters,
        seed=args.selection_seed,
        a_item_id=args.a_item_id,
        b_item_id=args.b_item_id,
    )
    offsets = parse_float_list(args.shift_offsets)
    a_refs = by_item[str(a["item_id"])]
    b_refs = by_item[str(b["item_id"])]
    variants = build_variants(
        out_dir=args.out_dir,
        a=a,
        b=b,
        a_refs=a_refs,
        b_refs=b_refs,
        offsets=offsets,
        late_start_sec=args.late_start_sec,
        mid_start_sec=args.mid_start_sec,
    )

    load_args = Namespace(
        model=args.model,
        revision=args.revision,
        checkpoint=args.checkpoint,
        checkpoint_kind=args.checkpoint_kind,
        cache_dir=args.cache_dir,
        local_files_only=args.local_files_only,
        device=args.device,
    )
    processor, model, checkpoint_identity, checkpoint_kind = collector.load_model(load_args)
    collector.atomic_json(args.out_dir / "config_probe.json", config_probe(processor, model))

    selection_payload = {
        "schema_version": "qwen_fa_240_cliff_selection_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_seed": args.selection_seed,
        "constraints": {
            "split": args.split,
            "min_duration": args.min_duration,
            "max_duration": args.max_duration,
            "min_characters": args.min_characters,
            "max_characters": args.max_characters,
        },
        "A": {
            key: a.get(key)
            for key in (
                "item_id",
                "song_id",
                "audio_relpath",
                "duration_sec",
                "resolved_character_count",
                "stable_rank",
            )
        },
        "B": {
            key: b.get(key)
            for key in (
                "item_id",
                "song_id",
                "audio_relpath",
                "duration_sec",
                "resolved_character_count",
                "stable_rank",
            )
        },
        "eligible_candidate_count": len(candidates),
        "shift_offsets": offsets,
        "equal_total_design": {
            "late_A_start_sec": args.late_start_sec,
            "mid_A_start_sec": args.mid_start_sec,
            "B_start_sec": args.late_start_sec + len(read_audio(Path(a["resolved_audio_path"]))) / 16000.0,
            "conditions": [
                "silence(240)+A+B",
                "silence(180)+A+silence(60)+B",
                "A+silence(240)+B",
            ],
        },
    }
    collector.atomic_json(args.out_dir / "selection.json", selection_payload)

    infer_args = Namespace(
        experiment="cliff240",
        language=args.language,
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
    )
    character_rows: list[dict[str, Any]] = []
    item_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        rows, summary, audit = collector.infer_variant(
            processor,
            model,
            infer_args,
            variant,
            args.model_name,
            checkpoint_kind,
        )
        character_rows.extend(rows)
        item_rows.append(summary)
        audit_rows.append(audit)
        print(
            json.dumps(
                {
                    "completed": index,
                    "total": len(variants),
                    "condition": variant["probe_condition"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    collector.atomic_jsonl(args.out_dir / "diagnostic_rows.jsonl", character_rows)
    collector.atomic_jsonl(args.out_dir / "item_summary.jsonl", item_rows)
    collector.atomic_jsonl(args.out_dir / "input_audit.jsonl", audit_rows)
    identity = {
        "schema_version": "qwen_fa_240_cliff_identity_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_name": args.model_name,
        "model_id": args.model,
        "revision": args.revision,
        "checkpoint": str(args.checkpoint) if args.checkpoint else None,
        "checkpoint_identity": checkpoint_identity,
        "checkpoint_kind": checkpoint_kind,
        "labels": str(args.labels),
        "labels_sha256": collector.sha256(args.labels),
        "characters": str(args.characters),
        "characters_sha256": collector.sha256(args.characters),
        "audio_root": str(args.audio_root),
        "variant_count": len(variants),
        "character_row_count": len(character_rows),
        "diagnostic_only": True,
    }
    collector.atomic_json(args.out_dir / "identity.json", identity)
    print(json.dumps({"status": "complete", "out_dir": str(args.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
