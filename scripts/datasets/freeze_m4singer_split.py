#!/usr/bin/env python3
"""Freeze a song-level M4Singer split from accepted candidate manifests."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.split import canonical_hash, freeze_m4singer_three_way_split, leakage_audit


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--validation-percent", type=int, default=5)
    parser.add_argument("--test-percent", type=int, default=5)
    args = parser.parse_args()
    records = [row for row in read_jsonl(args.input) if row.get("status") == "accepted"]
    frozen = freeze_m4singer_three_way_split(
        records, args.seed, validation_percent=args.validation_percent, test_percent=args.test_percent
    )
    audit = leakage_audit(frozen)
    if not audit["passed"]:
        raise SystemExit(json.dumps(audit, ensure_ascii=False))
    atomic_jsonl(args.out_dir / "m4singer_accepted_split_manifest.jsonl", frozen)
    split_counts: dict[str, int] = {}
    song_counts: dict[str, set[str]] = {}
    singer_counts: dict[str, set[str]] = {}
    duration_sec: dict[str, float] = {}
    for row in frozen:
        split = str(row["split"])
        split_counts[split] = split_counts.get(split, 0) + 1
        song_counts.setdefault(split, set()).add(str(row["song_id"]))
        singer_counts.setdefault(split, set()).add(str(row.get("singer_id", "")))
        duration_sec[split] = duration_sec.get(split, 0.0) + float(row.get("duration_sec", 0.0))
    summary = {"status": "passed", "input_accepted_records": len(records), "manifest_hash": canonical_hash(frozen), "leakage_audit": audit,
               "split_summary": {split: {"item_count": split_counts.get(split, 0), "song_count": len(song_counts.get(split, set())), "singer_count": len(singer_counts.get(split, set())), "duration_sec": duration_sec.get(split, 0.0)} for split in ("train", "validation", "test")}}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
