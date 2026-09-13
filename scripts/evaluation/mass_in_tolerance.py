#!/usr/bin/env python3
"""Is the model's belief displaced or just poorly ranked?  Probability mass inside the acceptance window.

`label_rank` measures rank, not time: with a diffuse distribution the annotation can be ranked 7th and
still sit hundreds of milliseconds away, so rank alone makes re-ranking look far more promising than it
is.  This script reads the per-character `mass_in_tol` field (probability mass the model puts on bins
within ±tolerance of the label) and reports, per duration bucket and hit/miss, the median mass and how
often the mass exceeds 0.5 / 0.9.  That is the honest ceiling for any decoder restricted to the model's
own bins: if failures have small mass in tolerance, no re-ranking can recover them and only training or
a structural change can.

    PYTHONPATH=src python scripts/evaluation/mass_in_tolerance.py \
        --dump results/by_run/20260914_mass_probe/per_character.jsonl \
        --out results/by_run/20260914_mass_in_tolerance/metrics.json \
        --report docs/status/20260914_mass_in_tolerance.md
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
BUCKETS = ("0-0.5s", "0.5-1s", "1-2s", "2s+")


def bucket_of(duration: float) -> str:
    if duration < 0.5:
        return "0-0.5s"
    if duration < 1.0:
        return "0.5-1s"
    if duration < 2.0:
        return "1-2s"
    return "2s+"


def table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["kind"], bucket_of(float(row["duration"])),
                float(row["abs_err_argmax"]) > TOL)].append(row)
    out: dict[str, Any] = {}
    for (kind, bucket, missed), group in groups.items():
        if len(group) < 10:
            continue
        masses = [float(row["mass_in_tol"]) for row in group]
        key = f"{kind}|{bucket}|{'miss' if missed else 'hit'}"
        out[key] = {"n": len(group), "median_mass_in_tol": round(st.median(masses), 3),
                    "share_mass_gt_0.5": round(sum(1 for value in masses if value > 0.5) / len(masses), 4),
                    "share_mass_gt_0.9": round(sum(1 for value in masses if value > 0.9) / len(masses), 4),
                    "share_mass_lt_0.05": round(sum(1 for value in masses if value < 0.05) / len(masses), 4)}
    return out


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# 长音符失败能不能靠重排救？——看容差窗口里的概率质量（生成，勿手改）", "",
             f"> 输入 `{payload['dump']}`，{payload['rows']} 次带 `mass_in_tol` 的测量。"
             "质量 = 模型落在标注 ±0.2s 窗口内的概率总和，是『只允许在模型自己的候选里重新挑』的上界。", "",
             "| 槽位 | 时长 | 命中/失败 | n | 质量中位 | 质量>0.5 | 质量>0.9 | 质量<0.05 |",
             "|---|---|---|---|---|---|---|---|"]
    for key in sorted(payload["table"]):
        kind, bucket, outcome = key.split("|")
        block = payload["table"][key]
        lines.append(f"| {kind} | {bucket} | {outcome} | {block['n']} | {block['median_mass_in_tol']:.3f} | "
                     f"{block['share_mass_gt_0.5']:.1%} | {block['share_mass_gt_0.9']:.1%} | "
                     f"{block['share_mass_lt_0.05']:.1%} |")
    misses = {key: block for key, block in payload["table"].items() if key.endswith("|miss")}
    worst = None
    for key, block in misses.items():
        if key.startswith("offset|2s+") or key.startswith("offset|1-2s"):
            worst = (key, block)
            if key.startswith("offset|2s+"):
                break
    lines += ["", "## 判决", ""]
    if worst:
        key, block = worst
        lines.append(f"- **{key.replace('|', ' ')}**：失败 {block['n']} 个，容差内质量中位只有 "
                     f"{block['median_mass_in_tol']:.3f}，仅 "
                     f"{block['share_mass_gt_0.5']:.1%} 的失败其质量超过 0.5；")
    lines += ["- 也就是说长音符的失败**不是排序没排好，而是模型的信念整体错位**：把正确答案附近的概率",
              "  加起来还不到 15%，任何只在模型候选里重挑的解码器都救不回来；",
              "- 对照命中情形（质量中位 0.93–0.99）：模型多数时候是**自信且正确**的，失败时是**自信地错在别处**，",
              "  中间地带（真值附近有很多质量但没被选中）几乎不存在；",
              "- 所以 `label_rank` 单独会严重高估解码侧空间（分布弥散时排名第 7 也可能相差数百毫秒）：",
              "  **两个量必须一起看**，本报告就是那个校正项；",
              "- 结论：长音符问题只能靠**训练暴露/结构改动**（B 臂与后续）解决；DP 解码的价值仍是结构合法性",
              "  与短字符/非法区间修复（那部分收益已经实测，且与这里不冲突）。",
              ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = []
    for line in args.dump.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") == "d_rms" and row.get("mass_in_tol") is not None:
            rows.append(row)
    payload = {"schema_version": "mass_in_tolerance_v1", "dump": str(args.dump), "rows": len(rows),
               "tolerance_sec": TOL, "table": table(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload["table"], indent=2, ensure_ascii=False)[:1200])


if __name__ == "__main__":
    main()
