#!/usr/bin/env python3
"""Emit explicit requested/applicable coverage counts for a frozen behavior manifest."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args(argv); rows = [json.loads(line) for line in Path(args.manifest).read_text(encoding="utf-8").splitlines() if line]
    def count(keys):
        values = collections.Counter(tuple(row.get(key) for key in keys) for row in rows)
        return [{key: value for key, value in zip(keys, group)} | {"count": n} for group, n in sorted(values.items(), key=str)]
    output = {"schema": "v7/behavior_manifest_coverage_v1", "total_count": len(rows), "item_count": len({row["item_id"] for row in rows}),
              "by_mutation": count(("mutation_type",)), "by_mutation_position": count(("mutation_type", "mutation_position")),
              "by_relation": count(("mutation_type", "text_relation", "audio_relation")),
              "note": "Absent combinations are not inferred as zero-effect; inspect this coverage before claims."}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "total_count": len(rows), "out": args.out}, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
