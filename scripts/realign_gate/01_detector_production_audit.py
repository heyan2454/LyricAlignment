#!/usr/bin/env python
"""CLI: run the 01_detector_audit stage for Detector Production Audit + Realign Gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lyricalign.realign_gate.detector_audit import run_stage


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, help="run_root (CONFIG.json under 00_meta/)")
    parser.add_argument("--cfg", default=None, help="path to CONFIG.json (default <run-root>/00_meta/CONFIG.json)")
    parser.add_argument("--limit", type=int, default=0, help="cap population rows (0=all)")
    parser.add_argument(
        "--audit-source", choices=("baseline", "raw_requests"), default="baseline",
        help="population source: baseline (production, default) or raw_requests (degraded E5 proposal bank)")
    args = parser.parse_args(argv)
    cfg_path = Path(args.cfg) if args.cfg else Path(args.run_root) / "00_meta" / "CONFIG.json"
    summary = run_stage(args.run_root, cfg_path, limit=args.limit, audit_source=args.audit_source)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
