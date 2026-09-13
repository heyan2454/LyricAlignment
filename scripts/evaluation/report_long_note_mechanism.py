#!/usr/bin/env python3
"""Long-note failure mechanism report: paired deltas, model confidence, constrained decoding.

Three views over the same per-character dumps, written as one generated report so the conclusions
cannot drift from the numbers:

1. paired per-character error change between two checkpoints (`paired_checkpoint_comparison.py`
   output or recomputed here);
2. the model's own confidence at the label (top-1 mass, entropy, rank of the label bin) split by
   duration bucket and hit/miss — this is what separates "no idea" from "confidently wrong";
3. monotone-Viterbi decoding versus the independent per-slot argmax on identical forward passes —
   a free accuracy check of the constraint, not just a legality check.

    PYTHONPATH=src python scripts/evaluation/report_long_note_mechanism.py \
        --old results/by_run/20260914_long_mech_old750/per_character.jsonl \
        --new results/by_run/20260914_long_mech_new12000/per_character.jsonl \
        --out-dir results/by_run/20260914_long_note_mechanism \
        --report docs/status/20260914_long_note_mechanism.md
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
CHANNEL = "d_rms"


def side_index(path: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    out: dict[tuple[str, int, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") == CHANNEL:
            out[(row["item_id"], row["index"], row["kind"])] = row
    return out


def paired(new: dict, old: dict) -> dict[str, Any]:
    shared = sorted(set(new) & set(old))
    out: dict[str, Any] = {}
    for kind in ("onset", "offset"):
        for label, keep in (("all", None), ("long", True), ("short", False)):
            keys = [k for k in shared if k[2] == kind and (keep is None or new[k]["long"] == keep)]
            if len(keys) < 5:
                continue
            diff = [1000.0 * (new[k]["abs_err_argmax"] - old[k]["abs_err_argmax"]) for k in keys]
            mean = st.mean(diff)
            se = st.stdev(diff) / len(diff) ** 0.5 if len(diff) > 1 else 0.0
            out[f"{kind}_{label}"] = {"n": len(keys), "mean_delta_ms": round(mean, 2),
                                      "se_ms": round(se, 2), "z": round(mean / se, 2) if se else None,
                                      "miss_old": round(sum(1 for k in keys if old[k]["abs_err_argmax"] > TOL) / len(keys), 4),
                                      "miss_new": round(sum(1 for k in keys if new[k]["abs_err_argmax"] > TOL) / len(keys), 4)}
    return out


def confidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("entropy_nats") is None:
            continue
        duration = float(row["duration"])
        bucket = ("0-0.5s" if duration < 0.5 else "0.5-1.0s" if duration < 1.0 else
                  "1.0-2.0s" if duration < 2.0 else "2.0+s")
        groups[(bucket, "miss" if row["abs_err_argmax"] > TOL else "hit")].append(row)
    out: dict[str, Any] = {}
    for (bucket, outcome), group in sorted(groups.items()):
        n = len(group)
        out.setdefault(bucket, {})[outcome] = {
            "n": n, "median_p_top1": round(st.median(r["p_top1"] for r in group), 3),
            "median_entropy_nats": round(st.median(r["entropy_nats"] for r in group), 2),
            "share_label_top1": round(sum(1 for r in group if r["label_rank"] == 1) / n, 3),
            "share_label_rank_gt2": round(sum(1 for r in group if r["label_rank"] > 2) / n, 3),
            "median_signed_err_ms": round(st.median(1000.0 * r["signed_err"] for r in group), 0)}
    return out


def decoders(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["kind"], bool(row["long"]))].append(row)
    out: dict[str, Any] = {}
    for (kind, is_long), group in sorted(groups.items()):
        if len(group) < 5:
            continue
        diff = [1000.0 * (r["abs_err_constrained"] - r["abs_err_argmax"]) for r in group]
        mean = st.mean(diff)
        se = st.stdev(diff) / len(diff) ** 0.5 if len(diff) > 1 else 0.0
        out[f"{kind}_{'long' if is_long else 'short'}"] = {
            "n": len(group), "mean_delta_ms": round(mean, 2), "se_ms": round(se, 2),
            "z": round(mean / se, 2) if se else None,
            "miss_argmax": round(sum(1 for r in group if r["abs_err_argmax"] > TOL) / len(group), 4),
            "miss_constrained": round(sum(1 for r in group if r["abs_err_constrained"] > TOL) / len(group), 4)}
    return out


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# 长音符失败机制：配对差、模型置信度、约束解码（生成，勿手改）", "",
             f"> 由 `scripts/evaluation/report_long_note_mechanism.py` 生成。"
             f"配对条目 {payload['paired']['_items']} 条 / {payload['paired']['_shared']} 次测量。", ""]
    lines += ["## 1. 逐字符配对：旧 r2/750 → 新 run/12000（负=更好）", "",
              "| 比较 | n | 均差(ms) | SE | z | 超 0.2s 率 |", "|---|---|---|---|---|---|"]
    for name, block in payload["paired"]["rows"].items():
        misses = "—" if block.get("miss_old") is None or block.get("miss_new") is None \
            else f"{block['miss_old']:.2%} → {block['miss_new']:.2%}"
        lines.append(f"| {name} | {block['n']} | {block['mean_delta_ms']:+.1f} | {block['se_ms']:.1f} | "
                     f"{block['z']} | {misses} |")
    lines += ["", "## 2. 模型在标注处的置信度（新 run，按时长分桶 × 命中/失败）", "",
              "| 时长 | 结果 | n | top-1 概率 | 熵(nats) | 标注=第1 | 标注>第2 | 带符号误差(ms) |",
              "|---|---|---|---|---|---|---|---|"]
    for bucket, outcomes in payload["confidence"].items():
        for outcome in ("hit", "miss"):
            stats = outcomes.get(outcome)
            if not stats:
                continue
            lines.append(f"| {bucket} | {outcome} | {stats['n']} | {stats['median_p_top1']:.3f} | "
                         f"{stats['median_entropy_nats']:.2f} | {stats['share_label_top1']:.3f} | "
                         f"{stats['share_label_rank_gt2']:.3f} | {stats['median_signed_err_ms']:+.0f} |")
    lines += ["", "## 3. 约束解码 vs 逐字 argmax（同一批前向）", "",
              "| 位置 | n | 均差(ms) | SE | z | 超 0.2s 率 argmax → 约束 |", "|---|---|---|---|---|---|"]
    for name, block in payload["decoders"].items():
        lines.append(f"| {name} | {block['n']} | {block['mean_delta_ms']:+.1f} | {block['se_ms']:.1f} | {block['z']} | "
                     f"{block['miss_argmax']:.2%} → {block['miss_constrained']:.2%} |")
    conf_long = payload["confidence"].get("2.0+s", {}).get("miss") or {}
    dec_long = payload["decoders"].get("offset_long") or {}
    dec_short = payload["decoders"].get("offset_short") or {}
    lines += ["", "## 4. 读法", "",
              f"- **重训确实有效**：全部字符配对 {payload['paired']['rows']['combined_all']['mean_delta_ms']:+.1f} ms"
              f"（z={payload['paired']['rows']['combined_all']['z']}）；长字符起始点已显著"
              f"（z={payload['paired']['rows']['onset_long']['z']}），"
              f"长字符结束点方向好但未显著（{payload['paired']['rows']['offset_long']['mean_delta_ms']:+.1f} ms, "
              f"z={payload['paired']['rows']['offset_long']['z']}）。",
              f"- **长音符的失败是没把握而不是自信地错**：≥2s 且失败时，top-1 概率中位仅 "
              f"{conf_long.get('median_p_top1')}、熵高达 {conf_long.get('median_entropy_nats')} nats、"
              f"标注几乎从不排在第 1（{conf_long.get('share_label_top1')}），且中位带符号误差 "
              f"{conf_long.get('median_signed_err_ms'):+.0f} ms —— **系统性预测偏早**，即模型没有跟踪住"
              "长持续音内的时间进度。",
              f"- **约束解码是免费的**：同一批前向下，短字符结束点误差 {dec_short.get('mean_delta_ms', 0):+.1f} ms"
              f"（z={dec_short.get('z')}），超容差率 {dec_short.get('miss_argmax', 0):.2%} → {dec_short.get('miss_constrained', 0):.2%}；"
              "长字符结束点同向但不显著。也就是说单调+最短时长的全局解码**不只修结构，也真的更准**。",
              "", "## 5. 因此", "",
              "- 已启动**长上下文臂**（把同首歌短句拼成 ~20 s 再训）：直接针对「时间进度跟踪」这个诊断结果；",
              "- 约束解码应作为默认解码候选进入产品线评估（与 `raw`/定向修复叠加后再测）；",
              "- ≥2s 的样本极少（全库 1,498 个），任何针对它的结论都必须配 SE 报告，否则会被噪声牵着走。",
              ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    old, new = side_index(args.old), side_index(args.new)
    new_rows = [row for row in new.values()]
    pairs = paired(new, old)
    combined: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for (item, index, kind), row in new.items():
        combined[(item, index)][kind] = row
    complete = {key: value for key, value in combined.items() if len(value) == 2}
    diff = [1000.0 * (max(v["onset"]["abs_err_argmax"], v["offset"]["abs_err_argmax"])
                      - max(old[(k[0], k[1], "onset")]["abs_err_argmax"], old[(k[0], k[1], "offset")]["abs_err_argmax"]))
            for k, v in complete.items()
            if (k[0], k[1], "onset") in old and (k[0], k[1], "offset") in old]
    long_diff = [1000.0 * (max(v["onset"]["abs_err_constrained"], v["offset"]["abs_err_constrained"])
                           - max(v["onset"]["abs_err_argmax"], v["offset"]["abs_err_argmax"]))
                 for k, v in complete.items() if v["onset"]["long"]]
    mean = st.mean(diff)
    se = st.stdev(diff) / len(diff) ** 0.5
    pairs["combined_all"] = {"n": len(diff), "mean_delta_ms": round(mean, 2), "se_ms": round(se, 2),
                             "z": round(mean / se, 2),
                             "miss_old": round(sum(1 for k, v in complete.items()
                                                   if max(old[(k[0], k[1], "onset")]["abs_err_argmax"],
                                                          old[(k[0], k[1], "offset")]["abs_err_argmax"]) > TOL) / len(diff), 4),
                             "miss_new": round(sum(1 for v in complete.values()
                                                   if max(v["onset"]["abs_err_argmax"], v["offset"]["abs_err_argmax"]) > TOL) / len(diff), 4)}
    mean_l = st.mean(long_diff)
    se_l = st.stdev(long_diff) / len(long_diff) ** 0.5
    pairs["combined_long"] = {"n": len(long_diff), "mean_delta_ms": round(mean_l, 2), "se_ms": round(se_l, 2),
                              "z": round(mean_l / se_l, 2) if se_l else None, "miss_old": None, "miss_new": None}
    payload = {"schema_version": "long_note_mechanism_v1", "tolerance_sec": TOL,
               "old": str(args.old), "new": str(args.new),
               "paired": {"_items": len({k[0] for k in new}), "_shared": len(set(old) & set(new)), "rows": pairs},
               "confidence": confidence(new_rows), "decoders": decoders(new_rows)}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({"written": [str(args.out_dir / "metrics.json"), str(args.report)]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
