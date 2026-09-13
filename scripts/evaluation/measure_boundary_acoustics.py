#!/usr/bin/env python3
"""Track 1 step ②a: is an annotated character boundary inside a long note an acoustic event?

Step ① showed our labels are an exact 80 ms quantisation of M4Singer's TextGrid, so the long-note
ceiling cannot be blamed on the derivation.  The next question needs no model at all: **does the
annotated boundary sit on something audible?**

For every character boundary the script measures a *local prominence* of two acoustic novelty
signals (spectral flux and |Δ RMS|) at the boundary against the same note's own interior:

    prominence = max(novelty within ±context of the boundary) − median(novelty elsewhere in the note)

A boundary with prominence ≤ 0 is not distinguishable from the interior of the note it splits —
i.e. it is a *notational* boundary rather than an acoustic one.  Onsets and offsets are measured
separately, and long (≥`long_sec`) characters are compared against short ones as a control.

    PYTHONPATH=src python scripts/evaluation/measure_boundary_acoustics.py --limit 300 \
        --out results/by_run/20260913_boundary_acoustics/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any

import numpy as np

NON_CHARACTER_TOKENS = {"<SP>", "<AP>", "", "sil", "sp", "pau"}
FRAME_SEC = 0.025
HOP_SEC = 0.010


def bound_characters(grid_text: str, lyrics: str, class_ids: list[int],
                     step_sec: float) -> list[dict[str, Any]] | None:
    """Character intervals paired with our derived intervals, or None when the texts disagree."""
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "audit_char_labels_vs_textgrid",
        Path(__file__).resolve().parent / "audit_char_labels_vs_textgrid.py")
    assert spec and spec.loader
    audit = module_from_spec(spec)
    spec.loader.exec_module(audit)
    source = audit.character_intervals(grid_text)
    if "".join(str(interval["text"]) for interval in source) != lyrics:
        return None
    derived = audit.derived_intervals(class_ids, step_sec)
    out = []
    for interval, (start, end) in zip(source, derived, strict=True):
        out.append({"text": str(interval["text"]), "gt_start": float(interval["start"]),
                    "gt_end": float(interval["end"]), "dv_start": float(start), "dv_end": float(end)})
    return out


def novelty_frames(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Per-frame spectral flux, |Δ RMS| and the hop in seconds."""
    frame = max(8, int(FRAME_SEC * sample_rate))
    hop = max(1, int(HOP_SEC * sample_rate))
    window = np.hanning(frame)
    count = max(0, 1 + (len(samples) - frame) // hop)
    if count < 3:
        return np.zeros(0), np.zeros(0), HOP_SEC
    magnitudes = np.empty((count, frame // 2 + 1), dtype=np.float32)
    rms = np.empty(count, dtype=np.float32)
    for index in range(count):
        chunk = samples[index * hop:index * hop + frame] * window
        magnitudes[index] = np.abs(np.fft.rfft(chunk))
        rms[index] = float(np.sqrt(np.mean(chunk ** 2) + 1e-12))
    flux = np.maximum(0.0, np.diff(magnitudes, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    d_rms = np.concatenate([[0.0], np.abs(np.diff(rms))])
    return flux, d_rms, hop / sample_rate


def prominence(signal: np.ndarray, boundary_sec: float, interior: tuple[float, float], *,
               context_sec: float, scale: float) -> float | None:
    """Peak novelty near the boundary minus the median novelty *inside* the note nearby.

    The interior must be taken on the note's own side of the boundary.  A symmetric window would
    drag the *next* note's onset (a strong event) into the baseline of an offset and make every
    note end look un-prominent for a reason that has nothing to do with this note.
    """
    hop = HOP_SEC
    low = max(0, int((boundary_sec - context_sec) / hop))
    high = min(len(signal), int((boundary_sec + context_sec) / hop) + 1)
    start = max(0, int(interior[0] / hop))
    end = min(len(signal), int(interior[1] / hop) + 1)
    chunk = signal[start:end]
    if high <= low or chunk.size < 5:
        return None
    median = float(np.median(chunk))
    return (float(np.max(signal[low:high])) - median) / max(float(scale), 1e-9)


def summarise(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    array = np.array(values)
    return {"n": len(values), "mean": round(float(array.mean()), 3),
            "p10": round(float(np.percentile(array, 10)), 3),
            "p50": round(float(np.percentile(array, 50)), 3),
            "p90": round(float(np.percentile(array, 90)), 3),
            "share_not_above_interior": round(float((array <= 0).mean()), 4)}


def analyse(samples: np.ndarray, sample_rate: int, characters: list[dict[str, Any]], *, long_sec: float,
            context_sec: float) -> list[dict[str, Any]]:
    flux, d_rms, _ = novelty_frames(samples, sample_rate)
    rows: list[dict[str, Any]] = []
    scales = {"flux": float(np.median(flux)) if flux.size else 1e-9,
              "d_rms": float(np.median(d_rms)) if d_rms.size else 1e-9}
    for index, character in enumerate(characters):
        duration = character["gt_end"] - character["gt_start"]
        for channel, signal in (("flux", flux), ("d_rms", d_rms)):
            for kind, boundary in (("onset", character["gt_start"]), ("offset", character["gt_end"])):
                if kind == "onset":
                    interior = (boundary + 2 * context_sec, min(character["gt_end"], boundary + 6 * context_sec))
                else:
                    interior = (max(character["gt_start"], boundary - 6 * context_sec), boundary - 2 * context_sec)
                value = prominence(signal, boundary, interior, context_sec=context_sec,
                                   scale=scales[channel])
                if value is not None:
                    rows.append({"item": character.get("item_id"), "index": index, "channel": channel,
                                 "kind": kind, "long": bool(duration >= long_sec),
                                 "duration": round(duration, 3), "prominence": round(value, 3)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"))
    parser.add_argument("--audio-root", type=Path,
                        default=Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"))
    parser.add_argument("--limit", type=int, default=300, help="items to analyse (0 = all, slow)")
    parser.add_argument("--long-sec", type=float, default=1.0)
    parser.add_argument("--context-sec", type=float, default=0.06)
    parser.add_argument("--longest-first", action="store_true",
                        help="pick the items with the most long characters instead of the first N")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import soundfile as sf

    root = args.audio_root if args.audio_root.exists() else Path("/home/datasets/m4singer/raw/extracted/m4singer")
    if not root.exists():
        raise SystemExit(f"audio root not found: {args.audio_root}")
    rows = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.longest_first:
        rows.sort(key=lambda row: -sum(1 for index in range(len(row["timestamp_class_ids"]) // 2)
                                       if (row["timestamp_class_ids"][2 * index + 1]
                                           - row["timestamp_class_ids"][2 * index]) * 0.08 >= args.long_sec))
    if args.limit:
        rows = rows[: args.limit]
    observations: list[dict[str, Any]] = []
    items_used = 0
    for row in rows:
        wav = root / str(row["audio_relpath"])
        grid = wav.with_suffix(".TextGrid")
        if not wav.exists() or not grid.exists():
            continue
        characters = bound_characters(grid.read_text(encoding="utf-8"), str(row.get("lyrics_normalized", "")),
                                      row["timestamp_class_ids"], float(row["timestamp_segment_sec"]))
        if not characters:
            continue
        samples, rate = sf.read(str(wav), dtype="float32", always_2d=False)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        found = analyse(samples, rate, characters, long_sec=args.long_sec, context_sec=args.context_sec)
        for observation in found:
            observation["item"] = row["item_id"]
        observations.extend(found)
        items_used += 1
    groups: dict[str, list[float]] = {}
    for observation in observations:
        key = f"{observation['channel']}|{observation['kind']}|{'long' if observation['long'] else 'short'}"
        groups.setdefault(key, []).append(observation["prominence"])
    report = {"schema_version": "boundary_acoustics_v1", "items": items_used,
              "boundaries": len(observations), "context_sec": args.context_sec, "long_sec": args.long_sec,
              "long_characters": sum(1 for row in observations if row["channel"] == "flux" and row["long"]),
              "groups": {key: summarise(values) for key, values in sorted(groups.items())},
              "observations": observations[:5000]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    printable = {"items": items_used, "boundaries": len(observations), "long_characters": report["long_characters"]}
    for key, value in report["groups"].items():
        printable[key] = value
    print(json.dumps(printable, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
