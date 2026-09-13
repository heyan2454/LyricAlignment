#!/usr/bin/env python3
"""Track 1 step ②b: do the *model's* boundaries sit on stronger acoustic events than the labels'?

Step ②a showed, without any model, that annotated offsets of long characters are often acoustically
indistinguishable from the note interior (28.9% by spectral flux, vs 13.5% for short characters).
That establishes ambiguity in the supervision but not yet who is "right".

This script closes the loop: for the same long-note-rich items it runs the model, decodes with the
independent per-slot argmax *and* with the monotone Viterbi decoder, and measures the same local
prominence at three boundaries per character — the label's, the argmax's and the constrained one's.

Reading the outcome:
* predicted prominence ≫ label prominence  -> the metric punishes correct behaviour (H1 holds);
* both equally low                        -> the ambiguity is irreducible, and the fix is an
                                             admissible-boundary evaluation / label convention,
                                             not more training.

Inference runs happily on CPU (~1 s/item for short M4Singer phrases), so this does not compete with
a training job for the GPU.

    PYTHONPATH=src python scripts/evaluation/measure_predicted_boundary_acoustics.py \
        --checkpoint /home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750 \
        --limit 300 --longest-first --out results/by_run/20260913_boundary_pred_vs_gt/metrics.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.inference.constrained_timestamps import slot_logprobs, viterbi_monotone  # noqa: E402


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ACOUSTICS = load_module("measure_boundary_acoustics", ROOT / "scripts" / "evaluation" / "measure_boundary_acoustics.py")
AUDIT = load_module("audit_char_labels_vs_textgrid", ROOT / "scripts" / "evaluation" / "audit_char_labels_vs_textgrid.py")
TOPUP = load_module("run_funnel_topup", ROOT / "scripts" / "training" / "run_funnel_topup.py")


def prominence_pair(signal: np.ndarray, gt: float, predicted: float, note_span: tuple[float, float], *,
                    kind: str, context_sec: float, scale: float) -> tuple[float | None, float | None]:
    """Prominence at the label boundary and at the predicted boundary, same interior, same scale."""
    def interior(boundary: float) -> tuple[float, float]:
        if kind == "onset":
            return (boundary + 2 * context_sec, min(note_span[1], boundary + 6 * context_sec))
        return (max(note_span[0], boundary - 6 * context_sec), boundary - 2 * context_sec)
    gt_value = ACOUSTICS.prominence(signal, gt, interior(gt), context_sec=context_sec, scale=scale)
    pred_value = (ACOUSTICS.prominence(signal, predicted, interior(predicted),
                                      context_sec=context_sec, scale=scale)
                  if predicted is not None and np.isfinite(predicted) else None)
    # Controlled version: the same *local peak* at both positions, no position-dependent baseline.
    # The prominence above uses each boundary's own interior, which drifts with the boundary; a
    # predicted boundary that overshoots into the next note would then be compared against a
    # different baseline and could look better for the wrong reason.
    gt_peak = local_peak(signal, gt, context_sec=context_sec)
    pred_peak = (local_peak(signal, predicted, context_sec=context_sec)
                 if predicted is not None and np.isfinite(predicted) else None)
    return gt_value, pred_value, gt_peak, pred_peak


def slot_diagnostics(probabilities: np.ndarray, label_bins: np.ndarray):
    """Per slot: top-1 probability, entropy, rank of the *label's* bin, and top-5 mass.

    These separate the two very different ways a character can be wrong: the model is diffuse
    (high entropy, label buried deep but the answer is not confidently elsewhere) versus the model
    is confidently wrong (low entropy, label ranked far down).  Only the second one is a modelling
    failure the decoder or the training signal could plausibly fix.
    """
    probs = np.exp(probabilities - probabilities.max(axis=2, keepdims=True))
    probs = probs / probs.sum(axis=2, keepdims=True)
    top1 = probs.max(axis=2)
    entropy = -(probs * np.log(np.maximum(probs, 1e-12))).sum(axis=2)
    top5 = np.sort(probs, axis=2)[..., -5:].sum(axis=2)
    label_prob = np.take_along_axis(probs, label_bins[:, :, None], axis=2)[..., 0]
    rank = (probs > label_prob[:, :, None]).sum(axis=2) + 1
    return top1, entropy, rank, top5


def local_peak(signal: np.ndarray, position: float, *, context_sec: float) -> float | None:
    """Max novelty within +/- context of a position (the controlled, baseline-free comparison)."""
    low = max(0, int((position - context_sec) / ACOUSTICS.HOP_SEC))
    high = min(len(signal), int((position + context_sec) / ACOUSTICS.HOP_SEC) + 1)
    if high <= low:
        return None
    return float(np.max(signal[low:high]))


def summarise(values: list[float]) -> dict[str, Any]:
    return ACOUSTICS.summarise(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--labels", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"))
    parser.add_argument("--audio-root", type=Path,
                        default=Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"))
    parser.add_argument("--config", type=Path,
                        default=ROOT / "configs" / "training" / "qwen_fa_lora_from_official_20260913.yaml")
    parser.add_argument("--stage", default="r2")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--longest-first", action="store_true")
    parser.add_argument("--sample-seed", type=int, default=20260913,
                        help="random-but-deterministic sample of long-note items, so the sample is not one song")
    parser.add_argument("--long-sec", type=float, default=1.0)
    parser.add_argument("--context-sec", type=float, default=0.06)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    import yaml
    from lyricalign.training.qwen_fa_runtime import QwenFABatchCollator, move_inputs

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    model, processor = TOPUP.build_stage_model(cfg, args.stage, args.device, True)
    TOPUP.load_weights(args.checkpoint, model)
    model.eval()
    collator = QwenFABatchCollator(processor, audio_root=args.audio_root,
                                   language=cfg["data"]["language"],
                                   timestamp_token_id=model.config.timestamp_token_id)

    import random
    rows = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if (args.audio_root / row["audio_relpath"]).exists()]
    rows = [row for row in rows
            if any((row["timestamp_class_ids"][2 * index + 1] - row["timestamp_class_ids"][2 * index]) * 0.08
                   >= args.long_sec for index in range(len(row["timestamp_class_ids"]) // 2))]
    if args.longest_first:
        rows.sort(key=lambda row: -sum(1 for index in range(len(row["timestamp_class_ids"]) // 2)
                                       if (row["timestamp_class_ids"][2 * index + 1]
                                           - row["timestamp_class_ids"][2 * index]) * 0.08 >= args.long_sec))
    else:
        random.Random(args.sample_seed).shuffle(rows)   # deterministic sample across songs
    if args.limit:
        rows = rows[: args.limit]

    observations: list[dict[str, Any]] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    per_item_path = args.out.with_name("per_character.jsonl")
    started = time.time()
    processed = 0
    with per_item_path.open("w", encoding="utf-8") as handle:
        for offset in range(0, len(rows), args.batch_size):
            chunk = rows[offset: offset + args.batch_size]
            inputs, words = collator(chunk)
            dtype = getattr(torch, cfg["training"].get("dtype", "bfloat16"))
            with torch.no_grad():
                output = model(**move_inputs(inputs, args.device, dtype))
            for sample, record in enumerate(chunk):
                grid = args.audio_root / str(record["audio_relpath"]).replace(".wav", ".TextGrid")
                characters = AUDIT.character_intervals(grid.read_text(encoding="utf-8"))
                if len(characters) != len(words[sample]):
                    continue
                import soundfile as sf
                samples, rate = sf.read(str(args.audio_root / record["audio_relpath"]),
                                        dtype="float32", always_2d=False)
                if samples.ndim > 1:
                    samples = samples.mean(axis=1)
                flux, d_rms, _ = ACOUSTICS.novelty_frames(samples, rate)
                scales = {"flux": float(np.median(flux)) if flux.size else 1e-9,
                          "d_rms": float(np.median(d_rms)) if d_rms.size else 1e-9}
                probabilities = slot_logprobs(output.logits[sample: sample + 1],
                                              inputs["input_ids"][sample: sample + 1],
                                              timestamp_token_id=model.config.timestamp_token_id)
                step = float(record["timestamp_segment_sec"])
                class_ids = record["timestamp_class_ids"]
                label_bins = np.clip(np.asarray(class_ids[:2 * len(words[sample])], dtype=np.int64)
                                     .reshape(-1, 2), 0, probabilities.shape[2] - 1)
                diag = slot_diagnostics(probabilities, label_bins) if len(label_bins) == probabilities.shape[0] \
                    else None
                argmax_starts = probabilities[:, 0, :].argmax(axis=1) * step
                argmax_ends = probabilities[:, 1, :].argmax(axis=1) * step
                decoded = viterbi_monotone(probabilities[:, 0, :], probabilities[:, 1, :], min_duration=1)
                dp_starts = np.asarray(decoded["starts"], dtype=float) * step if decoded["feasible"] else argmax_starts
                dp_ends = np.asarray(decoded["ends"], dtype=float) * step if decoded["feasible"] else argmax_ends
                if len(dp_starts) < len(characters):
                    continue
                for index, interval in enumerate(characters):
                    duration = interval["end"] - interval["start"]
                    is_long = duration >= args.long_sec
                    for channel, signal in (("flux", flux), ("d_rms", d_rms)):
                        for kind, gt, predicted_am, predicted_dp in (
                                ("onset", float(interval["start"]), float(argmax_starts[index]), float(dp_starts[index])),
                                ("offset", float(interval["end"]), float(argmax_ends[index]), float(dp_ends[index]))):
                            gt_value, am_value, gt_peak, am_peak = prominence_pair(
                                signal, gt, predicted_am, (interval["start"], interval["end"]),
                                kind=kind, context_sec=args.context_sec, scale=scales[channel])
                            _, dp_value, _, dp_peak = prominence_pair(
                                signal, gt, predicted_dp, (interval["start"], interval["end"]),
                                kind=kind, context_sec=args.context_sec, scale=scales[channel])
                            if gt_value is None:
                                continue
                            # Control for the grid: predictions live on the 80 ms grid, annotations
                            # do not.  Snapping the label to the same grid removes the possibility
                            # that the model "wins" merely because its window is grid-aligned.
                            snapped = round(gt / step) * step
                            snapped_peak = local_peak(signal, snapped, context_sec=args.context_sec)
                            observation = {"item_id": record["item_id"], "index": index, "channel": channel,
                                           "kind": kind, "long": bool(is_long), "duration": round(duration, 3),
                                           "gt": round(gt_value, 3),
                                           "pred_argmax": (None if am_value is None else round(am_value, 3)),
                                           "pred_constrained": (None if dp_value is None else round(dp_value, 3)),
                                           "abs_err_argmax": round(abs(gt - predicted_am), 3),
                                           "abs_err_constrained": round(abs(gt - predicted_dp), 3),
                                           "pred_sec": round(predicted_am, 3),
                                           "signed_err": round(predicted_am - gt, 3),
                                           "p_top1": (None if diag is None else round(float(diag[0][index, 0 if kind == "onset" else 1]), 4)),
                                           "entropy_nats": (None if diag is None else round(float(diag[1][index, 0 if kind == "onset" else 1]), 3)),
                                           "label_rank": (None if diag is None else int(diag[2][index, 0 if kind == "onset" else 1])),
                                           "top5_mass": (None if diag is None else round(float(diag[3][index, 0 if kind == "onset" else 1]), 4)),
                                           "peak_gt": (None if gt_peak is None else round(gt_peak, 4)),
                                           "peak_gt_snapped": (None if snapped_peak is None else round(snapped_peak, 4)),
                                           "peak_pred_argmax": (None if am_peak is None else round(am_peak, 4)),
                                           "peak_pred_constrained": (None if dp_peak is None else round(dp_peak, 4))}
                            observations.append(observation)
                            handle.write(json.dumps(observation, ensure_ascii=False) + "\n")
                processed += 1
            if processed and processed % 40 == 0:
                print(f"processed {processed} items ({time.time() - started:.0f}s)", flush=True)

    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for observation in observations:
        key = f"{observation['channel']}|{observation['kind']}|{'long' if observation['long'] else 'short'}"
        groups[key]["gt"].append(observation["gt"])
        if observation["pred_argmax"] is not None:
            groups[key]["pred_argmax"].append(observation["pred_argmax"])
            groups[key]["delta_argmax"].append(observation["pred_argmax"] - observation["gt"])
        if observation["pred_constrained"] is not None:
            groups[key]["pred_constrained"].append(observation["pred_constrained"])
            groups[key]["delta_constrained"].append(observation["pred_constrained"] - observation["gt"])
        groups[key]["abs_err_argmax"].append(observation["abs_err_argmax"])
        groups[key]["abs_err_constrained"].append(observation["abs_err_constrained"])
    report = {"schema_version": "predicted_vs_gt_boundary_acoustics_v1",
              "checkpoint": str(args.checkpoint), "items": processed,
              "characters": len({(o["item_id"], o["index"]) for o in observations}),
              "long_sec": args.long_sec, "context_sec": args.context_sec,
              "groups": {key: {name: summarise(values) for name, values in sorted(channel.items())}
                         for key, channel in sorted(groups.items())}}
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for key in sorted(report["groups"]):
        block = report["groups"][key]
        print(f"{key:22s} gt={block.get('gt', {}).get('p50')} "
              f"argmax={block.get('pred_argmax', {}).get('p50')} "
              f"constrained={block.get('pred_constrained', {}).get('p50')} "
              f"Δ(argmax-gt)={block.get('delta_argmax', {}).get('p50')} "
              f"更好比例={None if not block.get('delta_argmax') else round(1 - block['delta_argmax']['share_not_above_interior'], 3)}")


if __name__ == "__main__":
    main()
