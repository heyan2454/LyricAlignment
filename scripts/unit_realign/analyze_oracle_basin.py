"""P6 Oracle Basin / request-sensitivity analysis for R-O run.

Compares oracle-timed (R-O) recovery against the same regions' production
(R-U/R-S) evidence from the mainline run, and reports oracle per-target error
vs GT along with sensitivity margins implied by audio/text span width.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ORACLE_RUN = Path("/home/hyan/Data/lyricalign/runs/unit_realign_r_o_oracle_20260813")
MAIN_RUN = Path("/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle-run", default=str(ORACLE_RUN))
    ap.add_argument("--main-run", default=str(MAIN_RUN))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    oracle_run = Path(args.oracle_run)
    main_run = Path(args.main_run)

    reqs = load_jsonl(oracle_run / "01_requests" / "REQUESTS_R_O.jsonl")
    ev_dir = oracle_run / "02_forwards" / "evidence"
    evidence_by_request: dict[str, list[dict]] = {}
    if ev_dir.is_dir():
        for p in sorted(ev_dir.glob("*.candidate.jsonl")):
            rid = p.name[: -len(".candidate.jsonl")]
            evidence_by_request.setdefault(rid, []).extend(load_jsonl(p))

    region_rows = load_jsonl(main_run / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")
    main_by_region = {r["region_id"]: r for r in region_rows}

    baseline_gt = load_jsonl(main_run / "06_evaluator_only" / "BASELINE_GT.jsonl")
    gt_by_key = {(str(g["song_id"]), str(g["canonical_unit_id"])): g for g in baseline_gt}

    per_target_err = []
    per_region: dict[str, dict] = {}
    for req in reqs:
        rid = req["region_id"]
        bucket = req.get("oracle_bucket", "unknown")
        main_row = main_by_region.get(rid)
        main_outcome = main_row["outcome"] if main_row else None
        main_stratum = main_row.get("stratum") if main_row else None
        gt_ids = req.get("gt_target_ids") or req.get("target_unit_ids") or ()
        targets = {}
        for row in evidence_by_request.get(req["request_id"], []):
            targets[str(row.get("canonical_unit_id"))] = row
        errors = []
        for cid in gt_ids:
            cid_s = str(cid)
            gt = gt_by_key.get((str(req["song_id"]), cid_s))
            cand = targets.get(cid_s)
            if not gt or not cand:
                continue
            gt_center = (gt["start_sec"] + gt["end_sec"]) / 2.0
            cand_center = (cand["start_sec"] + cand["end_sec"]) / 2.0
            errors.append((gt_center - cand_center) * 1000.0)
        if not errors:
            per_region[rid] = {
                "region_id": rid, "oracle_bucket": bucket, "n_targets": 0,
                "mean_err_ms": None, "max_err_ms": None, "recovered": False,
                "main_outcome": main_outcome, "main_stratum": main_stratum,
            }
            continue
        err = np.array(errors)
        per_target_err.extend(errors)
        per_region[rid] = {
            "region_id": rid, "oracle_bucket": bucket, "n_targets": len(err),
            "mean_err_ms": float(np.abs(err).mean()),
            "max_err_ms": float(np.abs(err).max()),
            "median_err_ms": float(np.median(np.abs(err))),
            "recovered": bool(float(np.max(np.abs(err))) <= 100.0),
            "main_outcome": main_outcome, "main_stratum": main_stratum,
        }

    errs = np.array(per_target_err)
    summary = {
        "schema": "unit_realign_oracle_basin_v1",
        "n_requests": len(reqs),
        "n_regions_analyzed": len(per_region),
        "n_target_units": len(errs),
        "abs_err_ms": {
            "mean": float(np.abs(errs).mean()),
            "median": float(np.median(np.abs(errs))),
            "p90": float(np.percentile(np.abs(errs), 90)),
            "max": float(np.abs(errs).max()),
        },
        "recovery_within_100ms_ratio": float((np.abs(errs) <= 100.0).mean()),
        "regions_recovered_ratio": float(
            sum(1 for v in per_region.values() if v["recovered"]) / len(per_region)),
        "by_bucket": {},
        "main_outcome_vs_oracle_recovered": {},
    }
    for bucket in sorted({v["oracle_bucket"] for v in per_region.values()}):
        bs = [v for v in per_region.values() if v["oracle_bucket"] == bucket]
        summary["by_bucket"][bucket] = {
            "n": len(bs),
            "recovered_ratio": float(sum(1 for v in bs if v["recovered"]) / len(bs)),
            "mean_abs_err_ms": float(np.mean([v["mean_err_ms"] for v in bs if v["mean_err_ms"] is not None])),
        }
    for oc in sorted({v["main_outcome"] for v in per_region.values() if v["main_outcome"]}):
        bs = [v for v in per_region.values() if v["main_outcome"] == oc]
        summary["main_outcome_vs_oracle_recovered"][oc] = {
            "n": len(bs),
            "oracle_recovered_ratio": float(sum(1 for v in bs if v["recovered"]) / len(bs)),
        }

    out_root = Path(args.out) if args.out else oracle_run / "05_analysis"
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "ORACLE_BASIN.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    (out_root / "ORACLE_BASIN_REGIONS.json").write_text(
        json.dumps(list(per_region.values()), ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
