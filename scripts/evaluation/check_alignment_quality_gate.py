#!/usr/bin/env python3
"""Check an alignment JSON against productization quality gates.

Gates:
- zero-duration rate
- inter-unit overlap count
- timestamp regression count
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--max-zero-rate", type=float, default=0.05)
    parser.add_argument("--max-overlap", type=int, default=0)
    parser.add_argument("--max-regression", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.alignment.read_text(encoding="utf-8"))
    chars = data.get("characters", [])
    zero = 0
    overlap = 0
    regression = 0
    for i, c in enumerate(chars):
        start = float(c.get("selected_start_sec", c.get("start_sec")))
        end = float(c.get("selected_end_sec", c.get("end_sec")))
        if end - start <= 0:
            zero += 1
        if i > 0:
            prev = chars[i - 1]
            prev_end = float(prev.get("selected_end_sec", prev.get("end_sec")))
            if start < prev_end - 1e-6:
                overlap += 1
        if i > 0:
            prev_start = float(prev.get("selected_start_sec", prev.get("start_sec")))
            if start < prev_start - 1e-6:
                regression += 1
    zero_rate = zero / len(chars) if chars else 0.0
    problems = []
    if zero_rate > args.max_zero_rate:
        problems.append(f"zero_duration_rate {zero_rate:.3f} > {args.max_zero_rate}")
    if overlap > args.max_overlap:
        problems.append(f"overlap_count {overlap} > {args.max_overlap}")
    if regression > args.max_regression:
        problems.append(f"regression_count {regression} > {args.max_regression}")
    report = {
        "schema_version": "alignment_quality_gate_v1",
        "alignment": str(args.alignment),
        "unit_count": len(chars),
        "zero_duration_count": zero,
        "zero_duration_rate": round(zero_rate, 4),
        "inter_unit_overlap_count": overlap,
        "timestamp_regression_count": regression,
        "passed": not problems,
        "problems": problems,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
