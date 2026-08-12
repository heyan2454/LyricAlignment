#!/usr/bin/env python
"""03_gate: paired GT metrics + no-GT gate features + analysis.

Reads 02_behavior artifacts plus real GT, writes 03_gate/ outputs.

Usage:
    PYTHONPATH=src python scripts/realign_gate/03_gate_feature_analysis.py \
        --run-root <run> [--cfg <CONFIG.json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lyricalign.realign_gate.gate_features import run_stage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Realign Gate 03_gate feature analysis")
    parser.add_argument("--run-root", required=True, help="gate run root (with 02_behavior/)")
    parser.add_argument("--cfg", default=None, help="optional CONFIG.json (default run_root/00_meta/CONFIG.json)")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    try:
        summary = run_stage(run_root, args.cfg)
    except FileNotFoundError as exc:
        print(json.dumps({"result_status": "blocked",
                          "reason": "not_executed_dependency",
                          "detail": str(exc),
                          "run_root": str(run_root)}, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("result_status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
