"""P5: extract no-GT per-unit features for shadow-only realign gating.

Consumes the mainline run's executed requests + baseline/candidate evidence
(plus detector rows if/when a producer lands) and emits one row per target unit
matching schema unit_realign_no_gt_features_v1. Detector-backed keys stay None
until a p_bad producer exists (see UNIT_GATE_FEATURES_AUDIT.md).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lyricalign.unit_realign.unit_gate_features import (
    build_unit_features,
    assert_no_gt_feature_row,
)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8")] if path.exists() else []


def _alias_times(rows: list[dict]) -> list[dict]:
    """evidence rows carry start_sec/end_sec; build_unit_features reads
    fixed_global_start_sec/fixed_global_end_sec."""
    out = []
    for r in rows:
        r = dict(r)
        if "start_sec" in r and "fixed_global_start_sec" not in r:
            r["fixed_global_start_sec"] = r["start_sec"]
            r["fixed_global_end_sec"] = r["end_sec"]
        out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-run", required=True)
    ap.add_argument("--detector-rows", default=None,
                    help="detector_rows.jsonl (schema unit_realign_detector_row_v1) from "
                         "emit_detector_rows.py; default <main-run>/02_forwards/detector_rows.jsonl "
                         "if present")
    ap.add_argument("--out", default=None,
                    help="output jsonl; default <main-run>/05_analysis/UNIT_GATE_FEATURES.jsonl")
    args = ap.parse_args()

    run = Path(args.main_run)
    ev_dir = run / "02_forwards" / "evidence"
    out_path = Path(args.out) if args.out else run / "05_analysis" / "UNIT_GATE_FEATURES.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    requests = [r for r in load_jsonl(run / "01_requests" / "REQUESTS.jsonl")
                if r.get("status") is None and r.get("request_id")]
    region_by_key = {f"{r['region_id']}:{r['family']}": r
                     for r in load_jsonl(run / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")}

    detector_path = (Path(args.detector_rows) if args.detector_rows
                     else run / "02_forwards" / "detector_rows.jsonl")
    detector_by_request: dict[str, dict[int, dict]] = {}
    if detector_path.exists():
        for row in load_jsonl(detector_path):
            detector_by_request.setdefault(str(row.get("request_id")), {})[
                int(row["unit_id"])] = row
    else:
        print(f"note: no detector rows at {detector_path}; detector keys stay null")

    rows: list[dict] = []
    labels: list[dict] = []
    missing_evidence = 0
    for req in requests:
        rid = req["request_id"]
        base_f = ev_dir / f"{rid}.baseline.jsonl"
        cand_f = ev_dir / f"{rid}.candidate.jsonl"
        if not cand_f.exists():
            missing_evidence += 1
            continue
        baseline = _alias_times(load_jsonl(base_f))
        candidate = _alias_times(load_jsonl(cand_f))
        targets = [int(x) for x in (req.get("target_unit_ids") or [])]
        if not targets:
            continue
        drow = detector_by_request.get(rid, {})
        detector_before = {cid: {"p_bad": v.get("p_bad_before")}
                           for cid, v in drow.items()}
        detector_after = {cid: {"p_bad": v.get("p_bad_after")}
                          for cid, v in drow.items()}
        built = build_unit_features(
            baseline_rows=baseline, candidate_rows=candidate,
            detector_before=detector_before, detector_after=detector_after,
            song_id=req.get("song_id", ""), region_id=req["region_id"],
            request_id=rid, family=req.get("family", ""),
            target_unit_ids=targets, request_identity=req.get("request_identity"),
        )
        reg = region_by_key.get(f"{req['region_id']}:{req.get('family')}")
        for row in built:
            if row.get("role") != "target":
                continue
            assert_no_gt_feature_row(row)
            rows.append(row)
        if reg and targets:
            labels.append({"request_id": rid, "region_id": req["region_id"],
                           "family": req.get("family"),
                           "outcome": reg.get("outcome"), "stratum": reg.get("stratum")})

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    label_path = out_path.with_name("UNIT_GATE_FEATURE_REGION_LABELS.jsonl")
    with label_path.open("w", encoding="utf-8") as fh:
        for row in labels:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    present = {k for row in rows for k in row}
    allowed = {
        "schema", "song_id", "region_id", "request_id", "request_identity", "family",
        "canonical_unit_id", "role", "baseline_present", "candidate_present", "candidate_missing",
        "mean_boundary_displacement_ms", "signed_start_displacement_ms", "signed_end_displacement_ms",
        "detector_p_bad_before", "detector_p_bad_after", "signed_detector_delta", "context_protected",
        "duration_sec", "decoder_confidence", "state_before", "state_after", "monotonicity_violation",
        "inversion_count", "overlap_sec", "compression_ratio", "slot_violation",
        "safe_context_changed_count", "raw_official_disagreement_ms", "local_consistency",
    }
    missing = sorted(allowed - present)
    print(json.dumps({
        "n_requests": len(requests),
        "n_missing_evidence": missing_evidence,
        "n_target_feature_rows": len(rows),
        "feature_keys_present": sorted(present),
        "feature_keys_missing": missing,
        "detector_keys_present": sorted(present
                                        & {"detector_p_bad_before", "detector_p_bad_after",
                                           "signed_detector_delta", "state_before", "state_after"}),
        "n_region_labels": len(labels),
        "out": str(out_path),
        "labels": str(label_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
