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
from lyricalign.datasets.split import canonical_hash, freeze_m4singer_split, leakage_audit


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
    parser.add_argument("--validation-percent", type=int, default=10)
    args = parser.parse_args()
    records = [row for row in read_jsonl(args.input) if row.get("status") == "accepted"]
    frozen = freeze_m4singer_split(records, args.seed, args.validation_percent)
    audit = leakage_audit(frozen)
    if not audit["passed"]:
        raise SystemExit(json.dumps(audit, ensure_ascii=False))
    atomic_jsonl(args.out_dir / "m4singer_accepted_split_manifest.jsonl", frozen)
    summary = {"status": "passed", "input_accepted_records": len(records), "manifest_hash": canonical_hash(frozen), "leakage_audit": audit}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
