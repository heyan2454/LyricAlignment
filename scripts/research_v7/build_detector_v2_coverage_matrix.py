#!/usr/bin/env python3
"""Initialize or validate the Detector V2 coverage matrix."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from lyricalign.research_v7.detector_v2_coverage import (
    populate_status_from_artifacts,
    validate_coverage_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", type=Path, help="copy a coverage template")
    group.add_argument("--validate", type=Path, help="validate a populated coverage matrix")
    parser.add_argument("--out", type=Path, help="destination for --init")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="repo root (code)")
    parser.add_argument("--run-root", type=Path, default=None, help="run artifact dir; artifacts checked against it")
    parser.add_argument("--matrix-out", type=Path, default=None, help="write matrix JSON (default DETECTOR_V2_COVERAGE_MATRIX.json)")
    parser.add_argument("--no-auto-populate", action="store_true", help="do not annotate pending cells from run-root artifacts")
    args = parser.parse_args()

    if args.init:
        if args.out is None:
            parser.error("--out is required with --init")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.init, args.out)
        print(json.dumps({"ok": True, "created": str(args.out)}, ensure_ascii=False))
        return 0

    matrix = json.loads(args.validate.read_text(encoding="utf-8"))
    if args.run_root is not None and not args.no_auto_populate:
        populate_status_from_artifacts(matrix, args.run_root)
    report = validate_coverage_matrix(matrix, repo_root=args.repo_root, run_root=args.run_root)
    matrix_out = args.matrix_out or Path("DETECTOR_V2_COVERAGE_MATRIX.json")
    matrix_out.parent.mkdir(parents=True, exist_ok=True)
    out_doc = dict(matrix)
    out_doc["_validation"] = report
    matrix_out.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
