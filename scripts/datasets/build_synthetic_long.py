#!/usr/bin/env python3
"""Build only verified adjacent same-song/singer synthetic-long examples."""

from __future__ import annotations

import argparse
import json
import hashlib
import tempfile
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.synthetic import build_synthetic_manifest, concat_wavs, segment_order, shifted_annotations, validate_source_annotations


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--bucket-sec", type=float, choices=(20, 30, 60, 180), required=True)
    parser.add_argument("--split", default=None, help="Restrict sources to one frozen split, for example test.")
    parser.add_argument("--max-candidates", type=int, default=0, help="Deterministic cap for smoke; 0 means all.")
    args = parser.parse_args()
    rows = jsonl(args.manifest)
    annotations = defaultdict(list)
    for row in jsonl(args.annotations):
        annotations[str(row["item_id"])].append(row)
    by_song_singer = defaultdict(list)
    for row in rows:
        if row.get("status") == "accepted" and (args.split is None or row.get("split") == args.split):
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
                minimum = {20: 20, 30: 30, 60: 45, 180: 150}[int(args.bucket_sec)]
                if sum(float(row["duration_sec"]) for row in chosen) >= minimum:
                    candidates.append(chosen)
                    break
            if candidates and candidates[-1] is chosen:
                # One non-overlapping formal window per song/singer and bucket.
                # Training window augmentation is a separate, explicitly opted-in
                # workflow rather than an accidental all-start expansion.
                break
        if args.max_candidates and len(candidates) >= args.max_candidates:
            candidates = candidates[: args.max_candidates]
            break
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifests, chars = [], []
    for index, chosen in enumerate(candidates):
        relpath = f"audio/bucket_{int(args.bucket_sec)}/{index:04d}.wav"
        try:
            validate_source_annotations(chosen, annotations)
        except ValueError as exc:
            failures.append({"source_item_ids": [row["item_id"] for row in chosen], "reason": str(exc)})
            continue
        duration, ranges = concat_wavs([args.audio_root / row["audio_relpath"] for row in chosen], args.out_dir / relpath)
        audio_path = args.out_dir / relpath
        shifted = shifted_annotations([annotation for row in chosen for annotation in sorted(annotations[row["item_id"]], key=lambda item: int(item["character_index"]))], {row["item_id"]: start for row, (start, _) in zip(sorted(chosen, key=lambda r: segment_order(str(r["item_id"]))), ranges, strict=True)})
        annotation_hash = hashlib.sha256("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in shifted).encode()).hexdigest()
        manifest = build_synthetic_manifest(chosen, duration, relpath, source_ranges=ranges, output_audio_sha256=hashlib.sha256(audio_path.read_bytes()).hexdigest(), annotation_sha256=annotation_hash)
        manifest["target_duration_sec"] = args.bucket_sec
        manifests.append(manifest)
        for character_index, annotation in enumerate(shifted):
            annotation["item_id"] = manifest["item_id"]
            annotation["character_index"] = character_index
            annotation["length_source"] = "synthetic_concat"
        chars.extend(shifted)
    for name, payload in (("synthetic_manifest.jsonl", manifests), ("synthetic_characters.jsonl", chars)):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.out_dir, delete=False) as handle:
            handle.write("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in payload)); temporary = Path(handle.name)
        temporary.replace(args.out_dir / name)
    durations = [float(row["duration_sec"]) for row in manifests]
    summary = {"status": "passed" if manifests else "external_or_data_limited", "bucket_sec": args.bucket_sec, "split": args.split, "synthetic_count": len(manifests), "character_count": len(chars), "failed_candidate_count": len(failures), "minimum_duration_sec": min(durations) if durations else None, "maximum_duration_sec": max(durations) if durations else None, "mean_duration_sec": sum(durations) / len(durations) if durations else None, "failure_reason": None if manifests else "no_adjacent_same_song_same_singer_accepted_sequence_reaches_bucket_or_annotation_validation"}
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
