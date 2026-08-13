#!/usr/bin/env python3
"""Build P6 Oracle (R-O) requests from the frozen unit-realign region pool.

R-O is a direct-oracle diagnostic: the target's audio/text window is built
from GT (reference_*) times instead of detector times, so we can separate
"request construction is bad" from "the aligner itself is unstable on a
near-correct request".  R-O stays evaluation-only and never feeds no-GT
gates (request_families sets ``evaluation_only`` for family R-O).

Selection (30-50 regions):
  - every target_unit_id must hit BASELINE_GT;
  - stratum S1-S4 coverage;
  - outcome coverage across the P6 buckets (strong recovery / mixed / harm /
    Reject-Safe / catastrophic) using REGION_OUTCOMES per-(region, family)
    labels from the already-forwarded production families.

Oracle construction keeps the ORIGINAL identity_context (baseline_digest,
audio_sha256, model/checkpoint identity ...) so the cache identity differs
from the production families exactly through the GT-derived intervention
payload, not through an identity-key change.  Only the target units' times
are replaced by reference_* (=GT); non-target context units keep detector
times, and the request uses GT target span +/- margin as the audio window.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.request_families import UNIT_REQUEST_SCHEMA, build_family_request

SOURCE_RUN = "/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify"
DEFAULT_OUT_ROOT = "/home/hyan/Data/lyricalign/runs/unit_realign_r_o_oracle_20260813"


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    path.write_text(payload, encoding="utf-8")


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _primary_label(outcomes_by_family: dict[str, str]) -> str:
    """Collapse per-family outcomes into one P6 bucket for selection."""
    labels = set(outcomes_by_family.values())
    if "catastrophic_harmful" in labels:
        return "catastrophic"
    if "beneficial" in labels:
        return "recovery"
    if "mixed" in labels:
        return "mixed"
    if "harmful" in labels:
        return "harm"
    if labels and labels <= {"neutral"}:
        return "safe"
    return "neutral"


def _with_gt_targets(region: dict, gt: dict[tuple[str, int], dict]) -> dict | None:
    """Copy region with target units' start/end replaced by GT times."""
    targets = [int(x) for x in region.get("target_unit_ids") or ()]
    by_gt = {(str(region.get("song_id")), int(cid)): gt[(str(region.get("song_id")), int(cid))]
             for cid in targets if (str(region.get("song_id")), int(cid)) in gt}
    if len(by_gt) != len(set(targets)):
        return None
    units = []
    song_key = str(region.get("song_id"))
    for u in region.get("units") or ():
        cid = int(u["canonical_unit_id"])
        key = (song_key, cid)
        if key in by_gt:
            u = dict(u)
            u["start_sec"] = float(by_gt[key]["start_sec"])
            u["end_sec"] = float(by_gt[key]["end_sec"])
        units.append(u)
    out = dict(region)
    out["units"] = units
    return out


