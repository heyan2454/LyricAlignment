#!/usr/bin/env python3
"""Audit whether a formal v7 sample covers its declared source-song frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def source_id(row: dict) -> str:
    return str(row.get("source_song_id") or row.get("song_id") or row["item_id"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population-manifest", required=True)
    parser.add_argument("--selected-manifest", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    population = [row for row in rows(Path(args.population_manifest))
                  if row.get("dataset") == args.dataset and row.get("split") == args.split]
    selected = rows(Path(args.selected_manifest))
    population_sources = {source_id(row) for row in population}
    selected_sources = {source_id(row) for row in selected}
    payload = {
        "schema": "research_v7/source_song_coverage_v1",
        "dataset": args.dataset,
        "split": args.split,
        "population_item_count": len(population),
        "population_source_song_count": len(population_sources),
        "selected_row_count": len(selected),
        "selected_item_count": len({str(row["item_id"]) for row in selected}),
        "selected_source_song_count": len(selected_sources),
        "missing_source_song_ids": sorted(population_sources - selected_sources),
        "extra_source_song_ids": sorted(selected_sources - population_sources),
        "source_song_population_complete": population_sources == selected_sources,
        "note": "Completeness is at source-song level; it does not imply every segment/item was model-run.",
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "complete": payload["source_song_population_complete"],
                      "population_sources": len(population_sources), "selected_sources": len(selected_sources)}, ensure_ascii=False))
    return 0 if payload["source_song_population_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
