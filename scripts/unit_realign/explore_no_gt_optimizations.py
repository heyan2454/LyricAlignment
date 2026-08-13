#!/usr/bin/env python3
"""Derive reproducible no-GT optimization experiments from formal artifacts."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--core-requests", required=True)
    p.add_argument("--demo-manifest", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    core = read_jsonl(args.core_requests)
    demo = read_jsonl(args.demo_manifest)
    sparse = [r for r in core if r.get("input_variant") == "R-S_sparse_fixed"]
    ratios = [len(r["active_slot_indices"]) / len(r["text_units"]) for r in sparse]
    rb = sum(r.get("input_variant") == "R-B_safe_anchor_bounded" for r in core)
    core_fallback = sum(
        x.get("baseline_source") != "production_detector_shadow"
        for r in sparse for x in r.get("fixed_slot_rows", []))
    demo_fallback = sum(
        x.get("baseline_source") == "test_demo_detector_baseline_repaired_inversion"
        for r in demo for x in r.get("fixed_slot_rows", []))
    experiment = {
        "schema": "unit_realign_no_gt_exploration_v1",
        "observations": {
            "core_sparse_requests": len(sparse),
            "core_mean_active_text_ratio": sum(ratios) / len(ratios) if ratios else None,
            "core_rb_coverage": {"available": rb, "eligible_regions": len(sparse)},
            "core_geometry_fallback_fixed_rows": core_fallback,
            "demo_geometry_repaired_fixed_rows": demo_fallback,
            "core_active_slot_histogram": dict(Counter(len(r["active_slot_indices"]) for r in sparse)),
        },
        "experiments": [
            {
                "id": "E1_context_padding",
                "hypothesis": "R-S context is too tight when active/text ratio is high.",
                "variants": [{"context_units_each_side": n, "fixed_remerge_required": True}
                             for n in (1, 2, 3, 4)],
                "no_gt_metrics": ["context_protection_ratio", "median_displacement_ms",
                                  "MAD across family", "missing/extra", "runtime"],
                "selection": "screen on song-disjoint regions; no writeback.",
            },
            {
                "id": "E2_anchor_radius",
                "hypothesis": "R-B coverage improves with wider nearest-ACCEPT search without sacrificing identity.",
                "variants": [{"max_anchor_distance_units": n} for n in (2, 4, 8, 16, 32)],
                "no_gt_metrics": ["valid_bilateral_anchor_rate", "request_identity_difference",
                                  "context_protection_ratio", "runtime"],
                "selection": "R-B is eligible only with two non-null ACCEPT anchors.",
            },
            {
                "id": "E3_geometry_sanitizer",
                "hypothesis": "pre-forward monotonic geometry sanitation reduces malformed sparse requests.",
                "variants": [{"policy": x} for x in ("reject", "timeline_fallback", "tick_repair")],
                "no_gt_metrics": ["invalid_geometry_count", "sparse_partition_validity",
                                  "fixed_slot_monotonicity", "runtime"],
                "selection": "keep provenance per repaired row; compare only no-GT structural metrics.",
            },
        ],
        "guardrails": {
            "actual_writeback": 0,
            "forbid_gt_features": True,
            "song_disjoint_screen": True,
            "candidate_not_unit_row_independence": True,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(experiment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(experiment, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
