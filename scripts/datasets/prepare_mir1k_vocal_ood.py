#!/usr/bin/env python3
"""Extract the confirmed MIR-1K vocal channel and freeze the aligned OOD subset."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.mir1k import extract_vocal_channel, prepare_partial_align_item


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mir1k-root", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--vocal-channel-index", type=int, default=1)
    args = parser.parse_args()
    raw = json.loads(args.annotations.read_text(encoding="utf-8"))
    aligned = [item for item in raw if item.get("on_offset")]
    vocal_dir = args.out_dir / "vocal_wavs"; vocal_dir.mkdir(parents=True, exist_ok=True)
    manifests, characters, extraction = [], [], []
    for item in aligned:
        song = str(item["song_id"])
        evidence = extract_vocal_channel(args.mir1k_root / "UndividedWavfile" / song, vocal_dir / song, vocal_channel_index=args.vocal_channel_index, overwrite=True)
        manifest, rows = prepare_partial_align_item(item, args.out_dir, audio_relpath_prefix="vocal_wavs", channel_extraction=evidence)
        manifests.append(manifest); characters.extend(rows); extraction.append(evidence)
    write_jsonl(args.out_dir / "mir1k_vocal_ood_manifest.jsonl", manifests)
    write_jsonl(args.out_dir / "mir1k_vocal_ood_characters.jsonl", characters)
    (args.out_dir / "channel_extraction_manifest.json").write_text(json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"status": "passed", "songs": len(manifests), "characters": len(characters), "vocal_channel_index": args.vocal_channel_index, "vocal_channel_confirmation": "user_manual_review_20260722", "split": "test", "usage": "ood_test_only", "source_root": str(args.mir1k_root.resolve())}
    (args.out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__": main()
