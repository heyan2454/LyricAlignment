#!/usr/bin/env python3
"""Summarize no-GT formal artifacts and surface safe optimization hypotheses."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def _rows(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--core-root", required=True)
    p.add_argument("--demo-root", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    core = Path(args.core_root) / "02_behavior"
    demo = Path(args.demo_root) / "04_test_demo"
    requests = _rows(core / "REQUESTS.jsonl")
    behavior = _rows(demo / "TEST_DEMO_REALIGN_BEHAVIOR.jsonl")
    demo_summary = json.loads((demo / "TEST_DEMO_DETECTOR_SUMMARY.json").read_text(encoding="utf-8"))
    core_by_variant = Counter(r["input_variant"] for r in requests)
    demo_by_variant = Counter(r["variant"] for r in behavior)
    sparse = [r for r in requests if r["input_variant"] == "R-S_sparse_fixed"]
    sparse_ratios = [
        len(r["active_slot_indices"]) / len(r["text_units"])
        for r in sparse if r.get("text_units")
    ]
    by_song = defaultdict(int)
    for r in requests:
        by_song[r["item_id"]] += 1
    report = {
        "schema": "unit_realign_formal_no_gt_summary_v1",
        "core": {
            "n_requests": len(requests), "by_variant": dict(core_by_variant),
            "n_songs": len(by_song), "max_requests_per_song": max(by_song.values(), default=0),
            "sparse": {
                "n": len(sparse),
                "mean_active_text_ratio": round(sum(sparse_ratios) / len(sparse_ratios), 6)
                if sparse_ratios else None,
                "min_active_text_ratio": min(sparse_ratios, default=None),
                "max_active_text_ratio": max(sparse_ratios, default=None),
            },
        },
        "test_demo": {
            "n_items_detector_ok": demo_summary.get("n_items"),
            "n_items_detector_failed": demo_summary.get("n_failed"),
            "n_local_regions": demo_summary.get("n_windows"),
            "n_forward_ok": len(behavior), "by_variant": dict(demo_by_variant),
            "n_r_null": demo_summary.get("n_r_null"),
            "languages": sorted({r["item"].split("/")[0] for r in behavior}),
        },
        "optimization_hypotheses": [
            {
                "name": "adaptive_sparse_context",
                "signal": "R-S active/text ratio distribution",
                "next_test": "compare 1/2/3 context-unit padding with fixed-slot preservation; keep full text and fixed remerge",
            },
            {
                "name": "detector_geometry_sanitizer",
                "signal": "formal encountered inverted detector intervals requiring auditable repair",
                "next_test": "pre-forward monotonic projection of baseline geometry and measure no-GT structural stability",
            },
            {
                "name": "anchor_availability_policy",
                "signal": "R-NULL count and R-B coverage",
                "next_test": "expand bilateral anchor search by local index/time radius while retaining explicit non-null anchor contract",
            },
        ],
        "boundary": "No GT accuracy, repair rate, or writeback recommendation is reported here.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
