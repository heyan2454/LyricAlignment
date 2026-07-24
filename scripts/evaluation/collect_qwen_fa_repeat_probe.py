#!/usr/bin/env python3
"""Collect controlled repeated-lyrics diagnostics for Qwen forced alignment.

Variants for each silence gap g:
- repeat_AA: A + silence(g) + A, transcript A+A
- control_AB: A + silence(g) + B, transcript A+B

The probe is diagnostic-only and must not be used for checkpoint selection.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
COLLECTOR_SPEC = importlib.util.spec_from_file_location(
    "qwen_fa_immediate_collector", HERE / "collect_qwen_fa_immediate_diagnostics.py"
)
PAIR_SPEC = importlib.util.spec_from_file_location(
    "qwen_fa_cliff_probe", HERE / "collect_qwen_fa_240_cliff_probe.py"
)
if COLLECTOR_SPEC is None or COLLECTOR_SPEC.loader is None:
    raise RuntimeError("cannot load immediate collector")
if PAIR_SPEC is None or PAIR_SPEC.loader is None:
    raise RuntimeError("cannot load cliff probe helpers")
collector = importlib.util.module_from_spec(COLLECTOR_SPEC)
COLLECTOR_SPEC.loader.exec_module(collector)
pair_helpers = importlib.util.module_from_spec(PAIR_SPEC)
PAIR_SPEC.loader.exec_module(pair_helpers)


def parse_float_list(text: str) -> list[float]:
    values = [float(part.strip()) for part in text.split(",") if part.strip()]
    if not values or any(value < 0 for value in values):
        raise ValueError("gaps must be a non-empty list of non-negative seconds")
    return values


def silence(seconds: float, sample_rate: int = 16000) -> np.ndarray:
    return np.zeros(int(round(seconds * sample_rate)), dtype=np.float32)


def write_audio(path: Path, pieces: Iterable[np.ndarray], sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return
    audio = np.concatenate([np.asarray(piece, dtype=np.float32) for piece in pieces])
    temporary = path.with_suffix(".tmp.wav")
    sf.write(temporary, audio, sample_rate, subtype="PCM_16")
    temporary.replace(path)


def build_repeat_variants(
    *,
    out_dir: Path,
    a: dict[str, Any],
    b: dict[str, Any],
    a_refs: list[dict[str, Any]],
    b_refs: list[dict[str, Any]],
    gaps: list[float],
) -> list[dict[str, Any]]:
    audio_dir = out_dir / "derived_audio"
    a_audio = pair_helpers.read_audio(Path(a["resolved_audio_path"]))
    b_audio = pair_helpers.read_audio(Path(b["resolved_audio_path"]))
    a_duration = a_audio.size / 16000.0
    b_duration = b_audio.size / 16000.0
    variants: list[dict[str, Any]] = []

    for gap in gaps:
        gap_label = f"{gap:.3f}"
        second_start = a_duration + gap

        aa_id = f"repeat:AA:gap={gap_label}:{a['item_id']}"
        aa_path = audio_dir / f"{hashlib.sha256(aa_id.encode()).hexdigest()[:20]}.wav"
        write_audio(aa_path, [a_audio, silence(gap), a_audio])
        aa_first = pair_helpers.shifted_segment_refs(
            a_refs,
            start_sec=0.0,
            role="A1",
            source_item_id=str(a["item_id"]),
            output_start_index=0,
        )
        aa_second = pair_helpers.shifted_segment_refs(
            a_refs,
            start_sec=second_start,
            role="A2",
            source_item_id=str(a["item_id"]),
            output_start_index=len(aa_first),
        )
        variants.append(
            {
                "variant_item_id": aa_id,
                "source_item_id": str(a["item_id"]),
                "song_id": a.get("song_id"),
                "audio_path": aa_path,
                "transcript": str(a["lyrics_normalized"]) * 2,
                "refs": aa_first + aa_second,
                "offset_sec": 0.0,
                "variant_kind": "repeat_AA",
                "probe_condition": f"repeat_AA_gap_{gap_label}",
                "join_points_sec": [a_duration] if gap == 0 else [a_duration, second_start],
                "duration_sec": 2 * a_duration + gap,
                "repeat_gap_sec": gap,
            }
        )

        ab_id = f"repeat:AB:gap={gap_label}:{a['item_id']}:{b['item_id']}"
        ab_path = audio_dir / f"{hashlib.sha256(ab_id.encode()).hexdigest()[:20]}.wav"
        write_audio(ab_path, [a_audio, silence(gap), b_audio])
        ab_first = pair_helpers.shifted_segment_refs(
            a_refs,
            start_sec=0.0,
            role="A",
            source_item_id=str(a["item_id"]),
            output_start_index=0,
        )
        ab_second = pair_helpers.shifted_segment_refs(
            b_refs,
            start_sec=second_start,
            role="B",
            source_item_id=str(b["item_id"]),
            output_start_index=len(ab_first),
        )
        variants.append(
            {
                "variant_item_id": ab_id,
                "source_item_id": f"A={a['item_id']}|B={b['item_id']}",
                "song_id": f"A={a.get('song_id')}|B={b.get('song_id')}",
                "audio_path": ab_path,
                "transcript": str(a["lyrics_normalized"]) + str(b["lyrics_normalized"]),
                "refs": ab_first + ab_second,
                "offset_sec": 0.0,
                "variant_kind": "control_AB",
                "probe_condition": f"control_AB_gap_{gap_label}",
                "join_points_sec": [a_duration] if gap == 0 else [a_duration, second_start],
                "duration_sec": a_duration + gap + b_duration,
                "repeat_gap_sec": gap,
            }
        )
    return variants


def complete(out_dir: Path) -> bool:
    return all(
        (out_dir / name).is_file()
        for name in (
            "identity.json",
            "selection.json",
            "diagnostic_rows.jsonl",
            "item_summary.jsonl",
            "input_audit.jsonl",
        )
    )


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
    parser.add_argument("--a-item-id")
    parser.add_argument("--b-item-id")
    parser.add_argument("--selection-seed", type=int, default=20260725)
    parser.add_argument("--min-duration", type=float, default=5.0)
    parser.add_argument("--max-duration", type=float, default=15.0)
    parser.add_argument("--min-characters", type=int, default=15)
    parser.add_argument("--max-characters", type=int, default=40)
    parser.add_argument("--gaps", default="0,0.5,1,2,4,8")
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    if args.out_dir.exists() and complete(args.out_dir):
        print(json.dumps({"status": "already_complete", "out_dir": str(args.out_dir)}))
        return
    if args.out_dir.exists():
        archived = args.out_dir.with_name(args.out_dir.name + ".incomplete")
        index = 0
        while archived.exists():
            index += 1
            archived = args.out_dir.with_name(args.out_dir.name + f".incomplete.{index}")
        args.out_dir.rename(archived)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    records = collector.read_jsonl(args.labels)
    by_item = collector.group_characters(args.characters)
    a, b, candidates = pair_helpers.select_pair(
        records,
        by_item,
        args.audio_root,
        split="test",
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        min_characters=args.min_characters,
        max_characters=args.max_characters,
        seed=args.selection_seed,
        a_item_id=args.a_item_id,
        b_item_id=args.b_item_id,
    )
    gaps = parse_float_list(args.gaps)
    variants = build_repeat_variants(
        out_dir=args.out_dir,
        a=a,
        b=b,
        a_refs=by_item[str(a["item_id"])],
        b_refs=by_item[str(b["item_id"])],
        gaps=gaps,
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
    infer_args = Namespace(
        experiment="repeat",
        language=args.language,
        device=args.device,
        timestamp_segment_sec=args.timestamp_segment_sec,
    )

    rows_all: list[dict[str, Any]] = []
    item_all: list[dict[str, Any]] = []
    audit_all: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        rows, summary, audit = collector.infer_variant(
            processor,
            model,
            infer_args,
            variant,
            args.model_name,
            checkpoint_kind,
        )
        rows_all.extend(rows)
        item_all.append(summary)
        audit_all.append(audit)
        print(json.dumps({"completed": index, "total": len(variants), "condition": variant["probe_condition"]}, ensure_ascii=False), flush=True)

    collector.atomic_jsonl(args.out_dir / "diagnostic_rows.jsonl", rows_all)
    collector.atomic_jsonl(args.out_dir / "item_summary.jsonl", item_all)
    collector.atomic_jsonl(args.out_dir / "input_audit.jsonl", audit_all)
    collector.atomic_json(
        args.out_dir / "selection.json",
        {
            "schema_version": "qwen_fa_repeat_selection_v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "selection_seed": args.selection_seed,
            "A": {key: a.get(key) for key in ("item_id", "song_id", "audio_relpath", "duration_sec", "resolved_character_count")},
            "B": {key: b.get(key) for key in ("item_id", "song_id", "audio_relpath", "duration_sec", "resolved_character_count")},
            "eligible_candidate_count": len(candidates),
            "gaps_sec": gaps,
        },
    )
    collector.atomic_json(
        args.out_dir / "identity.json",
        {
            "schema_version": "qwen_fa_repeat_identity_v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_name": args.model_name,
            "model_id": args.model,
            "revision": args.revision,
            "checkpoint": str(args.checkpoint) if args.checkpoint else None,
            "checkpoint_kind": checkpoint_kind,
            "checkpoint_identity": checkpoint_identity,
            "labels": str(args.labels),
            "labels_sha256": collector.sha256(args.labels),
            "characters": str(args.characters),
            "characters_sha256": collector.sha256(args.characters),
            "audio_root": str(args.audio_root),
            "variant_count": len(variants),
            "character_row_count": len(rows_all),
            "diagnostic_only": True,
        },
    )
    print(json.dumps({"status": "complete", "out_dir": str(args.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
