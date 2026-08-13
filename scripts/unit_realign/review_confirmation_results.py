#!/usr/bin/env python3
"""Cluster-aware review of a frozen evaluator-only confirmation run."""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[round((len(values) - 1) * q)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--outcomes", required=True, type=Path)
    p.add_argument("--gt-manifest", required=True, type=Path, action="append")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--bootstrap-reps", type=int, default=2000)
    args = p.parse_args()
    split = {}
    for manifest in args.gt_manifest:
        for row in read_jsonl(manifest):
            split[row["song_id"]] = row.get("source_split")
    rows = [row for row in read_jsonl(args.outcomes) if split.get(row["song_id"]) == "test"]
    target = [row for row in rows if row["role"] == "target"]
    by_family = defaultdict(list)
    for row in target:
        if row["old_max_boundary_error_ms"] is not None and row["new_max_boundary_error_ms"] is not None:
            by_family[row["family"]].append(row)
    family_summary = {}
    for family, values in sorted(by_family.items()):
        delta = [row["delta_max_boundary_error_ms"] for row in values]
        family_summary[family] = {
            "n_evaluable_target_units": len(values),
            "old_mean_max_error_ms": sum(row["old_max_boundary_error_ms"] for row in values) / len(values),
            "new_mean_max_error_ms": sum(row["new_max_boundary_error_ms"] for row in values) / len(values),
            "mean_delta_ms": sum(delta) / len(delta),
            "improved": sum(x < 0 for x in delta), "unchanged": sum(x == 0 for x in delta), "regressed": sum(x > 0 for x in delta),
            "both_boundary_500ms": {
                "old": sum(row["old_max_boundary_error_le_500ms"] is True for row in values) / len(values),
                "new": sum(row["new_max_boundary_error_le_500ms"] is True for row in values) / len(values),
            },
        }
    index = {(r["song_id"], r["region_id"], r["canonical_unit_id"], r["family"]): r for r in target
             if r["new_max_boundary_error_ms"] is not None}
    comparisons = {}
    for left, right in (("R-S_sparse_fixed", "R-U_unit_local"), ("R-S_sparse_fixed", "R-A_unsafe_old_range")):
        pairs = [(song, l["new_max_boundary_error_ms"] - index[(song, region, cid, right)]["new_max_boundary_error_ms"])
                 for (song, region, cid, family), l in index.items() if family == left
                 and (song, region, cid, right) in index]
        by_song = defaultdict(list)
        for song, value in pairs:
            by_song[song].append(value)
        song_means = {song: sum(values) / len(values) for song, values in by_song.items()}
        rng = random.Random(20260813)
        songs = sorted(song_means)
        boots = []
        for _ in range(args.bootstrap_reps):
            sample = [song_means[rng.choice(songs)] for _ in songs]
            boots.append(sum(sample) / len(sample))
        values = [value for _, value in pairs]
        comparisons[f"{left}_minus_{right}"] = {
            "n_paired_target_units": len(values), "n_test_songs": len(songs),
            "mean_difference_ms": sum(values) / len(values),
            "song_cluster_bootstrap_ci95_ms": [percentile(boots, .025), percentile(boots, .975)],
            "left_better": sum(value < 0 for value in values), "tie": sum(value == 0 for value in values), "left_worse": sum(value > 0 for value in values),
        }
    sparse_context = [r for r in rows if r["family"] == "R-S_sparse_fixed" and r["role"] == "context"]
    context_evaluable = [r for r in sparse_context if r["delta_max_boundary_error_ms"] is not None]
    report = {
        "schema": "unit_realign_confirmation_review_v1", "scope": "frozen_test_split_evaluator_only",
        "guardrails": {"runtime_gt_access": False, "actual_writeback": 0, "unit_rows_not_independent": True},
        "test_coverage": {"outcome_rows": len(rows), "songs": len({r['song_id'] for r in rows}), "target_rows": len(target)},
        "family_target_metrics": family_summary, "paired_family_comparisons": comparisons,
        "sparse_context_invariant": {"n_context_rows": len(sparse_context), "n_evaluable": len(context_evaluable),
            "unchanged_max_error": sum(r["delta_max_boundary_error_ms"] == 0 for r in context_evaluable),
            "non_evaluable_baseline_geometry": len(sparse_context) - len(context_evaluable)},
        "review_conclusion": "Do not select a writeback family from mean error alone; use the paired test comparison and preserve R-S only for its verified context-protection property.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
