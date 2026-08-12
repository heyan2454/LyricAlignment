"""05_report: build FINAL_REPORT.md + FINAL_SUMMARY.json from 00-04 stage artifacts.

Usage:
  PYTHONPATH=src python scripts/realign_gate/05_report.py --run-root <run> [--cfg <CONFIG.json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.realign_gate.report import run_stage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, help="run root directory")
    parser.add_argument("--cfg", default=None, help="optional CONFIG.json path (default run_root/00_meta/CONFIG.json)")
    args = parser.parse_args()

    summary = run_stage(args.run_root, cfg_path=args.cfg)
    print(json.dumps({"result_status": summary["result_status"], "run_root": args.run_root}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
