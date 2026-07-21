#!/usr/bin/env python3
"""Assign exactly one explainable quality tier to every manifest record."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.curation.quality import apply_quality_tier


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    input_rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line]
    rows = [apply_quality_tier(row) for row in input_rows]
    counts = Counter(row["quality_tier"] for row in rows)
    if len(rows) != sum(counts.values()):
        raise RuntimeError("quality tier conservation failure")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.out_dir, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(args.out_dir / "quality_tier_manifest.jsonl")
    summary = {"status": "passed", "total": len(rows), "quality_counts": dict(sorted(counts.items()))}
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