def build(target: int, out_root: str, source_run: str, margin_sec: float) -> dict:
    root = Path(out_root)
    source = Path(source_run)
    pool = _read_jsonl(source / "00_population" / "REGION_POOL.jsonl")
    region_outcomes = _read_jsonl(source / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")
    gt_rows = _read_jsonl(source / "06_evaluator_only" / "BASELINE_GT.jsonl")

    gt = {(str(r["song_id"]), int(r["canonical_unit_id"])): r for r in gt_rows}
    outcomes_by_region: dict[str, dict[str, str]] = {}
    for ro in region_outcomes:
        outcomes_by_region.setdefault(str(ro["region_id"]), {})[str(ro["family"])] = str(ro["outcome"])
    stratum_by_region = {str(ro["region_id"]): str(ro.get("stratum") or "unknown") for ro in region_outcomes}

    buckets = {"recovery": [], "mixed": [], "harm": [], "safe": [], "catastrophic": []}
    for region in pool:
        region_id = str(region.get("region_id") or "")
        targets = [int(x) for x in region.get("target_unit_ids") or ()]
        if not targets or any((str(region.get("song_id")), t) not in gt for t in targets):
            continue
        n_ids = len(region.get("units") or ())
        if not n_ids or len(targets) >= n_ids:
            continue
        outcomes = outcomes_by_region.get(region_id, {})
        if not outcomes:
            continue
        label = _primary_label(outcomes)
        if label in buckets:
            buckets[label].append((region, outcomes, stratum_by_region.get(region_id, "unknown")))
    # One region per outcome bucket; de-dup by region_id, prefer varied strata.
    for label, entries in buckets.items():
        seen = set()
        buckets[label] = [e for e in entries if not (e[0]["region_id"] in seen or seen.add(e[0]["region_id"]))]
        buckets[label].sort(key=lambda e: (e[2], e[0]["region_id"]))

    per_bucket = max(1, target // len(buckets))
    selected: list[dict] = []
    used: set[str] = set()
    for label, entries in buckets.items():
        for region, outcomes, stratum in entries:
            if len(selected) >= target:
                break
            region_id = str(region["region_id"])
            if region_id in used:
                continue
            if len([s for s in selected if s["stratum"] == stratum]) >= max(1, target // 4) + 1:
                continue
            selected.append({"region_id": region_id, "song_id": str(region.get("song_id")),
                             "stratum": stratum, "label": label,
                             "outcomes": outcomes, "region": region})
            used.add(region_id)
        if len(selected) >= target:
            break

    pool_rows, requests, forwards = [], [], []
    for row in selected:
        region = row["region"]
        oracle_region = _with_gt_targets(region, gt)
        if oracle_region is None:
            continue
        ctx = dict(region.get("identity_context") or {})
        try:
            req = build_family_request(
                family="R-O", oracle=True, song_id=str(region["song_id"]),
                region_id=str(region["region_id"]),
                audio_path=str(region.get("audio_path") or f"{region['song_id']}.wav"),
                units=oracle_region["units"], target_unit_ids=region["target_unit_ids"],
                identity_context=ctx, audio_margin_sec=margin_sec,
                left_anchor_id=region.get("left_anchor_id"),
                right_anchor_id=region.get("right_anchor_id"),
                left_accept_anchor_candidates=region.get("left_anchor_candidates"),
                right_accept_anchor_candidates=region.get("right_anchor_candidates"),
            )
        except Exception as exc:
            req = {"schema": UNIT_REQUEST_SCHEMA, "family": "R-O", "requested_family": "R-O",
                   "song_id": region["song_id"], "region_id": region["region_id"],
                   "status": "not_constructible", "reason": f"construction_failed:{type(exc).__name__}"}
        req["stratum"] = row["stratum"]
        req["stratum_status"] = "eligible"
        req["oracle_bucket"] = row["label"]
        req["gt_target_ids"] = [int(x) for x in region["target_unit_ids"]]
        requests.append(req)
        pool_rows.append(region)
        if req.get("status"):
            continue
        forwards.append({
            "schema": "unit_realign_forward_v1", "status": "queued",
            "request_identity": req.get("request_identity"),
            "request_id": req.get("request_id"),
            "region_id": req.get("region_id"), "song_id": req.get("song_id"),
            "family": "R-O", "stratum": row["stratum"],
            "forwarding": {"executor": "scripts/unit_realign/run_forward_real.py",
                           "evidence_dir": str(root / "02_forwards" / "evidence")},
        })

    _write_jsonl(root / "00_population" / "REGION_POOL.jsonl", pool_rows)
    _write_jsonl(root / "01_requests" / "REQUESTS_R_O.jsonl", requests)
    _write_jsonl(root / "02_forwards" / "FORWARDS.jsonl", forwards)

    summary = {
        "schema": "unit_realign_p6_r_o_construction_v1",
        "source_run": str(source),
        "n_regions": len(pool_rows),
        "n_requests": len(requests),
        "n_forwards": len(forwards),
        "buckets": {label: sum(1 for r in requests if r.get("oracle_bucket") == label) for label in buckets},
        "strata": {s: sum(1 for r in requests if r.get("stratum") == s) for s in ("S1", "S2", "S3", "S4")},
        "n_identity_none": sum(1 for r in requests if not r.get("request_identity")),
        "n_not_evaluation_only": sum(1 for r in requests if not r.get("evaluation_only")),
        "n_not_constructible": sum(1 for r in requests if r.get("status")),
        "outputs": {"pool": str(root / "00_population" / "REGION_POOL.jsonl"),
                    "requests": str(root / "01_requests" / "REQUESTS_R_O.jsonl"),
                    "forwards": str(root / "02_forwards" / "FORWARDS.jsonl")},
    }
    _write_json(root / "01_requests" / "R_O_CONSTRUCTION.json", summary)
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", type=int, default=40)
    p.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    p.add_argument("--source-run", default=SOURCE_RUN)
    p.add_argument("--margin-sec", type=float, default=0.5)
    args = p.parse_args(argv)
    summary = build(target=args.target, out_root=args.out_root,
                    source_run=args.source_run, margin_sec=args.margin_sec)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
