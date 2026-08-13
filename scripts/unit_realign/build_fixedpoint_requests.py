#!/usr/bin/env python3
"""P7 fixed-point requests builder.

Round-2 unit-realign requests: original -> candidate A -> same family local
request built on candidate A's target times -> candidate B.

Selection: 15-25 ambiguous/high-value regions from the round-1
REGION_OUTCOMES.jsonl, balanced across R-A/R-U/R-B (outcome in
{harmful, mixed, beneficial}) with R-S covered by catastrophic_harmful
fallback (R-S has no harmful/mixed/beneficial rows).

For each selected region the round-1 candidate A evidence
(02_forwards/evidence/<request_id>.candidate.jsonl) is written back into the
REGION_POOL units (target canonical_unit_id -> start_sec/end_sec); the same
family request is rebuilt with those units as the new baseline
(baseline_digest recomputed over the rewritten units).  request_id gets a
``:FP`` suffix and region_id a ``_FP`` suffix so nothing collides with the
round-1 run.

Outputs a self-contained run at <out-root>:
  00_population/REGION_POOL.jsonl  (subset, rewritten target times)
  01_requests/REQUESTS_FP.jsonl
  02_forwards/FORWARDS.jsonl       (queued rows driving run_forward_real.py)
  CONSTRUCTION_CHECK.json          (smoke verification, CPU)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.request_families import build_family_request  # noqa: E402

ORIG_RUN = Path("/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify")
FAMILY_QUOTA = {"R-A": 6, "R-U": 6, "R-S": 4, "R-B": 8}
OUTCOME_PRIORITY = ("beneficial", "mixed", "harmful", "catastrophic_harmful")
TARGET_OUTCOMES = ("harmful", "mixed", "beneficial")


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                    encoding="utf-8")


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _baseline_digest(units) -> str:
    rows = sorted(({"canonical_unit_id": int(u["canonical_unit_id"]),
                    "start_sec": float(u["start_sec"]), "end_sec": float(u["end_sec"])}
                   for u in units), key=lambda r: int(r["canonical_unit_id"]))
    raw = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _select(outcomes: list[dict]) -> list[dict]:
    """Deterministic family-balanced selection; R-S uses catastrophic_harmful."""
    by_fam: dict[str, list[dict]] = collections.defaultdict(list)
    for row in outcomes:
        if row["outcome"] in OUTCOME_PRIORITY:
            by_fam[row["family"]].append(row)

    chosen: list[dict] = []
    for fam, quota in FAMILY_QUOTA.items():
        rows = by_fam.get(fam, [])
        if fam == "R-S":
            rows = [r for r in rows if r["outcome"] == "catastrophic_harmful"]
            counts = [r.get("unit_class_counts") or {} for r in rows]
            rows = [r for r, c in zip(rows, counts) if c.get("unchanged_finite", 0) > 0]
            rows.sort(key=lambda r: (sum(v for k, v in (r.get("unit_class_counts") or {}).items()
                                         if k.startswith("degraded")),
                                     int(r.get("n_context") or 0), str(r["request_id"])))
        else:
            rows = [r for r in rows if r["outcome"] in TARGET_OUTCOMES]
            rows.sort(key=lambda r: str(r["request_id"]))
            bucket = collections.defaultdict(list)
            for r in rows:
                bucket[r["outcome"]].append(r)
            picked, idx = [], 0
            while len(picked) < quota:
                advanced = False
                for oc in ("beneficial", "mixed", "harmful"):
                    if idx < len(bucket[oc]):
                        picked.append(bucket[oc][idx])
                        advanced = True
                        if len(picked) >= quota:
                            break
                if not advanced:
                    break
                idx += 1
            rows = picked
        chosen.extend(rows[:quota])
    return chosen


def _rewrite_region(pool_region: dict, cand_rows: list[dict]) -> tuple[dict, dict]:
    """Write candidate A target times back into units; return (new_region, audit)."""
    cand = {int(r["canonical_unit_id"]): r for r in cand_rows}
    targets = [int(x) for x in pool_region.get("target_unit_ids") or ()]
    units = [dict(u) for u in pool_region.get("units") or ()]
    written = []
    for u in units:
        cid = int(u["canonical_unit_id"])
        if cid in targets and cid in cand:
            u["start_sec"] = float(cand[cid]["start_sec"])
            u["end_sec"] = float(cand[cid]["end_sec"])
            written.append(cid)
    new_region = dict(pool_region)
    new_region["units"] = units
    new_region["region_id"] = f"{pool_region['region_id']}_FP"
    ctx = dict(pool_region.get("identity_context") or {})
    ctx["baseline_digest"] = _baseline_digest(units)
    new_region["identity_context"] = ctx
    return new_region, {"targets": targets, "written_target_ids": written}


def _build_request(region: dict, family: str, song_id: str, orig_region_id: str) -> dict:
    targets = [int(x) for x in region.get("target_unit_ids") or ()]
    ctx = dict(region.get("identity_context") or {})
    kwargs = dict(family=family, song_id=song_id, region_id=str(region["region_id"]),
                  audio_path=str(region.get("audio_path") or f"{song_id}.wav"),
                  units=region["units"], target_unit_ids=targets, identity_context=ctx)
    if family == "R-B":
        lefts = sorted(int(c) for c in (region.get("left_anchor_candidates") or ())
                       if targets and int(c) < min(targets))
        rights = sorted(int(c) for c in (region.get("right_anchor_candidates") or ())
                        if targets and int(c) > max(targets))
        kwargs.update(left_anchor_id=lefts[-1] if lefts else None,
                      right_anchor_id=rights[0] if rights else None,
                      left_accept_anchor_candidates=region.get("left_anchor_candidates"),
                      right_accept_anchor_candidates=region.get("right_anchor_candidates"))
    req = build_family_request(**kwargs)
    req["request_id"] = f"{song_id}:{orig_region_id}:{family}:FP"
    req["fp_round"] = 2
    req["fp_parent_request_id"] = f"{song_id}:{orig_region_id}:{family}"
    req["fp_parent_region_id"] = orig_region_id
    req["stratum"] = region.get("stratum")
    req["stratum_status"] = region.get("stratum_status")
    return req


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--orig-run", default=str(ORIG_RUN))
    p.add_argument("--out-root", default="/home/hyan/Data/lyricalign/runs/unit_realign_fixedpoint_20260813")
    p.add_argument("--total", type=int, default=24)
    p.add_argument("--quota", default="R-A:6,R-U:6,R-S:4,R-B:8")
    args = p.parse_args(argv)

    orig = Path(args.orig_run)
    out = Path(args.out_root)
    quota = dict(item.split(":") for item in args.quota.split(","))
    quota = {k: int(v) for k, v in quota.items()}

    outcomes = _read_jsonl(orig / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")
    pool = _read_jsonl(orig / "00_population" / "REGION_POOL.jsonl")
    pool_by_key = {(str(r.get("song_id") or ""), str(r.get("region_id") or "")): r for r in pool}
    evidence = orig / "02_forwards" / "evidence"

    selected = _select(outcomes)
    if len(selected) > args.total:
        selected = selected[: args.total]
    if not 15 <= len(selected) <= 25:
        p.error(f"selected {len(selected)} not in [15, 25]")

    pool_rows, requests, forwards, checks = [], [], [], []
    for outcome_row in selected:
        song_id, region_id, family = (str(outcome_row.get("song_id") or ""),
                                      str(outcome_row.get("region_id") or ""),
                                      str(outcome_row.get("family") or ""))
        key = (song_id, region_id)
        pool_region = pool_by_key.get(key)
        if pool_region is None:
            checks.append({"region_id": region_id, "status": "failed", "reason": "region_not_in_pool"})
            continue
        parent_rid = f"{song_id}:{region_id}:{family}"
        cand_path = evidence / f"{parent_rid}.candidate.jsonl"
        if not cand_path.is_file():
            checks.append({"region_id": region_id, "status": "failed", "reason": f"missing_evidence:{parent_rid}"})
            continue
        cand_rows = _read_jsonl(cand_path)
        new_region, audit = _rewrite_region(pool_region, cand_rows)
        req = _build_request(new_region, family, song_id, region_id)
        fp_rid = req.get("request_id")
        pool_rows.append(new_region)
        requests.append(req)
        forwards.append({"schema": "unit_realign_forward_v1", "request_id": fp_rid, "song_id": song_id,
                         "region_id": region_id, "family": family, "stratum": outcome_row.get("stratum"),
                         "status": "queued"})
        targets = [int(x) for x in new_region.get("target_unit_ids") or ()]
        ids = [int(u["canonical_unit_id"]) for u in new_region["units"]]
        cand = {int(r["canonical_unit_id"]): r for r in cand_rows}
        t_match = all(abs(float(cand[t]["start_sec"]) - float(next(u["start_sec"] for u in new_region["units"]
                                                                  if int(u["canonical_unit_id"]) == t))) < 1e-6
                      for t in targets if t in cand)
        checks.append({
            "request_id": fp_rid, "parent_request_id": parent_rid, "song_id": song_id,
            "region_id": region_id, "family": family,
            "outcome": outcome_row.get("outcome"),
            "n_target": len(targets), "n_ids": len(ids), "target_ids": targets,
            "written_target_ids": audit["written_target_ids"],
            "request_identity_set": bool(req.get("request_identity")),
            "target_time_written": t_match,
            "not_whole_item_pseudo_local": (req.get("family") == family
                                            and not req.get("null_intervention", False)
                                            and len(targets) < len(ids)),
            "status": "ok" if (req.get("request_identity") and t_match
                               and req.get("family") == family and len(targets) < len(ids)
                               and not req.get("null_intervention", False)) else "invalid",
        })

    _write_jsonl(out / "00_population" / "REGION_POOL.jsonl", pool_rows)
    _write_jsonl(out / "01_requests" / "REQUESTS_FP.jsonl", requests)
    _write_jsonl(out / "02_forwards" / "FORWARDS.jsonl", forwards)
    summary = {
        "schema": "unit_realign_fixedpoint_construction_v1",
        "n_selected": len(selected), "n_built": len(requests), "n_valid": sum(c["status"] == "ok" for c in checks),
        "family_counts": dict(collections.Counter(r.get("family") for r in requests)),
        "outcome_counts": dict(collections.Counter(r.get("outcome") for r in selected)),
        "checks": checks,
    }
    _write_json(out / "CONSTRUCTION_CHECK.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["n_built"] == summary["n_valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
