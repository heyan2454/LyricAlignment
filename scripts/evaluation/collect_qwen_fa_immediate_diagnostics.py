#!/usr/bin/env python3
"""Collect targeted Qwen FA diagnostics in one forward path.

Experiments:
- existing: raw-vs-fixed, mask/feature audit, absolute-time and seam metadata.
- shift: prepend controlled silence and shift the same transcript/GT.
- crop: oracle-GT transcript/audio crops for full-vs-local consistency diagnosis.

This is diagnostic code. Crop and shift variants must not be reported as an
independent benchmark or used for checkpoint selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.training.qwen_fa_runtime import decode_audio, move_inputs, read_jsonl


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


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_kind(requested: str, checkpoint: Path | None) -> str:
    if requested != "auto":
        return requested
    if checkpoint is None:
        return "raw"
    if (checkpoint / "adapter" / "adapter_config.json").is_file():
        return "lora"
    if (checkpoint / "projector.pt").is_file():
        return "projector"
    raise ValueError(f"cannot infer checkpoint kind: {checkpoint}")


def load_projector(model: Any, checkpoint: Path) -> dict[str, Any]:
    import torch

    path = checkpoint / "projector.pt"
    if not path.is_file():
        raise FileNotFoundError(path)
    saved = torch.load(path, map_location="cpu", weights_only=True)
    parameters = dict(model.named_parameters())
    missing = sorted(set(saved) - set(parameters))
    if missing:
        raise RuntimeError(f"projector parameter names missing: {missing[:5]}")
    for name, value in saved.items():
        parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))
    return {"projector_path": str(path), "projector_sha256": sha256(path)}


def load_model(args: argparse.Namespace) -> tuple[Any, Any, dict[str, Any], str]:
    import torch
    from transformers import AutoModelForTokenClassification, AutoProcessor

    cache_dir = args.cache_dir or (Path(os.environ["HF_HUB_CACHE"]) if os.environ.get("HF_HUB_CACHE") else None)
    kwargs: dict[str, Any] = {
        "revision": args.revision,
        "local_files_only": args.local_files_only or env_true("HF_HUB_OFFLINE"),
    }
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    processor = AutoProcessor.from_pretrained(args.model, **kwargs)
    base = AutoModelForTokenClassification.from_pretrained(args.model, dtype=torch.bfloat16, **kwargs)
    kind = resolve_kind(args.checkpoint_kind, args.checkpoint)
    identity: dict[str, Any] = {"checkpoint_kind": kind}
    if kind == "lora":
        from peft import PeftModel

        if args.checkpoint is None:
            raise ValueError("LoRA requires --checkpoint")
        adapter = args.checkpoint / "adapter"
        model = PeftModel.from_pretrained(base, adapter)
        identity.update(
            {
                "adapter_dir": str(adapter),
                "adapter_model_sha256": sha256(adapter / "adapter_model.safetensors"),
                "adapter_config_sha256": sha256(adapter / "adapter_config.json"),
            }
        )
        identity.update(load_projector(model, args.checkpoint))
    elif kind == "projector":
        if args.checkpoint is None:
            raise ValueError("projector requires --checkpoint")
        model = base
        identity.update(load_projector(model, args.checkpoint))
    elif kind == "raw":
        if args.checkpoint is not None:
            raise ValueError("raw must not receive --checkpoint")
        model = base
    else:
        raise ValueError(kind)
    model = model.to(args.device).eval()
    return processor, model, identity, kind


def official_fix_timestamp(values: list[int]) -> list[int]:
    """Mirror the published Qwen forced-aligner LIS repair."""
    n = len(values)
    if n == 0:
        return []
    dp = [1] * n
    parent = [-1] * n
    for i in range(1, n):
        for j in range(i):
            if values[j] <= values[i] and dp[j] + 1 > dp[i]:
                dp[i] = dp[j] + 1
                parent[i] = j
    idx = dp.index(max(dp))
    lis: list[int] = []
    while idx != -1:
        lis.append(idx)
        idx = parent[idx]
    lis.reverse()
    normal = [False] * n
    for idx in lis:
        normal[idx] = True
    result: list[float] = [float(value) for value in values]
    i = 0
    while i < n:
        if normal[i]:
            i += 1
            continue
        j = i
        while j < n and not normal[j]:
            j += 1
        count = j - i
        left = next((result[k] for k in range(i - 1, -1, -1) if normal[k]), None)
        right = next((result[k] for k in range(j, n) if normal[k]), None)
        if count <= 2:
            for k in range(i, j):
                if left is None:
                    result[k] = right  # type: ignore[assignment]
                elif right is None:
                    result[k] = left
                else:
                    result[k] = left if (k - (i - 1)) <= (j - k) else right
        elif left is not None and right is not None:
            step = (right - left) / (count + 1)
            for k in range(i, j):
                result[k] = left + step * (k - i + 1)
        elif left is not None:
            for k in range(i, j):
                result[k] = left
        elif right is not None:
            for k in range(i, j):
                result[k] = right
        i = j
    return [int(value) for value in result]


def parse_float_list(text: str) -> list[float]:
    values = [float(value.strip()) for value in text.split(",") if value.strip()]
    if not values:
        raise ValueError("empty float list")
    return values


def parse_windows(text: str) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for part in text.split(","):
        if not part.strip():
            continue
        start, end = map(float, part.split(":", 1))
        if start < 0 or end <= start:
            raise ValueError(f"invalid crop window: {part}")
        result.append((start, end))
    if not result:
        raise ValueError("empty crop windows")
    return result


def group_characters(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(path):
        grouped[str(row["item_id"])].append(row)
    for item_id in grouped:
        grouped[item_id].sort(key=lambda row: int(row["character_index"]))
    return grouped


def make_silence_prefix(source: Path, output: Path, offset: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file():
        return
    temporary = output.with_suffix(".tmp.wav")
    if offset == 0:
        command = [
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary),
        ]
    else:
        command = [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-t", f"{offset:.6f}", "-i", "anullsrc=r=16000:cl=mono",
            "-i", str(source),
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]", "-map", "[out]",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary),
        ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    temporary.replace(output)


def make_crop(source: Path, output: Path, start: float, end: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file():
        return
    temporary = output.with_suffix(".tmp.wav")
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{start:.6f}",
            "-t", f"{end-start:.6f}", "-i", str(source), "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(temporary),
        ],
        check=True, capture_output=True, text=True,
    )
    temporary.replace(output)


def select_records(args: argparse.Namespace, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if args.split:
        records = [row for row in records if row.get("split") == args.split]
    if args.item_id:
        wanted = set(args.item_id)
        records = [row for row in records if str(row["item_id"]) in wanted]
        missing = wanted - {str(row["item_id"]) for row in records}
        if missing:
            raise ValueError(f"requested item IDs absent: {sorted(missing)[:3]}")
    if args.select_shortest:
        records = sorted(records, key=lambda row: (float(row["duration_sec"]), str(row["item_id"])))
    else:
        records = sorted(records, key=lambda row: str(row["item_id"]))
    if args.max_items:
        records = records[: args.max_items]
    if not records:
        raise ValueError("empty record selection")
    return records


def shifted_refs(rows: list[dict[str, Any]], offset: float, item_id: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        copied = dict(row)
        copied["item_id"] = item_id
        copied["start_sec"] = float(row["start_sec"]) + offset
        copied["end_sec"] = float(row["end_sec"]) + offset
        copied["source_character_index"] = int(row["character_index"])
        result.append(copied)
    return result


def cropped_refs(rows: list[dict[str, Any]], start: float, end: float, item_id: str) -> list[dict[str, Any]]:
    kept = [row for row in rows if float(row["start_sec"]) >= start and float(row["end_sec"]) <= end]
    result = []
    for index, row in enumerate(kept):
        copied = dict(row)
        copied["item_id"] = item_id
        copied["source_character_index"] = int(row["character_index"])
        copied["character_index"] = index
        copied["start_sec"] = float(row["start_sec"]) - start
        copied["end_sec"] = float(row["end_sec"]) - start
        result.append(copied)
    return result


def build_variants(
    args: argparse.Namespace,
    records: list[dict[str, Any]],
    by_item: dict[str, list[dict[str, Any]]],
    manifest_by_item: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    derived_audio = args.out_dir / "derived_audio"
    for record in records:
        source_id = str(record["item_id"])
        refs = by_item[source_id]
        source_audio = args.audio_root / str(record["audio_relpath"])
        if not source_audio.is_file():
            raise FileNotFoundError(source_audio)
        manifest = manifest_by_item.get(source_id, record)
        joins = [float(value) for value in manifest.get("join_points_sec", [])]
        if args.experiment == "existing":
            variants.append(
                {
                    "variant_item_id": source_id,
                    "source_item_id": source_id,
                    "song_id": record.get("song_id"),
                    "audio_path": source_audio,
                    "transcript": str(record["lyrics_normalized"]),
                    "refs": refs,
                    "offset_sec": 0.0,
                    "variant_kind": "full",
                    "join_points_sec": joins,
                    "duration_sec": float(record["duration_sec"]),
                }
            )
        elif args.experiment == "shift":
            for offset in parse_float_list(args.shift_offsets):
                variant_id = f"shift:{offset:.3f}:{source_id}"
                audio_path = derived_audio / "shift" / f"{hashlib.sha256(variant_id.encode()).hexdigest()[:16]}.wav"
                make_silence_prefix(source_audio, audio_path, offset)
                refs2 = shifted_refs(refs, offset, variant_id)
                variants.append(
                    {
                        "variant_item_id": variant_id,
                        "source_item_id": source_id,
                        "song_id": record.get("song_id"),
                        "audio_path": audio_path,
                        "transcript": str(record["lyrics_normalized"]),
                        "refs": refs2,
                        "offset_sec": offset,
                        "variant_kind": "shift",
                        "join_points_sec": [],
                        "duration_sec": float(record["duration_sec"]) + offset,
                    }
                )
        elif args.experiment == "crop":
            if args.include_full:
                variants.append(
                    {
                        "variant_item_id": source_id,
                        "source_item_id": source_id,
                        "song_id": record.get("song_id"),
                        "audio_path": source_audio,
                        "transcript": str(record["lyrics_normalized"]),
                        "refs": [dict(row, source_character_index=int(row["character_index"])) for row in refs],
                        "offset_sec": 0.0,
                        "variant_kind": "full",
                        "join_points_sec": joins,
                        "duration_sec": float(record["duration_sec"]),
                    }
                )
            for start, end in parse_windows(args.crop_windows):
                variant_id = f"crop:{start:.3f}:{end:.3f}:{source_id}"
                refs2 = cropped_refs(refs, start, end, variant_id)
                if len(refs2) < args.minimum_crop_characters:
                    raise ValueError(f"crop {start}:{end} keeps only {len(refs2)} characters")
                transcript = "".join(str(row["normalized_character"]) for row in refs2)
                audio_path = derived_audio / "crop" / f"{hashlib.sha256(variant_id.encode()).hexdigest()[:16]}.wav"
                make_crop(source_audio, audio_path, start, end)
                local_joins = [value - start for value in joins if start <= value <= end]
                variants.append(
                    {
                        "variant_item_id": variant_id,
                        "source_item_id": source_id,
                        "song_id": record.get("song_id"),
                        "audio_path": audio_path,
                        "transcript": transcript,
                        "refs": refs2,
                        "offset_sec": start,
                        "variant_kind": "crop",
                        "join_points_sec": local_joins,
                        "duration_sec": end - start,
                    }
                )
        else:
            raise ValueError(args.experiment)
    return variants


def tensor_audit(inputs: Any) -> dict[str, Any]:
    import torch

    result: dict[str, Any] = {}
    for name, value in inputs.items():
        if not isinstance(value, torch.Tensor):
            continue
        entry: dict[str, Any] = {"shape": list(value.shape), "dtype": str(value.dtype)}
        if value.numel():
            entry["finite_fraction"] = float(torch.isfinite(value).float().mean()) if value.is_floating_point() else 1.0
            entry["nonzero_fraction"] = float((value != 0).float().mean())
            if "mask" in name.lower():
                entry["nonzero_count_by_sample"] = [int(item.count_nonzero()) for item in value]
        result[name] = entry
    return result


def nearest_seam_distance(start: float, end: float, seams: list[float]) -> float | None:
    if not seams:
        return None
    midpoint = (start + end) / 2.0
    return min(abs(midpoint - seam) for seam in seams)


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "p90": None, "p95": None}
    ordered = sorted(values)
    def percentile(p: float) -> float:
        index = (len(ordered) - 1) * p
        lower, upper = math.floor(index), math.ceil(index)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
    }


def infer_variant(
    processor: Any,
    model: Any,
    args: argparse.Namespace,
    variant: dict[str, Any],
    model_name: str,
    checkpoint_kind: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    import torch

    audio = decode_audio(Path(variant["audio_path"]))
    inputs, word_lists = processor.prepare_forced_aligner_inputs(
        audio=[audio], transcript=[variant["transcript"]], language=args.language
    )
    audit = tensor_audit(inputs)
    batch = move_inputs(inputs, args.device, torch.bfloat16)
    with torch.inference_mode():
        output = model(**batch)
    input_ids = batch["input_ids"][0]
    positions = (input_ids == model.config.timestamp_token_id).nonzero(as_tuple=False).flatten()
    slot_logits = output.logits[0, positions].float()
    raw_classes = slot_logits.argmax(dim=-1).tolist()
    timestamp_unit_ms = float(args.timestamp_segment_sec) * 1000.0
    raw_timestamp_ms = [int(round(int(value) * timestamp_unit_ms)) for value in raw_classes]
    fixed_timestamp_ms = official_fix_timestamp(raw_timestamp_ms)
    probabilities = torch.softmax(slot_logits, dim=-1)
    top_values, top_indices = torch.topk(probabilities, k=2, dim=-1)
    entropy = -(probabilities * probabilities.clamp_min(1e-12).log()).sum(dim=-1)
    decoded = processor.decode_forced_alignment(
        output.logits, batch["input_ids"], word_lists, model.config.timestamp_token_id
    )[0]
    refs = variant["refs"]
    if len(decoded) != len(refs) or len(raw_classes) != 2 * len(refs):
        raise RuntimeError(
            f"decode/reference mismatch for {variant['variant_item_id']}: "
            f"decoded={len(decoded)} refs={len(refs)} slots={len(raw_classes)} words={len(word_lists[0])}"
        )
    segment_sec = float(args.timestamp_segment_sec)
    character_rows: list[dict[str, Any]] = []
    raw_errors: list[float] = []
    fixed_errors: list[float] = []
    repaired_slots = 0
    official_diffs: list[float] = []
    for index, (reference, item) in enumerate(zip(refs, decoded, strict=True)):
        raw_start_class, raw_end_class = int(raw_classes[2 * index]), int(raw_classes[2 * index + 1])
        reproduced_start, reproduced_end = fixed_timestamp_ms[2 * index] / 1000.0, fixed_timestamp_ms[2 * index + 1] / 1000.0
        raw_start, raw_end = raw_start_class * segment_sec, raw_end_class * segment_sec
        fixed_start, fixed_end = float(item["start_time"]), float(item["end_time"])
        gt_start, gt_end = float(reference["start_sec"]), float(reference["end_sec"])
        repaired_slots += int(abs(raw_start - reproduced_start) > 1e-9) + int(abs(raw_end - reproduced_end) > 1e-9)
        official_diffs.extend([abs(fixed_start - reproduced_start), abs(fixed_end - reproduced_end)])
        raw_errors.extend([abs(raw_start - gt_start), abs(raw_end - gt_end)])
        fixed_errors.extend([abs(fixed_start - gt_start), abs(fixed_end - gt_end)])
        slot_stats: dict[str, Any] = {}
        for boundary, slot_index in (("start", 2 * index), ("end", 2 * index + 1)):
            slot_stats[f"raw_{boundary}_top1_probability"] = float(top_values[slot_index, 0])
            slot_stats[f"raw_{boundary}_top2_probability"] = float(top_values[slot_index, 1])
            slot_stats[f"raw_{boundary}_top2_class"] = int(top_indices[slot_index, 1])
            slot_stats[f"raw_{boundary}_margin"] = float(top_values[slot_index, 0] - top_values[slot_index, 1])
            slot_stats[f"raw_{boundary}_entropy"] = float(entropy[slot_index])
        character_rows.append(
            {
                "schema_version": "qwen_fa_immediate_diagnostic_v1",
                "model_name": model_name,
                "checkpoint_kind": checkpoint_kind,
                "experiment": args.experiment,
                "variant_kind": variant["variant_kind"],
                "variant_item_id": variant["variant_item_id"],
                "source_item_id": variant["source_item_id"],
                "song_id": variant.get("song_id"),
                "variant_offset_sec": float(variant["offset_sec"]),
                "character_index": index,
                "source_character_index": int(reference.get("source_character_index", reference["character_index"])),
                "normalized_character": str(reference["normalized_character"]),
                "gt_start_sec": gt_start,
                "gt_end_sec": gt_end,
                "gt_global_start_sec": gt_start + float(variant["offset_sec"]) if variant["variant_kind"] == "crop" else gt_start,
                "gt_global_end_sec": gt_end + float(variant["offset_sec"]) if variant["variant_kind"] == "crop" else gt_end,
                "raw_start_class": raw_start_class,
                "raw_end_class": raw_end_class,
                "raw_start_sec": raw_start,
                "raw_end_sec": raw_end,
                "raw_global_start_sec": raw_start + float(variant["offset_sec"]) if variant["variant_kind"] == "crop" else raw_start,
                "raw_global_end_sec": raw_end + float(variant["offset_sec"]) if variant["variant_kind"] == "crop" else raw_end,
                "fixed_start_sec_reproduced": reproduced_start,
                "fixed_end_sec_reproduced": reproduced_end,
                "fixed_start_sec": fixed_start,
                "fixed_end_sec": fixed_end,
                "fixed_global_start_sec": fixed_start + float(variant["offset_sec"]) if variant["variant_kind"] == "crop" else fixed_start,
                "fixed_global_end_sec": fixed_end + float(variant["offset_sec"]) if variant["variant_kind"] == "crop" else fixed_end,
                "raw_start_abs_error_sec": abs(raw_start - gt_start),
                "raw_end_abs_error_sec": abs(raw_end - gt_end),
                "fixed_start_abs_error_sec": abs(fixed_start - gt_start),
                "fixed_end_abs_error_sec": abs(fixed_end - gt_end),
                "start_repaired": abs(raw_start - reproduced_start) > 1e-9,
                "end_repaired": abs(raw_end - reproduced_end) > 1e-9,
                "repair_delta_start_sec": reproduced_start - raw_start,
                "repair_delta_end_sec": reproduced_end - raw_end,
                "raw_invalid_interval": raw_start >= raw_end,
                "fixed_invalid_interval": fixed_start >= fixed_end,
                "distance_to_nearest_seam_sec": nearest_seam_distance(gt_start, gt_end, variant["join_points_sec"]),
                **slot_stats,
            }
        )
    item_summary = {
        "schema_version": "qwen_fa_immediate_item_summary_v1",
        "model_name": model_name,
        "checkpoint_kind": checkpoint_kind,
        "experiment": args.experiment,
        "variant_kind": variant["variant_kind"],
        "variant_item_id": variant["variant_item_id"],
        "source_item_id": variant["source_item_id"],
        "song_id": variant.get("song_id"),
        "variant_offset_sec": float(variant["offset_sec"]),
        "audio_duration_sec": float(audio.size / 16000.0),
        "declared_duration_sec": float(variant["duration_sec"]),
        "character_count": len(refs),
        "timestamp_slot_count": len(raw_classes),
        "repaired_slot_count": repaired_slots,
        "repaired_slot_rate": repaired_slots / len(raw_classes),
        "raw_boundary_error_sec": quantiles(raw_errors),
        "fixed_boundary_error_sec": quantiles(fixed_errors),
        "repair_amplification_mean_sec": statistics.fmean(fixed_errors) - statistics.fmean(raw_errors),
        "official_vs_reproduced_fix_max_abs_sec": max(official_diffs) if official_diffs else None,
    }
    input_audit = {
        "schema_version": "qwen_fa_immediate_input_audit_v1",
        "model_name": model_name,
        "experiment": args.experiment,
        "variant_item_id": variant["variant_item_id"],
        "source_item_id": variant["source_item_id"],
        "variant_kind": variant["variant_kind"],
        "variant_offset_sec": float(variant["offset_sec"]),
        "audio_path": str(variant["audio_path"]),
        "audio_sha256": sha256(Path(variant["audio_path"])),
        "decoded_num_samples": int(audio.size),
        "decoded_duration_sec": float(audio.size / 16000.0),
        "transcript_character_count": len(variant["transcript"]),
        "word_count": len(word_lists[0]),
        "timestamp_position_count": int(len(positions)),
        "tensors": audit,
    }
    return character_rows, item_summary, input_audit


def run_task(
    args: argparse.Namespace,
    *,
    processor: Any | None = None,
    model: Any | None = None,
    checkpoint_identity: dict[str, Any] | None = None,
    checkpoint_kind: str | None = None,
) -> dict[str, Any]:
    if args.max_items < 0:
        raise ValueError("--max-items must be non-negative")
    records = select_records(args, read_jsonl(args.labels))
    by_item = group_characters(args.characters)
    missing = [str(row["item_id"]) for row in records if str(row["item_id"]) not in by_item]
    if missing:
        raise ValueError(f"missing character references: {missing[:3]}")
    manifest_rows = read_jsonl(args.manifest) if args.manifest else []
    manifest_by_item = {str(row["item_id"]): row for row in manifest_rows}
    variants = build_variants(args, records, by_item, manifest_by_item)
    if processor is None or model is None:
        processor, model, loaded_identity, loaded_kind = load_model(args)
        checkpoint_identity = loaded_identity
        checkpoint_kind = loaded_kind
    assert processor is not None and model is not None
    assert checkpoint_identity is not None and checkpoint_kind is not None
    character_rows: list[dict[str, Any]] = []
    item_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        rows, summary, audit = infer_variant(
            processor, model, args, variant, args.model_name, checkpoint_kind
        )
        character_rows.extend(rows)
        item_rows.append(summary)
        audit_rows.append(audit)
        print(
            json.dumps(
                {"completed": index, "total": len(variants), "variant": variant["variant_item_id"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    atomic_jsonl(args.out_dir / "diagnostic_rows.jsonl", character_rows)
    atomic_jsonl(args.out_dir / "item_summary.jsonl", item_rows)
    atomic_jsonl(args.out_dir / "input_audit.jsonl", audit_rows)
    identity = {
        "schema_version": "qwen_fa_immediate_diagnostic_identity_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_name": args.model_name,
        "model_id": args.model,
        "revision": args.revision,
        "checkpoint": str(args.checkpoint) if args.checkpoint else None,
        "checkpoint_identity": checkpoint_identity,
        "experiment": args.experiment,
        "labels": str(args.labels),
        "labels_sha256": sha256(args.labels),
        "characters": str(args.characters),
        "characters_sha256": sha256(args.characters),
        "manifest": str(args.manifest) if args.manifest else None,
        "manifest_sha256": sha256(args.manifest) if args.manifest else None,
        "audio_root": str(args.audio_root),
        "selected_source_items": [str(row["item_id"]) for row in records],
        "variant_count": len(variants),
        "character_row_count": len(character_rows),
        "timestamp_segment_sec": args.timestamp_segment_sec,
        "diagnostic_only": True,
    }
    atomic_json(args.out_dir / "identity.json", identity)
    print(
        json.dumps(
            {"out_dir": str(args.out_dir), "variants": len(variants), "rows": len(character_rows)},
            ensure_ascii=False,
        )
    )
    return identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-kind", choices=("auto", "raw", "projector", "lora"), default="auto")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--experiment", choices=("existing", "shift", "crop"), required=True)
    parser.add_argument("--split")
    parser.add_argument("--item-id", action="append", default=[])
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--select-shortest", action="store_true")
    parser.add_argument("--shift-offsets", default="0,30,60,120,180,240")
    parser.add_argument("--crop-windows", default="90:120,110:150,120:140,140:151")
    parser.add_argument("--include-full", action="store_true")
    parser.add_argument("--minimum-crop-characters", type=int, default=4)
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    return parser


def main() -> None:
    run_task(build_parser().parse_args())


if __name__ == "__main__":
    main()
