#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Structural compliance audit + repair plan for the shipped real-song timelines (no ground truth).

    PYTHONPATH=src python scripts/evaluation/run_structural_compliance.py [--batch DIR]...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import structural_compliance as S

BATCHES = {
    "ktv_current_silence_33": S.RUNS / "20260814_ktv_current_silence",
    "ktv_B4_25": S.RUNS / "20260814_ktv_B4",
}
OUT = S.RUNS / "20260912_structural_compliance"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--stage", default="selected", choices=("selected", "raw"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {"schema": "structural_compliance_run_v1", "stage": args.stage,
                                 "batches": {}}
    for name, batch in BATCHES.items():
        df, meta = S.load_batch(batch, stage=args.stage)
        if df.empty:
            result["batches"][name] = {"present": False, "meta": meta}
            continue
        df = S.flag_violations(df)
        df, rep = S.repair(df)
        summ = S.summarise(df)
        summ["load"] = meta
        summ["repair_config"] = rep
        summ["export"] = S.export_repair_list(df, args.out_dir / f"repair_list_{name}.csv.gz")
        result["batches"][name] = summ
        o = summ["overall"]
        print(f"\n== {name}: {o['units']:,} units / {summ['songs']} songs (stage={args.stage}) ==")
        print(f"   shipped illegal {100*o['illegal_share']:.2f}% "
              f"(zero {100*o['zero_or_negative_share']:.2f}%, overlap {100*o['overlap_next_share']:.2f}%, "
              f"overshoot {100*o['overshoot_share']:.2f}%, regression {100*o['start_regression_share']:.2f}%)")
        print(f"   after repair illegal {100*summ['post_repair']['illegal_share']:.2f}% "
              f"(zero {summ['post_repair']['zero_or_negative_share']:.4f}, "
              f"overlap {summ['post_repair']['overlap_next_share']:.4f}, "
              f"overshoot {summ['post_repair']['overshoot_share']:.4f})")
        print(f"   units moved {100*o['repaired_share']:.2f}%  median shift {o['median_shift_sec']}s "
              f"p90 {o['p90_shift_sec']}s max {o['max_shift_sec']}s")
        print(f"   plausible mass {o['plausible_mass_sec']}s -> "
              f"{sum(x['plausible_mass_sec'] for x in summ['per_song'] if False) or '':s}"
              if False else
              f"   plausible mass (shipped) {o['plausible_mass_sec']}s")
        print("   by language:")
        for k, v in summ["by_language"].items():
            print(f"      {k:12s} units={v['units']:6d} illegal={100*v['illegal_share']:6.2f}% "
                  f"zero={100*v['zero_or_negative_share']:6.2f}% moved={100*v['repaired_share']:6.2f}%")
        print("   worst songs by illegal share:")
        for r in summ["per_song"][:5]:
            print(f"      {r['song'][:22]:22s} {r['language']:10s} units={r['units']:5d} "
                  f"illegal={100*r['illegal_share']:6.2f}% maxdur={r['max_duration_sec']}s "
                  f"moved={100*r['repaired_share']:5.1f}% max_shift={r['max_shift_sec']}s "
                  f"sha_recorded={'Y' if r['audio_sha_recorded'] else 'N'}")
    for name, batch in BATCHES.items():
        if batch.exists():
            result["batches"][name]["compression_damage"] = S.compression_damage(batch)
    cd = (result["batches"].get("ktv_current_silence_33", {}) or {}).get("compression_damage", {})
    if cd.get("totals"):
        tt = cd["totals"]
        print(f"\n== compression damage (33-song batch) ==")
        print(f"   zero-length units: raw {tt['zero_units_raw']:,} -> shipped {tt['zero_units_shipped']:,} "
              f"({100*tt['raw_zero_share']:.2f}% -> {100*tt['shipped_zero_share']:.2f}%)")
        print(f"   created by post-processing: {tt['created_by_postprocess_units']:,} units "
              f"({100*tt['created_by_postprocess_share']:.2f}%)")
        print(f"   pipeline's own counter says: {tt['pipeline_counter_total']:,} "
              f"=> blind to {100*tt['counter_blind_share']:.1f}% of its own damage")
        print(f"   corr(zero_share, seam_repaired_rate) = {cd.get('correlation_zero_share_vs_seam_repaired_rate')}")
        print(f"   corr(zero_share, overlap_compressed_rate) = {cd.get('correlation_zero_share_vs_overlap_compressed_rate')}")
        for r in cd.get("worst_songs", [])[:4]:
            print(f"      {r['song'][:20]:20s} {r['language']:10s} raw {100*(r['raw_zero_share'] or 0):5.1f}% "
                  f"-> shipped {100*r['shipped_zero_share']:5.1f}% created={r['created_by_postprocess']:4d} "
                  f"counter={r['counter_collapsed_to_zero']} seam_rate={r['seam_repaired_rate']}")
    (args.out_dir / "COMPLIANCE.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
