#!/usr/bin/env python3
"""Prepare deterministic sample selections for immediate Qwen FA diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def stable_rank(seed: int, item_id: str) -> str:
    return hashlib.sha256(f"{seed}:{item_id}".encode("utf-8")).hexdigest()


def select_shift_items(
    labels: list[dict[str, Any]],
    characters: list[dict[str, Any]],
    audio_root: Path,
    *,
    count: int,
    seed: int,
    min_duration: float,
    max_duration: float,
    min_characters: int,
    max_characters: int,
) -> list[dict[str, Any]]:
    character_count: dict[str, int] = defaultdict(int)
    for row in characters:
        character_count[str(row["item_id"])] += 1
    candidates: list[dict[str, Any]] = []
    for row in labels:
        item_id = str(row["item_id"])
        if row.get("split") != "test":
            continue
        duration = float(row["duration_sec"])
        chars = character_count.get(item_id, 0)
        audio_path = audio_root / str(row["audio_relpath"])
        if not (min_duration <= duration <= max_duration):
            continue
        if not (min_characters <= chars <= max_characters):
            continue
        if not audio_path.is_file():
            continue
        candidates.append(
            {
                "item_id": item_id,
                "song_id": row.get("song_id"),
                "audio_relpath": row.get("audio_relpath"),
                "duration_sec": duration,
                "character_count": chars,
                "stable_rank": stable_rank(seed, item_id),
            }
        )
    candidates.sort(key=lambda row: (row["stable_rank"], row["item_id"]))
    selected: list[dict[str, Any]] = []
    used_songs: set[str] = set()
    for row in candidates:
        song = str(row.get("song_id") or "")
        if song and song in used_songs:
            continue
        selected.append(row)
        if song:
            used_songs.add(song)
        if len(selected) >= count:
            break
    if len(selected) < count:
        selected_ids = {row["item_id"] for row in selected}
        for row in candidates:
            if row["item_id"] in selected_ids:
                continue
            selected.append(row)
            if len(selected) >= count:
                break
    if len(selected) < count:
        raise RuntimeError(f"only {len(selected)} eligible shift items; requested {count}")
    return selected


def select_crop_items(audit_path: Path, worst_count: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    items = list(data.get("paired_items", []))
    if len(items) < worst_count + 1:
        raise RuntimeError("outlier audit contains too few paired items")
    items.sort(key=lambda row: float(row["penalized_mae_sec"]), reverse=True)
    worst = items[:worst_count]
    remaining = items[worst_count:]
    values = [float(row["penalized_mae_sec"]) for row in remaining]
    target = statistics.median(values)
    control = min(remaining, key=lambda row: abs(float(row["penalized_mae_sec"]) - target))
    selected = [
        {
            "role": f"worst_{index + 1}",
            **row,
        }
        for index, row in enumerate(worst)
    ]
    selected.append({"role": "normal_control", **control})
    return selected, {"remaining_median_penalized_mae_sec": target}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--outlier-audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shift-count", type=int, default=3)
    parser.add_argument("--crop-worst-count", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--min-duration", type=float, default=5.0)
    parser.add_argument("--max-duration", type=float, default=15.0)
    parser.add_argument("--min-characters", type=int, default=15)
    parser.add_argument("--max-characters", type=int, default=40)
    args = parser.parse_args()

    labels = read_jsonl(args.labels)
    characters = read_jsonl(args.characters)
    shift_items = select_shift_items(
        labels,
        characters,
        args.audio_root,
        count=args.shift_count,
        seed=args.seed,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        min_characters=args.min_characters,
        max_characters=args.max_characters,
    )
    crop_items, crop_meta = select_crop_items(args.outlier_audit, args.crop_worst_count)
    payload = {
        "schema_version": "qwen_fa_immediate_all_selection_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "constraints": {
            "min_duration": args.min_duration,
            "max_duration": args.max_duration,
            "min_characters": args.min_characters,
            "max_characters": args.max_characters,
        },
        "shift_items": shift_items,
        "repeat_pair": {"A": shift_items[0], "B": shift_items[1]},
        "crop_items": crop_items,
        "crop_selection_metadata": crop_meta,
    }
    atomic_json(args.out, payload)
    print(json.dumps({"out": str(args.out), "shift_items": len(shift_items), "crop_items": len(crop_items)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
