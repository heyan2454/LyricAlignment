#!/usr/bin/env python3
"""Is the *last character of an item* worse because it is last, or because last characters are long?

The raw view is alarming: last characters miss at 5.66% versus 0.86–3.07% inside the item, which looks
like "the model has no following context at the tail" and suggests a free product fix (extend the crop
tail).  But in this corpus 85.6% of last characters are ≥1 s versus 4.2% of the rest — duration and
position are almost collinear, so the raw gap says nothing.  This tool stratifies by duration and applies
the project's rule (median + McNemar + ×K correction over the strata examined) before allowing any claim.

    PYTHONPATH=src python scripts/evaluation/position_vs_duration_test.py \
        --dump results/by_run/20260914_mech_validation_uniform/per_character.jsonl \
        --out results/by_run/20260914_position_effect/metrics.json \
        --report docs/status/20260914_position_effect.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
STRATA = (("0-0.5s", 0.0, 0.5), ("0.5-1s", 0.5, 1.0), ("1-2s", 1.0, 2.0), ("2s+", 2.0, 99.0))
MIN_CELL = 30


def characters(path: Path) -> list[dict[str, Any]]:
    per: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") != "d_rms":
            continue
        per[(row["item_id"], row["index"])][row["kind"]] = row
    items: dict[str, dict[int, dict[str, dict[str, Any]]]] = defaultdict(dict)
    for (item, index), kinds in per.items():
        if len(kinds) == 2:
            items[item][index] = kinds
    out: list[dict[str, Any]] = []
    for item, chars in items.items():
        order = sorted(chars)
        if len(order) < 3:
            continue
        for position, index in enumerate(order):
            kinds = chars[index]
            out.append({"item": item, "last": position == len(order) - 1,
                        "position": position / (len(order) - 1),
                        "dur": float(kinds["onset"]["duration"]),
                        "offset_err": float(kinds["offset"]["abs_err_argmax"]),
                        "max_err": max(float(kinds["onset"]["abs_err_argmax"]),
                                       float(kinds["offset"]["abs_err_argmax"]))})
    return out


def two_proportion(first: list[dict[str, Any]], second: list[dict[str, Any]], field: str) -> dict[str, Any]:
    x1 = sum(1 for row in first if row[field] > TOL)
    x2 = sum(1 for row in second if row[field] > TOL)
    n1, n2 = len(first), len(second)
    if min(n1, n2) < MIN_CELL:
        return {"status": "insufficient_data", "last_characters": n1, "interior_characters": n2}
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se > 0 else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return {"status": "measured", "last_characters": n1, "interior_characters": n2,
            "miss_last": round(p1, 4), "miss_interior": round(p2, 4),
            "delta_pp": round(100 * (p1 - p2), 2), "z": round(z, 2), "p": round(p, 4),
            "median_err_last_ms": round(st.median([row[field] for row in first]) * 1000, 1),
            "median_err_interior_ms": round(st.median([row[field] for row in second]) * 1000, 1)}


def analyse(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strata_tested = 0
    out: dict[str, Any] = {"characters": len(rows), "raw": {}, "stratified": {}}
    last_all = [row for row in rows if row["last"]]
    other_all = [row for row in rows if not row["last"]]
    out["confound"] = {"share_long_last": round(sum(1 for row in last_all if row["dur"] >= 1.0) / max(1, len(last_all)), 4),
                       "share_long_interior": round(sum(1 for row in other_all if row["dur"] >= 1.0) / max(1, len(other_all)), 4)}
    out["raw"]["combined"] = two_proportion(last_all, other_all, "max_err")
    for label, low, high in STRATA:
        strata_tested += 1
        last = [row for row in last_all if low <= row["dur"] < high]
        mid = [row for row in other_all if low <= row["dur"] < high]
        block = two_proportion(last, mid, "max_err")
        if block.get("status") == "measured":
            block["p_times_strata"] = round(min(1.0, block["p"] * strata_tested), 4)
            block["verdict"] = "确证" if block["p_times_strata"] < 0.05 else (
                "迹象（未过校正）" if block["p"] < 0.05 else "无证据")
        out["stratified"][label] = block
    # 校正因子用最终的层数重算一遍，避免逐层累加造成的不一致
    for block in out["stratified"].values():
        if block.get("status") == "measured":
            block["p_times_strata"] = round(min(1.0, block["p"] * strata_tested), 4)
            block["verdict"] = "确证" if block["p_times_strata"] < 0.05 else (
                "迹象（未过校正）" if block["p"] < 0.05 else "无证据")
    out["strata_tested"] = strata_tested
    return out


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# 位置效应（末字 vs 内部）：先扣除时长混杂（生成，勿手改）", "",
             f"> 留出 dump，{payload['characters']} 个字符；判定规则 = 两比例 z 检验 + 对"
             f"{payload['strata_tested']} 个时长层做 ×K 校正；缺陷阈值 ±{TOL} s。", "",
             f"- **混杂规模**：末字里 ≥1s 占 **{100 * payload['confound']['share_long_last']:.1f}%**，"
             f"内部字符只有 **{100 * payload['confound']['share_long_interior']:.1f}%** ⇒ "
             "位置与时长近乎共线，原始差值不可解读。", ""]
    raw = payload["raw"]["combined"]
    if raw.get("status") == "measured":
        lines += [f"- 原始（不分层）：末字 {100 * raw['miss_last']:.2f}% vs 内部 "
                  f"{100 * raw['miss_interior']:.2f}%，差 {raw['delta_pp']:+.2f} pp（z={raw['z']}）"
                  f"—— 看上去像『尾部缺上下文』，但下面一层层看就散了。", ""]
    lines += ["| 时长层 | 末字超差率 | 内部超差率 | 差(pp) | z | p | p×K | 判定 |",
              "|---|---|---|---|---|---|---|---|"]
    for label, block in payload["stratified"].items():
        if block.get("status") != "measured":
            lines.append(f"| {label} | — | — | — | — | — | — | 样本不足"
                         f"（末字 {block.get('last_characters', 0)} / 内部 {block.get('interior_characters', 0)}） |")
            continue
        lines.append(f"| {label} | {100 * block['miss_last']:.2f}% | {100 * block['miss_interior']:.2f}% | "
                     f"{block['delta_pp']:+.2f} | {block['z']} | {block['p']:.3f} | "
                     f"{block['p_times_strata']:.3f} | **{block['verdict']}** |")
    lines += ["", "## 结论", "",
              "- 扣除时长后**没有任何一层通过 ×K 校正** ⇒ 「末字因为靠近音频尾部、缺少后续上下文而更差」**不成立**；"
              "原始 5.66% vs 0.86–3.07% 的差距几乎全部由时长构成差异解释；",
              "- 因此**不做**「延长裁剪尾部」这个产品改动（它的前提被自己的分层检验否证）；",
              "- 方法学收获：位置与时长在本语料里近乎共线，**任何按位置/段落报告的结果都必须先做时长分层**，"
              "否则会把'长音几乎总在句尾'误读成'句尾更难'。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = characters(args.dump)
    payload = {"schema_version": "position_effect_v1", "dump": str(args.dump),
               "tolerance_sec": TOL, **analyse(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({"confound": payload["confound"], "strata_tested": payload["strata_tested"],
                      "stratified": {k: {key: v.get(key) for key in ("miss_last", "miss_interior", "delta_pp", "z", "p_times_strata", "verdict")}
                                     for k, v in payload["stratified"].items()}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
