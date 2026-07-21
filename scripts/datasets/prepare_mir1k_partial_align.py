#!/usr/bin/env python3
"""Export verified MIR-1K-partial-align records as external test-only JSONL."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.datasets.mir1k import prepare_partial_align_item


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mir1k-root", type=Path, required=True, help="Original MIR-1K root containing UndividedWavfile/")
    parser.add_argument("--annotations", type=Path, required=True, help="Downloaded MIR1k_partial_align.json")
    parser.add_argument("--out-dir", type=Path, required=True, help="External output directory")
    args = parser.parse_args()
    raw = json.loads(args.annotations.read_text(encoding="utf-8"))
    aligned = [item for item in raw if item.get("on_offset")]
    manifests, annotations = [], []
    for item in aligned:
        manifest, characters = prepare_partial_align_item(item, args.mir1k_root)
        manifests.append(manifest)
        annotations.extend(characters)
    write_jsonl(args.out_dir / "mir1k_partial_align_manifest.jsonl", manifests)
    write_jsonl(args.out_dir / "mir1k_partial_align_characters.jsonl", annotations)
    print(json.dumps({"songs": len(manifests), "character_records": len(annotations), "split": "test", "usage": "ood_test_only"}))


if __name__ == "__main__":
    main()
