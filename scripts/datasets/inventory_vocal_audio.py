#!/usr/bin/env python3
"""Create a hashable vocal-only inventory from a frozen JSONL manifest."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.audio.contract import inventory_record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--vocal-source-type", choices=("native_vocal", "official_vocal_channel", "model_separated_vocal"), required=True)
    parser.add_argument("--include-sha256", action="store_true")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line]
    output, statuses = [], Counter()
    for row in rows:
        record = dict(row)
        contract = inventory_record(args.audio_root / str(row["audio_relpath"]), args.vocal_source_type, include_hash=args.include_sha256)
        record["vocal_source_type"] = args.vocal_source_type
        record["audio_contract"] = contract
        output.append(record)
        statuses[contract["audio"]["audio_status"]] += 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.out_dir, delete=False) as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(args.out_dir / "vocal_inventory.jsonl")
    summary = {"status": "passed" if statuses["ok"] == len(output) else "failed", "records": len(output), "audio_status_counts": dict(statuses), "sha256_included": args.include_sha256}
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
