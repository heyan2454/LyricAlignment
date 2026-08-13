#!/usr/bin/env python3
"""Compare two realign context-padding runs using only no-GT evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sparse_rows(run_root: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for evidence_path in sorted((run_root / "02_behavior/forward/evidence").glob("*.json")):
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        attempt = evidence["attempt"]
        request = attempt["request"]
        if request.get("input_variant") != "R-S_sparse_fixed":
            continue
        constraint = attempt.get("decoder_outputs", {}).get("_sparse_constraint", {})
        canonical_ids = request.get("canonical_ids") or []
        active_indices = request.get("active_slot_indices") or []
        rows[request["request_id"]] = {
            "request_id": request["request_id"],
            "status": attempt.get("status"),
            "runtime_sec": attempt.get("runtime_sec"),
            "text_units": len(request["text_units"]),
            "active_units": len(request.get("active_slot_indices") or []),
            "fixed_units": len(request.get("fixed_slot_rows") or []),
            "active_indices": active_indices,
            "active_canonical_ids": [canonical_ids[index] for index in active_indices],
            "remerge_status": constraint.get("remerge_status"),
        }
    return rows


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--short-run", required=True, type=Path)
    parser.add_argument("--long-run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    short, long = sparse_rows(args.short_run), sparse_rows(args.long_run)
    paired_ids = sorted(set(short) & set(long))
    pairs = [{"request_id": key, "short": short[key], "long": long[key]} for key in paired_ids]
    violations = []
    for pair in pairs:
        a, b = pair["short"], pair["long"]
        if a["status"] != "ok" or b["status"] != "ok":
            violations.append({"request_id": pair["request_id"], "kind": "forward_status"})
        if a["active_canonical_ids"] != b["active_canonical_ids"] or a["active_units"] != b["active_units"]:
            violations.append({"request_id": pair["request_id"], "kind": "target_changed"})
        if a["remerge_status"] != "exact_baseline_rows_restored" or b["remerge_status"] != "exact_baseline_rows_restored":
            violations.append({"request_id": pair["request_id"], "kind": "fixed_remerge"})
        if b["fixed_units"] < a["fixed_units"]:
            violations.append({"request_id": pair["request_id"], "kind": "context_shrank"})

    report = {
        "schema": "unit_realign_context_padding_comparison_v1",
        "scope": "no_gt_structural_screen_only",
        "short_run": str(args.short_run),
        "long_run": str(args.long_run),
        "sparse_requests": {"short": len(short), "long": len(long), "paired": len(pairs)},
        "metrics": {
            "mean_fixed_units": {"short": mean([x["short"]["fixed_units"] for x in pairs]), "long": mean([x["long"]["fixed_units"] for x in pairs])},
            "mean_active_to_text_ratio": {
                "short": mean([x["short"]["active_units"] / x["short"]["text_units"] for x in pairs]),
                "long": mean([x["long"]["active_units"] / x["long"]["text_units"] for x in pairs]),
            },
            "mean_runtime_sec": {"short": mean([x["short"]["runtime_sec"] for x in pairs]), "long": mean([x["long"]["runtime_sec"] for x in pairs])},
        },
        "violations": violations,
        "status": "pass" if not violations and pairs else "fail",
        "interpretation": "Longer context is feasible only if target slots are unchanged and sparse fixed rows are exactly restored; this screen makes no accuracy claim.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
