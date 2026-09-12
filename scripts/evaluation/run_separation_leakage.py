#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is there time-local accompaniment leakage in the separated vocal stem at note endings?

    PYTHONPATH=src python scripts/evaluation/run_separation_leakage.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import separation_leakage as SL
from lyricalign.analysis import structural_compliance as SC

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_separation_leakage"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=RUNS / "20260814_ktv_current_silence")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    units, meta = SC.load_batch(args.batch, stage="selected")
    if units.empty:
        print(json.dumps({"available": False, "reason": "no units"}))
        return 1
    res = SL.measure_batch(args.batch, units[["song", "language", "unit_index",
                                              "start_sec", "end_sec"]])
    res["units_in_batch"] = int(len(units))
    (args.out_dir / "SEPARATION_LEAKAGE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    p = res["pooled"]
    print(f"batch={args.batch.name} units={res['units_in_batch']:,} "
          f"songs measured={res['songs_measured']} skipped={res['songs_skipped']}")
    print(f"  global separation_quality all passed: {p['separation_quality_all_passed']}")
    print(f"  median per-song corr(vocal_lead, accomp_lead) = {p['median_song_corr_vocal_vs_accomp_lead']}"
          f" | long-only {p['median_song_corr_long_units']}")
    print(f"  median share of boundaries whose vocal stem is still active 0-300ms after the end: "
          f"all {p['median_residual_active_share']:.3f} / long {p['median_long_residual_active_share']:.3f}")
    ok0 = [r for r in res["per_song"] if r.get("available")]
    g_all = [r["gaps"]["all_measurable"] for r in ok0 if r["gaps"]["all_measurable"]["units"]]
    g_long = [r["gaps"]["long_units"] for r in ok0 if r["gaps"]["long_units"]["units"]]
    def _med(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(float(np.median(vals)), 4) if vals else None
    print(f"  units with a measurable inter-unit gap (>= {SL.MIN_GAP_SEC * 1000:.0f}ms): "
          f"{_med([{'x': r['gap_measurable_share']} for r in ok0], 'x')}")
    print(f"  GAP-restricted RELATIVE (>25% of own core): all {_med(g_all, 'relative_residual_active_share')} "
          f"long {_med(g_long, 'relative_residual_active_share')}, "
          f"median residual ratio {_med(g_all, 'median_relative_residual')}")
    print(f"  GAP-restricted absolute floor: vocal-stem active share {_med(g_all, 'vocal_active_share_in_gap')} "
          f"(long {_med(g_long, 'vocal_active_share_in_gap')}), "
          f"median vocal rms {_med(g_all, 'median_vocal_gap_rms')} vs accomp {_med(g_all, 'median_accomp_gap_rms')}, "
          f"corr(v,a) {_med(g_all, 'corr_vocal_gap_vs_accomp_gap')} "
          f"(long {_med(g_long, 'corr_vocal_gap_vs_accomp_gap')})")
    res["pooled"]["gap_restricted"] = {
        "measurable_gap_share_median": _med([{"x": r["gap_measurable_share"]} for r in ok0], "x"),
        "vocal_active_share": _med(g_all, "vocal_active_share_in_gap"),
        "relative_residual_active_share": _med(g_all, "relative_residual_active_share"),
        "relative_residual_active_share_long": _med(g_long, "relative_residual_active_share"),
        "median_relative_residual": _med(g_all, "median_relative_residual"),
        "median_relative_residual_long": _med(g_long, "median_relative_residual"),
        "vocal_active_share_long": _med(g_long, "vocal_active_share_in_gap"),
        "median_vocal_gap_rms": _med(g_all, "median_vocal_gap_rms"),
        "median_accomp_gap_rms": _med(g_all, "median_accomp_gap_rms"),
        "corr_vocal_accomp_gap": _med(g_all, "corr_vocal_gap_vs_accomp_gap"),
        "corr_vocal_accomp_gap_long": _med(g_long, "corr_vocal_gap_vs_accomp_gap")}
    (args.out_dir / "SEPARATION_LEAKAGE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n  per language (median over songs):")
    ok = [r for r in res["per_song"] if r.get("available")]
    by_lang: dict[str, list[dict]] = {}
    for r in ok:
        by_lang.setdefault(r["language"], []).append(r)
    for lang, rows in sorted(by_lang.items()):
        gap_rows = [r["gaps"]["all_measurable"] for r in rows if r["gaps"]["all_measurable"]["units"]]
        gap_long = [r["gaps"]["long_units"] for r in rows if r["gaps"]["long_units"]["units"]]
        c = [r["corr_vocal_lead_vs_accomp_lead"] for r in rows
             if r.get("corr_vocal_lead_vs_accomp_lead") is not None]
        la = [r["all_units"]["residual_active_share"] for r in rows if r["all_units"].get("units")]
        lg = [r["long_units"]["residual_active_share"] for r in rows
              if r.get("long_units", {}).get("units")]
        vlc = [r["all_units"]["median_vocal_lead_over_core"] for r in rows
               if r["all_units"].get("units")]
        gv = [r["vocal_active_share_in_gap"] for r in gap_rows if r.get("vocal_active_share_in_gap") is not None]
        gc = [r["corr_vocal_gap_vs_accomp_gap"] for r in gap_rows
              if r.get("corr_vocal_gap_vs_accomp_gap") is not None]
        gl = [r["vocal_active_share_in_gap"] for r in gap_long
              if r.get("vocal_active_share_in_gap") is not None]
        print(f"   {lang:10s} songs={len(rows):2d} | gap: active={np.median(gv) if gv else float('nan'):.3f} "
              f"corr(v,a)={np.median(gc) if gc else float('nan'):+.3f} long-active="
              f"{np.median(gl) if gl else float('nan'):.3f} || naive lead corr={np.median(c) if c else float('nan'):+.3f}")
    print("\n  worst songs by residual-active share (all units):")
    for r in sorted(ok, key=lambda x: -x["all_units"].get("residual_active_share", 0))[:5]:
        print(f"   {r['song'][:18]:18s} {r['language']:10s} units={r['units']:5d} "
              f"active={r['all_units']['residual_active_share']:.3f} "
              f"corr={r['corr_vocal_lead_vs_accomp_lead']} "
              f"sep_passed={r.get('passed')} v/a_corr={r.get('vocals_vs_accompaniment_correlation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
