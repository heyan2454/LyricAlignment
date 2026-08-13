"""P12.5 companion: wire aggregate_consensus to the real P5 producer.

Consumes UNIT_GATE_FEATURES.jsonl (from extract_unit_gate_features.py) and emits
cross-family per-(song, region, canonical_unit) consensus views via
lyricalign.unit_realign.consensus.aggregate_consensus.

This is the median/MAD-displacement view of consensus (families agree on where
the unit moves). It complements analyze_multi_request_consensus.py, which uses a
span/consistent_34 view over raw evidence start times. Both read no-GT data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lyricalign.unit_realign.consensus import aggregate_consensus


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8")] if path.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main-run", required=True)
    ap.add_argument("--features", default=None,
                    help="UNIT_GATE_FEATURES.jsonl (default <main-run>/05_analysis/UNIT_GATE_FEATURES.jsonl)")
    ap.add_argument("--out", default=None,
                    help="output jsonl (default <main-run>/05_analysis/UNIT_CONSENSUS.jsonl)")
    args = ap.parse_args()

    run = Path(args.main_run)
    features_path = Path(args.features) if args.features \
        else run / "05_analysis" / "UNIT_GATE_FEATURES.jsonl"
    out_path = Path(args.out) if args.out else run / "05_analysis" / "UNIT_CONSENSUS.jsonl"
    if not features_path.exists():
        raise SystemExit(f"features not found: {features_path} (run extract_unit_gate_features.py first)")

    rows = load_jsonl(features_path)
    out = aggregate_consensus(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in out:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    n = len(out)
    n_multi = sum(1 for r in out if r["n_families"] >= 2)
    n_filled = sum(1 for r in out if r["median_displacement_ms"] is not None)
    n_context = sum(1 for r in out if r["context_protection_ratio"] is not None)
    print(json.dumps({
        "n_units": n,
        "n_multi_family": n_multi,
        "n_median_displacement_filled": n_filled,
        "n_context_protection_ratio_filled": n_context,
        "multi_family_ratio": round(n_multi / n, 4) if n else None,
        "median_displacement_fill_ratio": round(n_filled / n, 4) if n else None,
        "features": str(features_path),
        "out": str(out_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
