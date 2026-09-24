#!/usr/bin/env python3
""""同字连跑"短上下文重标探针：OpenCPOP（人工 GT）与 M4Singer（派生 GT）同设计对照。

背景：`20260924_opencpop_isolation.md` 里 4 个塌陷块有 3 个在单独切片后从 1.2–1.7 s 误差掉到 16–50 ms，
提示病根是**长序列里的槽位竞争**而非声学不可辨。但那 4 块是"先看窗内塌了才挑出来"的，有选择偏差。
本探针改成**按 GT 定义普查**：凡是连续 ≥N 个相同唱字的段，都同时给"长上下文"和"只给这一段"两种喂法，
按块长分桶看质量与误差的差 ⇒ 直接回答"短上下文重标到底普遍有效吗、什么条件下失效"。

两档喂法（同一批字）：
  parent  长上下文：OpenCPOP = 60 s 窗；M4Singer = 整条 item（产品口径）
  block   只给这些重复字（左右各留 margin 秒音频，避免切掉辅音尾）

用法：
    # 1) 生成切片与 evidence
    PYTHONPATH=src python scripts/evaluation/repeat_run_probe.py --mode prepare --domain opencpop --min-run 4
    PYTHONPATH=src python scripts/evaluation/repeat_run_probe.py --mode prepare --domain m4singer --min-run 5
    # 2) 每档各跑一次（parent 档 OpenCPOP 复用既有 units_window dump）
    # 3) 汇总
    PYTHONPATH=src python scripts/evaluation/repeat_run_probe.py --mode report \
        --out docs/status/20260924_repeat_run_probe.md
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics as st
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = Path("/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/repeat_probe")
TOL = 0.2
MARGIN_SEC = 0.15


# ------------------------------------------------------------------ 域的候选块
def opencpop_blocks(evidence: Path, min_run: int) -> list[dict]:
    by_item: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(evidence, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            by_item[row["utt"]].append(row)
    found: list[dict] = []
    for utt, rows in sorted(by_item.items()):
        rows.sort(key=lambda r: r["gt_start_sec"])   # evidence 行没有 unit_index，按 GT 起点排
        run: list[dict] = []
        for row in rows + [None]:
            if run and (row is None or row["text"] != run[-1]["text"]):
                if len(run) >= min_run:
                    found.append({"domain": "opencpop", "parent": utt, "parent_audio": run[0]["audio_path"],
                                  "char": run[0]["text"], "start": run[0]["gt_start_sec"],
                                  "end": run[-1]["gt_end_sec"], "block_len": len(run),
                                  "units": [dict(r) for r in run]})
                run = []
            if row is not None:
                run.append(row)
    return found


def m4singer_blocks(labels: Path, min_run: int, splits: tuple[str, ...]) -> list[dict]:
    found: list[dict] = []
    for line in labels.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") not in splits:
            continue
        text = str(row.get("lyrics_normalized") or "").replace(" ", "")
        classes = row.get("timestamp_class_ids") or []
        seg = float(row.get("timestamp_segment_sec") or 0.08)
        if len(text) < min_run or len(classes) != 2 * len(text):
            continue
        start = 0
        while start < len(text):
            end = start
            while end + 1 < len(text) and text[end + 1] == text[start]:
                end += 1
            length = end - start + 1
            if length >= min_run:
                units = [{"text": text[i], "gt_start_sec": classes[2 * i] * seg,
                          "gt_end_sec": classes[2 * i + 1] * seg} for i in range(start, end + 1)]
                found.append({"domain": "m4singer", "parent": row["item_id"],
                              "parent_relpath": row["audio_relpath"], "splits": row.get("split"),
                              "char": text[start], "start": units[0]["gt_start_sec"],
                              "end": units[-1]["gt_end_sec"], "block_len": length, "units": units})
            start = end + 1
    return found


# ------------------------------------------------------------------ prepare
def cut(source: Path, start: float, end: float, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-ss", f"{max(0.0, start):.3f}",
                    "-t", f"{end - max(0.0, start):.3f}", "-ac", "1", "-ar", "16000", str(target)], check=True)


def do_prepare(args: argparse.Namespace) -> None:
    out_dir = EVAL_ROOT / args.domain
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.domain == "opencpop":
        evidence = Path("/home/hyan/Data/lyricalign/derived/20260924_opencpop_eval/evidence_window.jsonl.gz")
        blocks = opencpop_blocks(evidence, args.min_run)
    else:
        labels = Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl")
        blocks = m4singer_blocks(labels, args.min_run, tuple(args.splits.split(",")))
    rows: list[dict] = []
    manifest: list[dict] = []
    for index, block in enumerate(blocks, start=1):
        if args.domain == "m4singer":
            source = Path(args.audio_root) / block["parent_relpath"]
        else:
            source = Path(block["parent_audio"])
        if not source.is_file():
            continue
        lo = max(0.0, block["start"] - MARGIN_SEC)
        hi = block["end"] + MARGIN_SEC
        for cond, units in (("block", block["units"]),
                            ("half", block["units"][: max(3, len(block["units"]) // 2)])):
            if len(units) < 3:
                continue
            cond_hi = min(hi, units[-1]["gt_end_sec"] + MARGIN_SEC)
            segment = f"{index:04d}__{cond}"
            target = out_dir / "clips" / f"{segment}.wav"
            cut(source, lo, cond_hi, target)
            manifest.append({"segment": segment, "domain": args.domain, "condition": cond,
                             "parent": block["parent"], "parent_source": str(source),
                             # parent 档 dump 里怎么找到这条音频：opencpop 用窗文件名，m4singer 用 relpath 尾段
                             "parent_match": block.get("parent_relpath") or f"{block['parent']}.wav",
                             "clip_start_sec": round(lo, 4), "clip_end_sec": round(cond_hi, 4),
                             "char": block["char"], "block_len": block["block_len"],
                             "units_in_slice": len(units)})
            for offset, unit in enumerate(units):
                rows.append({"model": "r2", "dataset": f"repeat-{args.domain}", "utt": str(target),
                             "audio_path": str(target),
                             "unit_index": offset, "text": unit["text"],
                             "gt_start_sec": round(unit["gt_start_sec"] - lo, 4),
                             "gt_end_sec": round(unit["gt_end_sec"] - lo, 4)})
    evidence_out = out_dir / "evidence_block.jsonl.gz"
    with gzip.open(evidence_out, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "MANIFEST.json").write_text(json.dumps(
        {"domain": args.domain, "min_run": args.min_run, "blocks": len(blocks),
         "block_len_hist": dict(sorted(st_deviation_hist(blocks).items())), "segments": manifest},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"domain": args.domain, "blocks": len(blocks), "slices": len(manifest),
                      "evidence": str(evidence_out)}, ensure_ascii=False))
    print("块长分布:", dict(sorted(st_deviation_hist(blocks).items())))


def st_deviation_hist(blocks: list[dict]) -> dict[int, int]:
    hist: dict[int, int] = defaultdict(int)
    for block in blocks:
        hist[min(block["block_len"], 12)] += 1
    return dict(hist)


def do_prepare_parent(args: argparse.Namespace) -> None:
    """M4Singer 的 parent 档 = 整条 item（产品口径），不切片，直接引用原音频。"""
    out_dir = EVAL_ROOT / args.domain
    blocks = m4singer_blocks(Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"),
                             args.min_run, tuple(args.splits.split(",")))
    by_parent: dict[str, dict] = {}
    for block in blocks:
        by_parent.setdefault(block["parent"], block)
    rows: list[dict] = []
    needed = set(by_parent)
    labels_path = Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl")
    for line in labels_path.read_text(encoding="utf-8").splitlines():   # 单次扫描，不逐项重读大文件
        if not line.strip():
            continue
        row = json.loads(line)
        item = row.get("item_id")
        if item not in needed:
            continue
        needed.discard(item)
        block = by_parent[item]
        audio = Path(args.audio_root) / block["parent_relpath"]
        if not audio.is_file():
            continue
        # parent 档 = 整条 item 的全部字（产品口径），否则音频与歌词不符
        text = str(row["lyrics_normalized"]).replace(" ", "")
        seg = float(row["timestamp_segment_sec"])
        classes = row["timestamp_class_ids"]
        for index, char in enumerate(text):
            rows.append({"model": "r2", "dataset": f"repeat-{args.domain}-parent", "utt": str(audio),
                         "audio_path": str(audio), "unit_index": index, "text": char,
                         "gt_start_sec": round(classes[2 * index] * seg, 4),
                         "gt_end_sec": round(classes[2 * index + 1] * seg, 4)})
    target = out_dir / "evidence_parent.jsonl.gz"
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"parent_items": len(by_parent), "units": len(rows), "evidence": str(target)},
                     ensure_ascii=False))


# ------------------------------------------------------------------ report
def read_dump(path: Path, key_mode: str = "name") -> dict[str, list[dict]]:
    """读逐单元 dump。key_mode=name 用文件名（切片档），full 保留完整路径（parent 档要用 relpath 尾段匹配）。"""
    rows: dict[str, list[dict]] = defaultdict(list)
    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                key = str(item["utt"]) if key_mode == "full" else Path(str(item["utt"])).name
                rows[key].append(item)
    for values in rows.values():
        values.sort(key=lambda r: r["unit_index"])
    return dict(rows)


def read_units_gz(path: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = defaultdict(list)
    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            rows[str(item["utt"])].append(item)
    return dict(rows)


def measure(units: list[dict], decoder: str) -> dict | None:
    if not units:
        return None
    ends = sorted(abs(row[f"{decoder}_end_sec"] - row["gt_end_sec"]) for row in units)
    mass = [row.get("end_mass_in_tol", 0.0) for row in units]
    return {"n": len(ends), "miss": 100 * sum(1 for e in ends if e > TOL) / len(ends),
            "median_ms": 1000 * st.median(ends), "mass": 100 * st.median(mass)}


def parent_units(dump: dict[str, list[dict]], meta: dict, decoder: str) -> list[dict]:
    """在 parent 档 dump 里取出同一批字：按 clip 时间窗 + 同字筛（clip 与 parent 同轴）。"""
    candidates = [row for name, values in dump.items() if name.endswith(meta["parent_match"]) for row in values]
    lo, hi = meta["clip_start_sec"], meta["clip_end_sec"]
    return [row for row in candidates
            if lo - 1e-3 <= row["gt_start_sec"] <= hi and row["gt_end_sec"] <= hi + 1e-3
            and row["text"] == meta["char"] and row.get(f"{decoder}_end_sec") is not None]


def do_report(args: argparse.Namespace) -> None:
    lines = ["# 同字连跑的短上下文重标探针（生成，勿手改）", "",
             "> 由 `scripts/evaluation/repeat_run_probe.py --mode report` 生成。块按 **GT 定义**普查"
             "（连续 ≥N 个相同唱字），不再以「窗内先塌了」为筛选条件 ⇒ 排除选择偏差。", "",
             "**判据**：`parent` = 长上下文喂法（OpenCPOP 60 s 窗 / M4Singer 整条 item），"
             "`block` = 只给这一段（左右各留 0.15 s）。只看块内字的结束点误差与 end mass-in-tolerance。", ""]
    for domain, min_run in (("opencpop", 4), ("m4singer", 5)):
        out_dir = EVAL_ROOT / domain
        manifest_path = out_dir / "MANIFEST.json"
        block_dump_path = out_dir / "units_old750.jsonl.gz"
        if not manifest_path.is_file():
            lines += [f"## {domain}", "", "未跑（缺 MANIFEST）。", ""]
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        block_rows = read_dump(block_dump_path)
        if domain == "opencpop":
            parent_dump = read_dump(Path("/home/hyan/Data/lyricalign/runs/20260924_opencpop_eval/units_window_old750.jsonl.gz"),
                                    key_mode="full")
        else:
            parent_dump = read_dump(out_dir / "units_parent.jsonl.gz", key_mode="full")
        buckets: dict[int, dict[str, list[dict]]] = defaultdict(lambda: {"parent": [], "block": []})
        per_block: list[dict] = []
        reversed_count = 0
        total = 0
        for meta in manifest["segments"]:
            if meta["condition"] != "block":
                continue
            # read_dump 的键是切片文件名；block 档每段就是一个切片
            block_units = block_rows.get(f"{meta['segment']}.wav", [])
            parent_units_list = parent_units(parent_dump, meta, args.decoder)
            if not block_units or not parent_units_list:
                continue
            total += 1
            bucket = min(meta["block_len"], 10)
            buckets[bucket]["block"].extend(block_units)
            buckets[bucket]["parent"].extend(parent_units_list)
            got_block, got_parent = measure(block_units, args.decoder), measure(parent_units_list, args.decoder)
            if got_block and got_parent:
                per_block.append({"block_len": meta["block_len"], "char": meta["char"],
                                  "parent": got_parent, "block": got_block})
                if got_block["median_ms"] < 0.5 * got_parent["median_ms"]:
                    reversed_count += 1
        lines += [f"## {domain}（min-run={manifest['min_run']}，块长分布 {manifest['block_len_hist']}）", "",
                  f"- 可配对的块：{total} 个；其中 block 档中位误差降到 parent 档一半以下的：**{reversed_count} 个"
                  f"（{100 * reversed_count / max(total, 1):.0f} %）**", "",
                  "| 块长 | parent 超差率 | parent 中位(ms) | parent mass | block 超差率 | block 中位(ms) | block mass | 质量倍数 |",
                  "|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for bucket in sorted(buckets):
            p = measure(buckets[bucket]["parent"], args.decoder)
            b = measure(buckets[bucket]["block"], args.decoder)
            if not p or not b:
                continue
            ratio = (b["mass"] / p["mass"]) if p["mass"] > 0 else float("inf")
            lines.append(f"| {'10+' if bucket == 10 else bucket} | {p['miss']:.1f} % | {p['median_ms']:.0f} | "
                         f"{p['mass']:.1f} % | {b['miss']:.1f} % | {b['median_ms']:.0f} | {b['mass']:.1f} % | "
                         f"{'∞' if ratio == float('inf') else f'{ratio:.1f}×'} |")
        lines += ["", "### 按 parent 档模型自评质量分层（对应产品里的触发条件）", "",
                  "每格是「该层各块指标的中位数」。parent mass 越低 = 模型在长上下文里越没把握，"
                  "也就是门控真正会命中的那些块。", "",
                  "| parent end mass | 块数 | parent 中位误差(ms) | block 中位误差(ms) | 收益倍数 | "
                  "parent 超差率 | block 超差率 | block 更优的块数 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        bands = ((0.0, 20.0, "<20 %（门控会命中）"), (20.0, 60.0, "20–60 %"), (60.0, 101.0, ">60 %（本来就标得好）"))
        for low, high, label in bands:
            members = [row for row in per_block if low <= row["parent"]["mass"] < high]
            if not members:
                continue
            pm = st.median([row["parent"]["median_ms"] for row in members])
            bm = st.median([row["block"]["median_ms"] for row in members])
            pmiss = st.median([row["parent"]["miss"] for row in members])
            bmiss = st.median([row["block"]["miss"] for row in members])
            better = sum(1 for row in members if row["block"]["median_ms"] < row["parent"]["median_ms"])
            lines.append(f"| {label} | {len(members)} | {pm:.0f} | {bm:.0f} | {pm / max(bm, 1):.1f}× | "
                         f"{pmiss:.1f} % | {bmiss:.1f} % | {better}/{len(members)} |")
        worst = sorted(per_block, key=lambda row: row["parent"]["mass"])[:6]
        if worst:
            lines += ["", "最没把握的 6 个块（parent mass 最低）逐块对照：", "",
                      "| 块长 | 字 | parent 中位(ms) | parent mass | block 中位(ms) | block mass |",
                      "|---:|---|---:|---:|---:|---:|"]
            for row in worst:
                lines.append(f"| {row['block_len']} | {row['char']} | {row['parent']['median_ms']:.0f} | "
                             f"{row['parent']['mass']:.1f} % | {row['block']['median_ms']:.0f} | "
                             f"{row['block']['mass']:.1f} % |")
        lines += ["", "> M4Singer 的 GT 是 **音素时长累积派生（rule_validated，0.08 s 格点）**，不是人工标注；"
                  "两域绝对误差不可直接比，只有「同一块 parent vs block 的比值」可比。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"[out] {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "prepare-parent", "report"), required=True)
    parser.add_argument("--domain", choices=("opencpop", "m4singer"), default="opencpop")
    parser.add_argument("--min-run", type=int, default=4)
    parser.add_argument("--splits", default="validation", help="逗号分隔：train,validation")
    parser.add_argument("--audio-root", default="/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer")
    parser.add_argument("--decoder", default="official")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/status/20260924_repeat_run_probe.md")
    args = parser.parse_args()
    if args.mode == "prepare":
        do_prepare(args)
    elif args.mode == "prepare-parent":
        do_prepare_parent(args)
    else:
        do_report(args)


if __name__ == "__main__":
    main()
