#!/usr/bin/env python3
"""E6 supplement: mechanism reaching-threshold report (no-GT friendly).

Even without GT (so atlas cannot claim a final 'recovered' class), each
mechanism's evidence still records which tolerance bucket its refine reached
(best_<mech>_100/200/500/1000ms).  Aggregate per-mechanism coverage: how many
regions each mechanism AT LEAST reached per tolerance, plus best tightest bucket
distribution.  This gives a 'mechanism lower-bound capability' table.

Usage:
  PYTHONPATH=src python scripts/unit_realign/report_atlas_thresholds.py \
     --atlas <run>/01_atlas/ATLAS.jsonl --out <REACH_THRESHOLDS.json>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

MECHANISMS = ["coarse_fine", "iterative", "recrop", "split"]
BUCKETS = [100, 200, 500, 1000]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.atlas.read_text(encoding="utf-8").splitlines() if l.strip()]
    n = len(rows)
    per_mech = {}
    for mech in MECHANISMS:
        tightest = Counter()
        reach_any = 0
        buckets_hit = {}
        for b in BUCKETS:
            key = f"best_{mech}_{b}ms"
            hit = sum(1 for r in rows if r.get(key))
            buckets_hit[b] = hit
            reach_any += hit
        # not additive (a region can hit multiple); just report each bucket coverage
        per_mech[mech] = {"regions_hitting_bucket": buckets_hit,
                          "regions_with_any_evidence": len([r for r in rows
                            if any(r.get(f"best_{mech}_{b}ms") for b in BUCKETS)
                            or r.get(f"best_{mech}_error_ms") is not None])}
    achievable = Counter(r.get("best_achievable_ms") for r in rows)
    report = {
        "schema": "atlas_reaching_thresholds_v1",
        "n_regions": n,
        "note": "no-GT: cannot claim final recovery class; reporting mechanism lower-bound per-bucket coverage",
        "best_achievable_ms_distribution": dict(achievable),
        "per_mechanism_bucket_coverage": per_mech,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
