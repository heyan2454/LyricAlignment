#!/usr/bin/env python3
"""P7 fixed-point analysis: candidate A (round-1) vs candidate B (round-2)
per-target displacement, consensus and per-region labels.

For every FP request in REQUESTS_FP.jsonl:
  candA = <orig-run>/02_forwards/evidence/<parent_request_id>.candidate.jsonl
  candB = <fp-run>/02_forwards/evidence/<request_id>.candidate.jsonl
displacement is measured on the target unit start_sec.

Labels (P7 semantics):
  stable        |A->B| < 200ms            -> likely at a stable fixed point
  drifted       200ms <= |A->B| < 2000ms  -> candidate unstable
  strong_reject |A->B| >= 2000ms          -> jump / strong-reject signal

Outputs 05_analysis/FIXED_POINT.json + FIXED_POINT_REPORT.md.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_candidate(evidence: Path, rid: str):
    path = evidence / f"{rid}.candidate.jsonl"
    if not path.is_file():
        return None
    out = {}
    for row in _read_jsonl(path):
        out[int(row["canonical_unit_id"])] = (float(row["start_sec"]), float(row["end_sec"]))
    return out


def _label(d: float) -> str:
    if d < 200.0:
        return "stable"
    if d < 2000.0:
        return "drifted"
    return "strong_reject"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--orig-run", default="/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify")
    p.add_argument("--out-root", default="/home/hyan/Data/lyricalign/runs/unit_realign_fixedpoint_20260813")
    args = p.parse_args(argv)

    orig, out = Path(args.orig_run), Path(args.out_root)
    requests = _read_jsonl(out / "01_requests" / "REQUESTS_FP.jsonl")
    orig_evidence = orig / "02_forwards" / "evidence"
    fp_evidence = out / "02_forwards" / "evidence"
    orig_outcomes = {r["request_id"]: r for r in _read_jsonl(orig / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl")}

    rows = []
    for req in requests:
        rid = str(req["request_id"])
        parent_rid = str(req["fp_parent_request_id"])
        targets = [int(x) for x in (req.get("active_target_unit_ids") or req.get("target_unit_ids") or ())]
        cand_a = _load_candidate(orig_evidence, parent_rid)
        cand_b = _load_candidate(fp_evidence, rid)
        if cand_a is None or cand_b is None:
            rows.append({"request_id": rid, "family": req.get("family"), "song_id": req.get("song_id"),
                         "region_id": req.get("fp_parent_region_id"), "status": "missing_evidence",
                         "has_cand_a": cand_a is not None, "has_cand_b": cand_b is not None})
            continue
        per_unit = []
        for t in targets:
            if t not in cand_a or t not in cand_b:
                per_unit.append({"canonical_unit_id": t, "status": "target_not_in_evidence"})
                continue
            a_start, a_end = cand_a[t]
            b_start, b_end = cand_b[t]
            per_unit.append({"canonical_unit_id": t, "a_start_sec": a_start, "a_end_sec": a_end,
                             "b_start_sec": b_start, "b_end_sec": b_end,
                             "displacement_ms": abs(b_start - a_start) * 1000.0,
                             "boundary_shift_ms": abs((b_end - a_end) - (b_start - a_start)) * 1000.0})
        disp = [u["displacement_ms"] for u in per_unit if "displacement_ms" in u]
        max_disp = max(disp) if disp else None
        parent_out = orig_outcomes.get(parent_rid) or {}
        rows.append({
            "request_id": rid, "family": req.get("family"), "song_id": req.get("song_id"),
            "region_id": req.get("fp_parent_region_id"), "n_target": len(targets),
            "max_displacement_ms": max_disp,
            "per_unit": per_unit,
            "label": _label(max_disp) if max_disp is not None else "unknown",
            "consensus": bool(disp) and all(d < 200.0 for d in disp),
            "detector_evidence": {"round1_outcome": parent_out.get("outcome"),
                                  "round1_unit_class_counts": parent_out.get("unit_class_counts"),
                                  "stratum": parent_out.get("stratum")},
        })

    ok = [r for r in rows if "max_displacement_ms" in r and r["max_displacement_ms"] is not None]
    all_disp = [r["max_displacement_ms"] for r in ok]
    label_counts = collections.Counter(r["label"] for r in rows)
    consensus_count = sum(1 for r in rows if r.get("consensus"))
    drifted_gt500 = sum(1 for r in ok if r["max_displacement_ms"] > 500.0)
    n_stable = label_counts.get("stable", 0)
    summary = {
        "schema": "unit_realign_fixedpoint_analysis_v1",
        "n_requests": len(requests), "n_analyzed": len(ok), "n_missing_evidence": len(rows) - len(ok),
        "n_target_units": sum(len(r.get("per_unit") or []) for r in ok),
        "displacement_stats_ms": {
            "mean": round(statistics.mean(all_disp), 3) if all_disp else None,
            "median": round(statistics.median(all_disp), 3) if all_disp else None,
            "max": round(max(all_disp), 3) if all_disp else None,
            "p90": round(sorted(all_disp)[int(len(all_disp) * 0.9) - 1], 3) if all_disp else None,
        },
        "a_approx_b_lt_200ms": {"n": n_stable, "ratio": round(n_stable / len(ok), 4) if ok else None},
        "drifted_gt_500ms": drifted_gt500,
        "label_counts": dict(label_counts),
        "consensus_count": consensus_count,
        "regions": rows,
    }
    analysis_dir = out / "05_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "FIXED_POINT.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# P7 Fixed-point / Iterative Stability Report",
        "",
        f"- run: `{out}`  (round-1 parent: `{orig}`)",
        f"- requests analyzed: {len(ok)} / {len(requests)} (missing evidence: {len(rows) - len(ok)})",
        f"- target units: {summary['n_target_units']}",
        "",
        "## A->B displacement (ms)",
        "",
        f"- mean: {summary['displacement_stats_ms']['mean']}  median: {summary['displacement_stats_ms']['median']}  "
        f"max: {summary['displacement_stats_ms']['max']}  p90: {summary['displacement_stats_ms']['p90']}",
        f"- A≈B (<200ms): {n_stable}  ratio {summary['a_approx_b_lt_200ms']['ratio']}",
        f"- drifted (>500ms): {drifted_gt500}",
        f"- labels: {summary['label_counts']}  consensus(A≈B all targets): {consensus_count}",
        "",
        "## Per-region interpretation",
        "",
        "| family | region_id | round1 outcome | max disp (ms) | label |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r.get('family')} | {r.get('region_id')} | "
                     f"{(r.get('detector_evidence') or {}).get('round1_outcome')} | "
                     f"{r.get('max_displacement_ms')} | {r.get('label')} |")
    lines.append("")
    lines.append("Labels: `stable` <200ms (fixed point); `drifted` 200-2000ms (unstable candidate); "
                 "`strong_reject` >=2000ms (jump/strong-reject).")
    lines.append("")
    (analysis_dir / "FIXED_POINT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
