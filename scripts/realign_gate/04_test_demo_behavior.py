#!/usr/bin/env python3
"""04_test_demo_behavior: Test Demo no-GT stress (detector summary + stress realign).

Usage:
    PYTHONPATH=src python scripts/realign_gate/04_test_demo_behavior.py \
        --run-root <run> --cfg <CONFIG.json> [--top-k 20] [--limit N]

Writes under <run>/04_test_demo/:
    TEST_DEMO_DETECTOR_SUMMARY.json  TEST_DEMO_SUSPICIOUS_WINDOWS.jsonl
    TEST_DEMO_REALIGN_BEHAVIOR.jsonl
No accuracy/harm labels are produced.  --adapter mock in CONFIG.json runs the
deterministic CPU adapter (no model); default runs the real detector adapter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", required=True)
    p.add_argument("--cfg", required=True)
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--gpu", action="store_true", help="execute generated Demo requests with the frozen model")
    p.add_argument("--checkpoint-path")
    args = p.parse_args()

    cfg_path = Path(args.cfg)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if args.limit:
        cfg["limit"] = args.limit
    cfg["command"] = " ".join(sys.argv)

    from lyricalign.realign_gate.test_demo import run_stage

    summary = run_stage(args.run_root, str(cfg_path), top_k=args.top_k, limit=args.limit)
    if args.gpu:
        if cfg.get("adapter") == "mock":
            p.error("--gpu requires a real detector adapter, not mock")
        from lyricalign.realign_gate.case_selection import _invoke_suite, _suite_argv
        from lyricalign.realign_gate import identity
        manifest = Path(args.run_root) / "04_test_demo" / "TEST_DEMO_EXECUTOR_MANIFEST.jsonl"
        out = Path(args.run_root) / "04_test_demo" / "forward"
        suite = _invoke_suite(_suite_argv(manifest, out, smoke=False, gpu=True, limit=0,
                                          model_id=identity.MODEL_ID, checkpoint_id=identity.CHECKPOINT_ID,
                                          model_revision=identity.MODEL_REVISION,
                                          checkpoint_path=args.checkpoint_path or identity.CHECKPOINT_PATH,
                                          resume=True))
        if suite["returncode"] != 0:
            raise RuntimeError(suite["stderr"])
        run_manifest = json.loads((out / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
        evidence_by_request = {
            row.get("request_id"): row for row in (run_manifest.get("requests_identity") or [])
        }
        behavior = []
        for request in (json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()):
            identity_row = evidence_by_request.get(request.get("request_id"), {})
            behavior.append({
                "request_id": request.get("request_id"), "item": request.get("item_id"),
                "variant": request.get("input_variant"), "target_unit_ids":
                    (request.get("provenance") or {}).get("target_unit_ids"),
                "request_identity": identity_row.get("request_identity"),
                "execution_status": identity_row.get("status", "unknown"),
                "no_gt": True,
            })
        (Path(args.run_root) / "04_test_demo" / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in behavior), encoding="utf-8")
        summary["realign_execution_status"] = "real_forward_completed"
        summary["realign_executor"] = "research_v7.run_behavior_suite"
        (Path(args.run_root) / "04_test_demo" / "TEST_DEMO_DETECTOR_SUMMARY.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (Path(args.run_root) / "04_test_demo" / "TEST_DEMO_EXECUTION.json").write_text(
            json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "n_items": summary.get("n_items"),
        "n_failed": summary.get("n_failed"),
        "n_windows": summary.get("n_windows"),
        "n_requests": summary.get("n_requests"),
        "output": str(Path(args.run_root) / "04_test_demo"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
