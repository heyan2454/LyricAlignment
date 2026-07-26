#!/usr/bin/env python3
"""Run reproducible MIR-1K context, separator, and serial-propagation probes.

MIR-1K is test-only.  The development subset may be used to choose a demo
configuration; the held-out subset is reserved for one confirmation run.
Oracle-window experiments use GT only to define window transcript coverage and
evaluation ownership.  GT timestamps are never passed to the aligner.
"""
from __future__ import annotations

import argparse
import bisect
import gc
import importlib.util
import json
import math
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.alignment_artifacts import stage_rows
from lyricalign.demo.karaoke import build_serial_windows, parse_lyrics_text
from lyricalign.training.qwen_fa_runtime import decode_audio


def load_serial_module() -> Any:
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("lyricalign_serial_demo_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load serial demo module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERIAL = load_serial_module()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def quantile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def metric_summary(errors: list[dict[str, Any]]) -> dict[str, Any]:
    onset_abs = [row["onset_abs_error_sec"] for row in errors]
    offset_abs = [row["offset_abs_error_sec"] for row in errors]
    onset_signed = [row["onset_signed_error_sec"] for row in errors]
    offset_signed = [row["offset_signed_error_sec"] for row in errors]
    result: dict[str, Any] = {
        "matched_unit_count": len(errors),
        "onset_mae_sec": statistics.fmean(onset_abs) if onset_abs else None,
        "onset_median_sec": quantile(onset_abs, 0.5),
        "onset_p90_sec": quantile(onset_abs, 0.9),
        "onset_max_sec": max(onset_abs, default=None),
        "offset_mae_sec": statistics.fmean(offset_abs) if offset_abs else None,
        "offset_median_sec": quantile(offset_abs, 0.5),
        "offset_p90_sec": quantile(offset_abs, 0.9),
        "offset_max_sec": max(offset_abs, default=None),
        "onset_signed_mean_sec": statistics.fmean(onset_signed) if onset_signed else None,
        "offset_signed_mean_sec": statistics.fmean(offset_signed) if offset_signed else None,
    }
    for tolerance in (0.08, 0.16, 0.24, 0.5, 1.0):
        key = str(tolerance).replace(".", "p")
        result[f"onset_within_{key}_rate"] = (
            sum(value <= tolerance for value in onset_abs) / len(onset_abs) if onset_abs else None
        )
        result[f"joint_onset_offset_within_{key}_rate"] = (
            sum(
                row["onset_abs_error_sec"] <= tolerance and row["offset_abs_error_sec"] <= tolerance
                for row in errors
            ) / len(errors) if errors else None
        )
    return result


def evaluate_rows(
    predictions: Iterable[dict[str, Any]],
    gt_by_index: dict[int, dict[str, Any]],
    indices: Iterable[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pred_by_index = {int(row["global_character_index"]): row for row in predictions}
    index_list = list(indices)
    details: list[dict[str, Any]] = []
    missing: list[int] = []
    for index in index_list:
        if index not in pred_by_index:
            missing.append(index)
            continue
        gt = gt_by_index[index]
        pred = pred_by_index[index]
        pred_start = float(pred["start_sec"])
        pred_end = float(pred["end_sec"])
        gt_start = float(gt["start_sec"])
        gt_end = float(gt["end_sec"])
        details.append({
            "character_index": index,
            "character": gt.get("normalized_character") or gt.get("character"),
            "gt_start_sec": gt_start,
            "gt_end_sec": gt_end,
            "pred_start_sec": pred_start,
            "pred_end_sec": pred_end,
            "onset_signed_error_sec": pred_start - gt_start,
            "offset_signed_error_sec": pred_end - gt_end,
            "onset_abs_error_sec": abs(pred_start - gt_start),
            "offset_abs_error_sec": abs(pred_end - gt_end),
            "raw_start_top1_probability": pred.get("raw_start_top1_probability"),
            "raw_end_top1_probability": pred.get("raw_end_top1_probability"),
            "raw_start_margin": pred.get("raw_start_margin"),
            "raw_end_margin": pred.get("raw_end_margin"),
            "raw_start_entropy": pred.get("raw_start_entropy"),
            "raw_end_entropy": pred.get("raw_end_entropy"),
        })
    summary = metric_summary(details)
    summary.update({
        "requested_unit_count": len(index_list),
        "missing_unit_count": len(missing),
        "missing_indices": missing,
    })
    return summary, details


def audio_variant_path(item_root: Path, variant: str, demucs_model: str) -> Path:
    mapping = {
        "mix": item_root / "audio" / "mix.wav",
        "official_vocal": item_root / "audio" / "official_vocal.wav",
        "spleeter": item_root / "audio" / "spleeter_vocals.wav",
        "demucs": item_root / "audio" / f"demucs_{demucs_model}_vocals.wav",
    }
    return mapping[variant]


def verify_document_gt(document: Any, gt: list[dict[str, Any]]) -> None:
    ordered = sorted(gt, key=lambda row: int(row["character_index"]))
    if len(document.characters) != len(ordered):
        raise ValueError(f"lyrics/GT unit count mismatch: {len(document.characters)} != {len(ordered)}")
    for meta, row in zip(document.characters, ordered, strict=True):
        expected = row.get("normalized_character") or row.get("character")
        if expected is not None and str(expected) != meta.text:
            raise ValueError(
                f"lyrics/GT mismatch at {meta.global_index}: lyrics={meta.text!r} gt={expected!r}"
            )


def crop_audio(audio: np.ndarray, start_sec: float, end_sec: float) -> np.ndarray:
    start = max(0, int(round(start_sec * 16000)))
    end = min(len(audio), int(round(end_sec * 16000)))
    if end <= start:
        raise ValueError(f"empty crop {start_sec}-{end_sec}")
    return audio[start:end]


def candidate_bounds(
    gt: list[dict[str, Any]],
    *,
    input_start_sec: float,
    input_end_sec: float,
    core_start_sec: float,
    core_end_sec: float,
    future_text_sec: float,
    left_text_policy: str,
) -> tuple[int, int, list[int]]:
    starts = [float(row["start_sec"]) for row in gt]
    ends = [float(row["end_sec"]) for row in gt]
    if left_text_policy == "matched":
        begin = bisect.bisect_right(ends, input_start_sec)
    elif left_text_policy == "omit":
        begin = bisect.bisect_left(starts, core_start_sec)
    else:
        raise ValueError(left_text_policy)
    evaluation = [
        index for index, row in enumerate(gt)
        if float(row["start_sec"]) >= core_start_sec
        and (float(row["start_sec"]) < core_end_sec or math.isclose(core_end_sec, float(gt[-1]["end_sec"])))
    ]
    if not evaluation:
        return begin, begin, []
    limit = input_end_sec + future_text_sec
    end = bisect.bisect_right(starts, limit)
    end = max(end, max(evaluation) + 1)
    begin = min(begin, min(evaluation))
    return begin, min(end, len(gt)), evaluation


def oracle_trial(
    *,
    processor: Any,
    model: Any,
    audio: np.ndarray,
    document: Any,
    gt: list[dict[str, Any]],
    args: argparse.Namespace,
    future_text_sec: float,
    left_text_policy: str,
) -> dict[str, Any]:
    duration = len(audio) / 16000.0
    windows = build_serial_windows(
        duration,
        core_sec=args.oracle_core_sec,
        left_context_sec=args.left_context_sec,
        right_context_sec=args.right_context_sec,
    )
    stage_predictions: dict[str, list[dict[str, Any]]] = {"raw": [], "processor_decoded": []}
    evaluated_indices: list[int] = []
    window_records: list[dict[str, Any]] = []
    for window in windows:
        core_start = float(window["core_start_sec"])
        core_end = float(window["core_end_sec"])
        input_start = float(window["input_start_sec"])
        input_end = float(window["input_end_sec"])
        char_start, char_end, owned = candidate_bounds(
            gt,
            input_start_sec=input_start,
            input_end_sec=input_end,
            core_start_sec=core_start,
            core_end_sec=core_end,
            future_text_sec=future_text_sec,
            left_text_policy=left_text_policy,
        )
        if not owned:
            continue
        rows, audit = SERIAL.infer_slice(
            processor=processor,
            model=model,
            audio=crop_audio(audio, input_start, input_end),
            document=document,
            character_start=char_start,
            character_end=char_end,
            global_audio_offset_sec=input_start,
            args=args,
        )
        raw = stage_rows(rows, "raw")
        fixed = stage_rows(rows, "processor_decoded")
        owned_set = set(owned)
        stage_predictions["raw"].extend(row for row in raw if int(row["global_character_index"]) in owned_set)
        stage_predictions["processor_decoded"].extend(
            row for row in fixed if int(row["global_character_index"]) in owned_set
        )
        evaluated_indices.extend(owned)
        window_records.append({
            "window_index": int(window["window_index"]),
            "core": [core_start, core_end],
            "input": [input_start, input_end],
            "candidate_character_range": [char_start, char_end],
            "evaluated_character_range": [min(owned), max(owned) + 1],
            "candidate_character_count": char_end - char_start,
            "evaluated_character_count": len(owned),
            "future_text_sec": future_text_sec,
            "left_text_policy": left_text_policy,
            "inference_audit": audit,
        })
    gt_by_index = {int(row["character_index"]): row for row in gt}
    metrics: dict[str, Any] = {}
    details: dict[str, Any] = {}
    unique_indices = sorted(set(evaluated_indices))
    for stage, predictions in stage_predictions.items():
        metrics[stage], details[stage] = evaluate_rows(predictions, gt_by_index, unique_indices)
    return {
        "mode": "oracle_independent_windows",
        "future_text_sec": future_text_sec,
        "left_text_policy": left_text_policy,
        "metrics": metrics,
        "errors": details,
        "windows": window_records,
    }


def serial_trial(
    *, processor: Any, model: Any, audio: np.ndarray, document: Any,
    gt: list[dict[str, Any]], args: argparse.Namespace,
) -> dict[str, Any]:
    rows, trace = SERIAL.windowed_alignment(processor, model, audio, document, args)
    gt_by_index = {int(row["character_index"]): row for row in gt}
    indices = sorted(gt_by_index)
    metrics: dict[str, Any] = {}
    details: dict[str, Any] = {}
    for stage in ("raw", "processor_decoded", "selected", "final"):
        projected = stage_rows(rows, stage)
        metrics[stage], details[stage] = evaluate_rows(projected, gt_by_index, indices)
    return {
        "mode": "current_v6_serial_propagation",
        "metrics": metrics,
        "errors": details,
        "window_trace": trace,
    }


def aggregate_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        condition = trial["condition_id"]
        for stage, details in trial["result"]["errors"].items():
            grouped.setdefault(f"{condition}:{stage}", []).extend(details)
    return {key: metric_summary(rows) for key, rows in sorted(grouped.items())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--experiment", choices=("context", "separator", "serial"), required=True)
    parser.add_argument("--role", choices=("development", "heldout"), default="development")
    parser.add_argument("--item-id", action="append", default=[])
    parser.add_argument("--model-kind", choices=("raw", "projector", "lora"), default="lora")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--model", default=os.environ.get("MODEL_ID", "Qwen/Qwen3-ForcedAligner-0.6B-hf"))
    parser.add_argument("--revision", default=os.environ.get("MODEL_REVISION", "c07281df297b9905d24a508279258cccf987a064"))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true", default=os.environ.get("HF_HUB_OFFLINE") == "1")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--demucs-model", default="htdemucs_ft")
    parser.add_argument("--audio-variant", choices=("mix", "official_vocal", "spleeter", "demucs"), default="official_vocal")
    parser.add_argument("--audio-variants", nargs="+", choices=("mix", "official_vocal", "spleeter", "demucs"), default=["mix", "official_vocal", "spleeter", "demucs"])
    parser.add_argument("--future-text-sec", nargs="+", type=float, default=[0.0, 5.0, 15.0, 30.0])
    parser.add_argument("--left-text-policies", nargs="+", choices=("matched", "omit"), default=["matched"])
    parser.add_argument("--separator-future-text-sec", type=float, default=5.0)
    parser.add_argument("--oracle-core-sec", type=float, default=30.0)
    parser.add_argument("--core-sec", type=float, default=60.0)
    parser.add_argument("--left-context-sec", type=float, default=10.0)
    parser.add_argument("--right-context-sec", type=float, default=10.0)
    parser.add_argument("--future-line-padding", type=int, default=1)
    parser.add_argument("--minimum-forward-characters", type=int, default=64)
    parser.add_argument("--future-character-ratio", type=float, default=1.35)
    parser.add_argument("--max-candidate-expansions", type=int, default=4)
    parser.add_argument("--boundary-start-tolerance-sec", type=float, default=0.32)
    parser.add_argument("--seam-tolerance-sec", type=float, default=0.16)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    selection = read_jsonl(args.subset_root / "selection.jsonl")
    selected = [row for row in selection if row["selection_role"] == args.role]
    if args.item_id:
        wanted = set(args.item_id)
        selected = [row for row in selected if str(row["item_id"]) in wanted]
    if not selected:
        raise ValueError("no MIR-1K items selected")
    checkpoint = args.checkpoint.resolve() if args.checkpoint else None
    identity = SERIAL.checkpoint_identity(args.model_kind, checkpoint)
    processor, model = SERIAL.load_model(args, args.model_kind, checkpoint)
    trials: list[dict[str, Any]] = []
    try:
        for selected_row in selected:
            item_id = str(selected_row["item_id"])
            item_root = args.subset_root / "items" / item_id
            document = parse_lyrics_text((item_root / "lyrics.txt").read_text(encoding="utf-8"), language="Chinese")
            gt = sorted(read_jsonl(item_root / "ground_truth.characters.jsonl"), key=lambda row: int(row["character_index"]))
            verify_document_gt(document, gt)
            if args.experiment == "context":
                variants = [args.audio_variant]
                conditions = [
                    (f"future_{future:g}s_left_{left}", future, left)
                    for left in args.left_text_policies for future in args.future_text_sec
                ]
            elif args.experiment == "separator":
                variants = args.audio_variants
                conditions = [(f"separator_{variant}", args.separator_future_text_sec, "matched") for variant in variants]
            else:
                variants = args.audio_variants
                conditions = [(f"serial_{variant}", None, None) for variant in variants]

            for condition_id, future, left in conditions:
                variant = condition_id.split("separator_", 1)[1] if condition_id.startswith("separator_") else (
                    condition_id.split("serial_", 1)[1] if condition_id.startswith("serial_") else variants[0]
                )
                path = audio_variant_path(item_root, variant, args.demucs_model)
                if not path.is_file():
                    raise FileNotFoundError(f"missing {variant} audio for {item_id}: {path}")
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.reset_peak_memory_stats()
                except ImportError:
                    torch = None
                trial_started = time.perf_counter()
                audio = decode_audio(path)
                if args.experiment == "serial":
                    result = serial_trial(processor=processor, model=model, audio=audio, document=document, gt=gt, args=args)
                else:
                    result = oracle_trial(
                        processor=processor,
                        model=model,
                        audio=audio,
                        document=document,
                        gt=gt,
                        args=args,
                        future_text_sec=float(future),
                        left_text_policy=str(left),
                    )
                elapsed_sec = time.perf_counter() - trial_started
                peak_gpu_memory_bytes = None
                try:
                    if torch is not None and torch.cuda.is_available():
                        peak_gpu_memory_bytes = int(torch.cuda.max_memory_allocated())
                except (NameError, RuntimeError):
                    pass
                payload = {
                    "schema_version": "mir1k_demo_diagnostic_trial_v1",
                    "experiment": args.experiment,
                    "role": args.role,
                    "item_id": item_id,
                    "condition_id": condition_id,
                    "audio_variant": variant,
                    "audio_path": str(path.resolve()),
                    "model": args.model,
                    "revision": args.revision,
                    "checkpoint_identity": identity,
                    "runtime": {
                        "trial_wall_sec_including_audio_decode": elapsed_sec,
                        "peak_gpu_memory_allocated_bytes": peak_gpu_memory_bytes,
                        "model_load_excluded": True,
                    },
                    "result": result,
                }
                output = args.out_dir / args.experiment / args.role / condition_id / f"{item_id}.json"
                atomic_json(output, payload)
                trials.append(payload)
                print(json.dumps({"completed": str(output), "condition": condition_id, "item_id": item_id}, ensure_ascii=False), flush=True)
    finally:
        del model
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    summary = {
        "schema_version": "mir1k_demo_diagnostic_summary_v1",
        "experiment": args.experiment,
        "role": args.role,
        "test_only": True,
        "heldout_selection_rule": "heldout may be run once only after freezing the chosen configuration",
        "trial_count": len(trials),
        "checkpoint_identity": identity,
        "aggregate": aggregate_trials(trials),
        "trials": [
            {
                "item_id": trial["item_id"],
                "condition_id": trial["condition_id"],
                "audio_variant": trial["audio_variant"],
            }
            for trial in trials
        ],
    }
    atomic_json(args.out_dir / args.experiment / args.role / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
