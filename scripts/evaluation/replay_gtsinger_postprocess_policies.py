#!/usr/bin/env python3
"""Replay boundary post-processing policies over the GTSinger GT evidence panel (CPU only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import postprocess_replay as pr

DEFAULT_EVIDENCE = Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="defaults to the evidence file's parent directory")
    args = ap.parse_args()
    out_dir = args.out_dir or args.evidence.parent
    print(json.dumps(pr.main(args.evidence, out_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
