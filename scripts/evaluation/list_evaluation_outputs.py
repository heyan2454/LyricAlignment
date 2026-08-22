#!/usr/bin/env python3
"""List all Evaluation V1 external output batches and their cleanup status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_ROOT = Path("/home/hyan/Data/lyricalign/runs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    items = []
    for p in sorted(args.runs_root.glob("20260816_evaluation_v1_*")):
        if not p.is_dir():
            continue
        files = sorted(x.name for x in p.iterdir() if x.is_file())
        items.append({
            "path": str(p),
            "name": p.name,
            "has_cleanup_report": (p / "cleanup_report.md").is_file(),
            "file_count": len(files),
            "files": files,
        })
    payload = {"schema_version": "evaluation_outputs_index_v1", "runs_root": str(args.runs_root), "batches": items}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"batch_count": len(items), "out": str(args.out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
