#!/usr/bin/env python3
"""Run dense absolute-position and total-input-length probes with one model load."""
from __future__ import annotations

import argparse
from argparse import Namespace
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "qwen_fa_immediate_collector", HERE / "collect_qwen_fa_immediate_diagnostics.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load immediate diagnostic collector")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def checkpoint_request_identity(kind: str, checkpoint: Path | None) -> dict[str, Any]:
    if kind == "raw":
        return {"checkpoint_kind": kind}
    if checkpoint is None:
        raise ValueError(f"{kind} requires checkpoint")
    result: dict[str, Any] = {
        "checkpoint_kind": kind,
        "checkpoint_path": str(checkpoint.resolve()),
        "projector_sha256": collector.sha256(checkpoint / "projector.pt"),
    }
    if kind == "lora":
        result["adapter_model_sha256"] = collector.sha256(
            checkpoint / "adapter" / "adapter_model.safetensors"
        )
        result["adapter_config_sha256"] = collector.sha256(
            checkpoint / "adapter" / "adapter_config.json"
        )
    return result


def task_current(path: Path, request_hash: str) -> bool:
    required = ("identity.json", "diagnostic_rows.jsonl", "item_summary.jsonl", "input_audit.jsonl")
    if not all((path / name).is_file() for name in required):
        return False
    try:
        identity = json.loads((path / "identity.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return identity.get("request_hash") == request_hash


def archive_stale(path: Path) -> None:
    if not path.exists():
        return
    candidate = path.with_name(path.name + ".identity_mismatch")
    counter = 0
    while candidate.exists():
        counter += 1
        candidate = path.with_name(path.name + f".identity_mismatch.{counter}")
    path.rename(candidate)


def task_args(base: argparse.Namespace, *, experiment: str, out_dir: Path, request_hash: str) -> Namespace:
    return Namespace(
        model=base.model,
        revision=base.revision,
        model_name=base.model_name,
        checkpoint=base.checkpoint,
        checkpoint_kind=base.checkpoint_kind,
        labels=base.labels,
        characters=base.characters,
        manifest=None,
        audio_root=base.audio_root,
        out_dir=out_dir,
        experiment=experiment,
        split=base.split,
        item_id=[],
        max_items=base.sample_count,
        select_shortest=True,
        shift_offsets=base.shift_offsets,
        target_durations=base.target_durations,
        crop_windows="90:120",
        include_full=False,
        minimum_crop_characters=4,
        timestamp_segment_sec=base.timestamp_segment_sec,
        device=base.device,
        language=base.language,
        cache_dir=base.cache_dir,
        local_files_only=base.local_files_only,
        request_hash=request_hash,
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
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--shift-offsets", default="0,90,105,115,120,125,135,150")
    parser.add_argument("--target-durations", default="0,60,90,105,115,120,125,135,150,180")
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    shift_values = collector.parse_float_list(args.shift_offsets)
    target_values = collector.parse_float_list(args.target_durations)
    if not any(abs(value) < 1e-9 for value in shift_values):
        raise ValueError("--shift-offsets must include 0 for the baseline")
    if not any(abs(value) < 1e-9 for value in target_values):
        raise ValueError("--target-durations must include 0 for the native-duration baseline")

    common_request = {
        "schema_version": "qwen_fa_120_quick_feedback_request_v1",
        "model_name": args.model_name,
        "model_id": args.model,
        "revision": args.revision,
        "checkpoint": checkpoint_request_identity(args.checkpoint_kind, args.checkpoint),
        "labels_sha256": collector.sha256(args.labels),
        "characters_sha256": collector.sha256(args.characters),
        "audio_root": str(args.audio_root.resolve()),
        "split": args.split,
        "sample_count": args.sample_count,
        "timestamp_segment_sec": args.timestamp_segment_sec,
    }
    task_specs = []
    for experiment, parameters in (
        ("shift", {"shift_offsets": shift_values}),
        ("tailpad", {"target_durations": target_values}),
    ):
        request = {**common_request, "experiment": experiment, **parameters}
        request_hash = canonical_hash(request)
        out_dir = args.out_root / experiment
        task_specs.append((task_args(args, experiment=experiment, out_dir=out_dir, request_hash=request_hash), request_hash))

    pending = []
    for task, request_hash in task_specs:
        if not args.force and task_current(task.out_dir, request_hash):
            print(json.dumps({"skip": str(task.out_dir), "reason": "identity match"}), flush=True)
        else:
            archive_stale(task.out_dir)
            pending.append(task)
    if not pending:
        print(json.dumps({"model": args.model_name, "status": "already_complete"}), flush=True)
        return

    processor, model, identity, kind = collector.load_model(args)
    for task in pending:
        collector.run_task(
            task,
            processor=processor,
            model=model,
            checkpoint_identity=identity,
            checkpoint_kind=kind,
        )
    print(json.dumps({"model": args.model_name, "status": "complete", "tasks": len(pending)}))


if __name__ == "__main__":
    main()
