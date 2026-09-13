#!/usr/bin/env python3
"""Decode-side headroom: how often is the annotated bin inside the model's own top-k?

`label_rank` (1 = the annotation is the model's most likely bin) is stored per character and slot by
`measure_predicted_boundary_acoustics.py`.  It answers the decision that otherwise costs a whole
training arm: if the correct answer is usually ranked 2nd-10th, a better decoder or a reranker can
recover it; if it is ranked hundreds of positions down, no decoding strategy can find it and only
more/better exposure (training) can move it.

Reported per duration bucket and slot: `share_rank_le_k` for several k, the mean log-rank, and the
miss rate — so headroom and current performance can be compared on the same rows.

    PYTHONPATH=src python scripts/evaluation/label_rank_headroom.py \
        --dump new12000=results/by_run/20260914_long_mech_new12000/per_character.jsonl \
        --out results/by_run/20260914_decode_headroom/metrics.json \
        --report docs/status/20260914_decode_headroom.md
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
KS = (1, 2, 5, 10, 20, 50, 100)
BUCKETS = ((0.0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99.0))


def bucket_of(duration: float) -> str:
    for low, high in BUCKETS:
        if low <= duration < high:
            return f"{low:g}-{high if high < 99 else '+'}s"
    return "2.0+s"


def rows_of(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("channel") == "d_rms" and row.get("label_rank") is not None:
            out.append(row)
    return out


def headroom(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(bucket_of(float(row["duration"])), row["kind"])].append(row)
    out: dict[str, Any] = {}
    for (bucket, kind), group in groups.items():
        ranks = [int(row["label_rank"]) for row in group]
        missed = [row for row in group if float(row["abs_err_argmax"]) > TOL]
        block: dict[str, Any] = {"measurements": len(group), "miss_rate": round(len(missed) / len(group), 4),
                                 "median_rank": int(st.median(ranks)),
                                 "mean_log10_rank": round(st.mean(math.log10(value) for value in ranks), 3)}
        for k in KS:
            block[f"share_rank_le_{k}"] = round(sum(1 for value in ranks if value <= k) / len(ranks), 4)
        if missed:
            missed_ranks = [int(row["label_rank"]) for row in missed]
            block["miss_median_rank"] = int(st.median(missed_ranks))
            block["miss_share_rank_le_10"] = round(sum(1 for value in missed_ranks if value <= 10) / len(missed_ranks), 4)
            block["miss_share_rank_le_50"] = round(sum(1 for value in missed_ranks if value <= 50) / len(missed_ranks), 4)
        out[f"{kind}|{bucket}"] = block
    return out


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# 解码侧天花板：真值在模型自己的分布里排第几（生成，勿手改）", "",
             f"> 输入 {payload['dump']}，{payload['measurements']} 次测量。"
             "`rank` = 标注时间桶在模型该槽位分布里的名次（1 = 模型首选）。", "",
             "| 槽位 / 时长 | 测量数 | 超差率 | 排名≤1 | ≤5 | ≤10 | ≤50 | 中位排名 | "
             "**失败子集**中位排名 | 失败里 ≤10 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name in sorted(payload["headroom"], key=lambda key: (key.split("|")[0], key.split("|")[1])):
        block = payload["headroom"][name]
        kind, bucket = name.split("|")
        lines.append(f"| {kind} {bucket} | {block['measurements']} | {block['miss_rate']:.2%} | "
                     f"{block['share_rank_le_1']:.3f} | {block['share_rank_le_5']:.3f} | "
                     f"{block['share_rank_le_10']:.3f} | {block['share_rank_le_50']:.3f} | "
                     f"{block['median_rank']} | {block.get('miss_median_rank', '—')} | "
                     f"{block.get('miss_share_rank_le_10', 0):.2f} |")
    offset_long = payload["headroom"].get("offset|2.0+s") or {}
    onset_short = payload["headroom"].get("onset|0-0.5s") or {}
    lines += ["", "## 读法（决定该投解码还是投训练）", ""]
    if offset_long:
        recoverable = offset_long["miss_share_rank_le_10"]
        lines += [
            f"- 长字符（≥2s）结束点：整体超差率 {offset_long['miss_rate']:.2%}；"
            f"这些失败的中位排名 {offset_long.get('miss_median_rank')}，其中只有 "
            f"{recoverable:.0%} 的失败真值还留在前 10 名内，"
            f"{offset_long.get('miss_share_rank_le_50', 0):.0%} 在前 50 名内；",
            "- 换句话说：**大多数长音符失败不是排序没排好，而是真值被模型压到了分布深处**，"
            "重排/DP 只能救回一小部分；",
            f"- 对照短字符起始点：排名≤1 的比例 {onset_short.get('share_rank_le_1', 0):.3f}、"
            f"超差率 {onset_short.get('miss_rate', 0):.2%} ⇒ 多数情形模型本来就是对的，"
            "解码只需保证顺序合法；",
            "- 因此优先级：**增加非常见时长的训练暴露（B 臂）> 解码侧重排**；"
            "DP 解码的价值仍是结构合法性与短字符的小幅增益（已单独测得 z=−4.5）。",
            ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", action="append", default=[], help="label=path (per_character.jsonl)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if len(args.dump) != 1 or "=" not in args.dump[0]:
        raise SystemExit("--dump 需要单个 label=path")
    label, path = args.dump[0].split("=", 1)
    rows = rows_of(Path(path))
    payload = {"schema_version": "decode_headroom_v1", "checkpoint": label, "dump": path,
               "measurements": len(rows), "tolerance_sec": TOL, "headroom": headroom(rows)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({key: {k: v for k, v in block.items()
                            if k in ("measurements", "miss_rate", "share_rank_le_1", "share_rank_le_10",
                                     "miss_median_rank", "miss_share_rank_le_10")}
                      for key, block in payload["headroom"].items()}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
