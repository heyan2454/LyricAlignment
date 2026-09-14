#!/usr/bin/env python3
"""Count-level (not rate-level) breakdown of an arm-to-arm comparison across duration buckets.

Rates hide how few characters actually move: a bucket can go from 11 misses to 6 misses on 127
characters, which is *five characters*.  Tonight's B verdict turned on exactly that, so this tool
reports, per ground-truth duration bucket:
  * how many characters are in the bucket,
  * the number with an offset error above tolerance, per arm,
  * the *discordant* counts between the two compared arms (newly fixed / newly broken).

Only the offset side is counted per arm-vs-arm, because adding onset and offset counts would silently
double the denominator relationship and invite reading 34 discordants where there are 17 characters.

    PYTHONPATH=src python scripts/evaluation/arms_by_bucket_counts.py \
        --dump "起点=results/by_run/20260914_mech_validation_uniform/per_character.jsonl" \
        --dump "A对照=results/by_run/20260914_mech_control/per_character.jsonl" \
        --dump "B上采样=results/by_run/20260914_mech_treatment/per_character.jsonl" \
        --better-than A对照 --worse-reference B上采样 \
        --out results/by_run/20260914_arms_by_bucket/metrics.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
EDGES = ((0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 99.0))


def bucket_of(duration: float) -> str:
    for low, high in EDGES:
        if low <= duration < high:
            return f"{low:g}-{high:g}s" if high < 99 else "2s+"
    return "other"


def offsets(path: Path) -> dict[tuple[str, int], tuple[float, float]]:
    """(gt duration, offset error) per character, from the d_rms channel of a dump."""
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    return {key: (float(kinds["onset"]["duration"]), float(kinds["offset"]["abs_err_argmax"]))
            for key, kinds in per.items() if len(kinds) == 2}


def parse_specs(specs: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for spec in specs:
        label, _, location = spec.partition("=")
        out[label.strip()] = Path(location.strip() if location else label)
    return out


def tabulate(arms: dict[str, dict[Any, tuple[float, float]]], *,
             reference: str | None = None, challenger: str | None = None) -> dict[str, Any]:
    names = list(arms)
    shared = set.intersection(*(set(arms[name]) for name in names)) if names else set()
    shared = sorted(shared, key=str)
    buckets: dict[str, Any] = {}
    for low, high in EDGES:
        label = f"{low:g}-{high:g}s" if high < 99 else "2s+"
        keys = [key for key in shared if low <= arms[names[0]][key][0] < high]
        if not keys:
            continue
        block: dict[str, Any] = {name: {"n": len(keys),
                                        "offset_miss": sum(1 for key in keys if arms[name][key][1] > TOL),
                                        "rate": round(sum(1 for key in keys if arms[name][key][1] > TOL) / len(keys), 4)}
                                 for name in names}
        if reference and challenger and reference in arms and challenger in arms:
            block["discordant_challenger_vs_reference"] = {
                "newly_ok": sum(1 for key in keys
                                if arms[reference][key][1] > TOL >= arms[challenger][key][1]),
                "newly_broken": sum(1 for key in keys
                                    if arms[challenger][key][1] > TOL >= arms[reference][key][1])}
        buckets[label] = block
    totals: dict[str, Any] = {"characters": len(shared), "arms": {}}
    for name in names:
        totals["arms"][name] = sum(1 for key in shared if arms[name][key][1] > TOL)
    if reference and challenger:
        totals["discordant"] = {
            "newly_ok": sum(1 for key in shared
                            if arms[reference][key][1] > TOL >= arms[challenger][key][1]),
            "newly_broken": sum(1 for key in shared
                                if arms[challenger][key][1] > TOL >= arms[reference][key][1])}
    return {"shared_characters": len(shared), "tolerance_sec": TOL, "buckets": buckets, "totals": totals}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", action="append", default=[], required=True,
                        help="label=path 逐字符 dump（可多次；只取所有臂的交集）")
    parser.add_argument("--reference", help="对照臂标签（用于不一致对子计数）")
    parser.add_argument("--challenger", help="挑战者臂标签")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    specs = parse_specs(args.dump)
    missing = {label: str(path) for label, path in specs.items() if not path.exists()}
    if missing:
        raise SystemExit(f"这些 dump 不存在，拒绝用部分数据出表：{missing}")
    arms = {label: offsets(path) for label, path in specs.items()}
    payload = {"schema_version": "arm_bucket_counts_v2",
               "dumps": {label: str(path) for label, path in specs.items()},
               "discordant_pair": [args.reference, args.challenger],
               "note": "不一致对子只统计结束点侧；把 onset 与 offset 相加会让『字符数』被双计",
               **tabulate(arms, reference=args.reference, challenger=args.challenger)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    names = list(specs)
    print(f"{'时长桶':9s} {'n':>5} " + " ".join(f"{name:>10}" for name in names)
          + ("   新修好 新弄坏" if args.reference and args.challenger else ""))
    for label, block in payload["buckets"].items():
        discord = block.get("discordant_challenger_vs_reference")
        tail = f"   {discord['newly_ok']:5} {discord['newly_broken']:5}" if discord else ""
        print(f"{label:9s} {block[names[0]]['n']:5} "
              + " ".join(f"{block[name]['offset_miss']:10}" for name in names) + tail)
    print(json.dumps(payload["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
