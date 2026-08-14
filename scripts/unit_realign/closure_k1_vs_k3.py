#!/usr/bin/env python3
"""WP5 — E3-A k1/k3 closure: no-GT structural reuse of old runs (read-only).

The old ``unit_realign_explore_context_{k1,k3,_v2, k1_vs_k3}_20260813*`` runs are
research_v7-schema artifacts (``input_variant``/``workflow_mode``/``parent_request_id``),
NOT v2 ``unit_realign_request_v2`` rows (C_note §4).  So this closure does NOT
re-materialize requests or re-forward anything — it only redistills the
already-computed no-GT structural screen and writes a ``CLOSURE_REFERENCE.json``
for the WP5 study.  It never reads GT/outcome buckets and makes no accuracy claim
(consistent with the original ``CONTEXT_PADDING_COMPARISON`` scope
``no_gt_structural_screen_only``).

Inputs:
  - ``--comparison CONTEXT_PADDING_COMPARISON.json`` (the k1_vs_k3 run's screen),
  - ``--k3-root`` / ``--k1-root`` optional research_v7 behavior roots to re-derive
    structural counts (sparse requests, fixed-slot restoration audit) when present.

Output: ``--out CLOSURE_REFERENCE.json`` (schema ``audio_view_study_k1vsk3_closure_v1``).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _sparse_structural_audit(behavior_root: Path) -> dict:
    """Rederive no-GT structural facts from a research_v7 02_behavior root.

    Counts sparse-fixed requests and their active-to-text ratio + fixed-slot
    restoration.  Reads only request geometry, never GT.
    """
    requests_path = behavior_root / "REQUESTS.jsonl"
    if not requests_path.exists():
        return {"available": False, "reason": "missing_REQUESTS"}
    requests = _read_jsonl(requests_path)
    sparse = [r for r in requests if str(r.get("input_variant", "")).startswith("R-S")]
    ratios = []
    for r in sparse:
        text = r.get("text_units") or ()
        active = r.get("active_slot_indices") or r.get("timestamp_slot_indices") or ()
        n = len(text) if isinstance(text, (list, tuple)) else 0
        if n:
            ratios.append(len(active) / n)
    return {
        "available": True,
        "n_requests": len(requests),
        "n_sparse_fixed": len(sparse),
        "mean_active_to_text_ratio": round(sum(ratios) / len(ratios), 6) if ratios else None,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--comparison", required=True, help="CONTEXT_PADDING_COMPARISON.json of the k1_vs_k3 run")
    p.add_argument("--k1-root", help="research_v7 02_behavior root of the k1 run (optional)")
    p.add_argument("--k3-root", help="research_v7 02_behavior root of the k3 run (optional)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    comp_path = Path(args.comparison)
    comparison = json.loads(comp_path.read_text(encoding="utf-8"))

    # Validate this is the expected no-GT structural screen (never GT/accuracy).
    if str(comparison.get("scope", "")) != "no_gt_structural_screen_only":
        raise ValueError("comparison JSON is not the no-GT structural screen; "
                         "refusing to treat as closure reference")
    if comparison.get("schema") != "unit_realign_context_padding_comparison_v1":
        raise ValueError(f"unexpected schema {comparison.get('schema')}")

    k1_audit = _sparse_structural_audit(Path(args.k1_root)) if args.k1_root else {"available": False}
    k3_audit = _sparse_structural_audit(Path(args.k3_root)) if args.k3_root else {"available": False}

    metrics = comparison.get("metrics", {})
    mean_fixed = metrics.get("mean_fixed_units", {})
    short_fixed = mean_fixed.get("short")
    long_fixed = mean_fixed.get("long")
    # Structural interpretation strictly no-GT: what does longer context buy in
    # terms of fixed-slot restoration / coverage, NOT accuracy.
    if short_fixed is not None and long_fixed is not None:
        fixed_delta = round(long_fixed - short_fixed, 6)
        structural_read = (
            f"longer context (k3) restores {fixed_delta} additional fixed units on "
            f"average vs k1 while keeping target slots identical and sparse fixed rows "
            f"exactly restored (screen {comparison.get('status')})")
    else:
        fixed_delta, structural_read = None, "fixed-unit delta not derivable from screen metrics"

    violations = comparison.get("violations", [])
    conclusion: dict = {
        "schema": "audio_view_study_k1vsk3_closure_v1",
        "provenance": {
            "comparison_json": args.comparison,
            "comparison_schema": comparison.get("schema"),
            "short_run": comparison.get("short_run"),
            "long_run": comparison.get("long_run"),
            "k1_behavior_root": args.k1_root,
            "k3_behavior_root": args.k3_root,
        },
        "compatibility_note": (
            "Old k1/k3 runs are research_v7-schema (input_variant/workflow_mode/..."
            "), NOT v2 unit_realign_request_v2; this closure reuses their no-GT "
            "structural result only and does NOT re-materialize/re-forward for the "
            "v2 visualization (C_note §4 / 07 §11 anti-scope)."),
        "structural_screen": {
            "scope": comparison.get("scope"),
            "status": comparison.get("status"),
            "sparse_requests": comparison.get("sparse_requests"),
            "violations": violations,
            "metrics": comparison.get("metrics"),
        },
        "no_gt_structural_conclusion": {
            "short_context_k": 1, "long_context_k": 3,
            "mean_fixed_units_short": short_fixed,
            "mean_fixed_units_long": long_fixed,
            "fixed_units_delta_long_minus_short": fixed_delta,
            "read": structural_read,
            "interpretation": comparison.get("interpretation"),
        },
        "re_derived_audit": {"k1": k1_audit, "k3": k3_audit},
        "gt_firewall": {"reads_gt_buckets": False, "accuracy_claim": False,
                        "scope_is_no_gt_structural_screen_only": True},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(conclusion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
