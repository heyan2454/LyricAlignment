#!/usr/bin/env python3
"""把 OpenCPOP 域外复评的 JSON 汇总成人读报告（数字一律来自 JSON，不手抄）。

    python scripts/evaluation/make_opencpop_report.py \
        --run-root /home/hyan/Data/lyricalign/runs/20260924_opencpop_eval \
        --out docs/status/20260924_opencpop_eval.md
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MODEL_ORDER = ("baseweight", "old750", "pick4850", "uniform12000")
LABELS = {"baseweight": "未微调官方底座（r0，无任何自训权重）",
          "old750": "线上产品点 20260724/step-000750",
          "pick4850": "现行 1SE 选点 20260913/step-004850",
          "uniform12000": "均匀重训终局 20260913/step-012000"}


def pp(value: float) -> str:
    return f"{100 * value:.2f} %"


def load(run_root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(run_root.glob("eval_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        view, _, name = path.stem[len("eval_"):].partition("_")
        out.setdefault(view, {})[name] = payload
    return out


def table(view: str, runs: dict[str, dict]) -> list[str]:
    lines = [f"### {view} 视图", "",
             "| 模型点 | 段数 | 字数 | official 超差率 | DP 超差率 | Δ(pp) | "
             "长字 official | 长字 DP | 长字 n | 中位误差(ms) off/dp |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in MODEL_ORDER:
        payload = runs.get(name)
        if not payload:
            lines.append(f"| {LABELS.get(name, name)} | 未跑 | | | | | | | | |")
            continue
        buckets = payload["by_selection"]
        official, dp = buckets["official"], buckets["dp"]
        all_o, all_d = official["all"], dp["all"]
        long_o, long_d = official["long"], dp["long"]
        delta = 100 * (all_d.get("miss_share", 0) - all_o.get("miss_share", 0))
        lines.append(
            f"| {LABELS.get(name, name)} | {payload['items_compared']:,} | {all_o.get('units', 0):,} | "
            f"{pp(all_o.get('miss_share', 0))} | {pp(all_d.get('miss_share', 0))} | {delta:+.2f} | "
            f"{pp(long_o.get('miss_share', 0))} | {pp(long_d.get('miss_share', 0))} | {long_o.get('units', 0):,} | "
            f"{all_o.get('median_err_ms', 0):.1f} / {all_d.get('median_err_ms', 0):.1f} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval"))
    parser.add_argument("--stats", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260924_opencpop_eval"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    stats = {}
    for name in ("STATS_sentence.json", "STATS_window.json"):
        path = args.stats / name
        if path.is_file():
            stats[name[len("STATS_"):-len(".json")]] = json.loads(path.read_text(encoding="utf-8"))

    runs = load(args.run_root)
    lines = ["# OpenCPOP 域外字符级复评（生成，勿手改）", "",
             f"> 由 `scripts/evaluation/make_opencpop_report.py` 从 `{args.run_root}/eval_*.json` 生成；"
             "缺数据显示「未跑」而不是沉默。", "",
             "**口径**：GT 只用 OpenCPOP 人工汉字轨（`_` 连音续格并入前字、SP/AP 剔除）；"
             "`official` 与 `DP` 来自**同一次前向**，只比**结束点**绝对误差，容差 0.2 s，长字桶 ≥1.5 s。",
             "**防火墙**：OpenCPOP 于 2026-09-22 才进入本机，所有 checkpoint 的训练时间均更早 ⇒ "
             "本域**只作报告，绝不参与选点/调参**。", ""]

    if stats:
        lines += ["## 数据供给（准入普查）", "", "| 视图 | 段数 | 字数 | ≥1.0s | ≥1.5s | ≥2.0s | 段长 p50(s) | 对齐通过 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for view, item in stats.items():
            long_supply = item.get("long_supply", {})
            lines.append(f"| {view} | {item.get('items', 0):,} | {item.get('units', 0):,} | "
                         f"{long_supply.get('>=1.0s', 0):,} | {long_supply.get('>=1.5s', 0):,} | "
                         f"{long_supply.get('>=2.0s', 0):,} | {item.get('item_dur_sec', {}).get('p50')} | "
                         f"{item.get('aligned', item.get('windows', '—'))} |")
        lines.append("")

    lines += ["## 读数", ""]
    for view in ("sentence", "window"):
        if view in runs:
            lines += table(view, runs[view]) + [""]

    sentence = runs.get("sentence", {})
    if {"baseweight", "old750"} <= set(sentence):
        base = sentence["baseweight"]["by_selection"]["official"]["all"]["miss_share"]
        prod = sentence["old750"]["by_selection"]["official"]["all"]["miss_share"]
        lines += ["## 自动结论（由上面这些数字算出）", "",
                  f"- 未微调底座 official 超差率 {pp(base)} vs 线上 750 {pp(prod)} ⇒ "
                  f"自训权重在该域上的净增益 {100 * (base - prod):+.2f} pp。", ""]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
