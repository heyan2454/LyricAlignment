#!/usr/bin/env python3
"""End-to-end decoder comparison on real songs: shipped decode vs monotone Viterbi.

The zero-inference version (`real_song_dp_alternative_evidence.py`) could only ask what DP would pick
out of the stored top-k.  This one actually runs both decoders on the delivered separated vocals, so
the structural comparison covers the whole pipeline (same audio, same transcript, same logits):

* zero-length / reversed intervals — the defect users see;
* overlap and the longest identical-time block — the collapse signature;
* agreement between the two timelines (median |Δ| per character) — how much the decoder moves things;
* a held-out-free design: no ground truth is claimed, because there is none on this batch.

Audio is cropped to the first `--span-sec` seconds and the transcript is the character sequence the
shipped run aligned inside that span, so both decoders see exactly what the product saw, only shorter.

    PYTHONPATH=src python scripts/evaluation/real_song_decoder_probe.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --songs 4 --span-sec 90 --device cuda \
        --out results/by_run/20260914_real_song_decoder/metrics.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any

ALIGN_SUFFIX = "alignments/r2/vocal/windowed/alignment.raw.json"


def shipped_units_in_span(song_dir: Path, span_sec: float) -> list[str]:
    document = json.loads((song_dir / ALIGN_SUFFIX).read_text(encoding="utf-8"))
    units: list[tuple[float, str]] = []
    for character in document.get("characters", []):
        start = character.get("raw_global_start_sec")
        unit = str(character.get("alignment_unit") or character.get("character") or "").strip()
        if start is None or not unit:
            continue
        if float(start) < span_sec:
            units.append((float(start), unit))
    units.sort()
    return [unit for _start, unit in units]


def structural(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["start_sec"]) for row in rows], [float(row["end_sec"]) for row in rows]
    starts, ends = values
    zero = sum(1 for start, end in zip(starts, ends, strict=True) if end <= start)
    overlap = sum(1 for index in range(len(rows) - 1)
                  if starts[index + 1] < ends[index] - 1e-6)
    longest_block = 0
    from collections import Counter
    counter = Counter(round(end, 4) for end in ends)
    longest_block = max(counter.values()) if counter else 0
    return {"intervals": len(rows), "zero_length": zero, "zero_share": round(zero / max(1, len(rows)), 4),
            "overlap_pairs": overlap, "longest_same_end_block": longest_block,
            "span_sec": round(max(ends) - min(starts), 2) if ends else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence"))
    parser.add_argument("--songs", type=int, default=4)
    parser.add_argument("--span-sec", type=float, default=90.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model-revision", default="c07281df297b9905d24a508279258cccf987a064")
    parser.add_argument("--checkpoint", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import subprocess
    import sys
    import numpy as np
    import torch
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from transformers import AutoModelForTokenClassification, AutoProcessor
    from lyricalign.inference.constrained_timestamps import dp_timestamp_items
    from lyricalign.training.qwen_fa_runtime import move_inputs

    candidates = []
    for song_dir in sorted(child for child in args.batch.iterdir() if child.is_dir()):
        path = song_dir / ALIGN_SUFFIX
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = [(float(c["raw_global_start_sec"]), float(c["raw_global_end_sec"])) for c in document.get("characters", [])
                if c.get("raw_global_start_sec") is not None and c.get("raw_global_end_sec") is not None]
        if len(rows) < 40:
            continue
        candidates.append((sum(1 for s, e in rows if e <= s) / len(rows), song_dir))
    candidates.sort(key=lambda item: -item[0])
    chosen = candidates[: args.songs]

    model_id = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
    processor = AutoProcessor.from_pretrained(model_id, revision=args.model_revision, local_files_only=True)
    model = AutoModelForTokenClassification.from_pretrained(
        model_id, revision=args.model_revision, local_files_only=True, dtype=torch.bfloat16).to(args.device)
    state = torch.load(args.checkpoint / "trainer_state.pt", map_location="cpu", weights_only=False)
    parameters = dict(model.named_parameters())
    with torch.no_grad():
        for name, value in (state.get("trainable_state") or {}).items():
            if name in parameters:
                parameters[name].data.copy_(value.to(parameters[name].device, parameters[name].dtype))
    model.eval()

    payload: dict[str, Any] = {"schema_version": "real_song_decoder_probe_v1", "checkpoint": str(args.checkpoint),
                               "span_sec": args.span_sec, "model_revision": args.model_revision, "songs": []}
    for collapse_rate, song_dir in chosen:
        vocals = sorted((song_dir / "work" / "audio").glob("*vocal*.wav"))
        units = shipped_units_in_span(song_dir, args.span_sec)
        if not vocals or len(units) < 20:
            payload["songs"].append({"song": song_dir.name, "skipped": "缺人声或字太少"})
            continue
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(vocals[0]), "-ac", "1", "-ar", "16000",
                              "-f", "f32le", "-"], check=True, capture_output=True).stdout
        samples = np.frombuffer(raw, dtype=np.float32)[: int(args.span_sec * 16000)]
        transcript = " ".join(units)
        inputs, word_lists = processor.prepare_forced_aligner_inputs(audio=[samples], transcript=[transcript],
                                                                     language="Chinese")
        with torch.no_grad():
            batch = move_inputs(inputs, args.device, torch.bfloat16)
            logits = model(**batch).logits
        official = processor.decode_forced_alignment(logits=logits, input_ids=batch["input_ids"],
                                                     word_lists=word_lists,
                                                     timestamp_token_id=model.config.timestamp_token_id)[0]
        dp_items = dp_timestamp_items(logits, batch["input_ids"], word_lists,
                                      timestamp_token_id=model.config.timestamp_token_id,
                                      segment_sec=float(getattr(processor, "timestamp_segment_time", 80.0)) / 1000.0)[0]
        official_rows = [{"start_sec": item["start_time"], "end_sec": item["end_time"]} for item in official]
        dp_rows = [{"start_sec": item["start_time"], "end_sec": item["end_time"]} for item in dp_items]
        deltas = [abs(a["end_sec"] - b["end_sec"]) for a, b in zip(official_rows, dp_rows, strict=False)]
        entry = {"song": song_dir.name, "units_in_span": len(units), "shipped_collapse_rate": round(collapse_rate, 4),
                 "official": structural(official_rows), "dp": structural(dp_rows),
                 "agreement_median_end_delta_ms": round(1000 * st.median(deltas), 1) if deltas else None,
                 "agreement_p90_end_delta_ms": round(1000 * sorted(deltas)[int(0.9 * len(deltas))], 1) if deltas else None,
                 "dp_shifts_official_zero_to_nonzero": sum(
                     1 for a, b in zip(official_rows, dp_rows, strict=False)
                     if a["end_sec"] <= a["start_sec"] and b["end_sec"] > b["start_sec"])}
        payload["songs"].append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:220], flush=True)
    totals = {"songs": len([e for e in payload["songs"] if "official" in e]),
              "official_zero": sum(e["official"]["zero_length"] for e in payload["songs"] if "official" in e),
              "dp_zero": sum(e["dp"]["zero_length"] for e in payload["songs"] if "official" in e),
              "intervals": sum(e["official"]["intervals"] for e in payload["songs"] if "official" in e)}
    totals["official_zero_share"] = round(totals["official_zero"] / max(1, totals["intervals"]), 4)
    totals["dp_zero_share"] = round(totals["dp_zero"] / max(1, totals["intervals"]), 4)
    payload["totals"] = totals
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False))


if __name__ == "__main__":
    main()
