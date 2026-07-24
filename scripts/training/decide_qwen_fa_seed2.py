#!/usr/bin/env python3
"""Apply a preregistered validation-only gate for a second full R2 seed."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def metric(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("metric", data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r1-evaluation", type=Path, required=True)
    parser.add_argument("--r2-evaluation", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-absolute-improvement-sec", type=float, default=0.005)
    parser.add_argument("--minimum-relative-improvement", type=float, default=0.10)
    parser.add_argument("--maximum-invalid-rate-increase", type=float, default=0.01)
    parser.add_argument("--maximum-coverage-decrease", type=float, default=0.01)
    args = parser.parse_args()

    r1, r2 = metric(args.r1_evaluation), metric(args.r2_evaluation)
    primary = "song_macro_boundary_mae_sec"
    r1_value, r2_value = float(r1[primary]), float(r2[primary])
    absolute = r1_value - r2_value
    relative = absolute / r1_value if r1_value > 0 else float("-inf")
    invalid_delta = float(r2.get("invalid_prediction_rate", 1.0)) - float(r1.get("invalid_prediction_rate", 1.0))
    coverage_delta = float(r2.get("item_coverage", 0.0)) - float(r1.get("item_coverage", 0.0))
    finite = all(math.isfinite(value) for value in (r1_value, r2_value, absolute, relative, invalid_delta, coverage_delta))
    criteria = {
        "finite_metrics": finite,
        "absolute_improvement_pass": absolute >= args.minimum_absolute_improvement_sec,
        "relative_improvement_pass": relative >= args.minimum_relative_improvement,
        "invalid_rate_pass": invalid_delta <= args.maximum_invalid_rate_increase,
        "coverage_pass": coverage_delta >= -args.maximum_coverage_decrease,
    }
    recommend = all(criteria.values())
    result = {
        "schema_version": 1,
        "decision_scope": "validation_only_paired_100_step_seed2_pilot",
        "seed": args.seed,
        "test_or_ood_used_for_decision": False,
        "primary_metric": primary,
        "r1_value_sec": r1_value,
        "r2_value_sec": r2_value,
        "absolute_improvement_sec": absolute,
        "relative_improvement": relative,
        "invalid_rate_delta": invalid_delta,
        "item_coverage_delta": coverage_delta,
        "thresholds": {
            "minimum_absolute_improvement_sec": args.minimum_absolute_improvement_sec,
            "minimum_relative_improvement": args.minimum_relative_improvement,
            "maximum_invalid_rate_increase": args.maximum_invalid_rate_increase,
            "maximum_coverage_decrease": args.maximum_coverage_decrease,
        },
        "criteria": criteria,
        "recommend_full_r2_second_seed": recommend,
        "conclusion_strength": "pilot_gate_only; full second-seed training is still required for cross-seed evidence" if recommend else "pilot did not reproduce the R2-over-R1 advantage strongly enough",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
