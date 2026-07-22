#!/usr/bin/env python3
"""Audit all M4Singer metadata and WAVs without modifying the source dataset."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.audit import classify_item, summarize


def read_overlays(path: Path | None) -> list[dict]:
    if path is None:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m4singer-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--representatives-per-class", type=int, default=10)
    parser.add_argument("--token-overlays", type=Path, help="Approved hash-anchored JSONL source-token overlays")
    args = parser.parse_args()
    raw = json.loads((args.m4singer_root / "meta.json").read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("meta.json must contain a list")
    overlays = read_overlays(args.token_overlays)
    records = [classify_item(item, str(args.m4singer_root), overlays=overlays) for item in raw]
    summary = summarize(records)
    representatives: dict[str, list[dict]] = {}
    for record in records:
        representatives.setdefault(record["taxonomy"], [])
        if len(representatives[record["taxonomy"]]) < args.representatives_per_class:
            representatives[record["taxonomy"]].append(record)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.out_dir, delete=False) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(args.out_dir / "m4singer_audit.jsonl")
    atomic_json(args.out_dir / "m4singer_audit_summary.json", {**summary, "representatives": representatives, "token_overlay_count": len(overlays)})
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
