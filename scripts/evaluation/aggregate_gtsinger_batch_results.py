#!/usr/bin/env python3
"""Combine GTSinger batch evaluation JSONs (r0/r1/r2) into one summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r0", type=Path, required=True)
    parser.add_argument("--r1", type=Path, required=True)
    parser.add_argument("--r2", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    evals = {name: load_json(path) for name, path in [("r0", args.r0), ("r1", args.r1), ("r2", args.r2)]}
    summary = {"schema_version": "gtsinger_batch_aggregate_v1", "models": {}}
    for name, data in evals.items():
        results = data.get("results", [])
        ok = [r for r in results if r.get("status") == "ok"]
        total_units = sum(r.get("unit_count", 0) for r in ok)
        total_b100 = sum(int(round(r.get("unit_count", 0) * r.get("both_100ms", 0.0))) for r in ok)
        total_b200 = sum(int(round(r.get("unit_count", 0) * r.get("both_200ms", 0.0))) for r in ok)
        total_b500 = sum(int(round(r.get("unit_count", 0) * r.get("both_500ms", 0.0))) for r in ok)
        summary["models"][name] = {
            "items_ok": len(ok),
            "total_units": total_units,
            "both_100ms": round(total_b100 / total_units, 4) if total_units else None,
            "both_200ms": round(total_b200 / total_units, 4) if total_units else None,
            "both_500ms": round(total_b500 / total_units, 4) if total_units else None,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
