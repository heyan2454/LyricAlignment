#!/usr/bin/env python
"""Audit round-2 gates (eligible >= 500, selected >= 300) for a unit_realign run.

Reads 02_behavior/SAMPLE_ACCOUNTING.json and, if present,
05_analysis/STRATIFIED_POOL.jsonl (or 03_unit_outcomes/STRATIFIED_POOL.jsonl).
Writes 05_analysis/ROUND2_GATE_AUDIT.json.

Usage:
    PYTHONPATH=src python scripts/unit_realign/audit_round2_gates.py \
        --run-root <run> [--out <path>]
"""
import argparse
import json
import os

STRATA = ["S1", "S2", "S3", "S4", "SG"]
GATE_ELIGIBLE = 500
GATE_SELECTED = 300


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _count_pool(pool_path):
    n_total = 0
    n_baseline_valid = 0
    for line in open(pool_path, "r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        n_total += 1
        if row.get("baseline_available", True) and not row.get("ineligible"):
            n_baseline_valid += 1
    return {"n_total": n_total, "n_baseline_valid": n_baseline_valid}


def audit_gates(run_root):
    acc = _load_json(os.path.join(run_root, "02_behavior", "SAMPLE_ACCOUNTING.json"))
    pool_path = None
    for candidate in (
        os.path.join(run_root, "05_analysis", "STRATIFIED_POOL.jsonl"),
        os.path.join(run_root, "03_unit_outcomes", "STRATIFIED_POOL.jsonl"),
        os.path.join(run_root, "STRATIFIED_POOL.jsonl"),
    ):
        if os.path.isfile(candidate):
            pool_path = candidate
            break

    eligible_per_stratum = {}
    eligible_total = 0
    if acc:
        eligible = acc.get("eligible") or {}
        for k in STRATA:
            eligible_per_stratum[k] = eligible.get(k, 0)
            eligible_total += eligible.get(k, 0)

    pool_stats = _count_pool(pool_path) if pool_path else None

    selected = None
    attempts = (acc or {}).get("attempts") or []
    if attempts:
        selected = attempts[-1].get("selected")
    elif acc and acc.get("selected") is not None:
        selected = acc.get("selected")

    status = (acc or {}).get("status")

    # 注意：eligible>=500 / selected>=300 是本脚本自定的 exploratory 阈值，不是 P1 formal
    # acceptance 门槛。P1 completion 只按 v2 resolved config 的 strata/family denominator
    # （S1–S4 各 25 valid case）判定；本脚本是只读 audit，不消费 formal pass/fail 与
    # writeback discussion。见 08_OPENCODE_REVIEW_REBUTTAL.md P1-5。
    eligible_pass = eligible_total >= GATE_ELIGIBLE
    selected_pass = (selected or 0) >= GATE_SELECTED
    report = {
        "schema": "unit_realign_round2_gate_audit_v1",
        "exploratory_only": True,
        "run_root": run_root,
        "gate": {"eligible_min": GATE_ELIGIBLE, "selected_min": GATE_SELECTED},
        "eligible": {
            "total": eligible_total,
            "per_stratum": eligible_per_stratum,
            "source": "SAMPLE_ACCOUNTING.json" if acc else "not_found",
            "pool": pool_stats,
        },
        "selected_requests": selected,
        "source_accounting_status": status,
        "eligible_gate": {
            "target": GATE_ELIGIBLE,
            "actual": eligible_total,
            "pass": eligible_pass,
            "gap": max(0, GATE_ELIGIBLE - eligible_total),
        },
        "selected_gate": {
            "target": GATE_SELECTED,
            "actual": selected,
            "pass": selected_pass,
            "gap": max(0, GATE_SELECTED - (selected or 0)),
        },
        "round2_gate_pass": eligible_pass and selected_pass,
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    run_root = os.path.abspath(args.run_root)
    report = audit_gates(run_root)
    out = args.out or os.path.join(run_root, "05_analysis", "ROUND2_GATE_AUDIT.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"WROTE {out}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
