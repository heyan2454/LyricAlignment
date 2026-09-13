#!/usr/bin/env python3
"""Price a ship-ready decode rule on the whole validation split: snap offsets to the next onset.

`contiguity_offset_test.py` showed, on already-collected dumps, that borrowing the next character's
predicted onset beats the model's own offset slot (miss rate 2.05% -> 1.23%).  That test could use
the annotation's contiguity, which is unknown at inference.  This script evaluates the *inference
legal* version: a forward-only snap that closes predicted gaps of at most G, swept over G, against
the independent argmax and the monotone Viterbi decode — one forward pass, three policies, on the
exact test-scale metric and the label-defined subsets used everywhere else.

    PYTHONPATH=src python scripts/evaluation/eval_snap_rule.py \
        --run-dir /home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724 \
        --checkpoint /home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/checkpoints/step-012000 \
        --device cpu --out results/by_run/20260914_snap_rule/metrics.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import yaml  # noqa: E402

from lyricalign.inference.constrained_timestamps import slot_logprobs, viterbi_monotone  # noqa: E402
from lyricalign.metrics.scale_metrics import test_scale_metrics  # noqa: E402
from lyricalign.training.qwen_fa_runtime import (decoded_character_predictions, move_inputs,  # noqa: E402
                                                 read_jsonl)


def load_topup() -> Any:
    spec = importlib.util.spec_from_file_location("run_funnel_topup", ROOT / "scripts" / "training" / "run_funnel_topup.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def snapped_ends(starts: np.ndarray, ends: np.ndarray, gap_bins: int) -> np.ndarray:
    """Forward-only snap: pull an offset up to the next onset when the predicted gap is tiny.

    Only the model's own predicted gap is consulted, so nothing about the annotation is assumed —
    this is the version that could actually ship.
    """
    out = np.array(ends, dtype=np.int64)
    if gap_bins <= 0:
        return out
    for index in range(len(out) - 1):
        gap = int(starts[index + 1]) - int(out[index])
        if 0 < gap <= gap_bins:
            out[index] = int(starts[index + 1])
    return out


def build_rows(record: dict[str, Any], words: list[str], starts: np.ndarray, ends: np.ndarray,
               segment_sec: float) -> list[dict[str, Any]]:
    item = str(record["item_id"])
    return [{"item_id": item, "song_id": record.get("song_id", item), "character_index": index,
             "normalized_character": words[index] if index < len(words) else "?",
             "start_sec": float(starts[index]) * segment_sec, "end_sec": float(ends[index]) * segment_sec}
            for index in range(min(len(starts), len(ends), len(words)))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True, help="run providing config.yaml")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--gaps", default="0,1,2,3,4", help="snap thresholds in 80ms bins, comma separated")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoProcessor
    from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator

    TOPUP = load_topup()
    cfg = yaml.safe_load((args.run_dir / "config.yaml").read_text(encoding="utf-8"))
    labels = read_jsonl(Path(cfg["data"]["labels"]))
    valid = [row for row in labels if row["split"] == "validation"]
    if args.limit:
        valid = valid[: args.limit]
    references: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(Path(cfg["data"]["characters"])):
        references[row["item_id"]].append(row)
    for item in references:
        references[item].sort(key=lambda row: int(row["character_index"]))

    from transformers import AutoModelForTokenClassification
    model, _ = TOPUP.build_stage_model(cfg, "r2", args.device, True)
    state = torch.load(args.checkpoint / "trainer_state.pt", map_location="cpu", weights_only=False)
    current = dict(model.named_parameters())
    with torch.no_grad():
        for name, value in state["trainable_state"].items():
            current[name].data.copy_(value.to(current[name].device, current[name].dtype))
    segment_sec = float(cfg["training"].get("timestamp_segment_sec", 0.08))
    processor = AutoProcessor.from_pretrained(cfg["model"]["id"], revision=cfg["model"]["revision"],
                                             local_files_only=True)
    collator = QwenFABatchCollator(processor, audio_root=Path(cfg["data"]["audio_root"]),
                                   language=cfg["data"]["language"],
                                   timestamp_token_id=model.config.timestamp_token_id)
    gap_bins = [int(value) for value in args.gaps.split(",") if value.strip() != ""]
    policies = ["argmax", "viterbi"] + [f"snap{gap}" for gap in gap_bins if gap > 0]
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in policies}
    reference_rows: list[dict[str, Any]] = []
    per_character: dict[str, dict[tuple[str, int], float]] = {name: {} for name in policies}
    model.eval()
    for offset in range(0, len(valid), args.batch_size):
        chunk = [row for row in valid[offset: offset + args.batch_size]
                 if references.get(str(row["item_id"]))]
        if not chunk:
            continue
        for item in chunk:
            reference_rows.extend(references[str(item["item_id"])])
        inputs, words = collator(chunk)
        batch = move_inputs(inputs, args.device, getattr(torch, cfg["training"].get("dtype", "bfloat16")))
        with torch.no_grad():
            logits = model(**batch).logits
        ids = inputs["input_ids"]
        for index, record in enumerate(chunk):
            item = str(record["item_id"])
            probabilities = slot_logprobs(logits[index: index + 1], ids[index: index + 1],
                                           timestamp_token_id=model.config.timestamp_token_id)
            argmax_starts = probabilities[:, 0, :].argmax(axis=1)
            argmax_ends = probabilities[:, 1, :].argmax(axis=1)
            vit = viterbi_monotone(probabilities[:, 0, :], probabilities[:, 1, :])
            starts, ends = vit["starts"], vit["ends"]
            store = {"argmax": (argmax_starts, argmax_ends), "viterbi": (starts, ends)}
            for gap in gap_bins:
                if gap > 0:
                    store[f"snap{gap}"] = (starts, snapped_ends(starts, ends, gap))
            for name, (start_values, end_values) in store.items():
                built = build_rows(record, words[index], start_values, end_values, segment_sec)
                rows[name].extend(built)
                for row in built:
                    per_character[name][(item, int(row["character_index"]))] = row["end_sec"]
        print(f"processed {offset + len(chunk)}/{len(valid)} items", flush=True)

    payload: dict[str, Any] = {"schema_version": "snap_rule_v1", "checkpoint": str(args.checkpoint),
                               "items": len(valid), "gap_bins": gap_bins, "segment_sec": segment_sec,
                               "policies": {}}
    for name in policies:
        metric = test_scale_metrics(reference_rows, rows[name])
        metric.pop("per_unit", None)
        payload["policies"][name] = {key: metric.get(key) for key in
                                     ("macro_song_within_primary", "macro_song_se_primary", "mae_all_ms",
                                      "usable_rate", "collapse_longest_run")}
        payload["policies"][name]["subsets"] = metric.get("subsets")
    baseline = per_character["argmax"]
    payload["paired_vs_argmax"] = {}
    for name in policies:
        shared = set(baseline) & set(per_character[name])
        errors = {(row["item_id"], int(row["character_index"])): row
                  for row in reference_rows}
        diff = [1000.0 * (abs(per_character[name][key] - errors[key]["end_sec"])
                          - abs(baseline[key] - errors[key]["end_sec"])) for key in shared]
        if len(diff) < 20:
            continue
        mean = st.mean(diff)
        se = st.stdev(diff) / len(diff) ** 0.5 if len(diff) > 1 else 0.0
        payload["paired_vs_argmax"][name] = {"n": len(diff), "mean_delta_ms": round(mean, 2),
                                             "se_ms": round(se, 2), "z": round(mean / se, 2) if se else None}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"policies": payload["policies"], "paired": payload["paired_vs_argmax"]},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
