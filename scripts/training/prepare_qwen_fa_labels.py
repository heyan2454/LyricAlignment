#!/usr/bin/env python3
"""Create immutable derived Qwen FA timestamp labels from a frozen split."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.training.qwen_fa_labels import build_label_record, collect_character_rows, label_summary


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--timestamp-segment-sec", type=float, default=0.08)
    parser.add_argument("--num-labels", type=int, default=5000)
    parser.add_argument("--output-name", default="m4singer_qwen_fa_labels.jsonl")
    args = parser.parse_args()
    manifest = read_jsonl(args.split_manifest)
    chars = collect_character_rows(args.characters)
    records = [build_label_record(row, chars[str(row["item_id"])], segment_sec=args.timestamp_segment_sec, num_labels=args.num_labels) for row in manifest]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    labels_path = args.out_dir / args.output_name
    atomic_jsonl(labels_path, records)
    summary = label_summary(records) | {
        "source_split_manifest": str(args.split_manifest), "source_split_manifest_sha256": sha256(args.split_manifest),
        "source_character_annotations": str(args.characters), "source_character_annotations_sha256": sha256(args.characters),
        "output_labels_sha256": sha256(labels_path), "quantization": "round_half_up(time_sec / timestamp_segment_sec)",
    }
    (args.out_dir / "label_preparation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
