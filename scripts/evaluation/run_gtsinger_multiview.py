#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GTSinger 12-view selection experiment against human ground truth.

    PYTHONPATH=src python scripts/evaluation/run_gtsinger_multiview.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as G
from lyricalign.analysis import gtsinger_multiview as M


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", type=Path,
                    default=Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep"
                                 "/unit_evidence.jsonl.gz"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_multiview"))
    args = ap.parse_args()
    df = G.load_panel(args.evidence)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    all_out: dict[str, object] = {"schema": "gtsinger_multiview_v1", "evidence": str(args.evidence)}
    for pipe in ("official", "raw"):
        d = M.build_view_frame(df, pipeline=pipe)
        if d.empty:
            continue
        qual = M.view_quality(d)
        res, rows, cons = M.selection_experiment(d)
        res["diversity"] = {"cross_view_disagreement": qual["cross_view_disagreement"],
                            "factor_decomposition": qual["factor_decomposition"],
                            "views": qual["views"], "units": qual["units"]}
        # keep the module's per_view_baseline (production view + bootstrap CIs); the driver only
        # attaches the diversity diagnostics, so the two sources cannot disagree on shape
        res["per_view_baseline"]["all_views"] = qual["views"]
        res["factor_content_audit"] = M.factor_content_audit(df, pipeline=pipe)
        all_out[pipe] = res
        rows.to_csv(args.out_dir / f"view_rows_{pipe}.csv.gz", index=False, compression="gzip")
        cons.to_csv(args.out_dir / f"consensus_{pipe}.csv.gz", index=False, compression="gzip")
    (args.out_dir / "MULTIVIEW.json").write_text(
        json.dumps(all_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for pipe in ("official", "raw"):
        if pipe not in all_out:
            continue
        r = all_out[pipe]
        prod = (r["per_view_baseline"].get("production_view") or {})
        print(f"\n=== {pipe}: units={r['diversity']['units']} views={len(r['diversity']['views'])} ===")
        print(f"  production view {prod.get('hit100', float('nan')):.4f} hit@100 "
              f"MAE {prod.get('mae_both_sec', float('nan')):.4f}")
        print(f"  disagreement median {r['diversity']['cross_view_disagreement']['median_sec']}s "
              f"share>100ms {r['diversity']['cross_view_disagreement']['share_gt_100ms']}")
        print(f"  oracle gap vs production: {r['oracle_gap_pp']:+.2f}pp")
        for k, v in sorted(r["gap_closed"].items(), key=lambda kv: -kv[1]["hit100"]):
            print(f"    {k:46s} hit100={v['hit100']:.4f} Δ={v['delta_pp_vs_production']:+.2f}pp "
                  f"share={v['share_of_oracle_gap']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
