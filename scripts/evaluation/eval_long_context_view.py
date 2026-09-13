#!/usr/bin/env python3
"""Primary endpoint of the long-context arm: score checkpoints on a concatenated validation view.

The arm is trained on ~20 s streams assembled from consecutive phrases of the same song, so the
pre-registered endpoint must use the same construction on the *validation* split (see
`docs/status/20260914_concat_arm_prereg.md`).  References come from the merged label bins, which are
themselves the source TextGrid annotation quantised to 80 ms — the same ground truth as the short-item
evaluation, just seen as a long stream.

    PYTHONPATH=src python scripts/evaluation/eval_long_context_view.py \
        --run-dir /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_concat20b_seed20260724 \
        --checkpoint <ckpt dir> [--checkpoint <another>] \
        --out results/by_run/20260914_long_context_view/metrics.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.training.qwen_fa_concat import QwenFAConcatCollator, group_concat_records  # noqa: E402
from lyricalign.training.qwen_fa_runtime import read_jsonl  # noqa: E402


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOPUP = load_module("run_funnel_topup", ROOT / "scripts" / "training" / "run_funnel_topup.py")
STEP_SEC = 0.08


def merged_reference(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Character intervals implied by the merged label bins (the ground truth of the long view)."""
    ids = record["timestamp_class_ids"]
    item = str(record["item_id"])
    song = str(record.get("song_id") or item)
    return [{"item_id": item, "song_id": song, "character_index": index,
             "normalized_character": str(record["lyrics_normalized"][index])
             if index < len(record.get("lyrics_normalized", "")) else "?",
             "start_sec": ids[2 * index] * STEP_SEC, "end_sec": ids[2 * index + 1] * STEP_SEC}
            for index in range(len(ids) // 2)]


def drift_profile(variants: dict[str, Any], references: dict[str, list[dict[str, Any]]],
                  *, bucket_sec: float = 5.0, tolerance: float = 0.2) -> dict[str, Any]:
    """Error as a function of elapsed stream time — the absolute-time-tracking signature.

    If the model tracked a long stream well, the error would be flat in elapsed time; growth means
    the timestamp head loses registration as the stream goes on, which is exactly what the
    long-context arm is meant to fix, and it is invisible in the short-item view.
    """
    onset_of: dict[tuple[str, int], float] = {}
    for item, rows in references.items():
        for row in rows:
            onset_of[(item, int(row["character_index"]))] = float(row["start_sec"])
    out: dict[str, Any] = {}
    for variant, metric in variants.items():
        per_unit = metric.get("per_unit") or []
        groups: dict[int, list[float]] = {}
        for row in per_unit:
            key = (str(row["item_id"]), int(row["character_index"]))
            if key not in onset_of:
                continue
            bucket = int(onset_of[key] // bucket_sec)
            groups.setdefault(bucket, []).append(float(row["max_boundary_err_sec"]))
        out[variant] = {f"{index * bucket_sec:g}-{(index + 1) * bucket_sec:g}s": {
            "characters": len(values),
            "median_err_ms": round(1000.0 * st.median(values), 1),
            "mean_err_ms": round(1000.0 * sum(values) / len(values), 1),
            "miss_rate": round(sum(1 for value in values if value > tolerance) / len(values), 4)}
            for index, values in sorted(groups.items()) if values}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True, help="run providing config.yaml")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--checkpoint", action="append", default=[], required=True,
                        help="label=<checkpoint dir>; repeatable")
    parser.add_argument("--target-sec", type=float, default=20.0)
    parser.add_argument("--max-sec", type=float, default=28.0)
    parser.add_argument("--gap-sec", type=float, default=0.4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoProcessor

    cfg = yaml.safe_load((args.config or (args.run_dir / "config.yaml")).read_text(encoding="utf-8"))
    labels = read_jsonl(Path(cfg["data"]["labels"]))
    valid = [row for row in labels if row["split"] == "validation"]
    records, stats = group_concat_records(valid, target_sec=args.target_sec, max_sec=args.max_sec,
                                          gap_sec=args.gap_sec)
    if args.limit:
        records = records[: args.limit]
    references = {str(record["item_id"]): merged_reference(record) for record in records}

    processor = AutoProcessor.from_pretrained(cfg["model"]["id"], revision=cfg["model"]["revision"],
                                              local_files_only=True)
    model, _ = TOPUP.build_stage_model(cfg, "r2", args.device, True)
    collator = QwenFAConcatCollator(processor, audio_root=Path(cfg["data"]["audio_root"]),
                                    language=cfg["data"]["language"],
                                    timestamp_token_id=model.config.timestamp_token_id,
                                    gap_sec=args.gap_sec)
    payload: dict[str, Any] = {"schema_version": "long_context_view_v1", "config": str(args.config or args.run_dir / "config.yaml"),
                               "concat_stats": stats, "eval_records": len(records),
                               "eval_characters": sum(len(value) for value in references.values()),
                               "eval_songs": len({str(row.get("song_id")) for row in records}),
                               "tolerances_sec": list(TOPUP.DEFAULT_TOLERANCES_SEC), "checkpoints": {}}
    for spec in args.checkpoint:
        if "=" not in spec:
            raise SystemExit(f"--checkpoint needs label=<dir>, got {spec!r}")
        label, path = spec.split("=", 1)
        loaded_step = TOPUP.load_weights(Path(path), model)
        outcome = TOPUP.evaluate_variants(model, processor, collator, records, references,
                                          device=args.device,
                                          dtype=getattr(torch, cfg["training"].get("dtype", "bfloat16")),
                                          batch_size=args.batch_size,
                                          segment_sec=float(cfg["training"].get("timestamp_segment_sec", STEP_SEC)),
                                          keep_per_unit=True)
        payload["checkpoints"][label] = {"checkpoint": str(path), "loaded_step": loaded_step,
                                         "drift_profile": drift_profile(outcome["variants"], references),
                                         "val_loss": outcome["val_loss"],
                                         "variants": outcome["variants"],
                                         "summary": outcome["variants_summary"]}
        summary = outcome["variants_summary"]
        print(f"{label}: " + "  ".join(f"{name}={block['macro_within_primary']:.4f}"
                                       f"(usable {block['usable_rate']:.4f}, mae {block['mae_all_ms']:.0f}ms)"
                                       for name, block in summary.items()), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(args.out), "records": payload["eval_records"],
                      "characters": payload["eval_characters"], "songs": payload["eval_songs"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
