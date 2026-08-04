#!/usr/bin/env python3
"""Inventory existing materialized long-song assets into a traceable v7 manifest.

This intentionally labels records as ``derived_pilot``.  It does not infer the
split of a legacy materialization or silently treat it as a formal heldout set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import wave
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialized-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    root = Path(args.materialized_root).resolve()
    rows = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        audio = directory / "vocal.wav"
        gt = directory / "ground_truth.characters.jsonl"
        source = directory / "source_manifest.json"
        if not (audio.is_file() and gt.is_file() and source.is_file()):
            continue
        try:
            meta = json.loads(source.read_text(encoding="utf-8"))
            gt_rows = [json.loads(line) for line in gt.read_text(encoding="utf-8").splitlines() if line]
        except (OSError, json.JSONDecodeError):
            continue
        if not gt_rows:
            continue
        rows.append({
            "item_id": meta.get("item_id", directory.name),
            "source_song_id": meta.get("song_id", directory.name),
            "song_id": meta.get("song_id", directory.name),
            "dataset": "m4singer_materialized_legacy",
            "split": "derived_pilot",
            "audio_path": str(audio), "gt_path": str(gt), "text_source": str(gt),
            "duration_sec": duration_sec(audio), "unit_count": len(gt_rows),
            "provenance": {"materialized_root": str(root), "source_manifest": str(source),
                           "source_manifest_sha256": sha256(source), "audio_sha256": sha256(audio),
                           "gt_sha256": sha256(gt), "formal_split_inference": "not_claimed"},
        })
    if args.limit:
        rows = rows[:args.limit]
    target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"ok": True, "rows": len(rows), "out": str(target),
                      "sha256": sha256(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
