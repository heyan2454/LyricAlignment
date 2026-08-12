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
    args = p.parse_args()

    cfg_path = Path(args.cfg)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if args.limit:
        cfg["limit"] = args.limit
    cfg["command"] = " ".join(sys.argv)

    from lyricalign.realign_gate.test_demo import run_stage

    summary = run_stage(args.run_root, str(cfg_path), top_k=args.top_k)
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
