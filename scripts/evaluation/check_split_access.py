#!/usr/bin/env python3
"""Gate utility for Evaluation V1 manifests.

By default this refuses to proceed when the manifest contains `sealed_final`
rows. Pass `--allow-sealed` only for a registered milestone run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_group_integrity(rows: list[dict]) -> list[str]:
    group_tiers: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group_tiers[str(row.get("group_id", ""))].add(str(row.get("tier", "")))
    return sorted(g for g, tiers in group_tiers.items() if len(tiers) > 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allow-sealed", action="store_true", help="Permit sealed_final rows for milestone runs")
    parser.add_argument("--expected-sha256", help="Optional expected manifest SHA-256")
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    counts = Counter(str(row.get("tier", "")) for row in rows)
    sealed = [row for row in rows if str(row.get("tier", "")) == "sealed_final"]
    cross = check_group_integrity(rows)
    problems: list[str] = []
    if not args.allow_sealed and sealed:
        problems.append(f"manifest contains {len(sealed)} sealed_final rows; pass --allow-sealed only for milestone runs")
    if cross:
        problems.append(f"same group appears in multiple tiers: {cross}")
    if args.expected_sha256:
        actual = sha256_file(args.manifest)
        if actual != args.expected_sha256:
            problems.append(f"SHA-256 mismatch: expected {args.expected_sha256}, got {actual}")
    report = {
        "manifest": str(args.manifest),
        "row_count": len(rows),
        "tier_counts": dict(sorted(counts.items())),
        "sealed_count": len(sealed),
        "allow_sealed": args.allow_sealed,
        "group_cross_tier": cross,
        "problems": problems,
        "allowed": not problems,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
