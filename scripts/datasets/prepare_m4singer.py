#!/usr/bin/env python3
"""Build external, review-gated M4Singer manifest and character-mapping JSONL files."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.m4singer import MAPPING_VERSION, NORMALIZATION_VERSION, prepare_item


def read_overlays(path: Path | None) -> list[dict]:
    if path is None:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_character_time_anchors(path: Path | None) -> dict[str, list[dict]]:
    anchors: dict[str, list[dict]] = {}
    if path is None:
        return anchors
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            anchors.setdefault(str(row["item_id"]), []).append(row)
    for rows in anchors.values():
        rows.sort(key=lambda row: int(row["character_index"]))
    return anchors


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m4singer-root", type=Path, required=True, help="Directory containing meta.json and singer#song WAV directories")
    parser.add_argument("--out-dir", type=Path, required=True, help="External output directory; never place large data in the repository")
    parser.add_argument("--limit", type=int, help="Process only the first N metadata entries for a reproducibility smoke")
    parser.add_argument("--include-audio-sha256", action="store_true", help="Hash each WAV; slower but required before a frozen dataset release")
    parser.add_argument("--token-overlays", type=Path, help="Approved hash-anchored JSONL source-token overlays")
    parser.add_argument("--character-time-anchors", type=Path, help="Independent character-timing JSONL; enables the incremental slur time stage")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    metadata_path = args.m4singer_root / "meta.json"
    raw_items = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(raw_items, list):
        raise SystemExit(f"Expected a list in {metadata_path}")
    if args.limit is not None:
        raw_items = raw_items[: args.limit]
    overlays = read_overlays(args.token_overlays)
    anchors = read_character_time_anchors(args.character_time_anchors)

    manifests: list[dict] = []
    annotations: list[dict] = []
    statuses: Counter[str] = Counter()
    mapping_statuses: Counter[str] = Counter()
    for raw in raw_items:
        manifest, item_annotations = prepare_item(raw, args.m4singer_root, include_audio_hash=args.include_audio_sha256, overlays=overlays, character_time_anchors=anchors.get(str(raw["item_name"])))
        manifests.append(manifest)
        annotations.extend(item_annotations)
        statuses[manifest["status"]] += 1
        mapping_statuses[manifest["mapping_status"]] += 1

    write_jsonl(args.out_dir / "m4singer_manifest.jsonl", manifests)
    write_jsonl(args.out_dir / "m4singer_character_annotations.jsonl", annotations)
    summary = {
        "schema_version": 1,
        "dataset_id": "m4singer",
        "source_metadata": "meta.json",
        "item_count": len(manifests),
        "character_record_count": len(annotations),
        "status_counts": dict(sorted(statuses.items())),
        "mapping_status_counts": dict(sorted(mapping_statuses.items())),
        "normalization_version": NORMALIZATION_VERSION,
        "mapping_version": MAPPING_VERSION,
        "token_overlay_count": len(overlays),
        "character_time_anchor_item_count": len(anchors),
        "audio_sha256_included": args.include_audio_sha256,
        "scope": "manifest and review-gated character-to-phoneme candidate mapping; no character timestamps or split assignment",
    }
    temporary = args.out_dir / "m4singer_preparation_summary.json.tmp"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out_dir / "m4singer_preparation_summary.json")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
