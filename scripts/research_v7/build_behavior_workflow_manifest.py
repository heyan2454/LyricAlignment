#!/usr/bin/env python3
"""Compile baseline behavior rows into P0/P1/P2/D/S workflow requests.

This only plans model inputs.  P2 is explicitly marked as requiring a prior
predicted cursor and S remains blocked from real execution until the processor
can construct an actual sparse timestamp-slot input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def request_id(item_id: str, mode: str, part: int) -> str:
    return f"{item_id}:{mode}:{part:03d}"


def compile_rows(rows: list[dict], chunk_units: int, cursor_offsets: tuple[int, ...] = (), provisional_tails: tuple[int, ...] = (), provisional_last_sec: float = 0.0) -> list[dict]:
    output = []
    for baseline in rows:
        if baseline.get("mutation_type") != "baseline":
            continue
        units = list(baseline["text_units"])
        item_id = baseline["item_id"]
        common = {key: baseline.get(key) for key in ("song_id", "source_song_id", "dataset", "split", "language", "duration_sec", "audio_path", "gt_path", "text_source", "provenance")}
        output.append({**common, "request_id": request_id(item_id, "P0", 0), "item_id": item_id,
                       "workflow_mode": "production_full_once", "parent_request_id": None,
                       "text_units": units, "text_start_index": 0, "text_end_index": len(units),
                       "timestamp_slot_indices": list(range(len(units))), "input_variant": "full"})
        previous = None
        for part, start in enumerate(range(0, len(units), chunk_units)):
            end = min(start + chunk_units, len(units))
            segment = units[start:end]
            prefix = units[:end]
            p1_id = request_id(item_id, "P1", part)
            output.append({**common, "request_id": p1_id, "item_id": item_id,
                           "workflow_mode": "strict_serial_same_audio", "parent_request_id": previous,
                           "text_units": prefix, "text_start_index": 0, "text_end_index": len(prefix),
                           "source_text_start_index": start, "source_text_end_index": end,
                           "timestamp_slot_indices": list(range(len(prefix))), "input_variant": "strict_serial_committed_prefix_all_slots"})
            if part > 0:
                for offset in cursor_offsets:
                    if offset == 0:
                        continue
                    shifted_end = max(start + 1, min(len(units), end + offset))
                    shifted_start = max(0, min(shifted_end - 1, start + offset))
                    shifted_prefix = units[:shifted_end]
                    suffix = f"p{offset}" if offset > 0 else f"m{-offset}"
                    output.append({**common, "request_id": request_id(item_id, f"P1O{suffix}", part), "item_id": item_id,
                                   "workflow_mode": "strict_serial_same_audio_cursor_injection", "parent_request_id": previous,
                                   "text_units": shifted_prefix, "text_start_index": 0, "text_end_index": len(shifted_prefix),
                                   "source_text_start_index": shifted_start, "source_text_end_index": shifted_end,
                                   "timestamp_slot_indices": list(range(len(shifted_prefix))), "input_variant": "strict_serial_committed_prefix_all_slots",
                                   "cursor_offset_units": offset})
                for tail in provisional_tails:
                    slot_start = max(0, start - tail)
                    output.append({**common, "request_id": request_id(item_id, f"P1PR{tail}", part), "item_id": item_id,
                                   "workflow_mode": "strict_serial_provisional_slots", "parent_request_id": previous,
                                   "text_units": prefix, "text_start_index": 0, "text_end_index": len(prefix),
                                   "source_text_start_index": start, "source_text_end_index": end,
                                   "timestamp_slot_indices": list(range(slot_start, len(prefix))), "input_variant": "strict_serial_committed_prefix_all_slots",
                                   "provisional_policy": f"last_{tail}_units", "provisional_tail_units": tail})
                if provisional_last_sec > 0:
                    output.append({**common, "request_id": request_id(item_id, "P1PRtime", part), "item_id": item_id,
                                   "workflow_mode": "strict_serial_provisional_slots", "parent_request_id": previous,
                                   "text_units": prefix, "text_start_index": 0, "text_end_index": len(prefix),
                                   "source_text_start_index": start, "source_text_end_index": end,
                                   "timestamp_slot_indices": list(range(start, len(prefix))), "input_variant": "strict_serial_committed_prefix_all_slots",
                                   "provisional_policy": "last_predicted_seconds", "provisional_last_sec": provisional_last_sec})
            output.append({**common, "request_id": request_id(item_id, "D", part), "item_id": item_id,
                           "workflow_mode": "independent_short_text_diagnostic", "parent_request_id": None,
                           "text_units": segment, "text_start_index": 0, "text_end_index": len(segment),
                           "source_text_start_index": start, "source_text_end_index": end,
                           "timestamp_slot_indices": list(range(len(segment))), "input_variant": "independent"})
            output.append({**common, "request_id": request_id(item_id, "P2", part), "item_id": item_id,
                           "workflow_mode": "strict_serial_progressive_crop", "parent_request_id": previous,
                           "text_units": segment, "text_start_index": 0, "text_end_index": len(segment),
                           "source_text_start_index": start, "source_text_end_index": end,
                           "timestamp_slot_indices": list(range(len(segment))), "input_variant": "requires_predicted_cursor",
                           "left_context_sec": 10.0})
            output.append({**common, "request_id": request_id(item_id, "S", part), "item_id": item_id,
                           "workflow_mode": "strict_serial_sparse_slots", "parent_request_id": previous,
                           "text_units": prefix, "text_start_index": 0, "text_end_index": end,
                           "timestamp_slot_indices": list(range(start, end)), "input_variant": "sparse_slots_requires_processor"})
            previous = p1_id
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behavior-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--chunk-units", type=int, default=32)
    parser.add_argument("--cursor-offset", action="append", type=int, default=[], help="append P1 cursor ±unit injection")
    parser.add_argument("--provisional-tail-units", action="append", type=int, default=[], help="re-open the final N committed slots")
    parser.add_argument("--provisional-last-sec", type=float, default=0.0, help="re-open slots whose parent predicted end is within seconds")
    args = parser.parse_args(argv)
    if args.chunk_units < 1:
        parser.error("--chunk-units must be positive")
    rows = [json.loads(line) for line in Path(args.behavior_manifest).read_text(encoding="utf-8").splitlines() if line]
    compiled = compile_rows(rows, args.chunk_units, tuple(args.cursor_offset), tuple(args.provisional_tail_units), args.provisional_last_sec)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in compiled), encoding="utf-8")
    print(json.dumps({"ok": True, "requests": len(compiled), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
