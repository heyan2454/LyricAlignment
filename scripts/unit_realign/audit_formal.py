#!/usr/bin/env python3
"""Fail-fast audit for completed unit-realign formal artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--core-root", required=True)
    p.add_argument("--demo-root", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    core = Path(args.core_root) / "02_behavior"
    demo = Path(args.demo_root) / "04_test_demo"
    core_req = rows(core / "REQUESTS.jsonl")
    core_check = rows(core / "NO_GT_CHECK.jsonl")
    core_manifest = json.loads((core / "forward" / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    demo_manifest = json.loads((demo / "forward" / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    demo_behavior = rows(demo / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl")
    violations = []
    if any(not x.get("validated") for x in core_check):
        violations.append("core_no_gt_firewall")
    if any(x.get("status") != "ok" for x in core_manifest.get("requests_identity", [])):
        violations.append("core_forward_status")
    if len(core_manifest.get("requests_identity", [])) != len(core_req):
        violations.append("core_manifest_request_count")
    if any(x.get("status") != "ok" for x in demo_manifest.get("requests_identity", [])):
        violations.append("demo_forward_status")
    if len(demo_manifest.get("requests_identity", [])) != len(demo_behavior):
        violations.append("demo_behavior_request_count")
    for req in core_req:
        if req.get("input_variant") == "R-S_sparse_fixed":
            active = set(req.get("active_slot_indices") or [])
            fixed = {x.get("local_index") for x in req.get("fixed_slot_rows") or []}
            if not active or active & fixed or active | fixed != set(range(len(req.get("text_units") or []))):
                violations.append(f"sparse_partition:{req.get('request_id')}")
    result = {
        "schema": "unit_realign_formal_audit_v1",
        "status": "pass" if not violations else "fail",
        "violations": violations,
        "core_request_count": len(core_req),
        "core_forward_ok": sum(x.get("status") == "ok" for x in core_manifest.get("requests_identity", [])),
        "demo_forward_ok": sum(x.get("status") == "ok" for x in demo_manifest.get("requests_identity", [])),
        "demo_behavior_count": len(demo_behavior),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
