#!/usr/bin/env python3
"""Build no-GT demo behavior requests from the frozen active manifest.

The result deliberately has no GT field and is suitable only for behavior
inspection/review, never numeric accuracy evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import wave
from pathlib import Path


def lyric_units(path: str) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    return [char for char in text if not char.isspace() and char not in "，。！？、,.!?;:：；()（）[]【】\"'“”‘’—-…"]


def duration_sec(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def partition(record: dict) -> str:
    """Frozen deterministic split over source identity, preventing title leakage."""
    identity = str(record.get("source_identity_short_hash") or record["item_id"])
    bucket = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 50:
        return "demo_dev"
    if bucket < 75:
        return "demo_validation"
    if bucket < 90:
        return "demo_heldout"
    return "demo_challenge"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True); parser.add_argument("--out", required=True)
    parser.add_argument("--item-id", action="append", required=True); parser.add_argument("--unit-count", type=int, default=64)
    parser.add_argument("--ratio", type=float, default=.5)
    args = parser.parse_args(argv)
    wanted = set(args.item_id)
    records = {row["item_id"]: row for row in (json.loads(line) for line in Path(args.manifest).read_text(encoding="utf-8").splitlines() if line) if row.get("item_id") in wanted}
    if wanted != set(records):
        raise SystemExit("missing requested demo item(s): " + ", ".join(sorted(wanted - set(records))))
    prepared = []
    for item_id in args.item_id:
        record = records[item_id]; audio = Path(record["audio_path"]); lyrics = Path(record["lyrics_path"])
        if record.get("dataset") != "demo" or record.get("gt_path") is not None or not audio.is_file() or not lyrics.is_file():
            raise SystemExit(f"{item_id}: requires a no-GT demo with local vocal and lyrics")
        units = lyric_units(str(lyrics))[:args.unit_count]
        if len(units) < 2:
            raise SystemExit(f"{item_id}: insufficient lyrics units")
        prepared.append((record, units, duration_sec(str(audio))))
    output = []
    for index, (record, base, duration) in enumerate(prepared):
        other = prepared[(index + 1) % len(prepared)][1]
        changed = max(1, round(len(base) * args.ratio))
        common = {"item_id": record["item_id"], "song_id": record["source_song_id"], "source_song_id": record["source_song_id"],
                  "dataset": "demo", "split": partition(record), "gt_available": False, "audio_path": record["audio_path"],
                  "text_source": record["lyrics_path"], "audio_start_sec": 0.0, "audio_end_sec": duration,
                  "baseline_unit_count": len(base), "language": record.get("language"),
                  "provenance": {"active_manifest_item_id": record["item_id"], "selection_role": record.get("selection_role"),
                                 "source_identity_short_hash": record.get("source_identity_short_hash")}}
        output.extend((
            {**common, "request_id": f"{record['item_id']}:demo:baseline", "mutation_type": "baseline", "text_units": base},
            {**common, "request_id": f"{record['item_id']}:demo:extra-tail-{args.ratio}", "mutation_type": "extra", "ratio": args.ratio, "position": "tail", "source": "lookahead", "text_units": base + base[:changed]},
            {**common, "request_id": f"{record['item_id']}:demo:missing-tail-{args.ratio}", "mutation_type": "missing", "ratio": args.ratio, "position": "tail", "text_units": base[:-changed]},
            {**common, "request_id": f"{record['item_id']}:demo:no-match", "mutation_type": "no_match", "position": "whole", "source": "cross_song", "text_units": (other * ((len(base) + len(other) - 1) // len(other)))[:len(base)]},
        ))
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len(prepared), "requests": len(output), "out": str(target)}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
