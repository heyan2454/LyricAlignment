#!/usr/bin/env python3
"""Compile frozen GT-backed baseline and mutation requests from donor records."""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def read_units(path: str) -> tuple[list[str], list[dict]]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
    return [row["normalized_character"] for row in rows], rows


def audio_duration(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--donors", required=True, help="JSON made by build_cross_song_donor_manifest")
    parser.add_argument("--out", required=True)
    parser.add_argument("--unit-count", type=int, default=64)
    parser.add_argument("--ratio", type=float, default=0.5)
    parser.add_argument("--oracle-gt-audio-end", action="store_true",
                        help="explicit oracle-only control; production defaults to the full source audio")
    args = parser.parse_args(argv)
    records = {row["item_id"]: row for row in (json.loads(line) for line in Path(args.manifest).read_text(encoding="utf-8").splitlines() if line)}
    donor_rows = json.loads(Path(args.donors).read_text(encoding="utf-8"))["rows"]
    output = []
    for donor in donor_rows:
        record = records[donor["target_item_id"]]
        units, gt = read_units(record["gt_path"])
        n = min(args.unit_count, len(units))
        if n < 2 or len(donor["donor_units"]) < n:
            raise RuntimeError(f"invalid donor or target for {record['item_id']}")
        base = units[:n]
        full_duration = audio_duration(record["audio_path"])
        audio_end = float(gt[n - 1]["end_sec"]) if args.oracle_gt_audio_end else full_duration
        common = {"item_id": record["item_id"], "song_id": record.get("song_id"),
                  "source_song_id": record.get("source_song_id"), "audio_path": record["audio_path"],
                  "gt_path": record["gt_path"], "text_source": record["gt_path"],
                  "audio_start_sec": 0.0, "audio_end_sec": audio_end,
                  "duration_sec": full_duration,
                  "audio_relation": "oracle_gt_localized" if args.oracle_gt_audio_end else "full_source_audio",
                  "baseline_unit_count": n, "donor": donor,
                  "provenance": record.get("provenance", {})}
        output.append({**common, "request_id": f"{record['item_id']}:mutation:baseline", "mutation_type": "baseline", "text_units": base})
        changed = max(1, round(n * args.ratio))
        output.append({**common, "request_id": f"{record['item_id']}:mutation:extra-tail-{args.ratio}", "mutation_type": "extra", "ratio": args.ratio, "position": "tail", "source": "lookahead", "text_units": base + base[:changed]})
        output.append({**common, "request_id": f"{record['item_id']}:mutation:missing-tail-{args.ratio}", "mutation_type": "missing", "ratio": args.ratio, "position": "tail", "text_units": base[:-changed]})
        output.append({**common, "request_id": f"{record['item_id']}:mutation:replace-tail-{args.ratio}", "mutation_type": "replace", "ratio": args.ratio, "position": "tail", "text_units": base[:-changed] + donor["donor_units"][:changed]})
        output.append({**common, "request_id": f"{record['item_id']}:mutation:no-match", "mutation_type": "no_match", "position": "whole", "source": "cross_song", "text_units": donor["donor_units"][:n]})
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"ok": True, "items": len(donor_rows), "requests": len(output), "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
