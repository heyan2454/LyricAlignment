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
    lines += lines_note + [""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out.with_name("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
