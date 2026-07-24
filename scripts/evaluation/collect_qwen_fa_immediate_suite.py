#!/usr/bin/env python3
"""Run all immediate diagnostics for one model with a single model load."""
from __future__ import annotations

import argparse
import importlib.util
import json
from argparse import Namespace
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


def task_complete(path: Path) -> bool:
    return all((path / name).is_file() for name in ("identity.json", "diagnostic_rows.jsonl", "item_summary.jsonl", "input_audit.jsonl"))


def task_args(base: argparse.Namespace, **updates: Any) -> Namespace:
    values = {
        "model": base.model,
        "revision": base.revision,
        "model_name": base.model_name,
        "checkpoint": base.checkpoint,
        "checkpoint_kind": base.checkpoint_kind,
        "device": base.device,
        "language": base.language,
        "cache_dir": base.cache_dir,
        "local_files_only": base.local_files_only,
        "item_id": [],
        "max_items": 0,
        "select_shortest": False,
        "shift_offsets": base.shift_offsets,
        "crop_windows": base.crop_windows,
        "include_full": False,
        "minimum_crop_characters": base.minimum_crop_characters,
        "timestamp_segment_sec": base.timestamp_segment_sec,
        "manifest": None,
        "split": "test",
    }
    values.update(updates)
    return Namespace(**values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-kind", choices=("raw", "projector", "lora"), required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--m4-labels", type=Path, required=True)
    parser.add_argument("--m4-characters", type=Path, required=True)
    parser.add_argument("--m4-audio-root", type=Path, required=True)
    parser.add_argument("--mir-labels", type=Path, required=True)
    parser.add_argument("--mir-characters", type=Path, required=True)
    parser.add_argument("--mir-audio-root", type=Path, required=True)
    parser.add_argument("--long-labels", type=Path, required=True)
    parser.add_argument("--long-characters", type=Path, required=True)
    parser.add_argument("--long-manifest", type=Path, required=True)
    parser.add_argument("--long-audio-root", type=Path, required=True)
    parser.add_argument("--outlier-item-id", required=True)
    parser.add_argument("--shift-offsets", default="0,30,60,120,180,240")
    parser.add_argument("--crop-windows", default="90:120,110:150,120:140,140:151")
    parser.add_argument("--long-max-items", type=int, default=0)
    parser.add_argument("--mir-max-items", type=int, default=0)
    parser.add_argument("--minimum-crop-characters", type=int, default=4)
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    tasks = [
        task_args(
            args,
            experiment="existing",
            labels=args.long_labels,
            characters=args.long_characters,
            manifest=args.long_manifest,
            audio_root=args.long_audio_root,
            out_dir=args.out_root / "existing_b180",
            max_items=args.long_max_items,
        ),
        task_args(
            args,
            experiment="shift",
            labels=args.m4_labels,
            characters=args.m4_characters,
            audio_root=args.m4_audio_root,
            out_dir=args.out_root / "shift",
            max_items=1,
            select_shortest=True,
        ),
        task_args(
            args,
            experiment="crop",
            labels=args.long_labels,
            characters=args.long_characters,
            manifest=args.long_manifest,
            audio_root=args.long_audio_root,
            out_dir=args.out_root / "crop_outlier",
            item_id=[args.outlier_item_id],
            include_full=True,
        ),
        task_args(
            args,
            experiment="existing",
            labels=args.mir_labels,
            characters=args.mir_characters,
            audio_root=args.mir_audio_root,
            out_dir=args.out_root / "existing_mir1k",
            max_items=args.mir_max_items,
        ),
    ]
    pending = [task for task in tasks if not task_complete(task.out_dir)]
    if not pending:
        print(json.dumps({"model": args.model_name, "status": "already_complete"}))
        return
    processor, model, identity, kind = collector.load_model(args)
    for task in tasks:
        if task_complete(task.out_dir):
            print(json.dumps({"skip": str(task.out_dir)}, ensure_ascii=False), flush=True)
            continue
        if task.out_dir.exists():
            archived = task.out_dir.with_name(task.out_dir.name + ".incomplete")
            counter = 0
            while archived.exists():
                counter += 1
                archived = task.out_dir.with_name(task.out_dir.name + f".incomplete.{counter}")
            task.out_dir.rename(archived)
        collector.run_task(
            task,
            processor=processor,
            model=model,
            checkpoint_identity=identity,
            checkpoint_kind=kind,
        )
    print(json.dumps({"model": args.model_name, "status": "complete", "task_count": len(tasks)}))


if __name__ == "__main__":
    main()
