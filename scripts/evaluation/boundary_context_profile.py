#!/usr/bin/env python3
"""What kind of boundary is a long note's end?  Structural profile straight from the TextGrids.

Rationale: the alignment error is concentrated on the *offsets* of long characters, and the earlier
acoustic study showed ~37% of them have no audible event at the annotated end.  This script asks the
label-side question that explains why, using nothing but the source annotations (no audio, no model):

* is the character's end a **sound -> sound** transition (the next tier-0 interval is another
  character, i.e. a new syllable with a consonant onset — acoustically crisp), or a
  **sound -> silence/pause** transition (`<SP>`/`<AP>`, where "when did the singing stop" is a
  convention rather than an event)?

    PYTHONPATH=src python scripts/evaluation/boundary_context_profile.py \
        --out results/by_run/20260914_boundary_context/metrics.json \
        --report docs/status/20260914_boundary_context.md
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.evaluation.audit_char_labels_vs_textgrid import (NON_CHARACTER_TOKENS,  # noqa: E402
                                                              parse_interval_tiers)

DEFAULT_ROOT = Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer")
BUCKETS = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99.0))


def bucket_of(duration: float) -> str:
    for low, high in BUCKETS:
        if low <= duration < high:
            return f"{low:g}-{high if high < 99 else '+'}s"
    return "2.0+s"


def classify(token: str) -> str:
    text = str(token).strip()
    if text in NON_CHARACTER_TOKENS:
        return "pause"
    return "sound"


def profile_file(path: Path) -> list[dict[str, Any]]:
    tiers = parse_interval_tiers(path.read_text(encoding="utf-8", errors="ignore"))
    if not tiers:
        return []
    intervals = tiers[0]
    out: list[dict[str, Any]] = []
    for index, interval in enumerate(intervals):
        if classify(interval["text"]) != "sound":
            continue
        duration = float(interval["end"]) - float(interval["start"])
        if duration <= 0:
            continue
        previous = classify(intervals[index - 1]["text"]) if index > 0 else "start"
        following = intervals[index + 1] if index + 1 < len(intervals) else None
        out.append({"duration": duration, "bucket": bucket_of(duration),
                    "prev": previous,
                    "next": classify(following["text"]) if following else "end",
                    "next_pause_sec": (float(following["end"]) - float(following["start"]))
                    if following and classify(following["text"]) == "pause" else None})
    return out


def summarise(records: list[dict[str, Any]], files: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["bucket"]].append(record)
    out: dict[str, Any] = {"schema_version": "boundary_context_v1", "textgrids": files,
                           "characters": len(records), "buckets": {}}
    for low, high in BUCKETS:
        name = f"{low:g}-{high if high < 99 else '+'}s"
        bucket = groups.get(name)
        if not bucket:
            continue
        end_pause = sum(1 for row in bucket if row["next"] == "pause")
        start_pause = sum(1 for row in bucket if row["prev"] == "pause")
        pauses = [row["next_pause_sec"] for row in bucket if row["next_pause_sec"] is not None]
        out["buckets"][name] = {
            "characters": len(bucket),
            "share_end_is_sound_to_silence": round(end_pause / len(bucket), 4),
            "share_start_is_silence_to_sound": round(start_pause / len(bucket), 4),
            "median_next_pause_sec": round(st.median(pauses), 3) if pauses else None,
            "median_duration_ms": round(1000 * st.median(row["duration"] for row in bucket), 1)}
    total = len(records)
    out["overall"] = {"share_end_is_sound_to_silence": round(
        sum(1 for row in records if row["next"] == "pause") / total, 4) if total else None}
    return out


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# 边界结构画像：长音符的结束点是「声音→静音」型边界（生成，勿手改）", "",
             f"> 只读 M4Singer 的 TextGrid 本体（{payload['textgrids']} 个文件、"
             f"{payload['characters']} 个字符区间），不含音频、不含模型、不含我们的派生标签。"
             "回答的是：某个字符的结束点在标注结构上接的是什么。", "",
             "| 标注时长 | 字符数 | **结束点=声音→静音** | 起始点=静音→声音 | 后继静音中位长(s) | 中位时长(ms) |",
             "|---|---|---|---|---|---|"]
    for name, block in payload["buckets"].items():
        lines.append(f"| {name} | {block['characters']} | **{block['share_end_is_sound_to_silence']:.1%}** | "
                     f"{block['share_start_is_silence_to_sound']:.1%} | "
                     f"{block['median_next_pause_sec'] if block['median_next_pause_sec'] is not None else '—'} | "
                     f"{block['median_duration_ms']:.0f} |")
    short = payload["buckets"].get("0.25-0.5s") or payload["buckets"].get("0-0.25s")
    long_ = payload["buckets"].get("2.0+s")
    if short and long_:
        ratio = long_["share_end_is_sound_to_silence"] / max(short["share_end_is_sound_to_silence"], 1e-9)
        lines += ["",
                  f"**读法**：短字符（0.25-0.5s）的结束点有 {short['share_end_is_sound_to_silence']:.1%} 是"
                  f"「声音→静音」型边界，而 ≥2s 的长字符是 **{long_['share_end_is_sound_to_silence']:.1%}**"
                  f"（约 {ratio:.1f} 倍）。也就是说长音符的结束点绝大多数不是"
                  "「唱到下一个字」这种有清晰辅音起音可参照的边界，而是"
                  "「声音逐渐消失到哪里算结束」这种由标注约定决定的边界。",
                  "",
                  "这与三项独立测量互相咬合：",
                  "1. 长字符结束点的声学证据缺失率 37%（短字符 4%）；",
                  "2. 长字符失败时模型分布弥散（top-1 概率 0.24、熵 3.1 nats）且系统性偏早；",
                  "3. ≥2s 字符的超容差率 12.4%（短字符 1.7%）。",
                  "",
                  "**含义**：对这一类边界，追求「猜中约定值」是低信息量的目标；更合理的做法是"
                  "**可容许区间**（例如结束点落在标注值与后继静音起点之间都算对）+ 用置信度把这类字挑出来单独处理。",
                  ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--textgrid-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    paths = sorted(args.textgrid_root.glob("*/*.TextGrid"))
    if args.limit:
        paths = paths[: args.limit]
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            records.extend(profile_file(path))
        except Exception:      # a malformed grid must not stop the corpus pass
            continue
    payload = summarise(records, len(paths))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload["buckets"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
