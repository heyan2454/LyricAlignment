#!/usr/bin/env python3
"""Robustness and multiplicity check for a paired per-character comparison.

A paired mean difference can be significant while the underlying *count* of newly-broken characters is
not, and vice versa — especially with heavy-tailed timing errors, where two characters moving by
seconds dominate a mean over 900.  Whenever a per-side contrast is picked out of several candidates,
it also needs a multiplicity correction, and a binary McNemar test on the pass/fail indicator is the
model-free cross-check.

This tool recomputes, for each side (onset/offset) and duration class (short/long):
mean Δ with t-approximated p, median Δ, trimmed mean, counts of large one-sided moves,
McNemar exact p on the >tolerance indicator, and the p adjusted for the number of sides examined.

    PYTHONPATH=src python scripts/evaluation/paired_robustness_check.py \
        --old results/by_run/20260914_mech_validation_uniform/per_character.jsonl \
        --new results/by_run/20260914_mech_control/per_character.jsonl \
        --out results/by_run/20260914_paired_A_vs_start/robustness.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

TOL = 0.2
SIDES = (("onset", "short", lambda d, e: d < 1.0),
         ("onset", "long", lambda d, e: d >= 1.0),
         ("offset", "short", lambda d, e: d < 1.0),
         ("offset", "long", lambda d, e: d >= 1.0))


def load(path: Path) -> dict[tuple[str, int], dict[str, dict[str, Any]]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    return {key: value for key, value in per.items() if len(value) == 2}


def mcnemar_exact(better: int, worse: int) -> float:
    total = better + worse
    if total == 0:
        return 1.0
    low = min(better, worse)
    tail = sum(math.comb(total, index) * 0.5 ** total for index in range(low + 1))
    return min(1.0, 2 * tail)


def two_sided_p_from_z(z: float) -> float:
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def trimmed_mean(values: list[float], fraction: float = 0.02) -> float:
    ordered = sorted(values)
    cut = int(len(ordered) * fraction)
    core = ordered[cut: len(ordered) - cut] if len(ordered) > 2 * cut else ordered
    return st.mean(core)


def analyse(old: dict, new: dict, shared: list[tuple[str, int]]) -> dict[str, Any]:
    n_sides = len(SIDES)
    out: dict[str, Any] = {"sides": {}, "sides_examined": n_sides}
    for kind, label, keep in SIDES:
        deltas: list[float] = []
        better = worse = large_up = large_down = 0
        for key in shared:
            duration = old[key][kind]["duration"]
            if not keep(duration, None):
                continue
            error_old = float(old[key][kind]["abs_err_argmax"])
            error_new = float(new[key][kind]["abs_err_argmax"])
            delta = 1000 * (error_new - error_old)
            deltas.append(delta)
            if error_new > TOL >= error_old:
                worse += 1
            elif error_old > TOL >= error_new:
                better += 1
            if delta > 100:
                large_up += 1
            elif delta < -100:
                large_down += 1
        n = len(deltas)
        if n < 20:
            out["sides"][f"{kind}_{label}"] = {"status": "insufficient_data", "n": n}
            continue
        mean = st.mean(deltas)
        se = st.stdev(deltas) / math.sqrt(n) if n > 1 else 0.0
        z = mean / se if se > 1e-12 else 0.0
        p_t = two_sided_p_from_z(z)
        p_m = mcnemar_exact(better, worse)
        out["sides"][f"{kind}_{label}"] = {
            "status": "measured", "n": n, "mean_delta_ms": round(mean, 2), "se_ms": round(se, 2),
            "z": round(z, 2), "p_t": round(p_t, 4), "p_t_times_sides": round(min(1, p_t * n_sides), 4),
            "median_delta_ms": round(st.median(deltas), 2),
            "trimmed_mean_delta_ms": round(trimmed_mean(deltas), 2),
            "moved_worse_gt_100ms": large_up, "moved_better_gt_100ms": large_down,
            "mcnemar_better": better, "mcnemar_worse": worse,
            "p_mcnemar_exact": round(p_m, 4), "p_mcnemar_times_sides": round(min(1, p_m * n_sides), 4),
            "verdict": ("确证" if min(1, p_t * n_sides) < 0.05 and min(1, p_m * n_sides) < 0.05 else
                        "迹象（未过校正）" if min(p_t, p_m) < 0.05 else "无证据")}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    old, new = load(args.old), load(args.new)
    shared = sorted(set(old) & set(new), key=lambda item: str(item))
    payload = {"schema_version": "paired_robustness_v1", "old": str(args.old), "new": str(args.new),
               "shared_characters": len(shared), "tolerance_sec": TOL,
               **analyse(old, new, shared)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.report:
        lines = ["# 配对稳健性与多重比较检查（生成，勿手改）", "",
                 f"> 同一批 {payload['shared_characters']} 个字符；缺陷阈值 ±{TOL} s；"
                 f"考察了 {payload['sides_examined']} 个位置，故同时给出 ×4 校正后的 p。", "",
                 "| 位置 | n | 均值Δ(ms) | 中位Δ | 截尾均值 | 均值 z (p, p×4) | McNemar 好/差 (p, p×4) | 判定 |",
                 "|---|---|---|---|---|---|---|---|"]
        for name, block in payload["sides"].items():
            if block.get("status") != "measured":
                lines.append(f"| {name} | {block.get('n')} | — | — | — | — | — | 数据不足 |")
                continue
            lines.append(f"| {name} | {block['n']} | {block['mean_delta_ms']:+.2f} | {block['median_delta_ms']:+.1f} | "
                         f"{block['trimmed_mean_delta_ms']:+.2f} | z={block['z']} ({block['p_t']:.3f}, "
                         f"{block['p_t_times_sides']:.3f}) | {block['mcnemar_better']}/{block['mcnemar_worse']} "
                         f"({block['p_mcnemar_exact']:.3f}, {block['p_mcnemar_times_sides']:.3f}) | **{block['verdict']}** |")
        lines += ["", "- 均值与中位/截尾均值不一致时，说明均值被少数大幅移动主导（见表中的 >100 ms 计数）；",
                  "- **只有均值与二项检验都过校正**才允许写『显著』；否则写『迹象』或『无证据』。", ""]
        args.report.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
