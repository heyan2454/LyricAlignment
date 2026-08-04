#!/usr/bin/env python3
"""Compile C7--C9 audio-range faults using duration ratios, never GT timestamps."""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def units(path: str) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def duration(path: str) -> float:
    with wave.open(path, "rb") as handle: return handle.getnframes() / handle.getframerate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", required=True); parser.add_argument("--out", required=True); parser.add_argument("--unit-count", type=int, default=64)
    args = parser.parse_args(argv); rows = []; records = [json.loads(line) for line in Path(args.manifest).read_text(encoding="utf-8").splitlines() if line]
    for record in records:
        base = units(record["gt_path"])[:args.unit_count]; total = duration(record["audio_path"])
        if len(base) < 2 or total <= .1: continue
        common = {"item_id": record["item_id"], "song_id": record.get("song_id"), "source_song_id": record.get("source_song_id"), "dataset": record.get("dataset"), "split": record.get("split"), "language": record.get("language", "Chinese"), "audio_path": record["audio_path"], "gt_path": record["gt_path"], "text_source": record["gt_path"], "duration_sec": total, "baseline_unit_count": len(base), "n_base": len(base), "text_units": base}
        def add(name: str, start: float, end: float, relation: str, ratio: float):
            rows.append({**common, "request_id": f"{record['item_id']}:C:{name}", "mutation_type": "baseline", "audio_start_sec": start, "audio_end_sec": end, "audio_relation": relation, "requested_ratio": ratio, "actual_ratio": (end-start)/total, "mutation_position": "audio"})
        add("audio-valid", 0., total, "full_source_audio", 0.)
        for ratio in (.10, .25, .50):
            add(f"audio-start-late-{ratio}", total * ratio, total, "start_late", ratio)
            add(f"audio-end-early-{ratio}", 0., total * (1-ratio), "end_early", ratio)
        add("audio-prefix-half", 0., total*.5, "partial_prefix", .5)
        add("audio-suffix-half", total*.5, total, "partial_suffix", .5)
        add("audio-middle-half", total*.25, total*.75, "partial_middle", .5)
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True); target.write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in rows), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len({row['item_id'] for row in rows}), "requests": len(rows), "out": str(target)}, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
