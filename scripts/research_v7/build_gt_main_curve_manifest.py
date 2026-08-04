#!/usr/bin/env python3
"""Compile the C1--C6 GT main curve without using GT timestamps as model input."""
from __future__ import annotations

import argparse
import json
import random
import wave
from pathlib import Path


EXTRA = (.10, .25, .50, 1.00, 2.00)
MISSING = (.10, .25, .50, .75, .90)
REPLACE = (.10, .25, .50, .75, 1.00)


def gt_units(path: str) -> list[str]:
    return [json.loads(line)["normalized_character"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def duration(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def cyclic(units: list[str], count: int) -> list[str]:
    return [units[index % len(units)] for index in range(count)] if units else []


def insert(base: list[str], added: list[str], position: str) -> list[str]:
    if position == "tail": return base + added
    if position == "head": return added + base
    pivot = len(base) // 2
    return base[:pivot] + added + base[pivot:]


def remove(base: list[str], count: int, position: str, seed: int) -> list[str]:
    count = min(len(base) - 1, count)
    if position == "tail": return base[:-count]
    if position == "head": return base[count:]
    if position == "middle":
        start = (len(base) - count) // 2; return base[:start] + base[start + count:]
    rng = random.Random(seed); discarded = set(rng.sample(range(len(base)), count))
    return [unit for index, unit in enumerate(base) if index not in discarded]


def replace(base: list[str], donor: list[str], count: int, position: str, seed: int) -> list[str]:
    out = list(base)
    if position == "head": indices = list(range(count))
    elif position == "tail": indices = list(range(len(base) - count, len(base)))
    elif position == "middle":
        start = (len(base) - count) // 2; indices = list(range(start, start + count))
    else: indices = sorted(random.Random(seed).sample(range(len(base)), count))
    for index, value in zip(indices, cyclic(donor, count)): out[index] = value
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True); parser.add_argument("--donors", required=True); parser.add_argument("--out", required=True)
    parser.add_argument("--unit-count", type=int, default=64); parser.add_argument("--seed", type=int, default=3407)
    args = parser.parse_args(argv)
    records = {row["item_id"]: row for row in (json.loads(line) for line in Path(args.manifest).read_text(encoding="utf-8").splitlines() if line)}
    donors = json.loads(Path(args.donors).read_text(encoding="utf-8"))["rows"]; output = []
    for donor_record in donors:
        record = records[donor_record["target_item_id"]]; full = gt_units(record["gt_path"]); n = min(args.unit_count, len(full)); base = full[:n]
        donor_full = gt_units(donor_record["donor_gt_path"])[donor_record["donor_start_index"]:]
        donor_units = donor_full[:n]
        if len(base) < 2 or len(donor_units) < n: raise RuntimeError(f"bad frozen donor for {record['item_id']}")
        full_duration = duration(record["audio_path"])
        common = {"item_id": record["item_id"], "song_id": record.get("song_id"), "source_song_id": record.get("source_song_id"),
                  "dataset": record.get("dataset"), "split": record.get("split"), "language": record.get("language", "Chinese"),
                  "audio_path": record["audio_path"], "gt_path": record["gt_path"], "text_source": record["gt_path"], "duration_sec": full_duration,
                  "audio_start_sec": 0.0, "audio_end_sec": full_duration, "audio_relation": "full_source_audio",
                  "baseline_unit_count": n, "n_base": n, "selection_seed": args.seed, "donor_song_id": donor_record["donor_source_song_id"],
                  "donor_start_index": donor_record["donor_start_index"], "donor_end_index": donor_record["donor_end_index"],
                  "donor_similarity": donor_record["similarity"], "provenance": {"donor_manifest": str(args.donors)}}
        def add(tag: str, mutation: str, text: list[str], **kw):
            output.append({**common, "request_id": f"{record['item_id']}:C:{tag}", "mutation_type": mutation, "text_units": text, **kw})
        add("baseline", "baseline", base, requested_ratio=0.0, actual_ratio=0.0, mutation_position="whole", text_relation="exact")
        for ratio in EXTRA:
            count = max(1, round(n * ratio))
            for position in ("tail", "head", "middle"):
                add(f"extra-lookahead-{position}-{ratio}", "extra", insert(base, cyclic(base, count), position), requested_ratio=ratio, actual_ratio=count/n, ratio=ratio, position=position, mutation_position=position, source="lookahead", text_relation="repeated_current", actual_added_units=count)
            if len(full) > n:
                add(f"extra-future-tail-{ratio}", "extra", insert(base, cyclic(full[n:], count), "tail"), requested_ratio=ratio, actual_ratio=count/n, ratio=ratio, position="tail", mutation_position="tail", source="future", text_relation="same_song_future", actual_added_units=count)
            add(f"extra-cross-song-tail-{ratio}", "extra", insert(base, cyclic(donor_full, count), "tail"), requested_ratio=ratio, actual_ratio=count/n, ratio=ratio, position="tail", mutation_position="tail", source="cross_song", text_relation="cross_song", actual_added_units=count)
        for ratio in MISSING:
            count = max(1, round(n * ratio))
            for position in ("tail", "head", "middle", "dispersed"):
                add(f"missing-{position}-{ratio}", "missing", remove(base, count, position, args.seed), requested_ratio=ratio, actual_ratio=count/n, ratio=ratio, position=position, mutation_position=position, text_relation="subset", actual_removed_units=count)
        for ratio in REPLACE:
            count = max(1, round(n * ratio))
            for position in ("tail", "head", "middle", "whole"):
                add(f"replace-{position}-{ratio}", "replace", replace(base, donor_units, count, position, args.seed), requested_ratio=ratio, actual_ratio=count/n, ratio=ratio, position=position, mutation_position=position, source="cross_song", text_relation="partial_cross_song", actual_replaced_units=count)
        add("no-match", "no_match", donor_units, requested_ratio=1.0, actual_ratio=1.0, mutation_position="whole", source="cross_song", text_relation="strict_cross_song_no_match", actual_replaced_units=n)
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True); target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len(donors), "requests": len(output), "out": str(target)}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
