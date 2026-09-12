#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command self-check for a batch of alignment artifacts (no ground truth, no GPU).

Answers three questions about a batch, each with an explicit verdict:

1. **Attributable?** does every song record audio sha / request hash / schema / planning flags;
2. **Structurally legal?** zero-length, overlap, start regression, implausible duration — measured per
   pipeline stage, so a regression is attributed to the stage that created it (round-13 lesson);
3. **Would a legal repair change the answer a lot?** the joint constrained solve is applied as a checker.

    PYTHONPATH=src python scripts/evaluation/audit_batch.py --batch <dir> [--compare-batch <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import evidence_identity_audit as EIA
from lyricalign.analysis import structural_compliance as SC

GATES = {
    "illegal_share_max": 0.05,          # delivery gate: >5% illegal units -> do not ship
    "stage_net_addition_max": 0.01,     # any stage creating >1% net degeneracy -> block + localise
    "pinned_anchor_share_max": 0.02,    # blocks pinned to a window anchor -> mapping defect
}


def audit(batch: Path) -> dict[str, object]:
    df, meta = SC.load_batch(batch)
    out: dict[str, object] = {"batch": str(batch), "present": bool(meta.get("songs")),
                              "songs": int(meta.get("songs", 0)), "units": int(meta.get("units", 0)),
                              "skipped": meta.get("skipped", [])[:5]}
    if df.empty:
        out["verdict"] = "no_artifacts"
        return out
    flagged = SC.flag_violations(df)
    repaired, rep = SC.repair(flagged)
    summ = SC.summarise(repaired)
    lin = SC.stage_lineage_attribution(batch)
    hyg = EIA.audit_identity_hygiene({batch.name: EIA.collect(batch)})[batch.name]
    overall, post = summ["overall"], summ["post_repair"]
    stage_created = lin["sum_of_positive_net_additions_by_stage"]
    pinned = lin.get("pinned_to_window_input", {})

    checks: dict[str, dict[str, object]] = {}
    checks["attributable_identity"] = {
        "value": {"missing_schema": hyg["share_missing_schema_version"],
                  "missing_audio_sha": hyg["share_missing_audio_sha"],
                  "missing_request_hash": hyg["share_missing_request_hash"],
                  "records_silence_flags": hyg["share_recording_silence_flags"]},
        "pass": bool(hyg["share_missing_audio_sha"] == 0.0 and hyg["share_missing_schema_version"] == 0.0
                     and hyg["share_missing_request_hash"] == 0.0),
    }
    checks["structural_legality"] = {
        "value": {"illegal_share": overall["illegal_share"],
                  "zero_share": overall["zero_or_negative_share"],
                  "overlap_share": overall["overlap_next_share"],
                  "overshoot_share": overall["overshoot_share"],
                  "regression_share": overall["start_regression_share"]},
        "pass": bool(overall["illegal_share"] <= GATES["illegal_share_max"]),
        "gate": GATES["illegal_share_max"],
    }
    worst_stage, worst_val = ("", 0.0)
    for key, v in stage_created.items():
        share = float(v) / max(overall["units"], 1)
        if share > worst_val:
            worst_stage, worst_val = key, share
    checks["stage_attribution"] = {
        "value": {"net_additions": stage_created, "worst_stage": worst_stage,
                  "worst_net_share": round(worst_val, 4),
                  "stage_shares": {k: v["degenerate_share"] for k, v in lin["totals"].items()},
                  "transitions": lin["stage_transitions_degenerate_share_delta"]},
        "pass": bool(worst_val <= GATES["stage_net_addition_max"]),
        "gate": GATES["stage_net_addition_max"],
    }
    pshare = float(pinned.get("share") or 0.0)
    checks["window_anchor_pinning"] = {
        "value": {"pinned_units": pinned.get("units"), "share": pshare,
                  "songs_affected": pinned.get("songs_affected"),
                  "top_songs": pinned.get("top_songs", [])[:3]},
        "pass": bool(pshare <= GATES["pinned_anchor_share_max"]),
        "gate": GATES["pinned_anchor_share_max"],
    }
    checks["repair_feasibility"] = {
        "value": {"post_repair_illegal_share": post["illegal_share"],
                  "units_moved_share": overall["repaired_share"],
                  "median_shift_sec": overall["median_shift_sec"],
                  "median_shift_excluding_overshoot_sec":
                      overall.get("median_shift_excluding_overshoot_sec"),
                  "solve_statuses": rep["solve_statuses"]},
        "pass": bool(post["illegal_share"] == 0.0),
    }
    out["checks"] = checks
    out["per_song_worst"] = sorted(summ["per_song"], key=lambda r: -r["illegal_share"])[:8]
    failing = [k for k, v in checks.items() if not v["pass"]]
    out["verdict"] = "ship_ok" if not failing else "blocked"
    out["blocking_checks"] = failing
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--compare-batch", type=Path, default=None,
                    help="optional second batch: run the identity/comparability gate between them")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result: dict[str, object] = {"schema": "batch_audit_v1", "gates": GATES,
                                 "batches": [audit(args.batch)]}
    if args.compare_batch:
        result["pairwise"] = EIA.audit_pair(
            f"{args.batch.name}__vs__{args.compare_batch.name}",
            EIA.collect(args.batch), EIA.collect(args.compare_batch))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    for b in result["batches"]:
        print(f"batch {b['batch']}  songs={b.get('songs')} units={b.get('units')}  "
              f"VERDICT={b['verdict']}"
              + (f"  blocking={b['blocking_checks']}" if b.get("blocking_checks") else ""))
        for k, v in b.get("checks", {}).items():
            print(f"   [{'OK ' if v['pass'] else 'FAIL'}] {k:24s} {json.dumps(v['value'], ensure_ascii=False)[:150]}")
    if "pairwise" in result:
        pw = result["pairwise"]
        print(f"pairwise -> {pw['verdict'].upper()}: {pw.get('reason')}")
    return 0 if all(b["verdict"] == "ship_ok" for b in result["batches"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
