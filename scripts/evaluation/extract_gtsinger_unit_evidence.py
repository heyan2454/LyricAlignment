#!/usr/bin/env python3
"""Extract per-unit GTSinger ground-truth evidence rows from evaluation_v1 runs.

CPU only, reads existing run artifacts, writes a small gzip JSONL plus a summary.

    PYTHONPATH=src python scripts/evaluation/extract_gtsinger_unit_evidence.py \
        --preset gtsinger --out-root /home/hyan/Data/lyricalign/runs/<out>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_evidence as gge

DATA_RUNS = Path("/home/hyan/Data/lyricalign/runs")


def discover_gtsinger_runs(root: Path) -> list[Path]:
    """Every ``20260816_evaluation_v1_gtsinger*`` run that carries a gt_map.jsonl."""
    found = []
    for path in sorted(root.glob("20260816_evaluation_v1_gtsinger*")):
        if path.is_dir() and (path / "gt_map.jsonl").exists():
            found.append(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", action="append", default=[], type=Path,
                        help="evaluation run root (repeatable); overrides --preset")
    parser.add_argument("--preset", default="gtsinger", choices=["gtsinger", "none"])
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--no-compress", action="store_true")
    args = parser.parse_args()

    roots = list(args.run_root)
    if not roots and args.preset == "gtsinger":
        roots = discover_gtsinger_runs(DATA_RUNS)
    if not roots:
        print(json.dumps({"error": "no run roots with gt_map.jsonl found"}, ensure_ascii=False))
        return 2

    args.out_root.mkdir(parents=True, exist_ok=True)
    compress = not args.no_compress
    out_path = args.out_root / ("unit_evidence.jsonl.gz" if compress else "unit_evidence.jsonl")

    rows, stats = gge.extract_runs(roots)
    gge.write_rows(rows, out_path, compress=compress)
    summary = gge.summarise(rows, stats, out_path, extra={
        "run_roots": [str(r) for r in roots],
        "singers": sorted({r["singer"] for r in rows}),
        "groups": sorted({r["group"] for r in rows}),
        "techniques": sorted({r["technique"] for r in rows}),
        "pipelines": sorted({r["pipeline"] for r in rows}),
        "models": sorted({r["model"] for r in rows}),
        "modes": sorted({r["mode"] for r in rows}),
        "audio_inputs": sorted({r["audio_input"] for r in rows}),
    })
    (args.out_root / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out_root / "SKIPPED.json").write_text(
        json.dumps(stats.items_skipped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"out": str(out_path), "stats": summary["stats"],
                      "per_run": summary["per_run"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
