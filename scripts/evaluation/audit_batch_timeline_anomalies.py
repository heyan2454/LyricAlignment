#!/usr/bin/env python3
'''Audit the shipped demo/delivery timelines for collapse-type anomalies, stage by stage.

Why stage by stage: each character in a delivered product carries three timelines —
`raw_global_*` (the model's own answer), `official_fixed_*` (after the upstream repair),
and `start_sec/end_sec` (what the user actually sees).  Counting anomalies only on the final one hides
which stage created or masked them, which is exactly the question the two training-free gains
(monotone DP decode + confidence gating) are meant to answer.

    PYTHONPATH=src python scripts/evaluation/audit_batch_timeline_anomalies.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_B4 \
        --out results/by_run/20260914_product_anomaly_audit/metrics.json
'''

from __future__ import annotations

import argparse
import glob
import json
import statistics as st
from pathlib import Path
from typing import Any

EPS = 1e-6
LONG_SEC = 2.0
MOVE_SEC = 0.2          # how far the pipeline may have shifted a boundary and still call it fine


def value(character: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        candidate = character.get(key)
        if candidate is not None:
            return float(candidate)
    return None


def anomalies_of(intervals: list[tuple[float, float]], audio_duration: float | None) -> dict[str, Any]:
    zero = negative = overlap = regress = outside = 0
    run_length = max_run = 0
    for index, (start, end) in enumerate(intervals):
        if end <= start + EPS:
            zero += 1 if end > start - EPS else 0
            negative += 1 if end < start - EPS else 0
        if index:
            previous_end = intervals[index - 1][1]
            if end <= start + EPS and previous_end <= start + EPS:
                run_length += 1
            else:
                max_run = max(max_run, run_length)
                run_length = 0
            if start < intervals[index - 1][0] - EPS:
                regress += 1
            if start < previous_end - EPS:
                overlap += 1
        if audio_duration and (start < -EPS or end > audio_duration + EPS):
            outside += 1
    max_run = max(max_run, run_length)
    long_notes = sum(1 for start, end in intervals if end - start >= LONG_SEC)
    return {"characters": len(intervals),
            "zero_duration": zero, "negative_duration": negative,
            "overlap_with_previous": overlap, "start_regresses": regress,
            "outside_audio": outside, "longest_collapse_run": max_run,
            "long_ge_2s": long_notes}


def audit_song(path: Path) -> dict[str, Any] | None:
    document = json.loads(path.read_text(encoding="utf-8"))
    characters = document.get("characters") or []
    if len(characters) < 5:
        return None
    audio_duration = (document.get("summary") or {}).get("audio_duration_sec")
    stages: dict[str, list[tuple[float, float]]] = {"raw": [], "official_fixed": [], "shipped": []}
    low_confidence_moved = 0
    moved_total = 0
    confidences: list[float] = []
    for character in characters:
        raw_start = value(character, "raw_global_start_sec")
        raw_end = value(character, "raw_global_end_sec")
        fixed_start = value(character, "official_fixed_global_start_sec", "gpu_fixed_global_start_sec")
        fixed_end = value(character, "official_fixed_global_end_sec", "gpu_fixed_global_end_sec")
        ship_start = value(character, "start_sec", "selected_start_sec")
        ship_end = value(character, "end_sec", "selected_end_sec")
        if raw_start is not None and raw_end is not None:
            stages["raw"].append((raw_start, raw_end))
        if fixed_start is not None and fixed_end is not None:
            stages["official_fixed"].append((fixed_start, fixed_end))
        if ship_start is not None and ship_end is not None:
            stages["shipped"].append((ship_start, ship_end))
        confidence = value(character, "raw_end_top1_probability")
        if confidence is not None and raw_end is not None and ship_end is not None:
            confidences.append(confidence)
            moved = abs(ship_end - raw_end) > MOVE_SEC
            moved_total += int(moved)
            if moved and confidence < 0.5:
                low_confidence_moved += 1
    quality_path = path.with_name("alignment.quality.json")
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    result = {"song": path.parents[4].name if len(path.parents) > 4 else path.parent.name,
              "stages": {name: anomalies_of(values, audio_duration) for name, values in stages.items() if values},
              "shipped_vs_raw_moved_ge_0.2s": moved_total,
              "moved_and_low_confidence": low_confidence_moved,
              "median_end_confidence": round(st.median(confidences), 4) if confidences else None,
              "product_status": quality.get("status"),
              "product_structural_errors": quality.get("structural_errors") or [],
              "product_warnings": quality.get("warnings") or []}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", action="append", required=True, type=Path)
    parser.add_argument("--pattern", default="*/alignments/*/*/*/alignment.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    payload: dict[str, Any] = {"schema_version": "product_anomaly_audit_v1",
                               "tolerance": {"move_sec": MOVE_SEC, "long_sec": LONG_SEC}, "batches": {}}
    for batch in args.batch:
        paths = sorted(glob.glob(str(batch / args.pattern)))
        if args.limit:
            paths = paths[: args.limit]
        songs = [report for path in map(Path, paths) if (report := audit_song(path))]
        totals: dict[str, int] = {}
        for stage in ("raw", "official_fixed", "shipped"):
            for key in ("characters", "zero_duration", "negative_duration", "overlap_with_previous",
                        "start_regresses", "outside_audio", "longest_collapse_run", "long_ge_2s"):
                values = [song["stages"][stage][key] for song in songs if stage in song["stages"]]
                totals[f"{stage}_{key}"] = (max(values) if key == "longest_collapse_run" else sum(values)) if values else 0
        totals["songs_with_warnings_but_no_structural_errors"] = sum(
            1 for song in songs if song["product_warnings"] and not song["product_structural_errors"])
        totals["songs"] = len(songs)
        totals["shipped_moved_ge_0.2s_vs_raw"] = sum(song["shipped_vs_raw_moved_ge_0.2s"] for song in songs)
        totals["moved_and_low_confidence"] = sum(song["moved_and_low_confidence"] for song in songs)
        payload["batches"][batch.name] = {"batch": str(batch), "totals": totals,
                                          "songs": sorted(songs, key=lambda song: -song["stages"].get(
                                              "shipped", {}).get("zero_duration", 0))}

    lines = ["# 成品异常审计（生成，勿手改）", "",
             "> 三个阶段都数一遍：**模型原始**（raw）→ **上游修补后**（official_fixed）→ **用户看到的成品**（shipped）。", ""]
    for name, block in payload["batches"].items():
        totals = block["totals"]
        lines += [f"## 批：`{name}`（{totals['songs']} 首歌）", "",
                  "| 阶段 | 字数 | 零时长 | 负时长 | 与上一字重叠 | 开始时间倒退 | 超出音频范围 | 最长连续坍缩 | ≥2s 长音 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for stage, label in (("raw", "模型原始"), ("official_fixed", "上游修补后"), ("shipped", "**成品**")):
            key = {"raw": "模型原始", "official_fixed": "上游修补后", "shipped": "**成品**"}[stage]
            lines.append(f"| {key} | {totals[f'{stage}_characters']} | {totals[f'{stage}_zero_duration']} | "
                         f"{totals[f'{stage}_negative_duration']} | {totals[f'{stage}_overlap_with_previous']} | "
                         f"{totals[f'{stage}_start_regresses']} | {totals[f'{stage}_outside_audio']} | "
                         f"{totals[f'{stage}_longest_collapse_run']} | {totals[f'{stage}_long_ge_2s']} |")
        worst = sorted(block["songs"], key=lambda song: -song["stages"].get("shipped", {}).get("zero_duration", 0))[:6]
        if worst:
            lines += ["", "最严重的几首歌（按成品里的零时长字数排序）：", "",
                      "| 歌 | 字数 | 成品零时长 | 成品最长连续坍缩 | ≥2s 长音：模型原始→成品 | 自检状态 |",
                      "|---|---|---|---|---|---|"]
            for song in worst:
                shipped = song["stages"].get("shipped", {})
                raw_stage = song["stages"].get("raw", {})
                lines.append(f"| {song['song']} | {shipped.get('characters', 0)} | "
                             f"{shipped.get('zero_duration', 0)} | {shipped.get('longest_collapse_run', 0)} | "
                             f"{raw_stage.get('long_ge_2s', 0)} → {shipped.get('long_ge_2s', 0)} | "
                             f"`{song['product_status']}`（结构错误 {len(song['product_structural_errors'])} 项、"
                             f"警告 {len(song['product_warnings'])} 项） |")
        lines += ["",
                  f"- 成品里被流水线挪动 ≥0.2 秒的字：**{totals['shipped_moved_ge_0.2s_vs_raw']}** 个"
                  f"（其中 {totals['moved_and_low_confidence']} 个模型自己就是低把握 ⇒ 挪动多发生在该复核的地方）；",
                  f"- **成品自检的漏检情况**：{totals['songs_with_warnings_but_no_structural_errors']} / {totals['songs']} 首歌"
                  "「有警告但结构错误记为 0」⇒ 严重问题落在 warnings 里，而看 status/structural_errors 的人会以为没问题。", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out.with_name("REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
