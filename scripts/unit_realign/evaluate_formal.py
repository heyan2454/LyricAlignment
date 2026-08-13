#!/usr/bin/env python3
"""Evaluator-only GT metrics for a completed unit-level realign run.

GT is accepted only by this post-hoc process.  It is never written into a
request, gate feature, model input, or writeback path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from lyricalign.unit_realign.unit_outcome import BUCKETS_MS, pair_unit_outcomes


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gt(paths: list[Path]) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, str]]:
    result: dict[str, dict[int, dict[str, Any]]] = {}
    source_split: dict[str, str] = {}
    for path in paths:
        for record in read_jsonl(path):
            item_id = record.get("item_id") or record.get("song_id")
            units = record.get("canonical_units")
            if not isinstance(item_id, str) or not isinstance(units, list):
                continue
            indexed = {int(row["canonical_unit_id"]): row for row in units if "canonical_unit_id" in row}
            if item_id in result and result[item_id] != indexed:
                raise ValueError(f"conflicting frozen GT for item {item_id}")
            result[item_id] = indexed
            split = record.get("source_split")
            if isinstance(split, str):
                if item_id in source_split and source_split[item_id] != split:
                    raise ValueError(f"conflicting source split for item {item_id}")
                source_split[item_id] = split
    return result, source_split


def candidate_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    attempt = evidence["attempt"]
    request = attempt["request"]
    decoded = attempt.get("decoder_outputs", {}).get("official", {}).get("rows", [])
    canonical_ids = request.get("canonical_ids") or []
    out = []
    for decoded_index, row in enumerate(decoded):
        copied = dict(row)
        local_index = row.get("global_character_index")
        if not isinstance(local_index, int):
            copied["canonical_unit_id"] = None
            copied["prediction_local_index"] = decoded_index
        elif 0 <= local_index < len(canonical_ids):
            copied["canonical_unit_id"] = int(canonical_ids[local_index])
            copied["prediction_local_index"] = local_index
        else:
            copied["canonical_unit_id"] = None
            copied["prediction_local_index"] = local_index
        out.append(copied)
    return out


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [row for row in rows if row["pairing"] == "canonical"]
    old_values = [row["old_max_boundary_error_ms"] for row in paired if row["old_max_boundary_error_ms"] is not None]
    new_values = [row["new_max_boundary_error_ms"] for row in paired if row["new_max_boundary_error_ms"] is not None]
    onset_old = [row["old_onset_error_ms"] for row in paired if row["old_onset_error_ms"] is not None]
    onset_new = [row["new_onset_error_ms"] for row in paired if row["new_onset_error_ms"] is not None]
    offset_old = [row["old_offset_error_ms"] for row in paired if row["old_offset_error_ms"] is not None]
    offset_new = [row["new_offset_error_ms"] for row in paired if row["new_offset_error_ms"] is not None]
    deltas = [row["delta_max_boundary_error_ms"] for row in paired if row["delta_max_boundary_error_ms"] is not None]
    hit_rates = {}
    for threshold in BUCKETS_MS:
        old_key = f"old_max_boundary_error_le_{threshold}ms"
        new_key = f"new_max_boundary_error_le_{threshold}ms"
        old_hit = sum(row.get(old_key) is True for row in paired)
        new_hit = sum(row.get(new_key) is True for row in paired)
        denom = len(paired)
        hit_rates[str(threshold)] = {
            "old": old_hit / denom if denom else None,
            "new": new_hit / denom if denom else None,
            "delta_pp": (new_hit - old_hit) * 100.0 / denom if denom else None,
        }
    return {
        "n_rows": len(rows), "n_paired": len(paired),
        "old_missing": sum(row["old_missing"] for row in rows),
        "new_missing": sum(row["new_missing"] for row in rows),
        "extra_prediction": sum(row["extra_prediction"] for row in rows),
        "baseline_duplicate_prediction": sum(row["baseline_duplicate_prediction"] for row in rows),
        "candidate_duplicate_prediction": sum(row["candidate_duplicate_prediction"] for row in rows),
        "max_boundary_error_ms": {
            "old_mean": sum(old_values) / len(old_values) if old_values else None,
            "new_mean": sum(new_values) / len(new_values) if new_values else None,
            "old_median": median(old_values) if old_values else None,
            "new_median": median(new_values) if new_values else None,
            "mean_delta_new_minus_old": sum(deltas) / len(deltas) if deltas else None,
            "improved": sum(value < 0 for value in deltas),
            "unchanged": sum(value == 0 for value in deltas),
            "regressed": sum(value > 0 for value in deltas),
        },
        "onset_mae_ms": {"old": sum(onset_old) / len(onset_old) if onset_old else None, "new": sum(onset_new) / len(onset_new) if onset_new else None},
        "offset_mae_ms": {"old": sum(offset_old) / len(offset_old) if offset_old else None, "new": sum(offset_new) / len(offset_new) if offset_new else None},
        "both_boundary_hit_rate": hit_rates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--gt-manifest", required=True, type=Path, action="append")
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args()
    behavior = args.run_root / "02_behavior"
    requests = {row["request_id"]: row for row in read_jsonl(behavior / "REQUESTS.jsonl")}
    cases = {row["case_id"]: row for row in read_jsonl(behavior / "CASES.jsonl")}
    run_manifest = json.loads((behavior / "forward" / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    active_evidence_ids = {row["request_identity"] for row in run_manifest["requests_identity"]}
    if len(active_evidence_ids) != len(requests):
        raise ValueError("current run manifest does not cover frozen requests one-to-one")
    no_gt = read_jsonl(behavior / "NO_GT_CHECK.jsonl")
    if not all(row.get("validated") is True for row in no_gt):
        raise ValueError("refuse evaluator run: formal no-GT request audit did not pass")
    gt, source_split = load_gt(args.gt_manifest)
    outcomes: list[dict[str, Any]] = []
    missing_gt_items: set[str] = set()
    stale_evidence_count = 0
    for path in sorted((behavior / "forward/evidence").glob("*.json")):
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("content_identity") not in active_evidence_ids:
            stale_evidence_count += 1
            continue
        attempt = evidence.get("attempt", {})
        if attempt.get("status") != "ok":
            continue
        request_id = attempt.get("request", {}).get("request_id")
        request = requests.get(request_id)
        if request is None:
            raise ValueError(f"evidence request not in frozen request manifest: {request_id}")
        evidence_request = attempt["request"]
        for field in ("canonical_ids", "text_units", "audio_start_sec", "audio_end_sec",
                      "timestamp_slot_indices", "active_slot_indices", "fixed_slot_rows",
                      "slot_constraint_schema"):
            if evidence_request.get(field) != request.get(field):
                raise ValueError(f"current evidence/request mismatch for {request_id}: {field}")
        item_id = request["item_id"]
        if item_id not in gt:
            missing_gt_items.add(item_id)
            continue
        case = cases[request["provenance"]["episode_id"]]
        allowed = set(int(x) for x in request["canonical_ids"])
        baseline = [dict(row) for row in case["old_units"] if int(row["canonical_unit_id"]) in allowed]
        candidate = candidate_rows(evidence)
        gt_rows = {cid: row for cid, row in gt[item_id].items() if cid in allowed}
        outcomes.extend(pair_unit_outcomes(
            baseline_rows=baseline, candidate_rows=candidate, gt_by_canonical=gt_rows,
            song_id=item_id, region_id=request["provenance"]["episode_id"], request_id=request_id,
            family=request["input_variant"], target_unit_ids=request["provenance"]["target_unit_ids"],
        ))
    if missing_gt_items:
        raise ValueError(f"frozen GT absent for formal items: {sorted(missing_gt_items)}")
    by_family_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        by_family_role[f"{row['family']}::{row['role']}"] .append(row)
        by_split[source_split.get(row["song_id"], "unknown")].append(row)
    summary = {
        "schema": "unit_realign_formal_evaluator_only_v1",
        "mode": "post_hoc_evaluator_only",
        "runtime_gt_access": False,
        "actual_writeback": 0,
        "inputs": {
            "run_root": str(args.run_root),
            "gt_manifests": [{"path": str(path), "sha256": sha256(path)} for path in args.gt_manifest],
            "request_count": len(requests), "no_gt_request_audit": "pass",
            "active_evidence_count": len(active_evidence_ids),
            "ignored_stale_evidence_count": stale_evidence_count,
        },
        "outcome_rows": len(outcomes),
        "all": aggregate(outcomes),
        "by_source_split": {key: aggregate(value) for key, value in sorted(by_split.items())},
        "by_family_and_role": {key: aggregate(value) for key, value in sorted(by_family_role.items())},
        "coverage": {"families": dict(Counter(row["family"] for row in outcomes)), "songs": len({row["song_id"] for row in outcomes})},
    }
    args.out_root.mkdir(parents=True, exist_ok=True)
    (args.out_root / "UNIT_OUTCOMES.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in outcomes), encoding="utf-8")
    (args.out_root / "EVALUATOR_ONLY_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
