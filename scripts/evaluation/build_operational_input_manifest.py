#!/usr/bin/env python3
"""Build an operational input manifest for raw-mixture datasets.

This does not separate vocals. It records the raw audio path, annotation source,
tier, license, and status so a later vocal-derivation step can consume it.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

DEFAULT_DATASETS_ROOT = Path("/home/hyan/Data/datasets")


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True, help="Evaluation V1 split manifest or filtered manifest")
    parser.add_argument("--datasets-root", type=Path, default=DEFAULT_DATASETS_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    out_rows = []
    for row in rows:
        ds = row.get("dataset_id")
        audio_rel = row.get("audio_relpath")
        if not audio_rel:
            continue
        if ds in ("mir_mlpop_cmn", "mir_mlpop_yue"):
            dataset_root = args.datasets_root / "mir_mlpop"
            lang = "cmn" if ds == "mir_mlpop_cmn" else "yue"
            annotation_rel = f"raw/extracted/official_repository/dataset/{lang}_dataset_240223.json"
            out_rows.append({
                "dataset_id": ds,
                "item_id": row.get("item_id"),
                "tier": row.get("tier"),
                "group_id": row.get("group_id"),
                "audio_relpath": audio_rel,
                "audio_abs": str(dataset_root / audio_rel),
                "annotation_relpath": annotation_rel,
                "annotation_abs": str(dataset_root / annotation_rel),
                "language": row.get("language"),
                "license_policy": "academic_noncommercial_only",
                "status": "raw_mixture_pending_vocal",
                "notes": ["Requires vocal derivation before operational alignment."],
            })
        elif ds == "jamendolyrics_en":
            dataset_root = args.datasets_root / "jamendolyrics_en"
            annotation_rel = "raw/extracted/huggingface_snapshot/subsets/en/metadata.jsonl"
            out_rows.append({
                "dataset_id": ds,
                "item_id": row.get("item_id"),
                "tier": row.get("tier"),
                "group_id": row.get("group_id"),
                "audio_relpath": audio_rel,
                "audio_abs": str(dataset_root / audio_rel),
                "annotation_relpath": annotation_rel,
                "annotation_abs": str(dataset_root / annotation_rel),
                "language": row.get("language"),
                "license_type": (row.get("metadata") or {}).get("license_type"),
                "status": "raw_mixture_pending_vocal",
                "notes": ["Requires vocal derivation and per-track license retention."],
            })
    atomic_jsonl(args.out, out_rows)
    print(json.dumps({"out": str(args.out), "operational_items": len(out_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
