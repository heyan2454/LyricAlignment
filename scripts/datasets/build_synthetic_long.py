#!/usr/bin/env python3
"""Build only verified adjacent same-song/singer synthetic-long examples."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.synthetic import build_synthetic_manifest, concat_wavs, segment_order, shifted_annotations


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--bucket-sec", type=float, choices=(20, 30, 60, 120), required=True)
    args = parser.parse_args()
    rows = jsonl(args.manifest)
    annotations = defaultdict(list)
    for row in jsonl(args.annotations):
        if row.get("start_sec") is not None:
            annotations[str(row["item_id"])].append(row)
    by_song_singer = defaultdict(list)
    for row in rows:
        if row.get("status") == "accepted":
            by_song_singer[(row["song_id"], row["singer_id"])].append(row)
    candidates, failures = [], []
    for key, group in sorted(by_song_singer.items()):
        group.sort(key=lambda row: segment_order(str(row["item_id"])))
        for start in range(len(group)):
            chosen = [group[start]]
            for candidate in group[start + 1:]:
                if segment_order(candidate["item_id"]) != segment_order(chosen[-1]["item_id"]) + 1:
                    break
                chosen.append(candidate)
                if sum(float(row["duration_sec"]) for row in chosen) >= args.bucket_sec:
                    candidates.append(chosen)
                    break
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifests, chars = [], []
    for index, chosen in enumerate(candidates):
        relpath = f"audio/bucket_{int(args.bucket_sec)}/{index:04d}.wav"
        duration = concat_wavs([args.audio_root / row["audio_relpath"] for row in chosen], args.out_dir / relpath)
        manifest = build_synthetic_manifest(chosen, duration, relpath)
        manifests.append(manifest)
        chars.extend(shifted_annotations([annotation for row in chosen for annotation in annotations[row["item_id"]]], manifest["cumulative_offsets"]))
    for name, payload in (("synthetic_manifest.jsonl", manifests), ("synthetic_characters.jsonl", chars)):
        (args.out_dir / name).write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in payload), encoding="utf-8")
    summary = {"status": "passed" if manifests else "external_or_data_limited", "bucket_sec": args.bucket_sec, "synthetic_count": len(manifests), "failure_reason": None if manifests else "no_adjacent_same_song_same_singer_A_tier_sequence_reaches_bucket"}
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
