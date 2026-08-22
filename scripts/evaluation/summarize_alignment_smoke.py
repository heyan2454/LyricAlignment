#!/usr/bin/env python3
"""Summarize a serial-demo alignment smoke run.

Reads `alignments/*/*/*/alignment.json` and emits a small JSON/Markdown summary
of structural quality, zero durations, and interval lengths.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

MODEL_ORDER = ("r0", "r1", "r2")
AUDIO_ORDER = ("mix", "vocal")
MODE_ORDER = ("full", "windowed")


def load_alignment(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_one(path: Path) -> dict:
    data = load_alignment(path)
    chars = data.get("characters", [])
    summary = data.get("summary", {})
    zero = 0
    intervals = []
    for c in chars:
        start = c.get("selected_start_sec", c.get("start_sec"))
        end = c.get("selected_end_sec", c.get("end_sec"))
        if start is None or end is None:
            continue
        dur = float(end) - float(start)
        intervals.append(dur)
        if dur <= 0:
            zero += 1
    intervals.sort()
    return {
        "path": str(path),
        "character_count": len(chars),
        "zero_duration_count": zero,
        "zero_duration_rate": round(zero / len(chars), 4) if chars else None,
        "min_interval_sec": round(intervals[0], 4) if intervals else None,
        "median_interval_sec": round(intervals[len(intervals) // 2], 4) if intervals else None,
        "max_interval_sec": round(intervals[-1], 4) if intervals else None,
        "quality_status": (data.get("quality") or {}).get("status"),
        "summary": {k: summary.get(k) for k in ("audio_duration_sec", "line_count", "character_count", "window_count", "overlap_compressed_character_count", "overlap_compression_collapsed_to_zero_count")},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    results = []
    for model in MODEL_ORDER:
        for audio in AUDIO_ORDER:
            for mode in MODE_ORDER:
                p = args.run_root / "alignments" / model / audio / mode / "alignment.json"
                if p.is_file():
                    results.append(summarize_one(p))
    payload = {
        "schema_version": "alignment_smoke_summary_v1",
        "run_root": str(args.run_root),
        "items": results,
        "item_count": len(results),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
