#!/usr/bin/env python3
"""Build a listen-and-classify review list for the long characters the model gets wrong.

Tonight's evidence says long-note failures are idiosyncratic (a global or selective duration recalibration
cannot fix them, and most characters' durations are already exact).  What is missing is a qualitative
portrait: which handful of long characters fail, and what the audio looks like at the true boundary versus
the predicted one.  This script assembles exactly that list from the existing validation dump — no GPU,
no new inference.

Each line carries the ground-truth and predicted end times, the acoustic prominence at both places, the
model's own uncertainty, and a hint category so a human can sort by listening rather than by guessing.

    PYTHONPATH=src python scripts/evaluation/make_long_failure_review.py \
        --dump results/by_run/20260914_mech_validation_uniform/per_character.jsonl \
        --min-duration 1.5 --out results/by_run/20260914_long_failure_review/review_list.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

TOL = 0.2


def classify(row: dict[str, Any]) -> str:
    """A first-pass label; the listening pass exists to correct these.

    Note (2026-09-14 20:24): in this dump `peak_pred` is null for every long-note failure, because the
    predicted end often falls outside the per-character analysis window — so any rule that compares
    prominence at the two places can never fire.  Classifying on it silently produced a fake "systematic"
    bucket; the honest signals here are the model's own uncertainty, whether the truth carried weight, and
    the **sign** of the error.
    """
    entropy = row.get("entropy_nats") or 0.0
    mass = row.get("mass_in_tol") or 0.0
    signed = row.get("signed_err") or 0.0
    magnitude = abs(signed)
    direction = "提前收（把长音切短）" if signed < 0 else "拖后收"
    if entropy >= 2.0:
        reason = "模型自己就很犹豫（高熵）⇒ 门控应当已标记它"
    elif mass >= 0.5:
        reason = "真值附近其实有权重、只是没被选中 ⇒ 属于挑选/解码问题"
    elif magnitude <= 0.5:
        reason = "低犹豫 + 真值在容差外 ⇒ **边缘失败**（差 0.2~0.5 秒，不是离谱错）"
    else:
        reason = "低犹豫 + 真值几乎没权重 + 大幅偏离 ⇒ 自信地错，最难的一类"
    return f"{direction}｜{reason}"


def direction_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    early = sum(1 for row in rows if (row.get("signed_err") or 0) < 0)
    return {"total": len(rows), "cut_early": early, "cut_late": len(rows) - early,
            "early_share": round(early / len(rows), 4) if rows else None,
            "median_signed_err_ms": round(1000 * sorted(
                float(row.get("signed_err") or 0) for row in rows)[len(rows) // 2], 1) if rows else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path,
                        default=Path("results/by_run/20260914_mech_validation_uniform/per_character.jsonl"))
    parser.add_argument("--min-duration", type=float, default=1.5)
    parser.add_argument("--max-items", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.dump.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [row for row in rows
                  if row.get("channel") == "d_rms" and row.get("kind") == "offset"
                  and float(row.get("duration") or 0) >= args.min_duration
                  and float(row.get("abs_err_argmax") or 0) > TOL]
    # 按"错得最离谱 + 模型最自信"排序：这两类最值得先听
    candidates.sort(key=lambda row: (-float(row["abs_err_argmax"]), float(row.get("entropy_nats") or 0)))
    picked = candidates[: args.max_items]

    hints: Counter[str] = Counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in picked:
            hint = classify(row)
            hints[hint.split("｜", 1)[1]] += 1
            handle.write(json.dumps({
                "item_id": row["item_id"], "index": row["index"],
                "character_duration_sec": round(float(row["duration"]), 3),
                "true_end_sec": round(float(row["pred_sec"]) - float(row["signed_err"]), 3),
                "predicted_end_sec": round(float(row["pred_sec"]), 3),
                "signed_error_ms": round(1000 * float(row["signed_err"]), 1),
                "abs_error_ms": round(1000 * float(row["abs_err_argmax"]), 1),
                "prominence_at_true": row.get("peak_gt"), "prominence_at_predicted": row.get("peak_pred"),
                "model_entropy_nats": row.get("entropy_nats"),
                "probability_mass_within_0.2s": row.get("mass_in_tol"),
                "top1_probability": row.get("p_top1"),
                "true_label_rank": row.get("label_rank"),
                "hint": hint}, ensure_ascii=False) + "\n")

    summary = {"schema_version": "long_failure_review_v1", "dump": str(args.dump),
               "min_duration_sec": args.min_duration, "tolerance_sec": TOL,
               "total_long_failures": len(candidates), "listed": len(picked),
               "hint_counts": dict(hints.most_common()),
               "direction": direction_stats(picked),
               "caveat": "本 dump 里预测处的响度全为 null（预测点常在逐字分析窗外），"
                         "因此任何比较两处响度的分类规则永远不会命中；已改用犹豫度/权重/误差符号分类。",
               "how_to_use": "按 abs_error_ms 从大到小听；每条都给了该听哪一秒（true_end_sec）"
                                       "与模型以为的秒数（predicted_end_sec），听完把 hint 改对即可统计成因分布。"}
    args.out.with_name("summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    lines = ["# 长音失败的可听复核清单（生成，勿手改）", "",
             f"> 数据源：`{args.dump.name}`（域内验证集，含人工标注），阈值 >{TOL} s、时长 ≥{args.min_duration} s；"
             f"共 **{len(candidates)} 个长音失败**，下面按「错得最离谱」取前 {len(picked)} 条。", "",
             "## 先按线索分个类（听完再纠正这些标签）", "", "| 线索 | 条数 |", "|---|---|"]
    for hint, count in hints.most_common():
        lines.append(f"| {hint} | {count} |")
    lines += ["", "## 清单", "", "| # | 曲目 | 字位 | 时长(s) | 真结束点(s) | 模型结束点(s) | 误差(ms) | "
              "真处响度 | 预测处响度 | 模型犹豫度 | 真值排名 | 线索 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for number, row in enumerate((json.loads(line) for line in args.out.read_text(encoding="utf-8").splitlines()), 1):
        lines.append(f"| {number} | {row['item_id']} | {row['index']} | {row['character_duration_sec']} | "
                     f"{row['true_end_sec']} | {row['predicted_end_sec']} | {row['abs_error_ms']} | "
                     f"{row['prominence_at_true']} | {row['prominence_at_predicted']} | {row['model_entropy_nats']} | "
                     f"{row['true_label_rank']} | {row['hint']} |")
    lines += ["", "## 这份清单想回答的唯一问题", "",
              "- 这些失败是**集中在少数可命名的声学情形**（收尾不响、转音多音字、气声尾…），"
              "还是**弥散得无法命名**？前者 ⇒ 有针对性做法；后者 ⇒ 这是底座能力上限，"
              "应该把「长音精度」目标降级、改为用复核清单兜底。", ""]
    args.out.with_name("REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
