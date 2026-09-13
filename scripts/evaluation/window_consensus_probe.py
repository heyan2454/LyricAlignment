#!/usr/bin/env python3
"""Shifted-window consensus: can asking the model twice, from different positions, fix what
re-ranking the same logits cannot?

The mass-in-tolerance study closed the re-ranking door — for long-note failures the acceptance window
holds ~0.14 of the probability mass, so no selection rule over the *same* logits recovers them.  The
door that remains is information: shifting the window changes the audio context, therefore the logits.
If the errors are partly noise, the median across covering windows beats any single window; if they are
a systematic bias, consensus cannot help and only training can.  This is the measurement that decides.

It is measurable because the streams are built from validation items with exact references: a long
stream is sliced into overlapping windows, each window is aligned with the transcript of the characters
whose annotated centre falls in its core, and the resulting bins are mapped back to stream time.
Policies compared, for both the greedy argmax and the monotone Viterbi decoder:

* `single_central`  — the covering window in which the character is most central (what a pipelined
  system effectively uses today);
* `median_all`      — median across all covering windows;
* `median_multi_only` / `single_multi_only` — the same two restricted to characters covered at least
  twice, so the paired comparison is made on identical units.

    PYTHONPATH=src python scripts/evaluation/window_consensus_probe.py \
        --run-dir /home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724 \
        --checkpoint <ckpt> --device cpu --streams 40 \
        --out results/by_run/20260914_window_consensus/metrics.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import yaml  # noqa: E402

from lyricalign.metrics.scale_metrics import test_scale_metrics  # noqa: E402
from lyricalign.training.qwen_fa_concat import group_concat_records  # noqa: E402
from lyricalign.training.qwen_fa_runtime import decode_audio, move_inputs, read_jsonl  # noqa: E402

def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONSTRAINED = load_module("constrained_timestamps_probe",
                          ROOT / "src" / "lyricalign" / "inference" / "constrained_timestamps.py")
TOPUP = load_module("run_funnel_topup_for_probe", ROOT / "scripts" / "training" / "run_funnel_topup.py")

STEP_SEC = 0.08
SAMPLE_RATE = 16000


def slot_bins(logits: Any, input_ids: Any, *, timestamp_token_id: int, monotone: bool) -> tuple[np.ndarray, np.ndarray]:
    probabilities = CONSTRAINED.slot_logprobs(logits, input_ids, timestamp_token_id=timestamp_token_id)
    if monotone:
        result = CONSTRAINED.viterbi_monotone(probabilities[:, 0, :], probabilities[:, 1, :])
        return result["starts"], result["ends"]
    return probabilities[:, 0, :].argmax(axis=1), probabilities[:, 1, :].argmax(axis=1)


def assemble_stream(parts: list[str], shifts: list[int], total_sec: float, audio_root: Path) -> np.ndarray:
    """Rebuild the concatenated stream in memory, exactly as the concat collator would."""
    timeline = np.zeros(int(round(total_sec * SAMPLE_RATE)), dtype=np.float32)
    for part, shift in zip(parts, shifts):
        chunk = decode_audio(audio_root / part)
        start = int(round(shift * STEP_SEC * SAMPLE_RATE))
        stop = min(len(timeline), start + len(chunk))
        timeline[start:stop] = chunk[: stop - start]
    return timeline


def window_bounds(total_sec: float, window_sec: float, hop_sec: float) -> list[tuple[float, float]]:
    bounds: list[tuple[float, float]] = []
    core = 0.0
    while core < total_sec:
        end = min(core + window_sec, total_sec)
        bounds.append((core, end))
        if end >= total_sec:
            break
        core += hop_sec
    return bounds


def summarise(reference_rows: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not prediction_rows:
        return {"characters": 0}
    metric = test_scale_metrics(reference_rows, prediction_rows)
    return {"characters": len(prediction_rows),
            "macro_within_primary": metric["macro_song_within_primary"],
            "se": metric["macro_song_se_primary"], "mae_all_ms": metric["mae_all_ms"],
            "usable_rate": metric["usable_rate"], "per_song": metric["per_song"]}


def paired_vs_single(accepted: dict[Any, tuple[float, float]], estimates: dict[Any, dict[str, list[float]]],
                     central: dict[Any, tuple[float, float]], *, min_windows: int) -> dict[str, Any]:
    keys = [key for key in estimates
            if key in accepted and key in central and len(estimates[key]["end"]) >= min_windows]
    diffs = [max(abs(st.median(estimates[key]["start"]) - accepted[key][0]),
                 abs(st.median(estimates[key]["end"]) - accepted[key][1]))
             - max(abs(central[key][0] - accepted[key][0]), abs(central[key][1] - accepted[key][1]))
             for key in keys]
    if len(diffs) < 5:
        return {"n": len(diffs)}
    mean = st.mean(diffs)
    se = st.stdev(diffs) / len(diffs) ** 0.5 if len(diffs) > 1 else 0.0
    return {"n": len(diffs), "mean_delta_ms": round(1000 * mean, 2), "se_ms": round(1000 * se, 2),
            "z": round(mean / se, 2) if se > 1e-12 else None,   # 零方差给 None，不造荒谬的 z
            "better": sum(1 for value in diffs if value < -1e-6),
            "worse": sum(1 for value in diffs if value > 1e-6),
            "coverage_median_windows": int(st.median([len(estimates[key]["end"]) for key in keys]))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--streams", type=int, default=40)
    parser.add_argument("--stream-target-sec", type=float, default=100.0)
    parser.add_argument("--stream-max-sec", type=float, default=130.0)
    parser.add_argument("--window-sec", type=float, default=25.0)
    parser.add_argument("--hop-sec", type=float, default=12.5)
    parser.add_argument("--pad-sec", type=float, default=1.0)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoProcessor

    cfg = yaml.safe_load((args.run_dir / "config.yaml").read_text(encoding="utf-8"))
    valid = [row for row in read_jsonl(Path(cfg["data"]["labels"])) if row["split"] == "validation"]
    gap_sec = 0.4
    streams, _built = group_concat_records(valid, target_sec=args.stream_target_sec,
                                           max_sec=args.stream_max_sec, gap_sec=gap_sec)
    streams = [row for row in streams if row.get("audio_parts")][: args.streams]
    if not streams:
        raise SystemExit("no concatenated streams could be built from the validation split")

    processor = AutoProcessor.from_pretrained(cfg["model"]["id"], revision=cfg["model"]["revision"],
                                              local_files_only=True)
    # the same builder the funnel/top-up path uses, so the LoRA wrapping matches the checkpoint exactly
    model, _ = TOPUP.build_stage_model(cfg, "r2", args.device, True)
    loaded_step = TOPUP.load_weights(args.checkpoint, model)
    model.eval()
    timestamp_token_id = model.config.timestamp_token_id
    audio_root = Path(cfg["data"]["audio_root"])
    language = cfg["data"]["language"]

    accepted: dict[tuple[int, int], tuple[float, float]] = {}
    songs: dict[tuple[int, int], str] = {}
    estimates: dict[str, dict[tuple[int, int], dict[str, list[float]]]] = {
        "argmax": defaultdict(lambda: {"start": [], "end": []}),
        "viterbi": defaultdict(lambda: {"start": [], "end": []})}
    central: dict[str, dict[tuple[int, int], tuple[float, float, float]]] = {"argmax": {}, "viterbi": {}}

    for stream_index, stream in enumerate(streams):
        total_sec = float(stream["duration_sec"])
        timeline = assemble_stream(stream["audio_parts"], stream["part_shift_bins"], total_sec, audio_root)
        lyrics = str(stream["lyrics_normalized"])
        classes = stream["timestamp_class_ids"]
        characters = [(index, lyrics[index] if index < len(lyrics) else "?",
                       classes[2 * index] * STEP_SEC, classes[2 * index + 1] * STEP_SEC)
                      for index in range(len(classes) // 2)]
        for index, _char, start_sec, end_sec in characters:
            accepted[(stream_index, index)] = (start_sec, end_sec)
            songs[(stream_index, index)] = str(stream.get("song_id") or f"stream{stream_index}")
        for core_start, core_end in window_bounds(total_sec, args.window_sec, args.hop_sec):
            inside = [row for row in characters if core_start <= (row[2] + row[3]) / 2.0 < core_end]
            if len(inside) < 3:
                continue
            slice_start = max(0.0, core_start - args.pad_sec)
            slice_stop = min(total_sec, core_end + args.pad_sec)
            samples = timeline[int(round(slice_start * SAMPLE_RATE)):int(round(slice_stop * SAMPLE_RATE))]
            if len(samples) < SAMPLE_RATE:
                continue
            transcript = "".join(row[1] for row in inside)
            inputs, words = processor.prepare_forced_aligner_inputs(audio=[samples], transcript=[transcript],
                                                                    language=language)
            with torch.no_grad():
                batch = move_inputs(inputs, args.device, next(model.parameters()).dtype)
                logits = model(**batch).logits
            for decoder, monotone in (("argmax", False), ("viterbi", True)):
                starts, ends = slot_bins(logits, batch["input_ids"],
                                         timestamp_token_id=timestamp_token_id, monotone=monotone)
                count = min(len(inside), len(starts), len(ends))
                centre = (core_start + core_end) / 2.0
                for position in range(count):
                    index = inside[position][0]
                    key = (stream_index, index)
                    start_sec = slice_start + float(starts[position]) * STEP_SEC
                    end_sec = slice_start + float(ends[position]) * STEP_SEC
                    estimates[decoder][key]["start"].append(start_sec)
                    estimates[decoder][key]["end"].append(end_sec)
                    distance = abs((inside[position][2] + inside[position][3]) / 2.0 - centre)
                    stored = central[decoder].get(key)
                    if stored is None or distance < stored[2]:
                        central[decoder][key] = (start_sec, end_sec, distance)
        print(f"stream {stream_index + 1}/{len(streams)} chars={len(characters)}", flush=True)

    payload: dict[str, Any] = {"schema_version": "window_consensus_v1", "checkpoint": str(args.checkpoint),
                               "loaded_step": loaded_step,
                               "streams": len(streams), "characters": len(accepted),
                               "window_sec": args.window_sec, "hop_sec": args.hop_sec, "pad_sec": args.pad_sec,
                               "policies": {}, "paired": {}}
    for decoder in ("argmax", "viterbi"):
        multi_keys = [key for key in estimates[decoder] if len(estimates[decoder][key]["end"]) >= 2
                      and key in accepted and key in central[decoder]]
        configurations = {
            "single_central": (lambda key: central[decoder][key][:2], None),
            "median_all": (lambda key: (st.median(estimates[decoder][key]["start"]),
                                        st.median(estimates[decoder][key]["end"])), None),
            "median_multi_only": (lambda key: (st.median(estimates[decoder][key]["start"]),
                                               st.median(estimates[decoder][key]["end"])), multi_keys),
            "single_multi_only": (lambda key: central[decoder][key][:2], multi_keys)}
        for name, (pick, restrict) in configurations.items():
            keys = restrict if restrict is not None else [key for key in central[decoder] if key in accepted]
            reference_rows, prediction_rows = [], []
            for position, key in enumerate(sorted(keys)):
                start_sec, end_sec = pick(key)
                song = songs[key]
                reference_rows.append({"item_id": song, "song_id": song, "character_index": position,
                                       "start_sec": accepted[key][0], "end_sec": accepted[key][1]})
                prediction_rows.append({"item_id": song, "song_id": song, "character_index": position,
                                        "start_sec": start_sec, "end_sec": end_sec})
            payload["policies"][f"{decoder}|{name}"] = summarise(reference_rows, prediction_rows)
        payload["paired"][decoder] = {
            "median_multi_vs_single_multi": paired_vs_single(accepted, estimates[decoder],
                                                             {key: central[decoder][key] for key in central[decoder]},
                                                             min_windows=2),
            "median_all_vs_single": paired_vs_single(accepted, estimates[decoder],
                                                     {key: central[decoder][key] for key in central[decoder]},
                                                     min_windows=1)}
    for section in ("policies",):
        for key in payload[section]:
            payload[section][key].pop("per_song", None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"policies": payload["policies"], "paired": payload["paired"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
