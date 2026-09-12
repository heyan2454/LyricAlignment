#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trace the longest degenerate blocks through the pipeline and name the step that grows them.

    PYTHONPATH=src python scripts/evaluation/run_degenerate_run_lineage.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import raw_degeneracy_forensics as RDF
from lyricalign.analysis import structural_compliance as SC

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_degenerate_run_lineage"
BATCH = RUNS / "20260814_ktv_current_silence"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    ap.add_argument("--min-run", type=int, default=50)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames: dict[str, object] = {}
    for stage in ("raw", "fixed", "selected", "final"):
        try:
            frame, _meta = SC.load_batch(args.batch, stage=stage)
        except Exception as exc:                                     # noqa: BLE001
            print(f"stage {stage}: {exc}")
            continue
        if frame.empty:
            continue
        frames[stage] = SC.flag_violations(frame)
    res = RDF.degenerate_run_lineage(frames, min_run=args.min_run)
    res["batch"] = str(args.batch)
    # how much of the shipped damage sits inside blocks that share a single start timestamp?
    sel = frames.get("selected")
    if sel is not None and not sel.empty:
        z = sel["flag_zero_or_negative"].to_numpy(dtype=bool)
        key = sel.assign(_k=sel["song"].astype(str) + "|"
                         + pd.to_numeric(sel["start_sec"], errors="coerce").round(4).astype(str))
        grp = key.groupby("_k", observed=True)["flag_zero_or_negative"].agg(["size", "sum"])
        big = grp[(grp["size"] >= 5) & (grp["sum"] == grp["size"])]
        res["pinning_inventory"] = {
            "shipped_zero_units": int(z.sum()),
            "zero_units_in_identical_start_blocks_ge5": int(big["size"].sum()),
            "share_of_zero_units_in_identical_start_blocks": round(
                float(big["size"].sum() / max(z.sum(), 1)), 4),
            "such_blocks": int(len(big)),
            "largest_identical_start_block": int(big["size"].max()) if len(big) else 0}
        print("\npinning inventory: " + json.dumps(res["pinning_inventory"], ensure_ascii=False))
    (args.out_dir / "DEGENERATE_RUN_LINEAGE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"stages: {res['stages']}; blocks >= {args.min_run} units at 'selected': "
          f"{res['summary']['blocks']}, total units {res['summary']['total_anchor_units']}")
    print(f"blocks already fully pinned at the first stage ({res['stages'][0]}): "
          f"{res['summary']['pinned_at_first_stage']}")
    for blk in res["blocks"][:8]:
        print(f"\n{blk['song']}  units {blk['start_index']}..{blk['end_index']} "
              f"(anchor length {blk['anchor_length']})")
        for stage, v in blk["by_stage"].items():
            print(f"   {stage:9s} units={v['units_in_span']:4d} zero={v['zero_units']:4d} "
                  f"distinct_starts={v['distinct_start_times']:4d} "
                  f"single_timestamp={v['single_timestamp_block']} span={v['span_sec']}s")
        print(f"   first stage fully pinned: {blk['first_stage_fully_pinned']}; "
              f"zero growth per step: {blk['zero_growth_vs_previous_stage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
