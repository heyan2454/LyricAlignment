#!/usr/bin/env python3
'''Independent-corpus check of tonight's central claim: is the error concentrated in long notes?

M4Singer (in-domain) says the end-boundary miss rate rises monotonically with character duration.
This script replays the *GTSinger* ground-truth panel (different corpus, different singers, labelled
durations) through the same buckets, so the claim is either corroborated outside the training domain or
corrected.  It also reports how many long units that corpus actually contains, because that number is
what closed the "add long-note data" path yesterday — if it is wrong, the plan changes.

    PYTHONPATH=src python scripts/evaluation/gtsinger_long_note_replication.py \
        --evidence /home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz \
        --out results/by_run/20260914_gtsinger_long_replication/metrics.json
'''

from __future__ import annotations

import argparse
import gzip
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

TOL = 0.2
BUCKETS = (("0-0.5s", 0.0, 0.5), ("0.5-1s", 0.5, 1.0), ("1-1.5s", 1.0, 1.5),
           ("1.5-2s", 1.5, 2.0), ("2s+", 2.0, 99.0))


def bucket_of(duration: float) -> str | None:
    for name, low, high in BUCKETS:
        if low <= duration < high:
            return name
    return None



def entropy_cross_tab(records: list[tuple[float, float, float]]) -> dict[str, Any]:
    if len(records) < 40:
        return {"status": "insufficient_data", "rows": len(records)}
    entropies = sorted(item[0] for item in records)

    def quantile(fraction: float) -> float:
        return entropies[min(len(entropies) - 1, int(fraction * len(entropies)))]

    cuts = [quantile(0.25), quantile(0.50), quantile(0.75)]

    def quartile(value: float) -> int:
        return sum(1 for cut in cuts if value >= cut)

    table: dict[str, dict[str, Any]] = {}
    for label, low, high in (("短 <1s", 0.0, 1.0), ("长 ≥1s", 1.0, 99.0)):
        subset = [item for item in records if low <= item[2] < high]
        per_quartile = {}
        for quartile_index in range(4):
            chosen = [item for item in subset if quartile(item[0]) == quartile_index]
            per_quartile[f"Q{quartile_index + 1}"] = {
                "characters": len(chosen),
                "miss_share": round(sum(1 for item in chosen if item[1] > TOL) / len(chosen), 4) if chosen else None}
        flagged = [item for item in subset if quartile(item[0]) == 3]
        defects = [item for item in subset if item[1] > TOL]
        table[label] = {
            "characters": len(subset), "defects": len(defects),
            "per_quartile": per_quartile,
            "q4_defect_share": round(sum(1 for item in defects if quartile(item[0]) == 3) / len(defects), 4) if defects else None,
            "q4_population_share": round(len(flagged) / len(subset), 4) if subset else None}
    return {"status": "measured", "rows": len(records), "buckets": table,
            "entropy_cuts": [round(value, 3) for value in cuts]}


