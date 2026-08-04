#!/usr/bin/env python3
"""Build paired vocal/accompaniment C6 controls from formal GT-backed assets."""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def gt_units(path: str, limit: int) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line][:limit]


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True); parser.add_argument("--dataset", default="mir1k")
    parser.add_argument("--split", default="heldout"); parser.add_argument("--unit-count", type=int, default=64)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv); output = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        if row.get("dataset") != args.dataset or row.get("split") != args.split:
            continue
        vocal = Path(row.get("audio_path", "")); accompaniment = vocal.with_name("accompaniment.wav")
        gt = Path(row.get("gt_path", "")); units = gt_units(str(gt), args.unit_count) if gt.is_file() else []
        if not vocal.is_file() or not accompaniment.is_file() or len(units) < 2:
            continue
        common = {"item_id": row["item_id"], "song_id": row.get("song_id"),
                  "source_song_id": row.get("source_song_id") or row["item_id"], "dataset": args.dataset,
                  "split": args.split, "language": row.get("language", "Chinese"), "gt_path": str(gt),
                  "text_source": str(gt), "text_units": units, "baseline_unit_count": len(units), "n_base": len(units),
                  "audio_start_sec": 0.0, "audio_relation": "full_source_audio", "provenance": {"prepared_from": str(vocal), "accompaniment_path": str(accompaniment)}}
        for tag, audio, mutation, relation in (("vocal-baseline", vocal, "baseline", "vocal_with_real_lyrics"),
                                               ("accompaniment-only", accompaniment, "replace", "instrumental_audio_with_real_lyrics")):
            total = wav_duration(audio)
            extra = {} if mutation == "baseline" else {"requested_ratio": 1.0, "actual_ratio": 1.0,
                                                          "actual_replaced_units": len(units), "position": "whole", "mutation_position": "whole"}
            output.append({**common, **extra, "request_id": f"{row['item_id']}:C6:{tag}", "audio_path": str(audio),
                           "audio_end_sec": total, "duration_sec": total, "mutation_type": mutation,
                           "text_relation": relation})
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len({row['item_id'] for row in output}), "requests": len(output), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
