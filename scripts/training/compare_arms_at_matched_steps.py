#!/usr/bin/env python3
"""Compare two training runs at *matched optimizer steps* on the shared in-training validation curve.

The funnel's L1 subset is deterministic (same labels, same split, same ordering), so two runs' L1
points are directly comparable step for step — which is the cheapest way to ask "did this change help
at equal compute?" before spending GPU time on full-set re-evaluation.  Differences here are on a
25% subset, so treat them as a screen, not a verdict; the pre-registered endpoints still decide.

    PYTHONPATH=src python scripts/training/compare_arms_at_matched_steps.py \
        --a /home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724 \
        --b /home/hyan/Data/lyricalign/runs/20260914_qwen_fa_r2_concat20c_seed20260724 \
        --out results/by_run/20260914_matched_steps/concat_vs_uniform.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any

VARIANTS = ("fixed", "raw", "raw_targeted")


def l1_curve(run_dir: Path) -> dict[int, dict[str, float]]:
    path = run_dir / "funnel_evals.jsonl"
    if not path.exists():
        raise SystemExit(f"missing {path}")
    out: dict[int, dict[str, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)["funnel_eval"]
        if record.get("level") != "l1":
            continue
        out[int(record["evaluated_step"])] = {
            variant: float(values["macro_within_primary"])
            for variant, values in (record.get("variants") or {}).items() if values.get("macro_within_primary") is not None}
    return out


def summarise(a: dict[int, dict[str, float]], b: dict[int, dict[str, float]],
              *, label_a: str, label_b: str) -> dict[str, Any]:
    common = sorted(set(a) & set(b))
    payload: dict[str, Any] = {"schema_version": "matched_steps_v1", "label_a": label_a, "label_b": label_b,
                               "shared_points": len(common),
                               "step_range": [common[0], common[-1]] if common else None,
                               "variants": {}}
    for variant in VARIANTS:
        diffs = [(b[step][variant] - a[step][variant]) * 100.0 for step in common
                 if variant in a[step] and variant in b[step]]
        if not diffs:
            continue
        block: dict[str, Any] = {"points": len(diffs), "mean_delta_pp": round(st.mean(diffs), 3),
                                 "median_delta_pp": round(st.median(diffs), 3),
                                 "se_pp": round(st.stdev(diffs) / len(diffs) ** 0.5, 3) if len(diffs) > 1 else None,
                                 "b_better_points": sum(1 for value in diffs if value > 0),
                                 "b_worse_points": sum(1 for value in diffs if value < 0),
                                 "last_shared": None}
        if common:
            last = common[-1]
            block["last_shared"] = {"step": last, "a": round(a[last].get(variant, float("nan")), 4),
                                    "b": round(b[last].get(variant, float("nan")), 4)}
        payload["variants"][variant] = block
    for label, curve in ((label_a, a), (label_b, b)):
        points = [step for step in sorted(curve) if step in set(common)]
        if len(points) >= 2:
            first, last = curve[points[0]], curve[points[-1]]
            payload.setdefault("own_progress", {})[label] = {
                "from_step": points[0], "to_step": points[-1],
                "fixed_delta_pp": round(100 * (last["fixed"] - first["fixed"]), 3)}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", type=Path, required=True, help="baseline run dir")
    parser.add_argument("--b", type=Path, required=True, help="challenger run dir")
    parser.add_argument("--label-a")
    parser.add_argument("--label-b")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    label_a = args.label_a or args.a.name
    label_b = args.label_b or args.b.name
    payload = summarise(l1_curve(args.a), l1_curve(args.b), label_a=label_a, label_b=label_b)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{label_b} 相对 {label_a}（同一 L1 子集，{payload['shared_points']} 个同步点）：")
    for variant, block in payload["variants"].items():
        se = block["se_pp"] if block["se_pp"] is not None else float("nan")
        print(f"  {variant:12s} 平均 {block['mean_delta_pp']:+.2f}pp (SE {se:.2f})  "
              f"B更好 {block['b_better_points']}/{block['points']}  最后同步点 {block['last_shared']}")
    for label, block in payload.get("own_progress", {}).items():
        print(f"  自身进步 {label:44s} {block['from_step']}->{block['to_step']} fixed {block['fixed_delta_pp']:+.2f}pp")


if __name__ == "__main__":
    main()
