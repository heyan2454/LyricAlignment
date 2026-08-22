#!/usr/bin/env python3
"""Compare two GTSinger batch evaluation JSONs (e.g., official vs raw decoder)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--variant", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    base = load_json(args.baseline)["results"]
    var = load_json(args.variant)["results"]
    by_base = {r["subdir"]: r for r in base}
    rows = []
    for r in var:
        b = by_base.get(r["subdir"])
        if b is None:
            continue
        diff = round(r["both_100ms"] - b["both_100ms"], 4)
        rows.append({
            "item": r["subdir"],
            "baseline_100": b["both_100ms"],
            "variant_100": r["both_100ms"],
            "diff_100": diff,
            "direction": "improved" if diff > 0.001 else ("regressed" if diff < -0.001 else "same"),
            "units": r["unit_count"],
        })
    improved = sum(1 for x in rows if x["direction"] == "improved")
    regressed = sum(1 for x in rows if x["direction"] == "regressed")
    same = sum(1 for x in rows if x["direction"] == "same")
    summary = {
        "schema_version": "gtsinger_eval_comparison_v1",
        "baseline": str(args.baseline),
        "variant": str(args.variant),
        "item_count": len(rows),
        "improved_100ms": improved,
        "regressed_100ms": regressed,
        "same_100ms": same,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
