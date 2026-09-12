#!/usr/bin/env python3
"""Build the long-form weak-GT panel from existing detector_v2 evidence (CPU only).

    PYTHONPATH=src python scripts/evaluation/build_m4_longform_weakgt_panel.py \
        --out-dir /home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt [--analyze]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import m4_longform_weakgt as P

DEFAULT_OUT = Path("/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--runs", nargs="*", default=["run1", "run2"])
    ap.add_argument("--analyze", action="store_true",
                    help="also run the analysis and write ANALYSIS.json")
    args = ap.parse_args()

    stats = P.build_panel(args.out_dir, tuple(args.runs))
    result = {"panel": {k: stats[k] for k in ("rows", "out", "bytes", "schema_version")},
              "runs": stats["runs"]}
    if args.analyze:
        df = P.load_frame(Path(stats["out"]))
        analysis = P.analyse(df)
        (args.out_dir / "ANALYSIS.json").write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["join"] = analysis.get("uniform_axis_trap")
        result["baseline_units"] = analysis["panel"]["baseline_unit_rows"]
        result["hit100"] = {"raw": analysis["stage_comparison"]["micro_hit100_raw"],
                            "official": analysis["stage_comparison"]["micro_hit100_official"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
