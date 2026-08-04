#!/usr/bin/env python3
"""Freeze exact-text, full-audio baseline requests for every eligible GT item."""
from __future__ import annotations

import argparse
import hashlib
import json
import wave
from pathlib import Path


def _units(gt_path: Path) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in gt_path.read_text(encoding="utf-8").splitlines() if line]


def _duration(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset", default="m4singer")
    parser.add_argument("--split", default="test")
    args = parser.parse_args()
    rows: list[dict] = []
    for line in args.manifest.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("dataset") != args.dataset or record.get("split") != args.split:
            continue
        audio_path = Path(record["audio_path"])
        gt_path = Path(record["gt_path"])
        if not audio_path.is_file() or not gt_path.is_file():
            raise FileNotFoundError(f"missing input for {record['item_id']}: {audio_path} / {gt_path}")
        units = _units(gt_path)
        if not units:
            raise ValueError(f"empty GT text for {record['item_id']}")
        duration = _duration(audio_path)
        rows.append({
            "request_id": f"{record['item_id']}:full-baseline",
            "item_id": record["item_id"], "song_id": record.get("song_id"),
            "source_song_id": record.get("source_song_id"), "dataset": record["dataset"],
            "split": record["split"], "language": record.get("language", "Chinese"),
            "audio_path": str(audio_path), "gt_path": str(gt_path), "text_source": str(gt_path),
            "duration_sec": duration, "audio_start_sec": 0.0, "audio_end_sec": duration,
            "audio_relation": "full_source_audio", "baseline_unit_count": len(units), "n_base": len(units),
            "mutation_type": "baseline", "text_units": units, "requested_ratio": 0.0,
            "actual_ratio": 0.0, "mutation_position": "whole", "text_relation": "exact",
            "provenance": {"source_manifest": str(args.manifest)},
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    args.out.write_text(serialized, encoding="utf-8")
    print(json.dumps({"status": "complete", "items": len(rows), "out": str(args.out),
                      "sha256": hashlib.sha256(serialized.encode()).hexdigest()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
