#!/usr/bin/env python
"""Re-aggregate unit outcomes by the v2 evaluator classification contract.

Classification policy lives in `lyricalign.unit_realign.unit_outcome`:
`aggregate_region_outcome` (per region, target + fixed-context + extra) and
`aggregate_candidate_outcome` (per request).  This script no longer owns its
own classification thresholds/policy; it only groups unit rows into regions,
delegates labels to the shared evaluator, and reports denominators.

Labels are the v2 set: beneficial / neutral / harmful / catastrophic_harmful /
mixed.  Fixed-context rows and extra/unpairable predictions are retained and
count toward harm; `covered_to_missing` is catastrophic.

Usage:
    PYTHONPATH=src python scripts/unit_realign/aggregate_classification.py \
        --run-root <run> [--unit-outcomes <jsonl>] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import os

from lyricalign.unit_realign.unit_outcome import (
    aggregate_candidate_outcome,
    aggregate_region_outcome,
)

OUTCOME_LABELS = ("beneficial", "neutral", "harmful", "catastrophic_harmful", "mixed")


def _find_unit_outcomes(run_root):
    for rel in (
        "06_evaluator_only/UNIT_OUTCOMES.jsonl",
        "03_unit_outcomes/UNIT_OUTCOMES.jsonl",
        "UNIT_OUTCOMES.jsonl",
    ):
        p = os.path.join(run_root, rel)
        if os.path.isfile(p):
            return p
    return None


def _read_rows(path):
    rows = []
    for line in open(path, "r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _region_key(row):
    request = str(row.get("request_id") or row.get("request_identity") or "")
    region = str(row.get("region_id") or "")
    return (request, region)


def _empty_counts():
    return {label: 0 for label in OUTCOME_LABELS}


def _group_regions(rows):
    by_region = {}
    for r in rows:
        by_region.setdefault(_region_key(r), []).append(r)
    return by_region


def _unit_level(rows):
    deltas = [r.get("delta_max_boundary_error_ms") for r in rows]
    finite = [d for d in deltas if isinstance(d, (int, float))]
    return {
        "n_rows": len(rows),
        "n_finite_delta": len(finite),
        "improved_any_delta": sum(d < 0 for d in finite),
        "unchanged_zero_delta": sum(d == 0 for d in finite),
        "regressed_any_delta": sum(d > 0 for d in finite),
    }


def _extra_stats(rows):
    return {
        "n_extra": sum(1 for r in rows if r.get("role") == "extra"),
        "n_invalid_unpairable": sum(1 for r in rows if r.get("invalid_unpairable")),
    }


def aggregate(run_root, unit_outcomes_path):
    rows = _read_rows(unit_outcomes_path)
    by_region = _group_regions(rows)

    region_outcomes = []
    per_region = {}
    region_target = 0
    region_context = 0
    for key, rrows in sorted(by_region.items()):
        outcome = aggregate_region_outcome(rrows)
        region_outcomes.append(outcome)
        per_region["::".join(x for x in key if x)] = {
            **outcome,
            "n_target_rows": outcome["n_target"],
            "n_context_rows": outcome["n_context"],
            **{"extra_and_unpairable": _extra_stats(rrows)},
        }
        region_target += outcome["n_target"]
        region_context += outcome["n_context"]

    region_counts = _empty_counts()
    for r in region_outcomes:
        region_counts[r["outcome"]] = region_counts.get(r["outcome"], 0) + 1

    by_request = {}
    for r in region_outcomes:
        rid = str(r.get("request_id") or r.get("request_identity") or "unknown")
        by_request.setdefault(rid, []).append(r)
    candidate_outcomes = {rid: aggregate_candidate_outcome(ro)
                          for rid, ro in sorted(by_request.items())}
    candidate_counts = _empty_counts()
    for r in candidate_outcomes.values():
        candidate_counts[r["outcome"]] = candidate_counts.get(r["outcome"], 0) + 1

    return {
        "schema": "unit_realign_classification_aggregate_v2",
        "run_root": run_root,
        "note": (
            "classification delegated to unit_realign.unit_outcome: "
            "aggregate_region_outcome (target+fixed-context+extra) and "
            "aggregate_candidate_outcome (per request). unit-count improved/"
            "regressed (any sign of delta) is NOT the classification label."
        ),
        "inputs": {
            "unit_outcomes_path": unit_outcomes_path,
            "n_rows": len(rows),
            "n_regions": len(by_region),
            "n_candidates": len(candidate_outcomes),
        },
        "unit_level": _unit_level(rows),
        "extra_and_unpairable": _extra_stats(rows),
        "region_level": {
            "n_regions": len(by_region),
            "classification_counts": region_counts,
            "target_rows": region_target,
            "fixed_context_rows": region_context,
        },
        "candidate_level": {
            "n_candidates": len(candidate_outcomes),
            "classification_counts": candidate_counts,
        },
        "per_region": per_region,
        "per_candidate": candidate_outcomes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--unit-outcomes")
    parser.add_argument("--out")
    args = parser.parse_args()
    run_root = os.path.abspath(args.run_root)
    upath = args.unit_outcomes or _find_unit_outcomes(run_root)
    if not upath:
        print("NO UNIT_OUTCOMES found; skipped")
        return 1
    report = aggregate(run_root, upath)
    out = args.out or os.path.join(run_root, "05_analysis", "CLASSIFICATION_AGGREGATE.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"WROTE {out}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
