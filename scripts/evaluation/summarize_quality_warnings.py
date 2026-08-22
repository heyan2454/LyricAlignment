#!/usr/bin/env python3
"""Summarize alignment quality status/warnings for a batch root."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", default="r0,r1,r2")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    result = {}
    for model in models:
        statuses = Counter()
        warnings = Counter()
        units = 0
        zero = 0
        for d in sorted(args.batch_root.iterdir()):
            if not d.is_dir():
                continue
            q = d / "alignments" / model / "vocal" / "windowed" / "alignment.quality.json"
            if not q.exists():
                continue
            data = json.loads(q.read_text(encoding="utf-8"))
            statuses[data.get("status")] += 1
            for w in data.get("warnings", []):
                warnings[w] += 1
            a = d / "alignments" / model / "vocal" / "windowed" / "alignment.json"
            if a.exists():
                ad = json.loads(a.read_text(encoding="utf-8"))
                chars = ad.get("characters", [])
                units += len(chars)
                zero += sum(
                    1 for c in chars
                    if (c.get("selected_end_sec", c.get("end_sec")) - c.get("selected_start_sec", c.get("start_sec"))) <= 0
                )
        result[model] = {
            "status_counts": dict(statuses),
            "warning_counts": dict(warnings),
            "units": units,
            "zero_duration_count": zero,
        }
    payload = {"schema_version": "quality_warnings_summary_v1", "batch_root": str(args.batch_root), "models": result}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
