#!/usr/bin/env python3
"""Run the deep GT analyses over an extracted GTSinger unit-evidence panel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as deep

DEFAULT_EVIDENCE = Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="defaults to the evidence file's parent directory")
    args = parser.parse_args()
    out_dir = args.out_dir or args.evidence.parent
    summary = deep.run_all(args.evidence, out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
