#!/usr/bin/env python3
"""Summarize collected v7 evidence with explicit denominators and taxonomy."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def automatic_taxonomy(request: dict, attempt: dict) -> list[str]:
    """Conservative geometry-only labels; absence means no automatic verdict."""
    rows = attempt.get("decoder_outputs", {}).get("official", {}).get("rows", [])
    if not rows:
        return ["UNRESOLVED"] if attempt.get("status") != "ok" else []
    labels = []
    durations = [float(row.get("fixed_global_end_sec", 0)) - float(row.get("fixed_global_start_sec", 0)) for row in rows]
    if sum(value <= .080001 for value in durations) / len(durations) >= .25:
        labels.append("ZERO_DURATION_CLUSTER")
    params = request.get("mutation_parameters", {}); n = params.get("baseline_unit_count")
    if request.get("mutation_type") == "extra" and n is not None:
        added = max(0, len(rows) - int(n)); position = params.get("position") or params.get("mutation_position")
        if added:
            segment = durations[-added:] if position == "tail" else durations[:added] if position == "head" else []
            if segment and sum(value <= .080001 for value in segment) / len(segment) >= .5:
                labels.append("TAIL_COLLAPSE" if position == "tail" else "HEAD_COLLAPSE")
    repair = attempt.get("decoder_outputs", {}).get("_repair_trace", {})
    if len(repair.get("boundary_moves", [])) / max(1, len(rows)) >= .30:
        labels.append("DECODER_REPAIR_DOMINATED")
    return labels


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    collection = json.loads(Path(args.collection).read_text(encoding="utf-8"))
    root = Path(collection["out_root"])
    rows = []
    for record in collection["records"]:
        payload = json.loads((root / record["source"]).read_text(encoding="utf-8"))
        attempt = payload["attempt"]
        request = attempt["request"]
        rows.append((request, attempt, automatic_taxonomy(request, attempt)))
    total = len(rows)
    by_mutation: dict[str, dict] = {}
    taxonomy = collections.Counter()
    automatic = collections.Counter()
    for request, attempt, labels in rows:
        key = request["mutation_type"]
        stat = by_mutation.setdefault(key, {"total_count": 0, "completed_count": 0, "success_count": 0, "failure_count": 0})
        stat["total_count"] += 1
        if attempt.get("status") not in {"timeout", "unresolved"}:
            stat["completed_count"] += 1
        if attempt.get("status") == "ok":
            stat["success_count"] += 1
        else:
            stat["failure_count"] += 1
        taxonomy.update(attempt.get("fa_taxonomy") or [])
        automatic.update(labels)
    for stat in by_mutation.values():
        stat["denominator"] = stat["total_count"]
        stat["rate"] = stat["success_count"] / stat["denominator"] if stat["denominator"] else None
    output = {
        "schema": "v7/alignment_behavior_analysis_v1",
        "total_count": total,
        "by_mutation": by_mutation,
        "failure_taxonomy": dict(sorted(taxonomy.items())),
        "automatic_failure_taxonomy": dict(sorted(automatic.items())),
        "note": "This is evidence/status aggregation; GT metrics and human verdicts remain separate inputs.",
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "total_count": total, "out": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
