#!/usr/bin/env python3
"""Add quality gate JSONs to existing GTSinger batch outputs without rerunning."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-root", type=Path, required=True)
    args = parser.parse_args()

    python = sys.executable
    env = {"PYTHONPATH": str(ROOT / "src")}
    done = 0
    missing = 0
    for d in sorted(args.batch_root.iterdir()):
        if not d.is_dir():
            continue
        alignment = d / "alignments/r2/vocal/windowed/alignment.json"
        if not alignment.is_file():
            continue
        gate_out = d / "quality_gate.json"
        if gate_out.exists():
            done += 1
            continue
        subprocess.run([
            python, str(ROOT / "scripts/evaluation/check_alignment_quality_gate.py"),
            "--alignment", str(alignment), "--out", str(gate_out),
        ], check=False, env=env)
        if gate_out.exists():
            done += 1
        else:
            missing += 1
    print(json.dumps({"batch_root": str(args.batch_root), "gates_written_or_present": done, "missing": missing}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
