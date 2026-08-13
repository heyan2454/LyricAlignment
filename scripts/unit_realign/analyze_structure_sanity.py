"""Structural sanity of realign on context units (P8 evidence).

Consumes evidence baseline/candidate rows only (no GT, no detector) and reports
per-request context stability: how far non-target units move under realign,
monotonicity/overlap integrity of the candidate timeline, and the split by
outcome (joined from 03_unit_outcomes region labels).  Output
STRUCTURE_SANITY.json + .md under 05_analysis.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8")] if path.exists() else []


def _t(row, k):
    v = row.get(k, row.get({"fixed_global_start_sec": "start_sec",
                            "fixed_global_end_sec": "end_sec"}.get(k)))
    return None if v is None else float(v)


def _mean(xs):
    return statistics.mean(xs) if xs else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main-run", required=True)
    args = ap.parse_args()
    run = Path(args.main_run)
    ev_dir = run / "02_forwards" / "evidence"
    out = run / "05_analysis"
    out.mkdir(parents=True, exist_ok=True)

    requests = [r for r in _load_jsonl(run / "01_requests" / "REQUESTS.jsonl")
                if r.get("status") is None and r.get("request_id")]
    labels = {r["request_id"]: r for r in _load_jsonl(run / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")}

    per: dict = defaultdict(list)
    per_displacement: dict[str, list[float]] = defaultdict(list)
    n_mono = n_overlap = n_context = 0
    for req in requests:
        rid = req["request_id"]
        base = {int(r["canonical_unit_id"]): r for r in _load_jsonl(ev_dir / f"{rid}.baseline.jsonl")}
        cand = {int(r["canonical_unit_id"]): r for r in _load_jsonl(ev_dir / f"{rid}.candidate.jsonl")}
        if not cand:
            continue
        targets = {int(x) for x in (req.get("target_unit_ids") or [])}
        outcome = (labels.get(rid) or {}).get("outcome") or "unknown"

        # context-only displacement
        for cid, b in base.items():
            if cid in targets:
                continue
            c = cand.get(cid)
            if not c:
                continue
            os_, oe_, ns, ne = _t(b, "fixed_global_start_sec"), _t(b, "fixed_global_end_sec"), _t(c, "fixed_global_start_sec"), _t(c, "fixed_global_end_sec")
            if None in (os_, oe_, ns, ne):
                continue
            d = (abs(ns - os_) + abs(ne - oe_)) * 500.0
            n_context += 1
            per_displacement[outcome].append(d)
            per[rid].append((cid, d))

        # monotonicity + overlap on candidate timeline (sorted by start)
        order = sorted(cand.items(), key=lambda kv: _t(kv[1], "fixed_global_start_sec") or 0.0)
        prev_end = None
        mono_ok = True
        for i in range(len(order) - 1):
            a_end = _t(order[i][1], "fixed_global_end_sec")
            b_start = _t(order[i + 1][1], "fixed_global_start_sec")
            if a_end is not None and b_start is not None:
                if b_start < a_end:
                    n_overlap += 1
                if b_start < (_t(order[i][1], "fixed_global_start_sec") or 0.0):
                    mono_ok = False
        if not mono_ok:
            n_mono += 1

    rows = []
    for rid, vals in per.items():
        ds = [d for _, d in vals]
        rows.append({"request_id": rid, "outcome": (labels.get(rid) or {}).get("outcome"),
                     "n_context_units": len(vals),
                     "context_mean_displacement_ms": round(_mean(ds), 3) if ds else None,
                     "context_max_displacement_ms": round(max(ds), 3) if ds else None,
                     "n_protected_lt10ms": sum(1 for d in ds if d <= 10.0),
                     "n_within60ms": sum(1 for d in ds if d <= 60.0)})

    by_outcome: dict[str, dict] = {}
    for o, v in per_displacement.items():
        req_ids = {rid for rid, vals in per.items()
                   if (labels.get(rid) or {}).get("outcome") == o}
        by_outcome[o] = {
            "n_requests": len(req_ids),
            "n_context_units": len(v),
            "context_mean_displacement_ms": round(_mean(v), 3),
            "frac_within60ms": round(sum(1 for d in v if d <= 60.0) / len(v), 4) if v else None,
            "frac_protected_lt10ms": round(sum(1 for d in v if d <= 10.0) / len(v), 4) if v else None,
            "p95_displacement_ms": round(sorted(v)[int(0.95 * len(v))], 3) if v else None,
        }

    summary = {
        "schema": "unit_realign_structure_sanity_v1",
        "n_requests": len(requests), "n_requests_with_candidate": len(rows),
        "n_context_units": n_context,
        "monotonicity": {
            "n_requests_non_monotonic_candidate": n_mono,
            "frac_non_monotonic": round(n_mono / max(1, len(rows)), 4),
            "n_overlapping_adjacent_pairs": n_overlap,
        },
        "per_outcome": by_outcome,
    }

    (out / "STRUCTURE_SANITY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    lines = ["# Structure sanity (P8 evidence)", "",
             f"- n_requests (with candidate): {len(rows)} / {len(requests)}",
             f"- n_context units measured: {n_context}",
             f"- non-monotonic candidate requests: {n_mono}",
             f"- overlapping adjacent candidate pairs: {n_overlap}", "",
             "## Per outcome context displacement", "", "| outcome | n_req | mean_ms | p95_ms | <=60ms | <=10ms |"]
    for o, s in summary["per_outcome"].items():
        lines.append(f"| {o} | {s['n_requests']} | {s['context_mean_displacement_ms']} | {s['p95_displacement_ms']} | {s['frac_within60ms']} | {s['frac_protected_lt10ms']} |")
    (out / "STRUCTURE_SANITY.md").write_text("\n".join(lines))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
