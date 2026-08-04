#!/usr/bin/env python3
"""Derive threshold, geometry, posterior and repair diagnostics from frozen GT evidence."""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


THRESHOLDS = (0.25, 0.5, 1.0, 2.0, 5.0)


def gt_index(request: dict, index: int) -> int | None:
    p = request.get("mutation_parameters", {}); n = int(p.get("baseline_unit_count") or len(request["text_units"]))
    kind = request["mutation_type"]; pos = p.get("position") or p.get("mutation_position") or "whole"
    if kind in {"baseline", "replace"}: return index if index < n else None
    if kind == "extra":
        added = int(p.get("actual_added_units") or max(0, len(request["text_units"]) - n))
        if pos == "tail": return index if index < n else None
        if pos == "head": return index - added if added <= index < added + n else None
        pivot = n // 2
        return index if index < pivot else (index - added if index >= pivot + added and index - added < n else None)
    if kind == "missing":
        removed = int(p.get("actual_removed_units") or max(0, n - len(request["text_units"])))
        if pos == "tail": return index
        if pos == "head": return index + removed
        if pos == "middle":
            pivot = (n - removed) // 2; return index if index < pivot else index + removed
        if pos == "dispersed":
            kept = [i for i in range(n) if i not in set(random.Random(int(p.get("selection_seed") or 0)).sample(range(n), removed))]
            return kept[index] if index < len(kept) else None
    return None


def mean(values: list[float]) -> float | None: return sum(values) / len(values) if values else None


def summarize(rows: list[dict]) -> dict:
    boundary = [value for row in rows for value in row["boundary_errors"]]
    duration = [value for row in rows for value in row["durations"]]
    gaps = [value for row in rows for value in row["gaps"]]
    overlaps = [value for row in rows for value in row["overlaps"]]
    entropy = [value for row in rows for value in row["entropy"]]
    repair = [value for row in rows for value in row["repair_ratios"]]
    return {"attempt_count": len(rows), "matched_boundary_count": len(boundary),
            "boundary_within_threshold_rate": {str(t): sum(e <= t for e in boundary) / len(boundary) if boundary else None for t in THRESHOLDS},
            "mean_boundary_abs_error_sec": mean(boundary), "zero_or_near_zero_duration_rate": sum(x <= .080001 for x in duration) / len(duration) if duration else None,
            "mean_positive_gap_sec": mean(gaps), "mean_overlap_sec": mean(overlaps),
            "mean_posterior_entropy": mean(entropy), "mean_repair_boundary_ratio": mean(repair)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--collection", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args(argv); collection = json.loads(Path(args.collection).read_text(encoding="utf-8")); root = Path(collection["out_root"])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in collection["records"]:
        payload = json.loads((root / record["source"]).read_text(encoding="utf-8")); attempt, request = payload["attempt"], payload["attempt"]["request"]
        if attempt.get("status") != "ok" or request["mutation_type"] == "no_match": continue
        try: gt = [json.loads(line) for line in Path(request["text_source"]).read_text(encoding="utf-8").splitlines() if line]
        except (OSError, json.JSONDecodeError): continue
        official = attempt["decoder_outputs"].get("official", {}).get("rows", []); boundary = []
        for row in official:
            i = int(row["global_character_index"]); j = gt_index(request, i)
            if j is not None and j < len(gt) and i < len(request["text_units"]) and request["text_units"][i] == gt[j]["normalized_character"]:
                boundary += [abs(float(row["fixed_global_start_sec"]) - float(gt[j]["start_sec"])), abs(float(row["fixed_global_end_sec"]) - float(gt[j]["end_sec"]))]
        ordered = sorted(official, key=lambda row: int(row["global_character_index"])); ends = [float(row["fixed_global_end_sec"]) for row in ordered]; starts = [float(row["fixed_global_start_sec"]) for row in ordered]
        deltas = [starts[i] - ends[i - 1] for i in range(1, len(starts))]
        entropy = [float(row[key]) for row in attempt["decoder_outputs"].get("raw", {}).get("rows", []) for key in ("raw_start_entropy", "raw_end_entropy") if row.get(key) is not None]
        trace = attempt["decoder_outputs"].get("_repair_trace", {}); repair = len(trace.get("boundary_moves", [])) / max(1, len(official))
        key = request["mutation_type"]
        grouped[key].append({"boundary_errors": boundary, "durations": [end - start for start, end in zip(starts, ends)],
                             "gaps": [d for d in deltas if d > 0], "overlaps": [-d for d in deltas if d < 0], "entropy": entropy, "repair_ratios": [repair]})
    output = {"schema": "research_v7/gt_evidence_diagnostics_v1", "by_mutation": {key: summarize(value) for key, value in sorted(grouped.items())},
              "note": "Thresholds are per boundary among exact text/GT matches. Geometry/posterior/repair are evidence-derived; no human taxonomy is inferred."}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "groups": len(grouped), "out": args.out}, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
