#!/usr/bin/env python3
"""Turn the validated confidence signal into a review list for a delivered batch.

The measurement (`confidence_abstention.py`) showed that the model's own slot entropy flags its own
collapses with AUC ~0.92 and that the effect survives leave-one-song-out.  This script ships that
result as an artefact the product team can act on **without touching the frozen pipeline**: it reads
an existing batch and writes, per song, the characters to re-listen to under a fixed review budget,
plus the expected residual defect rate for that budget.

Default budget is 10% of characters, and thresholds are always chosen out-of-sample
(leave-one-song-out), because an in-sample cut-off is optimistic and would overstate the gate.

    PYTHONPATH=src python scripts/evaluation/export_review_gating.py \
        --batch /home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence \
        --budget 0.10 --out /home/hyan/Data/lyricalign/runs/20260914_review_gating
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from typing import Any

ALIGN_SUFFIX = "alignments/r2/vocal/windowed/alignment.raw.json"
SIGNALS = ("raw_end_entropy", "raw_start_entropy")


def load_songs(batch: Path) -> list[dict[str, Any]]:
    songs: list[dict[str, Any]] = []
    for song_dir in sorted(child for child in batch.iterdir() if child.is_dir()):
        path = song_dir / ALIGN_SUFFIX
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        units: list[dict[str, Any]] = []
        for position, character in enumerate(document.get("characters", [])):
            start, end = character.get("raw_global_start_sec"), character.get("raw_global_end_sec")
            if start is None or end is None:
                continue
            score = next((float(character[name]) for name in SIGNALS
                          if character.get(name) is not None), None)
            if score is None:
                continue
            units.append({"position": position, "line_index": character.get("line_index"),
                          "character": character.get("character"), "signal": name_used(character),
                          "score": score, "defect": int(float(end) <= float(start)),
                          "start_sec": float(start), "end_sec": float(end)})
        if len(units) >= 20:
            songs.append({"song": song_dir.name, "units": units})
    return songs


def name_used(character: dict[str, Any]) -> str:
    return "raw_end_entropy" if character.get("raw_end_entropy") is not None else "raw_start_entropy"


def out_of_sample_thresholds(songs: list[dict[str, Any]], budget: float) -> tuple[dict[str, float], int, int]:
    """Per-song threshold from the *other* songs only, plus the resulting caught/dropped totals."""
    pooled = [unit["score"] for song in songs for unit in song["units"]]
    pooled.sort()
    global_threshold = pooled[min(len(pooled) - 1, int(round((1 - budget) * (len(pooled) - 1))))]
    thresholds: dict[str, float] = {}
    for song in songs:
        thresholds[song["song"]] = global_threshold          # fallback when a song is held out alone
    caught = dropped = 0
    for held in range(len(songs)):
        others = sorted(unit["score"] for index, song in enumerate(songs) if index != held
                        for unit in song["units"])
        if len(others) < 100:
            continue
        threshold = others[min(len(others) - 1, int(round((1 - budget) * (len(others) - 1))))]
        thresholds[songs[held]["song"]] = threshold
        for unit in songs[held]["units"]:
            if unit["score"] >= threshold:
                dropped += 1
                caught += unit["defect"]
    return thresholds, caught, dropped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--budget", type=float, default=0.10, help="share of characters to review")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    songs = load_songs(args.batch)
    if not songs:
        raise SystemExit(f"no usable alignments under {args.batch}")
    thresholds, caught, dropped = out_of_sample_thresholds(songs, args.budget)
    total_units = sum(len(song["units"]) for song in songs)
    total_defects = sum(unit["defect"] for song in songs for unit in song["units"])
    per_song: list[dict[str, Any]] = []
    for song in songs:
        threshold = thresholds[song["song"]]
        flagged = [unit for unit in song["units"] if unit["score"] >= threshold]
        per_song.append({"song": song["song"], "characters": len(song["units"]),
                         "threshold": round(threshold, 4), "flagged": len(flagged),
                         "flagged_share": round(len(flagged) / len(song["units"]), 4),
                         "defects_total": sum(unit["defect"] for unit in song["units"]),
                         "defects_flagged": sum(unit["defect"] for unit in flagged),
                         "residual_defect_rate_if_reviewed": round(
                             (sum(unit["defect"] for unit in song["units"])
                              - sum(unit["defect"] for unit in flagged))
                             / max(1, len(song["units"]) - len(flagged)), 4),
                         "review_list": [{"position": unit["position"], "line_index": unit["line_index"],
                                          "character": unit["character"], "start_sec": unit["start_sec"],
                                          "end_sec": unit["end_sec"], "score": round(unit["score"], 4),
                                          "is_defect": unit["defect"]} for unit in flagged]})
    payload = {"schema_version": "review_gating_v1", "batch": str(args.batch),
               "budget": args.budget, "signal": "raw_end_entropy 优先，缺失时退回 raw_start_entropy",
               "threshold_policy": "leave-one-song-out（阈值不含被评的歌自身）",
               "songs": len(songs), "characters": total_units, "defects": total_defects,
               "defect_rate": round(total_defects / total_units, 4),
               "flagged_units": dropped, "flagged_share": round(dropped / total_units, 4),
               "defects_caught": caught, "defect_capture_share": round(caught / total_defects, 4) if total_defects else None,
               "residual_defect_rate_after_review": round((total_defects - caught) / max(1, total_units - dropped), 4),
               "per_song": sorted(per_song, key=lambda row: -row["defects_total"])}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REVIEW_GATING.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    with (args.out / "review_list.jsonl").open("w", encoding="utf-8") as handle:
        for row in per_song:
            for entry in row["review_list"]:
                handle.write(json.dumps({"song": row["song"], **entry}, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in payload.items() if key != "per_song"},
                     ensure_ascii=False, indent=2))
    print(f"写到 {args.out}/REVIEW_GATING.json 与 review_list.jsonl")


if __name__ == "__main__":
    main()
