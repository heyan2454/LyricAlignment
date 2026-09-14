#!/usr/bin/env python3
"""Fill the pre-registered 2x2 decision table mechanically (prereg §3l).

The table was written at 08:39, before B's primary endpoint existed, precisely so the morning reading
cannot drift.  This script reads the three artifacts it needs and prints which row we are in plus the
pre-committed next action; any missing input yields `undecidable` rather than a guess.

Inputs (all produced by other tools; nothing is recomputed here):
* `--long-paired`  : robustness JSON for B vs A (per-side paired, ×K corrected)
* `--long-vs-start`: robustness JSON for B vs the warm-start source
* `--short`        : matched-steps JSON for B vs A on the short-item view

Rules, verbatim from the preregistration:
* "有改善且过三关" = offset_long mean Δ ≤ −10 ms **and** p_t×K < 0.05 **and** p_mcnemar×K < 0.05.
* "短条目变差"     = mean fixed Δ ≤ −0.10 pp; "不变" = |Δ| < 0.10 pp; "变好" = Δ ≥ +0.10 pp.
* Only the cell (no improvement, short unchanged) may be reported as refuting the exposure story,
  because item replication carries a coverage cost that can mask a real benefit.

    PYTHONPATH=src python scripts/evaluation/ab_decision_table.py \
        --long-paired results/by_run/20260914_mech_ab_paired/robustness.json \
        --long-vs-start results/by_run/20260914_mech_B_vs_start/robustness.json \
        --short results/by_run/20260914_matched_steps/B_vs_A.json \
        --out results/by_run/20260914_ab_decision/metrics.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

IMPROVE_MS = -10.0
SHORT_WORSE_PP = -0.10
SIDE = "offset_long"

ROWS = {
    ("improved", "worse"): ("第 1 行：暴露假设成立，但条目复制是错误的实现",
                            "直接跑 C 臂（字符级 loss 加权，无覆盖代价），按 C 预注册执行"),
    ("improved", "flat"): ("第 2 行：暴露假设成立且条目复制可用",
                           "另立验证（全量复评 + held-out 泛化）后再考虑并入主线配方"),
    ("improved", "better"): ("第 2 行的变体：长音改善且短条目也变好",
                             "同第 2 行，但需检查短条目变好是否只是噪声（5 个点不足以判定）"),
    ("nothing", "worse"): ("第 3 行：不确定 —— 复制作副作用可能掩盖了收益",
                           "仍跑 C 作为无副作用的判定实验，预算上限压到 1 小时 GPU"),
    ("nothing", "flat"): ("第 4 行：暴露假设在本数据条件下被否证",
                          "C 不启动；转结构改动立项（时间戳头改为 起始+时长 参数化）"),
    ("nothing", "better"): ("非预期格：长音无改善但短条目变好",
                            "不据以判读；按第 3 行处理（跑 C），并把该格记入异常表"),
    ("hint", "worse"): ("第 3 行的弱版本：长音只有迹象（未过三关），短条目有代价",
                        "按第 3 行处理：跑 C，预算 ≤1 小时；不得写'暴露假设成立'"),
    ("hint", "flat"): ("介于第 3 与第 4 行：只有迹象、无代价证据",
                       "跑 C（它是无副作用的判定实验）；若 C 亦无改善则按第 4 行收口"),
    ("hint", "better"): ("迹象格 + 短条目变好", "跑 C 判定；不据迹象宣布成功"),
}


def load(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    location = Path(path)
    if not location.exists():
        return None
    try:
        return json.loads(location.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def long_verdict(document: dict[str, Any] | None, *, adjust: str = "k4") -> tuple[str, dict[str, Any]]:
    if not document or "sides" not in document:
        return "missing", {}
    block = document["sides"].get(SIDE) or {}
    if block.get("status") != "measured":
        return "missing", block
    mean = float(block.get("mean_delta_ms", 0.0))
    key_t, key_m = (("p_t_times_sides", "p_mcnemar_times_sides") if adjust == "k4"
                    else ("p_t", "p_mcnemar_exact"))
    passes = (mean <= IMPROVE_MS and float(block.get(key_t, 1.0)) < 0.05
              and float(block.get(key_m, 1.0)) < 0.05)
    if passes:
        return "improved", block
    hint = mean <= IMPROVE_MS and (float(block.get(key_t, 1.0)) < 0.05
                                   or float(block.get(key_m, 1.0)) < 0.05)
    return ("hint" if hint else "nothing"), block


def short_verdict(document: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not document or "variants" not in document:
        return "missing", {}
    block = document["variants"].get("fixed") or {}
    if "mean_delta_pp" not in block:
        return "missing", block
    delta = float(block["mean_delta_pp"])
    if delta <= SHORT_WORSE_PP:
        return "worse", block
    if delta >= -SHORT_WORSE_PP:
        return "better", block
    return "flat", block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--long-paired")
    parser.add_argument("--long-vs-start")
    parser.add_argument("--short")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--challenger", default="B", help="挑战者臂标签，用于报告文字（如 C）")
    parser.add_argument("--reference-arm", default="A", help="对照臂标签，用于报告文字（如 A）")
    parser.add_argument("--adjust", default="both", choices=("both", "k4", "none"),
                        help="多重比较口径。k4=对四个位置做 ×4 校正（保守）；"
                             "none=按预注册的单一主判据 offset_long 不校正；both=两个都给，不许只挑有利的那个")
    args = parser.parse_args()
    paired = load(args.long_paired)
    versus_start = load(args.long_vs_start)
    short_doc = load(args.short)
    short_state, short_block = short_verdict(short_doc)
    states = {}
    for mode in (("k4", "none") if args.adjust == "both" else (args.adjust,)):
        ls, lb = long_verdict(paired, adjust=mode)
        ss, sb = long_verdict(versus_start, adjust=mode)
        states[mode] = {"b_vs_a": ls, "b_vs_start": ss, "block_a": lb, "block_start": sb}
    long_state, long_block = states["k4" if "k4" in states else args.adjust]["b_vs_a"], states["k4" if "k4" in states else args.adjust]["block_a"]
    start_state, start_block = states["k4" if "k4" in states else args.adjust]["b_vs_start"], states["k4" if "k4" in states else args.adjust]["block_start"]
    per_mode_rows = {}
    if args.adjust == "both":
        for mode, block in states.items():
            rank = {"improved": 3, "hint": 2, "nothing": 1, "missing": 0}
            primary_mode = max((block["b_vs_a"], block["b_vs_start"]), key=lambda state: rank[state])
            per_mode_rows[mode] = ROWS.get((primary_mode, short_state), ("非预期格", "记入异常表"))
    order = {"improved": 3, "hint": 2, "nothing": 1, "missing": 0}
    primary = max((long_state, start_state), key=lambda state: order[state])   # 任一口径过三关都算有改善
    inputs_missing = [name for name, state in
                      (("long_paired", long_state), ("long_vs_start", start_state), ("short", short_state))
                      if state == "missing"]
    if inputs_missing:
        row = "undecidable"
        action = f"输入缺失：{inputs_missing}；缺数据不判读，先补齐对应评测"
    else:
        key = (primary, short_state)
        row, action = ROWS.get(key, ("非预期格，需人工复核", "记入异常表，不临场造规则"))
    payload = {"schema_version": "ab_decision_table_v2", "per_adjustment": {
        mode: {"row": row, "next_action": action} for mode, (row, action) in per_mode_rows.items()}, "prereg": "docs/status/20260914_concat_arm_prereg.md §3l",
               "rules": {"improve_requires": f"{SIDE} mean Δ ≤ {IMPROVE_MS} ms 且 p_t×K<0.05 且 p_mcnemar×K<0.05",
                         "short_states": f"≤{SHORT_WORSE_PP}pp=变差, |Δ|<{abs(SHORT_WORSE_PP)}pp=不变, ≥+0.1pp=变好"},
               "cells": {"b_vs_a_long": {"state": long_state, "block": long_block},
                         "b_vs_start_long": {"state": start_state, "block": start_block},
                         "short_b_minus_a": {"state": short_state, "block": short_block}},
               "primary_long_state": primary, "row": row, "next_action": action,
               "inputs_missing": inputs_missing}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path = args.out.with_name("REPORT.md")     # --out 指向 metrics.json，报告写在同目录
    lines = [f"# {args.challenger} vs {args.reference_arm} 决策表填表结果（机械判定，勿手改）", "",
             f"> 规则登记于 08:39（早于任何主判据），来源 `§3l`；本文件由 `ab_decision_table.py` 生成。", "",
             f"- 长字符结束点 {args.challenger} vs {args.reference_arm}：**{long_state}**"
             + (f"（Δ={long_block.get('mean_delta_ms')} ms，p_t×K={long_block.get('p_t_times_sides')}，"
                f"McNemar×K={long_block.get('p_mcnemar_times_sides')}）" if long_block else ""),
             f"- 长字符结束点 {args.challenger} vs 起点：**{start_state}**"
             + (f"（Δ={start_block.get('mean_delta_ms')} ms）" if start_block else ""),
             f"- 短条目 {args.challenger}−{args.reference_arm}：**{short_state}**"
             + (f"（{short_block.get('mean_delta_pp')} pp，{args.challenger} 更好 {short_block.get('b_better_points')}/"
                f"{short_block.get('points')} 点）" if short_block else ""),
             "", f"**所在格（口径：{args.adjust}）**：{row}", "", f"**预定下一步**：{action}", ""]
    if per_mode_rows:
        lines += ["", "## 两种多重比较口径都给出（禁止只挑有利的那个）", "",
                  "| 口径 | 含义 | 所在格 | 下一步 |", "|---|---|---|---|",
                  f"| none | 预注册的**单一主判据**（只看 offset_long，不做位置校正） | {per_mode_rows['none'][0]} | {per_mode_rows['none'][1]} |",
                  f"| k4 | 保守：对考察过的 4 个位置做 ×4 校正 | {per_mode_rows['k4'][0]} | {per_mode_rows['k4'][1]} |",
                  "", "⇒ 两口径的下一步**动作相同**（都要跑 C），所以决策不受口径影响；"
                  "但**科学表述受影响**：none 口径下可以说'暴露假设成立'，k4 口径下只能说'迹象'。"
                  "报告里两句都要出现，不许合并成一句含糊的话。", ""]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
