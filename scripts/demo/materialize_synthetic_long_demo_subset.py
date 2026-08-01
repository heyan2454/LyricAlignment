#!/usr/bin/env python3
"""Materialize M4Singer synthetic-long records in demo-subset layout.

The source audio is already clean vocal audio. It is linked under the historical
``demucs_<model>_vocals.wav`` filename solely so the existing serial diagnostic
runner can reuse one path. The inventory records this provenance explicitly and
must not be interpreted as a separator comparison.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def safe_link(source: Path, target: Path, copy: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    if copy:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source.resolve())


def chunk(text: str, units: int) -> str:
    return "\n".join(text[i:i + units] for i in range(0, len(text), units)) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--characters", type=Path, required=True)
    p.add_argument("--audio-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--demucs-model", default="htdemucs_ft")
    p.add_argument("--units-per-line", type=int, default=20)
    p.add_argument("--copy-audio", action="store_true")
    args = p.parse_args()
    manifests = read_jsonl(args.manifest)
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(args.characters):
        by_item[str(row["item_id"])].append(row)
    selection: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for ordinal, row in enumerate(sorted(manifests, key=lambda value: str(value["item_id"]))):
        source_id = str(row["item_id"])
        item_id = f"m4long_{ordinal:04d}"
        chars = sorted(by_item.get(source_id, []), key=lambda value: int(value["character_index"]))
        lyrics = str(row.get("lyrics_normalized", ""))
        if not chars or len(chars) != len(lyrics):
            raise ValueError(f"{source_id}: character/lyrics mismatch {len(chars)} != {len(lyrics)}")
        source_audio = args.audio_root / str(row["audio_relpath"])
        if not source_audio.is_file():
            raise FileNotFoundError(source_audio)
        item_root = args.out_dir / "items" / item_id
        item_root.mkdir(parents=True, exist_ok=True)
        (item_root / "lyrics.txt").write_text(chunk(lyrics, args.units_per_line), encoding="utf-8")
        normalized_chars = []
        for index, char_row in enumerate(chars):
            copied = dict(char_row)
            copied["item_id"] = item_id
            copied["character_index"] = index
            copied.setdefault("normalized_character", lyrics[index])
            normalized_chars.append(copied)
        write_jsonl(item_root / "ground_truth.characters.jsonl", normalized_chars)
        target_audio = item_root / "audio" / f"demucs_{args.demucs_model}_vocals.wav"
        safe_link(source_audio, target_audio, args.copy_audio)
        safe_link(source_audio, item_root / "audio" / "mix.wav", args.copy_audio)
        provenance = {
            "schema_version": "m4singer_synthetic_long_demo_item_v1",
            "item_id": item_id,
            "source_item_id": source_id,
            "audio_origin": "m4singer_clean_vocal_not_demucs_output",
            "source_audio": str(source_audio.resolve()),
            "duration_sec": row.get("duration_sec"),
            "target_duration_sec": row.get("target_duration_sec"),
            "song_id": row.get("song_id"),
            "source_song_id": row.get("source_song_id") or row.get("song_id") or source_id,
            "singer_id": row.get("singer_id"),
            "split": row.get("split"),
            "source_splits": row.get("source_splits") or ([row.get("split")] if row.get("split") is not None else []),
            "training_exposure": bool(row.get("training_exposure", str(row.get("split")) == "train")),
            "join_points_sec": row.get("join_points_sec") or [],
            "seam_mask": row.get("seam_mask") or [],
            "source_item_ids": row.get("source_item_ids") or [],
        }
        (item_root / "source_manifest.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        selection.append({
            "item_id": item_id,
            "selection_role": row.get("selection_role") or "m4_synthetic_long",
            "selection_order": ordinal,
            "split": row.get("split"),
            "source_splits": row.get("source_splits") or ([row.get("split")] if row.get("split") is not None else []),
            "training_exposure": bool(row.get("training_exposure", str(row.get("split")) == "train")),
            "source_song_id": row.get("source_song_id") or row.get("song_id") or source_id,
            "song_id": row.get("song_id"),
            "singer_id": row.get("singer_id"),
            "duration_sec": row.get("duration_sec"),
            "source_item_id": source_id,
        })
        inventory.append(provenance)
    write_jsonl(args.out_dir / "selection.jsonl", selection)
    summary = {
        "schema_version": "m4singer_synthetic_long_demo_subset_v1",
        "item_count": len(selection),
        "audio_origin": "m4singer_clean_vocal_not_demucs_output",
        "items": inventory,
    }
    (args.out_dir / "subset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "item_count": len(selection), "out_dir": str(args.out_dir.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
