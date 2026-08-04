#!/usr/bin/env python3
"""Build C10 real repeated-section requests with multiple explicit GT answers.

Input audio is always the complete source WAV.  GT timestamps are read only to
identify repeated normalized text and are never passed to the aligner.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def gt_units(path: str) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def find_repeat(units: list[str]) -> tuple[int, int, int] | None:
    for size in range(min(16, len(units) // 2), 3, -1):
        seen: dict[tuple[str, ...], int] = {}
        for start in range(len(units) - size + 1):
            phrase = tuple(units[start:start + size])
            if phrase in seen and start - seen[phrase] >= size:
                return seen[phrase], start, size
            seen.setdefault(phrase, start)
    return None


def wav_duration(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dataset", default="mir1k")
    parser.add_argument("--split", default="heldout")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    output: list[dict] = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        if record.get("dataset") != args.dataset or record.get("split") != args.split:
            continue
        audio, gt = Path(record.get("audio_path", "")), Path(record.get("gt_path", ""))
        if not audio.is_file() or not gt.is_file():
            continue
        units = gt_units(str(gt)); repeated = find_repeat(units)
        if not repeated:
            continue
        first, second, count = repeated; phrase = units[first:first + count]; duration = wav_duration(str(audio))
        common = {
            "item_id": record["item_id"], "song_id": record.get("song_id"),
            "source_song_id": record.get("source_song_id") or record["item_id"],
            "dataset": args.dataset, "split": args.split, "language": record.get("language", "Chinese"),
            "audio_path": str(audio), "gt_path": str(gt), "text_source": str(gt),
            "audio_start_sec": 0.0, "audio_end_sec": duration, "duration_sec": duration,
            "audio_relation": "full_source_audio", "repeat_gt_starts": [first, second],
            "repeat_unit_count": count, "repeat_positions": [first, second],
            "provenance": {"repeat_detector": "exact_nonoverlap_gt_character_ngram", "gt_used_for": "posthoc_multi_answer_scoring_only"},
        }
        output.append({**common, "request_id": f"{record['item_id']}:C10:single-ambiguous",
                       "mutation_type": "baseline", "c10_case": "single_ambiguous_repeat",
                       "text_relation": "ambiguous_repeated_section", "text_units": phrase,
                       "baseline_unit_count": count, "n_base": count})
        output.append({**common, "request_id": f"{record['item_id']}:C10:double-sequence",
                       "mutation_type": "extra", "c10_case": "double_repeat_sequence",
                       "text_relation": "two_repeated_sections", "text_units": phrase + phrase,
                       "baseline_unit_count": count, "n_base": count, "requested_ratio": 1.0,
                       "actual_ratio": 1.0, "actual_added_units": count, "position": "tail", "mutation_position": "tail"})
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len({row['item_id'] for row in output}), "requests": len(output), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
