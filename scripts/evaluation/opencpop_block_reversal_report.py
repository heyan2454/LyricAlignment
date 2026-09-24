#!/usr/bin/env python3
"""塌陷块逐块反转诊断（跨模型点汇总）。

只回答一个问题：**窗内塌了的块，单独切给同一个 checkpoint 重标，会不会反转？**
逐块列出窗内与切片两种喂法的结束点误差与候选质量，不做任何生产路线推断。

    PYTHONPATH=src python scripts/evaluation/opencpop_block_reversal_report.py \
        --out docs/status/20260924_opencpop_block_reversal.md
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

TOL = 0.2
MIN_BLOCK = 5


def read_dump(path: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = defaultdict(list)
    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                rows[str(item["utt"])].append(item)
    for values in rows.values():
        values.sort(key=lambda r: r["unit_index"])
    return dict(rows)


def window_blocks(dump: dict[str, list[dict]], decoder: str) -> list[dict]:
    """窗内塌陷块：同一音频内连续 ≥MIN_BLOCK 个字共用同一个结束点。"""
    found: list[dict] = []
    for utt, rows in sorted(dump.items()):
        run: list[dict] = []
        for row in rows + [None]:
            if run and (row is None or row.get(f"{decoder}_end_sec") != run[-1].get(f"{decoder}_end_sec")):
                if len(run) >= MIN_BLOCK:
                    found.append({"utt": utt, "units": list(run), "char": run[0]["text"],
                                  "start": run[0]["gt_start_sec"], "end": run[-1]["gt_end_sec"]})
                run = []
            if row is not None:
                run.append(row)
    return found


def measure(units: list[dict], decoder: str) -> dict | None:
    usable = [row for row in units if row.get(f"{decoder}_end_sec") is not None]
    if not usable:
        return None
    ends = sorted(abs(row[f"{decoder}_end_sec"] - row["gt_end_sec"]) for row in usable)
    mass = [row.get("end_mass_in_tol", 0.0) for row in usable]
    ent = [row.get("end_entropy", 0.0) for row in usable]
    return {"n": len(ends), "miss": 100 * sum(1 for e in ends if e > TOL) / len(ends),
            "median_ms": 1000 * st.median(ends), "mass": 100 * st.median(mass),
            "entropy": st.median(ent)}


def verdict(in_win: float | None, isolated: float | None) -> str:
    if in_win is None or isolated is None:
        return "无法配对"
    if isolated < 0.25 * in_win:
        return "反转"
    if isolated < 0.75 * in_win:
        return "部分"
    if isolated < 1.25 * in_win:
        return "无变化"
    return "更差"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval"))
    parser.add_argument("--decoder", default="official")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    models = sorted(p.name[len("isolation_"):] for p in args.root.glob("isolation_*")
                    if (p / "MANIFEST.json").is_file() and (args.root / f"units_window_{p.name[len('isolation_'):]}.jsonl.gz").is_file())
    lines = ["# 塌陷块逐块反转诊断（生成，勿手改）", "",
             f"> 由 `scripts/evaluation/opencpop_block_reversal_report.py` 从"
             f" `{args.root}/isolation_*/` 与 `units_window_*.jsonl.gz` 生成。", "",
             "**唯一问题**：窗内塌了的块（连续 ≥5 字共用同一结束点），单独切给**同一个 checkpoint** 重标，"
             "会不会反转。判据只用量与质量：结束点中位误差与 end mass-in-tolerance。", "",
             "**反转** = 切片后中位误差 < 窗内的 25 %；部分 < 75 %；无变化 < 125 %；否则「更差」。", ""]

    summary: list[tuple[str, int, int, int, int, int]] = []
    for model in models:
        iso_dir = args.root / f"isolation_{model}"
        window_dump = read_dump(args.root / f"units_window_{model}.jsonl.gz")
        iso_units = read_dump(iso_dir / f"units_isolation_{model}.jsonl.gz")
        manifest = json.loads((iso_dir / "MANIFEST.json").read_text(encoding="utf-8"))["segments"]
        by_segment = {item["segment"]: item for item in manifest}

        blocks = window_blocks(window_dump, args.decoder)
        lines += [f"## {model}（窗内塌陷块 {len(blocks)} 个）", ""]
        if not blocks:
            lines += ["窗内无塌陷块。", ""]
            summary.append((model, 0, 0, 0, 0, 0))
            continue
        lines += ["| # | 窗 | 字 | 块长 | 窗内中位(ms) | 窗内 mass | 切片中位(ms) | 切片 mass | 熵 窗→切片 | 判定 |",
                  "|---:|---|---|---:|---:|---:|---:|---:|---|---|"]
        counts = {"反转": 0, "部分": 0, "无变化": 0, "更差": 0, "无法配对": 0}
        for index, block in enumerate(blocks, start=1):
            win = measure(block["units"], args.decoder)
            # 匹配键 = (同一窗音频, 块在窗内的起点)；prepare 记了 clip_start + 块在切片内的相对起点
            iso_item = next((meta for meta in by_segment.values()
                             if meta["condition"] == "block" and meta["source"] == block["utt"]
                             and abs(meta["clip_start_sec"] + meta["block_rel_start_sec"] - block["start"]) < 0.05),
                            None)
            iso_ms = iso_mass = iso_ent = None
            if iso_item:
                units = iso_units.get(str(iso_dir / "clips" / f"{iso_item['segment']}.wav"), [])
                got = measure(units, args.decoder)
                if got:
                    iso_ms, iso_mass, iso_ent = got["median_ms"], got["mass"], got["entropy"]
            call = verdict(win["median_ms"] if win else None, iso_ms)
            counts[call] += 1
            lines.append(f"| {index} | {Path(block['utt']).name} | {block['char']} | {len(block['units'])} | "
                         f"{win['median_ms']:.0f} | {win['mass']:.1f} % | "
                         + (f"{iso_ms:.0f} | {iso_mass:.1f} % | {win['entropy']:.2f}→{iso_ent:.2f} |" if iso_ms is not None
                            else "— | — | — |")
                         + f" {'**反转**' if call == '反转' else call} |")
        lines += ["", f"小结：反转 {counts['反转']} / 部分 {counts['部分']} / 无变化 {counts['无变化']}"
                  f" / 更差 {counts['更差']} / 无法配对 {counts['无法配对']}"
                  f"（共 {len(blocks)} 块）", ""]
        summary.append((model, len(blocks), counts["反转"], counts["部分"], counts["无变化"], counts["更差"]))

    lines += ["## 跨模型点汇总", "", "| 模型点 | 塌陷块数 | 反转 | 部分 | 无变化 | 更差 | 反转率 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for model, total, rev, part, same, worse in summary:
        lines.append(f"| {model} | {total} | {rev} | {part} | {same} | {worse} | "
                     f"{100 * rev / total:.0f} % |" if total else f"| {model} | 0 | 0 | 0 | 0 | 0 | — |")

    args.out.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
