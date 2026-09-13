#!/usr/bin/env python3
"""Track 1 step ①: is our character-level supervision a faithful copy of M4Singer's own annotation?

Every training/eval label in this project is *derived*: M4Singer ships Praat `TextGrid` files with
character intervals (plus `<SP>` rests, plus phoneme/note tiers), and we turned them into 80 ms
quantised `timestamp_class_ids` (two per character).  Before blaming the model for the long-note
ceiling, this audit asks the cheaper question first: **how much did the derivation itself move the
boundaries, and how wide are the source intervals it flattened?**

The distinction matters: if the derived labels match the source within one grid step, then any
long-note ambiguity is inherent to M4Singer's annotation, not to our pipeline — and the next
question (step ②) becomes whether that annotation is *acoustically identifiable* at all.

    PYTHONPATH=src python scripts/evaluation/audit_char_labels_vs_textgrid.py \
        --out results/by_run/20260913_label_audit/metrics.json \
        --report docs/status/20260913_label_audit.md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
from collections import Counter
from pathlib import Path
from typing import Any

# M4Singer marks two kinds of non-character intervals: `<SP>` (silence) and `<AP>`
# (audible pause / breath).  Both must be dropped before pairing, otherwise the text
# sequences "mismatch" on 85% of items for a purely notational reason.
NON_CHARACTER_TOKENS = {"<SP>", "<AP>", "", "sil", "sp", "pau"}
INTERVAL_RE = re.compile(
    r"intervals \[(\d+)\]:\s*\n\s*xmin = ([-\d.eE]+)\s*\n\s*xmax = ([-\d.eE]+)\s*\n\s*text = \"([^\"]*)\"")


def parse_interval_tiers(text: str) -> list[list[dict[str, Any]]]:
    """All IntervalTiers of a Praat TextGrid, in file order, as lists of intervals."""
    tiers: list[list[dict[str, Any]]] = []
    for chunk in text.split("item [")[1:]:
        if 'class = "IntervalTier"' not in chunk:
            continue
        tiers.append([{"index": int(index), "start": float(xmin), "end": float(xmax), "text": label}
                      for index, xmin, xmax, label in INTERVAL_RE.findall(chunk)])
    return tiers


def character_intervals(textgrid: str) -> list[dict[str, Any]]:
    """The character tier: M4Singer stores it first, with `<SP>` marking rests."""
    tiers = parse_interval_tiers(textgrid)
    if not tiers:
        return []
    return [interval for interval in tiers[0] if interval["text"].strip() not in NON_CHARACTER_TOKENS]


def derived_intervals(class_ids: list[int], step_sec: float) -> list[tuple[float, float]]:
    return [(class_ids[2 * index] * step_sec, class_ids[2 * index + 1] * step_sec)
            for index in range(len(class_ids) // 2)]


def load_labels(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
        if limit and len(rows) >= limit:
            break
    return rows


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    def pick(q: float) -> float:
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]
    return {"n": len(ordered), "p10": round(pick(0.10), 4), "p50": round(pick(0.50), 4),
            "p90": round(pick(0.90), 4), "max": round(ordered[-1], 4)}


def audit(rows: list[dict[str, Any]], grid_root: Path, *, long_sec: float = 1.0) -> dict[str, Any]:
    """Pair source and derived characters only when the two text sequences agree.

    Pairing by index is only meaningful after the sequences match: M4Singer sometimes repeats a
    syllable across a melisma (or our mapping drops one), and comparing those index-wise produces
    large fake deltas.  Mismatching items are counted and sampled instead of being averaged in.
    """
    counts = Counter()
    onset_err: list[float] = []
    offset_err: list[float] = []
    dur_all: list[float] = []
    dur_long: list[float] = []
    long_onset_err: list[float] = []
    post_rest: list[float] = []
    long_char_examples: list[dict[str, Any]] = []
    mismatch_examples: list[dict[str, Any]] = []
    for row in rows:
        grid = grid_root / str(row["audio_relpath"]).replace(".wav", ".TextGrid")
        if not grid.exists():
            counts["missing_textgrid"] += 1
            continue
        source = character_intervals(grid.read_text(encoding="utf-8"))
        derived = derived_intervals(row["timestamp_class_ids"], float(row["timestamp_segment_sec"]))
        lyrics = str(row.get("lyrics_normalized", ""))
        source_text = "".join(str(interval["text"]) for interval in source)
        counts["items"] += 1
        counts["source_chars"] += len(source)
        if source_text != lyrics or len(source) != len(derived):
            counts["text_mismatch"] += 1
            if len(mismatch_examples) < 12:
                mismatch_examples.append({"item_id": row["item_id"], "lyrics_normalized": lyrics,
                                          "source_text": source_text[:60],
                                          "source_chars": len(source), "derived_chars": len(derived)})
            continue
        counts["paired_items"] += 1
        counts["paired_chars"] += len(source)
        for index, (interval, (d_start, d_end)) in enumerate(zip(source, derived, strict=True)):
            duration = interval["end"] - interval["start"]
            onset_delta = abs(d_start - interval["start"])
            offset_delta = abs(d_end - interval["end"])
            onset_err.append(onset_delta)
            offset_err.append(offset_delta)
            dur_all.append(duration)
            if index > 0 and str(source[index - 1]["text"]).strip() in NON_CHARACTER_TOKENS:
                post_rest.append(onset_delta)
            if duration >= long_sec:
                dur_long.append(duration)
                long_onset_err.append(onset_delta)
                if len(long_char_examples) < 12:
                    long_char_examples.append({"item_id": row["item_id"], "index": index,
                                               "text": interval["text"],
                                               "source": [round(interval["start"], 3), round(interval["end"], 3)],
                                               "derived": [round(d_start, 3), round(d_end, 3)],
                                               "duration": round(duration, 3)})
        counts["quantised_exactly"] += sum(
            1 for interval, (d_start, d_end) in zip(source, derived, strict=True)
            if abs(d_start - interval["start"]) < 1e-9 and abs(d_end - interval["end"]) < 1e-9)
    step = float(rows[0]["timestamp_segment_sec"]) if rows else 0.08
    return {
        "schema_version": "label_vs_textgrid_audit_v1",
        "labels_audited": len(rows),
        "grid_step_sec": step,
        "counts": dict(counts),
        "onset_delta_sec": quantiles(onset_err),
        "offset_delta_sec": quantiles(offset_err),
        "onset_delta_within_one_grid_step": (round(sum(1 for value in onset_err if value <= step / 2 + 1e-9) / len(onset_err), 4)
                                             if onset_err else None),
        "source_character_duration_sec": quantiles(dur_all),
        "long_characters": {"threshold_sec": long_sec, "count": len(dur_long),
                            "duration_sec": quantiles(dur_long),
                            "onset_delta_sec": quantiles(long_onset_err)},
        "post_rest_onset_delta_sec": quantiles(post_rest),
        "long_character_examples": long_char_examples,
        "text_mismatch_examples": mismatch_examples,
    }


def markdown(result: dict[str, Any]) -> str:
    counts = result["counts"]
    long_block = result["long_characters"]
    lines = ["# 标签审计：派生字符标签 vs M4Singer 原始 TextGrid（生成，勿手改）", ""]
    lines.append(f"- 审计条目：**{counts.get('items', 0)}**（缺 TextGrid {counts.get('missing_textgrid', 0)}）；"
                 f"其中**文本可配对 {counts.get('paired_items', 0)}** 条（{counts.get('paired_chars', 0)} 字），"
                 f"文本序列不一致 {counts.get('text_mismatch', 0)} 条（单独列样例，不混入统计）")
    lines.append(f"- 量化格点：{result['grid_step_sec']}s；起止**逐位相同**的字符：{counts.get('quantised_exactly', 0)}")
    lines.append("")
    lines.append("| 量 | p10 | p50 | p90 | max |")
    lines.append("|---|---|---|---|---|")
    for name, key in (("起始边界差(秒)", "onset_delta_sec"), ("结束边界差(秒)", "offset_delta_sec"),
                      ("源字符时长(秒)", "source_character_duration_sec"),
                      (f"长字符(≥{long_block['threshold_sec']}s)时长(秒)", None),
                      ("长字符起始边界差(秒)", None)):
        block = long_block["duration_sec"] if key is None and "时长" in name else (
            long_block["onset_delta_sec"] if key is None else result[key])
        if not block:
            continue
        lines.append(f"| {name} | {block.get('p10')} | {block.get('p50')} | {block.get('p90')} | {block.get('max')} |")
    lines.append("")
    lines.append(f"- 起始边界差 ≤ 半个格点的比例：**{result['onset_delta_within_one_grid_step']}**")
    lines.append(f"- 长字符（≥{long_block['threshold_sec']}s）数量：**{long_block['count']}**")
    lines.append("")
    lines.append("## 文本序列不一致的样例（配对前先看这个）")
    lines.append("")
    lines.append("| item | 我们的歌词 | 源标注序列 | 源字数 | 派生字数 |")
    lines.append("|---|---|---|---|---|")
    for row in result.get("text_mismatch_examples", [])[:8]:
        lines.append(f"| {row['item_id']} | {row['lyrics_normalized'][:20]} | {row['source_text'][:20]} | "
                     f"{row['source_chars']} | {row['derived_chars']} |")
    lines.append("")
    lines.append("## 长字符样例（源标注 vs 我们派生的标签）")
    lines.append("")
    lines.append("| item | 序号 | 字 | 源区间 | 派生区间 | 时长 |")
    lines.append("|---|---|---|---|---|---|")
    for row in result["long_character_examples"][:10]:
        lines.append(f"| {row['item_id']} | {row['index']} | {row['text']} | {row['source']} | "
                     f"{row['derived']} | {row['duration']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path,
                        default=Path("/home/hyan/Data/lyricalign/derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"))
    parser.add_argument("--textgrid-root", type=Path,
                        default=Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer"))
    parser.add_argument("--limit", type=int, default=400, help="0 = all items")
    parser.add_argument("--long-sec", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = load_labels(args.labels, args.limit)
    result = audit(rows, args.textgrid_root, long_sec=args.long_sec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(result), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("labels_audited", "counts", "onset_delta_sec",
                                                   "offset_delta_sec", "onset_delta_within_one_grid_step",
                                                   "source_character_duration_sec", "long_characters")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
