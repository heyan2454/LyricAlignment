#!/usr/bin/env python3
"""Turn funnel / top-up evaluations into a comparison table and a per-song paired test.

Why paired: every candidate is scored on the *same* songs of the same nested subset, so the
informative quantity is the per-song difference, not two independently estimated macro means.
`macro_song_se_primary` already is the standard error across songs, but comparing two of them as if
they were independent throws away the pairing and roughly doubles the noise floor.  This script
therefore reports, for each pair (candidate, baseline) on a shared level and variant:

* the unpaired macro values and their 1-SE bands (what the in-training funnel used), and
* the **paired** mean difference over the shared songs, its standard error (`std(diff)/sqrt(n)`) and
  a normal-approximation z, plus how many songs moved each way.

All numbers come from `topup_evals.jsonl` (per-song data included) and `funnel_evals.jsonl` (summary
only), never from a hand-typed table.

    PYTHONPATH=src python scripts/training/summarize_funnel_topup.py \
        --run-dir <run> --out-dir results/by_run/20260913_funnel_topup --baseline old-r2-750
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

VARIANTS = ("fixed", "raw", "raw_targeted")
LEVELS = ("l1", "l2", "l3")


def read_jsonl(path: Path, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        block = payload.get(key)
        if isinstance(block, dict):
            rows.append(block)
    return rows


def per_song(block: dict[str, Any], variant: str) -> dict[str, float]:
    metric = (block.get("variants") or {}).get(variant) or {}
    songs = metric.get("per_song") or {}
    out: dict[str, float] = {}
    for song, values in songs.items():
        value = values.get("within_200ms")
        if isinstance(value, (int, float)):
            out[str(song)] = float(value)
    return out


def paired_stats(candidate: dict[str, float], baseline: dict[str, float]) -> dict[str, Any]:
    shared = sorted(set(candidate) & set(baseline))
    if len(shared) < 2:
        return {"songs": len(shared), "mean_delta_pp": None, "se_pp": None, "z": None,
                "wins": None, "losses": None}
    diffs = [candidate[song] - baseline[song] for song in shared]
    mean = sum(diffs) / len(diffs)
    variance = sum((value - mean) ** 2 for value in diffs) / (len(diffs) - 1)
    se = math.sqrt(variance / len(diffs))
    return {"songs": len(shared), "mean_delta_pp": 100.0 * mean, "se_pp": 100.0 * se,
            "z": (mean / se) if se > 0 else None,
            "wins": sum(1 for value in diffs if value > 0), "losses": sum(1 for value in diffs if value < 0),
            "ties": sum(1 for value in diffs if value == 0)}


def summarise(topup: list[dict[str, Any]], historical: list[dict[str, Any]],
              variants: tuple[str, ...]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for block in topup:
        row: dict[str, Any] = {"label": block["label"], "level": block["level"], "step": block.get("step"),
                               "source": block.get("source"), "subset_items": block.get("subset_items"),
                               "variants": {}}
        for variant in variants:
            metric = (block.get("variants") or {}).get(variant) or {}
            row["variants"][variant] = {
                "macro_within_primary": metric.get("macro_song_within_primary"),
                "se": metric.get("macro_song_se_primary"), "usable_rate": metric.get("usable_rate"),
                "mae_all_ms": metric.get("mae_all_ms"),
                "collapse_longest_run": metric.get("collapse_longest_run")}
        rows.append(row)
    history: list[dict[str, Any]] = []
    for block in historical:
        summary = block.get("variants") or {}
        history.append({"step": block.get("evaluated_step"), "level": block.get("level"),
                        "at_step": block.get("step_now"),
                        "variants": {variant: (summary.get(variant) or {}).get("macro_within_primary")
                                     for variant in variants}})
    return {"topup": rows, "historical": sorted(history, key=lambda row: (row["level"] or "", row["step"] or 0))}


def compare(rows: list[dict[str, Any]], topup: list[dict[str, Any]], *, baseline: str,
            variants: tuple[str, ...]) -> dict[str, Any]:
    baseline_block = next((b for b in topup if b["label"] == baseline), None)
    if baseline_block is None:
        return {"baseline": baseline, "found": False}
    comparisons: list[dict[str, Any]] = []
    for block in topup:
        if block["label"] == baseline or block["level"] != baseline_block["level"]:
            continue
        for variant in variants:
            stats = paired_stats(per_song(block, variant), per_song(baseline_block, variant))
            candidate_metric = (block.get("variants") or {}).get(variant) or {}
            baseline_metric = (baseline_block.get("variants") or {}).get(variant) or {}
            unpaired = None
            if candidate_metric.get("macro_song_within_primary") is not None \
                    and baseline_metric.get("macro_song_within_primary") is not None:
                unpaired = 100.0 * (candidate_metric["macro_song_within_primary"]
                                    - baseline_metric["macro_song_within_primary"])
            comparisons.append({"candidate": block["label"], "level": block["level"], "variant": variant,
                                "unpaired_delta_pp": unpaired, **stats})
    return {"baseline": baseline, "found": True, "level": baseline_block["level"],
            "baseline_macro": {variant: ((baseline_block.get("variants") or {}).get(variant) or {})
                               .get("macro_song_within_primary") for variant in variants},
            "comparisons": comparisons}


def variant_effect(topup: list[dict[str, Any]], variants: tuple[str, ...]) -> list[dict[str, Any]]:
    """Paired per-song effect of the decode variants *inside one checkpoint* (same forward pass).

    This is the tightest comparison available: `fixed` / `raw` / `raw_targeted` are three decodes of
    the same logits on the same items, so the per-song difference removes both the song difficulty
    and the checkpoint, leaving only the decode policy.
    """
    out: list[dict[str, Any]] = []
    for block in topup:
        for candidate_variant in variants:
            for base_variant in variants:
                if candidate_variant == base_variant:
                    continue
                stats = paired_stats(per_song(block, candidate_variant), per_song(block, base_variant))
                if stats["mean_delta_pp"] is None:
                    continue
                out.append({"label": block["label"], "level": block["level"],
                            "variant": candidate_variant, "against": base_variant, **stats})
    return out


def versus_history(topup: list[dict[str, Any]], historical: list[dict[str, Any]],
                   variants: tuple[str, ...], *, metric_key: str = "macro_within_primary") -> dict[str, Any]:
    """Unpaired comparison against the best *in-training* record at the same level (no per-song data)."""
    records: dict[str, dict[str, Any]] = {}
    for block in historical:
        level = block.get("level")
        summary = block.get("variants") or {}
        values = {variant: (summary.get(variant) or {}).get(metric_key) for variant in variants}
        numeric = [value for value in values.values() if isinstance(value, (int, float))]
        if level is None or not numeric:
            continue
        current = records.get(level)
        if current is None or max(numeric) > current["_best_value"]:
            records[level] = {"step": block.get("evaluated_step", block.get("step")),
                              "variants": values, "_best_value": max(numeric)}
    rows: list[dict[str, Any]] = []
    for block in topup:
        if block.get("source") != "run":
            continue
        reference = records.get(block["level"])
        if reference is None:
            continue
        deltas = {}
        for variant in variants:
            candidate = ((block.get("variants") or {}).get(variant) or {}).get("macro_song_within_primary")
            baseline = reference["variants"].get(variant)
            deltas[variant] = (100.0 * (candidate - baseline)
                               if candidate is not None and isinstance(baseline, (int, float)) else None)
        rows.append({"label": block["label"], "level": block["level"],
                     "historical_step": reference.get("step"), "deltas_pp": deltas})
    return {"records": {level: {"step": row["step"], "variants": row["variants"]}
                        for level, row in records.items()},
            "against_best_in_training": rows}


def pick_one_se(rows: list[dict[str, Any]], variant: str) -> dict[str, Any] | None:
    """One-standard-error rule over run candidates at the deepest available level, earliest step."""
    own = [row for row in rows if row.get("source") == "run" and row["variants"].get(variant)]
    if not own:
        return None
    for level in reversed(LEVELS):
        pool = [row for row in own if row["level"] == level and row["variants"][variant].get("macro_within_primary")
                is not None]
        if not pool:
            continue
        best = max(pool, key=lambda row: row["variants"][variant]["macro_within_primary"])
        floor = best["variants"][variant]["macro_within_primary"] - (best["variants"][variant].get("se") or 0.0)
        chosen = min((row for row in pool
                      if row["variants"][variant]["macro_within_primary"] >= floor),
                     key=lambda row: row["step"])
        return {"level": level, "step": chosen["step"], "label": chosen["label"],
                "macro_within_primary": round(chosen["variants"][variant]["macro_within_primary"], 4),
                "best_step": best["step"], "best": round(best["variants"][variant]["macro_within_primary"], 4),
                "one_se": round((best["variants"][variant].get("se") or 0.0), 4), "candidates": len(pool)}
    return None


def markdown(payload: dict[str, Any], variants: tuple[str, ...], baseline: str) -> str:
    lines = ["# 漏斗事后复评小结（自动生成，勿手改）", ""]
    lines.append(f"- 顶层结果文件：`{payload['source']}`")
    lines.append(f"- 行内候选（run 自己的存档，参与选点）与外来基线（`{baseline}`，只做对比）分开列出。")
    lines.append("")
    lines.append("## 各候选在同一子集上的明细")
    lines.append("")
    for variant in variants:
        lines.append(f"### 判据 `{variant}`（每首歌在 0.2s 容差内的字符比例，取歌平均）")
        lines.append("")
        lines.append("| 候选 | 层级 | 子集项数 | 主指标 | 1SE | 可用率 | 平均误差(ms) | 最长塌陷段 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in payload["summary"]["topup"]:
            metric = row["variants"].get(variant) or {}
            if metric.get("macro_within_primary") is None:
                continue
            source = "run" if row.get("source") == "run" else "外来"
            lines.append(f"| {row['label']} ({source}) | {row['level']} | {row.get('subset_items')} | "
                         f"{metric['macro_within_primary']:.4f} | {metric.get('se') or 0:.4f} | "
                         f"{metric.get('usable_rate'):.4f} | {metric.get('mae_all_ms'):.1f} | "
                         f"{metric.get('collapse_longest_run')} |")
        lines.append("")
    comparison = payload.get("comparison") or {}
    if comparison.get("found"):
        lines.append(f"## 与基线 `{baseline}`（同层级 `{comparison['level']}`）的配对比较")
        lines.append("")
        lines.append("配对 = 同一批歌上的逐歌差值；|z| < 2 基本就是噪声。")
        lines.append("")
        lines.append("| 候选 | 判据 | 非配对差(pp) | 配对均差(pp) | 配对SE(pp) | z | 更好的歌 | 更差的歌 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in comparison["comparisons"]:
            if row["mean_delta_pp"] is None:
                continue
            lines.append(f"| {row['candidate']} | {row['variant']} | "
                         f"{row['unpaired_delta_pp']:+.2f} | {row['mean_delta_pp']:+.2f} | "
                         f"{row['se_pp']:.2f} | {row['z']:+.2f} | {row['wins']} | {row['losses']} |")
        lines.append("")
    lines.append("## 1SE 选点（只看 run 自己的候选）")
    lines.append("")
    lines.append("| 判据 | 层级 | 选中步 | 最优步 | 最优值 | 1SE |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for variant in variants:
        pick = payload["pick"].get(variant)
        if pick:
            lines.append(f"| {variant} | {pick['level']} | {pick['step']} | {pick['best_step']} | "
                         f"{pick['best']:.4f} | {pick['one_se']:.4f} |")
    lines.append("")
    lines.append("## 同一存档内三种解码的配对差异（同一次前向，最干净的比较）")
    lines.append("")
    lines.append("| 候选 | 层级 | 比较 | 配对均差(pp) | 配对SE(pp) | z | 更好的歌 | 更差的歌 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in payload["variant_effect"]:
        lines.append(f"| {row['label']} | {row['level']} | {row['variant']} − {row['against']} | "
                     f"{row['mean_delta_pp']:+.2f} | {row['se_pp']:.2f} | {row['z']:+.2f} | "
                     f"{row['wins']} | {row['losses']} |")
    lines.append("")
    history_cmp = payload.get("versus_history") or {}
    if history_cmp.get("against_best_in_training"):
        best_bits = ", ".join(f"`{level}` 最好记录 = step {row['step']}"
                              for level, row in history_cmp["records"].items())
        lines.append(f"## 与训练内历史最好记录的对照（{best_bits}；无逐歌数据，只能比宏观值）")
        lines.append("")
        lines.append("| 候选 | 层级 | " + " | ".join(f"{v} 差(pp)" for v in variants) + " |")
        lines.append("| --- | --- | " + " | ".join("---" for _ in variants) + " |")
        for row in history_cmp["against_best_in_training"]:
            values = " | ".join("" if row["deltas_pp"].get(v) is None else f"{row['deltas_pp'][v]:+.2f}"
                                for v in variants)
            lines.append(f"| {row['label']} | {row['level']} | {values} |")
        lines.append("")
    lines.append("## 行内历史记录（仅汇总，无逐歌数据，供对照）")
    lines.append("")
    lines.append("| 步 | 层级 | " + " | ".join(variants) + " |")
    lines.append("| --- | --- | " + " | ".join("---" for _ in variants) + " |")
    for row in payload["summary"]["historical"]:
        values = " | ".join("" if row["variants"].get(v) is None else f"{row['variants'][v]:.4f}"
                            for v in variants)
        lines.append(f"| {row['step']} | {row['level']} | {values} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline", default="old-r2-750")
    parser.add_argument("--variants", default=",".join(VARIANTS))
    args = parser.parse_args()
    variants = tuple(part.strip() for part in args.variants.split(",") if part.strip())
    topup_path = args.run_dir / "topup_evals.jsonl"
    funnel_path = args.run_dir / "funnel_evals.jsonl"
    topup = read_jsonl(topup_path, "topup_eval")
    historical = read_jsonl(funnel_path, "funnel_eval")
    if not topup:
        raise SystemExit(f"no top-up evaluations yet in {topup_path}")
    summary = summarise(topup, historical, variants)
    payload = {"schema_version": 1, "source": str(topup_path), "funnel_source": str(funnel_path),
               "run_dir": str(args.run_dir), "summary": summary,
               "comparison": compare(summary["topup"], topup, baseline=args.baseline, variants=variants),
               "variant_effect": variant_effect(topup, variants),
               "versus_history": versus_history(topup, historical, variants),
               "pick": {variant: pick_one_se(summary["topup"], variant) for variant in variants}}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    (args.out_dir / "REPORT.md").write_text(markdown(payload, variants, args.baseline), encoding="utf-8")
    print(json.dumps({"metrics": str(args.out_dir / "metrics.json"), "report": str(args.out_dir / "REPORT.md"),
                      "candidates": [row["label"] for row in summary["topup"]],
                      "pick": payload["pick"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
