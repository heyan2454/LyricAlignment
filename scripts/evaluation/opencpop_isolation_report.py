#!/usr/bin/env python3
"""生成"塌陷块单独切片重标"的可复算报告（数字全部来自 dump，不手填）。

对比三件事：同一批字在**长窗内**、在**只含这些字的短切片**里、在**块±上下文**里，
模型给的候选质量（mass-in-tolerance）与结束点误差各是多少。

    PYTHONPATH=src python scripts/evaluation/opencpop_isolation_report.py \
        --isolation-dir /home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/isolation \
        --window-dump /home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/units_window_old750.jsonl.gz \
        --out docs/status/20260924_opencpop_isolation.md
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

TOL = 0.2
ORDER = ("block", "ctx2", "half")


def load_dump(path: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                rows[Path(str(item["utt"])).stem].append(item)
    for values in rows.values():
        values.sort(key=lambda r: r["unit_index"])
    return dict(rows)


def measure(units: list[dict], decoder: str) -> dict:
    ends = sorted(abs(row[f"{decoder}_end_sec"] - row["gt_end_sec"]) for row in units)
    mass = [row.get("end_mass_in_tol", 0.0) for row in units]
    ent = [row.get("end_entropy", 0.0) for row in units]
    return {"n": len(ends), "miss": 100 * sum(1 for e in ends if e > TOL) / len(ends),
            "median_ms": 1000 * st.median(ends), "mass": 100 * st.median(mass),
            "entropy": st.median(ent)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolation-dir", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/isolation"))
    parser.add_argument("--window-dump", type=Path, required=True)
    parser.add_argument("--decoder", default="official")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.isolation_dir / "MANIFEST.json").read_text(encoding="utf-8"))["segments"]
    by_segment: dict[str, dict] = {item["segment"]: item for item in manifest}
    iso = load_dump(args.isolation_dir / "units_isolation_old750.jsonl.gz")
    window = load_dump(args.window_dump)

    # 窗内基线：塌陷块成员 = 窗内共用同一 official 结束点的连续 ≥5 字；块号按出现顺序，与切片清单一致
    baseline: dict[tuple[str, int], list[dict]] = {}
    counter: dict[str, int] = defaultdict(int)
    for seg, rows in window.items():
        run: list[dict] = []
        for row in rows + [None]:
            if run and (row is None or row[f"{args.decoder}_end_sec"] != run[-1][f"{args.decoder}_end_sec"]):
                if len(run) >= 5:
                    counter[seg] += 1
                    baseline[(seg, counter[seg])] = run
                run = []
            if row is not None:
                run.append(row)

    lines = ["# 塌陷块单独切片重标（生成，勿手改）", "",
             f"> 由 `scripts/evaluation/opencpop_isolation_report.py` 生成；输入 `{args.isolation_dir}` 与"
             f" `{args.window_dump.name}`。模型点 = 切片 evidence 所用的那一个 checkpoint。", "",
             "**问题**：窗内前向里这些字的结束点 mass-in-tolerance≈0，看起来「候选里根本没有答案」。"
             "但那是**在同一张 91 字长窗里**算出的候选分布。把同一批字单独切出来重喂，候选可能完全不同。", "",
             "**判据**：只看原块成员（ctx2 档用 MANIFEST 记录的块相对区间筛，上下文单元仅用于让歌词与音频一致）。", ""]

    lines += ["## 逐块逐条件", "",
              "| 块 | 条件 | 单元数 | 切片时长(s) | 超差率 | 中位误差(ms) | mass-in-tol | 熵(nats) |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    per_condition: dict[str, list[dict]] = defaultdict(list)
    for seg in sorted(iso):
        meta = by_segment[seg]
        units = iso[seg]
        lo, hi = meta["block_rel_start_sec"], meta["block_rel_end_sec"]
        members = [row for row in units if row["gt_start_sec"] >= lo - 1e-3 and row["gt_end_sec"] <= hi + 1e-3]
        if not members:
            continue
        got = measure(members, args.decoder)
        per_condition[meta["condition"]].extend(members)
        seconds = meta["clip_end_sec"] - meta["clip_start_sec"]
        lines.append(f"| {seg[-30:]} | {meta['condition']} | {got['n']} | {seconds:.2f} | "
                     f"{got['miss']:.1f} % | {got['median_ms']:.0f} | {got['mass']:.1f} % | {got['entropy']:.2f} |")
    lines.append("")

    lines += ["## 汇总（同一批字，三种给法）", "",
              "| 条件 | 单元数 | 超差率 | 中位误差(ms) | mass-in-tol | 熵 | vs 窗内 |", "|---|---:|---:|---:|---:|---:|---|"]
    base_all = [row for seg, run in baseline.items() for row in run]
    base = measure(base_all, args.decoder) if base_all else None
    for cond in ORDER:
        units = per_condition.get(cond) or []
        if not units:
            continue
        got = measure(units, args.decoder)
        versus = f"窗内 {base['median_ms']:.0f} ms → 现在 {got['median_ms']:.0f} ms（{base['median_ms'] / max(got['median_ms'], 1):.1f}×）" if base else "—"
        lines.append(f"| {cond} | {got['n']} | {got['miss']:.1f} % | {got['median_ms']:.0f} | "
                     f"{got['mass']:.1f} % | {got['entropy']:.2f} | {versus} |")
    if base:
        lines += ["", f"窗内基线（同一批字在长窗里）：超差 {base['miss']:.1f} %、中位 {base['median_ms']:.0f} ms、"
                  f"mass {base['mass']:.1f} %、熵 {base['entropy']:.2f} nats。", ""]

    lines += ["## 逐块是否反转", "", "| 块（窗__编号） | 窗内中位误差(ms) | block 档 | ctx2 档 | half 档 | 反转？ |",
              "|---|---:|---:|---:|---:|---|"]
    blocks_meta: dict[tuple[str, int], dict[str, dict]] = {}
    for item in manifest:
        blocks_meta.setdefault((Path(item["source"]).stem, item["block"]), {})[item["condition"]] = item
    for (stem, block_no), conds in sorted(blocks_meta.items()):
        run = baseline.get((stem, block_no)) or []
        if not run:
            continue
        cells: dict[str, dict] = {}
        for cond, meta in conds.items():
            units = iso.get(meta["segment"], [])
            lo, hi = meta["block_rel_start_sec"], meta["block_rel_end_sec"]
            members = [row for row in units if row["gt_start_sec"] >= lo - 1e-3 and row["gt_end_sec"] <= hi + 1e-3]
            if members:
                cells[cond] = measure(members, args.decoder)
        in_win = measure(run, args.decoder)
        block_cell = cells.get("block")
        verdict = "—"
        if block_cell:
            if block_cell["median_ms"] < 0.25 * in_win["median_ms"]:
                verdict = "**是**"
            elif block_cell["median_ms"] < 0.75 * in_win["median_ms"]:
                verdict = "部分"
            else:
                verdict = "否"
        lines.append(f"| {stem}__b{block_no} | {in_win['median_ms']:.0f} | "
                     + " | ".join(f"{cells[c]['median_ms']:.0f}" if c in cells else "—" for c in ORDER)
                     + f" | {verdict} |")
    lines += ["", "> 「反转」= 单独切片后中位误差降到窗内的 25 % 以下。判据只依赖质量与误差，不含任何人工听感。"]

    args.out.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