def entropy_markdown(block: dict[str, Any]) -> list[str]:
    if block.get("status") != "measured":
        return [f"- 状态：样本不足（{block.get('rows')} 行）"]
    lines = [f"- 用于交叉表的 raw 行数 {block['rows']}；熵的四分位切点 {block['entropy_cuts']}（只用模型输出）：", "",
             "| 时长组 | n | Q1 超差率 | Q2 | Q3 | Q4 | 缺陷落在 Q4 的比例 | Q4 占全体比例 |",
             "|---|---|---|---|---|---|---|---|"]
    for label, bucket in block["buckets"].items():
        quartiles = bucket["per_quartile"]

        def cell(key: str) -> str:
            item = quartiles[key]
            return "—" if item["miss_share"] is None else f"{100 * item['miss_share']:.2f}%（{item['characters']}）"
        lines.append(f"| {label} | {bucket['characters']} | {cell('Q1')} | {cell('Q2')} | {cell('Q3')} | {cell('Q4')} | "
                     + ("—" if bucket["q4_defect_share"] is None else f"{100 * bucket['q4_defect_share']:.1f}%")
                     + f" | {100 * bucket['q4_population_share']:.1f}% |")
    lines.append("- 读法：若长音组的 **Q4 缺陷占比 ≫ Q4 人口占比** ⇒ 熵在**另一个语料上**也能把长音失败挑出来，"
                 "门控的跨语料适用性得到独立支持；反之则不成立。")
    return lines



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz"))
    parser.add_argument("--model", default="r2",
                        help="model tier (evidence field `model`); note `checkpoint_kind` is the "
                             "weight-source kind {raw, projector, lora}, not r0/r1/r2")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    # One row per (audio, unit index) per decoder kind; keep only the plain model decode so the
    # duration curve is about the model, not about post-processing.
    melisma: dict[str, list[float]] = defaultdict(list)
    nonmelisma: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, dict[str, list[float]]] = defaultdict(lambda: {name: [] for name, _l, _h in BUCKETS})
    medians: dict[str, dict[str, list[float]]] = defaultdict(lambda: {name: [] for name, _l, _h in BUCKETS})
    unique_long_units: dict[str, set[tuple[str, int]]] = {name: set() for name, _l, _h in BUCKETS}
    seen_units: set[tuple[str, int]] = set()
    raw_records: list[dict[str, Any]] = []
    decoder_kinds: dict[str, int] = defaultdict(int)
    total_rows = 0

    with gzip.open(args.evidence, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total_rows += 1
            row = json.loads(line)
            if str(row.get("model")) != args.model:
                continue
            duration = row.get("gt_dur_sec")
            if duration is None:
                continue
            name = bucket_of(float(duration))
            if name is None:
                continue
            key = (str(row.get("item") or row.get("audio_path")), int(row.get("unit_index", -1)))
            seen_units.add(key)
            if float(duration) >= 1.0:
                for bucket, low, high in BUCKETS:
                    if low <= float(duration) < high:
                        unique_long_units[bucket].add(key)
            kind = str(row.get("decoder_kind") or row.get("decoder_id_kind") or "unknown")
            decoder_kinds[kind] += 1
            end_error = row.get("end_abs_err_sec")
            if end_error is None:
                continue
            if kind == "raw" and row.get("raw_entropy_end") is not None:
                raw_records.append(row)
            errors[kind][name].append(float(end_error))
            medians[kind][name].append(float(end_error))
            (melisma if int(row.get("gt_is_melisma") or 0) == 1 else nonmelisma)[kind].append(float(end_error))

    payload: dict[str, Any] = {"schema_version": "gtsinger_long_replication_v1",
                               "evidence": str(args.evidence), "model": args.model,
                               "total_rows": total_rows,
                               "distinct_units_seen": len(seen_units),
                               "decoder_kinds": dict(sorted(decoder_kinds.items())),
                               "unique_units_by_bucket": {name: len(values) for name, values in unique_long_units.items()},
                               "per_decoder": {}}
    for kind, buckets in sorted(errors.items()):
        table = {}
        for name, _low, _high in BUCKETS:
            values = buckets[name]
            if len(values) < 20:
                table[name] = {"characters": len(values), "status": "insufficient_data"}
                continue
            table[name] = {"characters": len(values),
                           "miss_share": round(sum(1 for value in values if value > TOL) / len(values), 4),
                           "median_err_ms": round(1000 * st.median(values), 1),
                           "mean_err_ms": round(1000 * st.mean(values), 1)}
        payload["per_decoder"][kind] = table
    def block_of(values: list[float]) -> dict[str, Any]:
        if len(values) < 20:
            return {"characters": len(values), "status": "insufficient_data"}
        return {"characters": len(values),
                "miss_share": round(sum(1 for value in values if value > TOL) / len(values), 4),
                "median_err_ms": round(1000 * st.median(values), 1)}
    payload["melisma"] = {kind: block_of(values) for kind, values in sorted(melisma.items())}
    payload["non_melisma"] = {kind: block_of(values) for kind, values in sorted(nonmelisma.items())}
    # 跨语料的"置信度 × 时长"交叉表：门控能否在另一语料上也把长音失败挑出来。
    ent_rows = [(float(row["raw_entropy_end"]), float(row["end_abs_err_sec"]), float(row["gt_dur_sec"]))
                for row in raw_records]
    payload["entropy_duration"] = entropy_cross_tab(ent_rows)
    entropy_lines = ["", "### 置信度 × 时长（只用模型自己的把握程度，不用真值分组）", ""]
    entropy_lines += entropy_markdown(payload["entropy_duration"])

    lines_note = ["", "### melisma（转音，独立语料里\u201c长音\u201d的对应物）vs 非转音", "",
                  "| 解码 | melisma n | melisma 超差率 | 非转音 n | 非转音超差率 | Δ(pp) |", "|---|---|---|---|---|---|"]
    for kind in sorted(set(payload["melisma"]) | set(payload["non_melisma"])):
        m, nm = payload["melisma"].get(kind, {}), payload["non_melisma"].get(kind, {})
        if m.get("status") == "insufficient_data" or nm.get("status") == "insufficient_data":
            lines_note.append(f"| {kind} | {m.get('characters', 0)} | 样本不足 | {nm.get('characters', 0)} | "
                              f"{('—' if nm.get('status') == 'insufficient_data' else f'{100 * nm["miss_share"]:.2f}%')} | — |")
            continue
        lines_note.append(f"| {kind} | {m['characters']} | {100 * m['miss_share']:.2f}% | {nm['characters']} | "
                          f"{100 * nm['miss_share']:.2f}% | {100 * (m['miss_share'] - nm['miss_share']):+.2f} |")

    lines = ["# GTSinger 上的长音误差复现（独立语料，生成勿手改）", "",
             f"> 证据：`{args.evidence.name}`，`model={args.model}`，"
             f"共 {total_rows} 行 / {len(seen_units)} 个不同单元。", "",
             f"> 供给复核（各桶去重后的**唯一单元数**）："
             + "、".join(f"{name} {count}" for name, count in payload["unique_units_by_bucket"].items()), ""]
    for kind, table in payload["per_decoder"].items():
        lines += [f"### 解码 `{kind}`", "", "| 时长桶 | n | 中位误差(ms) | 平均误差(ms) | 超差率(>0.2s) |", "|---|---|---|---|---|"]
        for name, _low, _high in BUCKETS:
            block = table[name]
            if block.get("status") == "insufficient_data":
                lines.append(f"| {name} | {block['characters']} | 样本不足 | — | — |")
                continue
            lines.append(f"| {name} | {block['characters']} | {block['median_err_ms']} | {block['mean_err_ms']} | "
                         f"{100 * block['miss_share']:.2f}% |")
        series = [table[name]["miss_share"] for name, _l, _h in BUCKETS if table[name].get("status") != "insufficient_data"]
        if len(series) >= 2:
            lines.append(f"- 该解码下超差率随时长桶**单调不降**：{'是' if all(b >= a - 0.002 for a, b in zip(series, series[1:])) else '否'}"
                         f"（{100 * series[0]:.2f}% → {100 * series[-1]:.2f}%）")
        lines.append("")
    lines += lines_note + entropy_lines + [""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out.with_name("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
