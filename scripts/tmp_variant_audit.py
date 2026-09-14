#!/usr/bin/env python3
"""Temporary helper: per-variant product anomaly numbers (to correct a wrong headline)."""
import glob
import json
from pathlib import Path
import sys

VARIANTS = ("r2/vocal/windowed", "r2/vocal/full", "r0/mix/full")
BATCHES = ("/home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence",
           "/home/hyan/Data/lyricalign/runs/20260814_ktv_B4")
EPS = 1e-6


def stage_intervals(characters):
    keys = (("raw", "raw_global_start_sec", "raw_global_end_sec"),
            ("fixed", "official_fixed_global_start_sec", "official_fixed_global_end_sec"),
            ("shipped", "start_sec", "end_sec"))
    out = {}
    for label, start_key, end_key in keys:
        intervals = []
        for character in characters:
            start, end = character.get(start_key), character.get(end_key)
            if start is not None and end is not None:
                intervals.append((float(start), float(end)))
        if intervals:
            out[label] = intervals
    return out


def count(intervals):
    zero = sum(1 for start, end in intervals if abs(end - start) <= EPS)
    negative = sum(1 for start, end in intervals if end < start - EPS)
    overlap = sum(1 for index in range(1, len(intervals))
                  if intervals[index][0] < intervals[index - 1][1] - EPS)
    run = longest = 0
    for start, end in intervals:
        if abs(end - start) <= EPS:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    long_notes = sum(1 for start, end in intervals if end - start >= 2.0)
    return {"n": len(intervals), "zero": zero, "negative": negative,
            "overlap": overlap, "longest_run": longest, "long": long_notes}


for batch in BATCHES:
    for variant in VARIANTS:
        paths = sorted(glob.glob(f"{batch}/*/alignments/{variant}/alignment.json"))
        if not paths:
            continue
        totals = {label: {"n": 0, "zero": 0, "negative": 0, "overlap": 0, "longest_run": 0, "long": 0}
                  for label in ("raw", "fixed", "shipped")}
        for path in paths:
            characters = (json.loads(Path(path).read_text(encoding="utf-8")).get("characters") or [])
            if len(characters) < 5:
                continue
            for label, intervals in stage_intervals(characters).items():
                values = count(intervals)
                for key in ("n", "zero", "negative", "overlap", "long"):
                    totals[label][key] += values[key]
                totals[label]["longest_run"] = max(totals[label]["longest_run"], values["longest_run"])
        songs = {path.split("/alignments/")[0].split("/")[-1] for path in paths}
        print(f"\n【{batch.split('/')[-1]} / {variant}】文件 {len(paths)} 份、不同歌 {len(songs)} 首")
        for label, name in (("raw", "模型原始"), ("fixed", "上游修补后"), ("shipped", "成品")):
            values = totals[label]
            share = 100 * values["zero"] / values["n"] if values["n"] else 0.0
            print(f"  {name:8s} 字 {values['n']:7,}  零时长 {values['zero']:6,} ({share:5.1f}%)"
                  f"  负时长 {values['negative']:6,}  重叠 {values['overlap']:6,}"
                  f"  最长连续坍缩 {values['longest_run']:4,}  ≥2s 长音 {values['long']:6,}")
