#!/usr/bin/env python3
"""Fail closed audit for a frozen evaluator-only unit-realign report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-root", required=True, type=Path)
    p.add_argument("--eval-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    behavior = args.run_root / "02_behavior"
    summary = json.loads((args.eval_root / "EVALUATOR_ONLY_SUMMARY.json").read_text(encoding="utf-8"))
    outcomes = rows(args.eval_root / "UNIT_OUTCOMES.jsonl")
    requests = rows(behavior / "REQUESTS.jsonl")
    checks = rows(behavior / "NO_GT_CHECK.jsonl")
    manifest = json.loads((behavior / "forward" / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    problems = []
    if summary.get("mode") != "post_hoc_evaluator_only" or summary.get("runtime_gt_access") is not False:
        problems.append("evaluator_mode")
    if summary.get("actual_writeback") != 0:
        problems.append("writeback")
    if not all(row.get("validated") is True for row in checks):
        problems.append("no_gt_request_firewall")
    current = manifest.get("requests_identity") or []
    if len(current) != len(requests) or any(row.get("status") != "ok" for row in current):
        problems.append("current_forward_identity")
    inp = summary.get("inputs") or {}
    if inp.get("request_count") != len(requests) or inp.get("active_evidence_count") != len(current):
        problems.append("evaluator_input_coverage")
    if not outcomes:
        problems.append("no_outcomes")
    for row in outcomes:
        if row.get("pairing") != "canonical":
            problems.append("noncanonical_outcome")
            break
        if row.get("old_missing") or row.get("new_missing") or row.get("extra_prediction"):
            problems.append("coverage_failure")
            break
        if row.get("baseline_duplicate_prediction") or row.get("candidate_duplicate_prediction"):
            problems.append("duplicate_prediction")
            break
    result = {
        "schema": "unit_realign_evaluator_only_audit_v1",
        "status": "pass" if not problems else "fail", "problems": problems,
        "request_count": len(requests), "current_forward_ok": sum(x.get("status") == "ok" for x in current),
        "outcome_rows": len(outcomes), "all_canonical": all(x.get("pairing") == "canonical" for x in outcomes),
        "missing_or_extra": sum(bool(x.get("old_missing") or x.get("new_missing") or x.get("extra_prediction")) for x in outcomes),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
