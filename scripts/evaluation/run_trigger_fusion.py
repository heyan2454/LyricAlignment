#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the fused reference-free trigger on GTSinger, then queue real songs for re-decode.

    PYTHONPATH=src python scripts/evaluation/run_trigger_fusion.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as GG
from lyricalign.analysis import structural_compliance as SC
from lyricalign.analysis import trigger_fusion as TF

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_trigger_fusion"
KEY = ["item", "model", "audio_input", "mode", "unit_index"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=RUNS / "20260814_ktv_current_silence")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, Any] = {"schema": "trigger_fusion_v1",
                           "discipline": "triggers are reference-free; thresholds frozen from rounds "
                                         "15/19/26 and validated on GTSinger (human GT, not a test "
                                         "set); the real-song output is a queue, not an accuracy claim",
                           "review_budgets": list(TF.BUDGETS)}

    # ---------- validation on GTSinger ----------
    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    off = panel[panel["pipeline"] == "official"].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec"]).copy()
    gaps = pd.read_csv(RUNS / "20260912_gap_shape/gtsinger_gap_features.csv.gz")
    feats = TF.build_features(off.merge(gaps[KEY + ["gap_over_core"]], on=KEY, how="left"))
    dur = pd.to_numeric(feats["gt_dur_sec"], errors="coerce").to_numpy(dtype=float)
    prod = ((feats["model"] == "r2") & (feats["audio_input"] == "vocal")
            & (feats["mode"] == "windowed")).to_numpy(dtype=bool)
    res["gtsinger_validation"] = {
        "units": int(len(feats)),
        "gap_coverage": round(float(np.mean(np.isfinite(
            pd.to_numeric(feats["gap_over_core"], errors="coerce")))), 4),
        "all_views": TF.evaluate_triggers(feats),
        "long_note": TF.evaluate_triggers(feats[dur >= 1.0]),
        "production_view": TF.evaluate_triggers(feats[prod])}

    # ---------- frozen application to the real songs (no references) ----------
    sel, _ = SC.load_batch(args.batch, stage="selected")
    raw, _ = SC.load_batch(args.batch, stage="raw")
    wide = sel[["song", "language", "unit_index", "start_sec", "end_sec", "ent_end", "ent_start"]].rename(
        columns={"start_sec": "pred_start_sec", "end_sec": "pred_end_sec",
                 "ent_end": "raw_entropy_end", "ent_start": "raw_entropy_start"})
    wide = wide.merge(raw[["song", "unit_index", "start_sec", "end_sec"]].rename(
        columns={"start_sec": "raw_start_sec", "end_sec": "raw_end_sec"}),
        on=["song", "unit_index"], how="inner")
    rg = pd.read_csv(RUNS / "20260912_gap_shape/real_song_gap_features.csv.gz")
    wide = wide.merge(rg[["song", "unit_index", "gap_over_core"]], on=["song", "unit_index"], how="left")
    rf = TF.build_features(wide)
    queue = TF.redecode_queue(rf, group_cols=["song"], review_budget=0.15)
    queue["language"] = queue["song"].map(sel.drop_duplicates("song").set_index("song")["language"].to_dict())
    queue.to_csv(args.out_dir / "redecode_queue_real_songs.csv.gz", index=False, compression="gzip")
    res["real_songs"] = {"units": int(len(rf)),
                         "gap_coverage": round(float(np.mean(np.isfinite(
                             pd.to_numeric(rf["gap_over_core"], errors="coerce")))), 4),
                         "flag_shares": {name: round(float(rf[c].mean()), 4)
                                         for name, c in (("inversion", "flag_inversion"),
                                                         ("gap_residual", "flag_gap_residual"),
                                                         ("high_entropy_end", "flag_high_entropy_end"),
                                                         ("low_conf_end", "flag_low_conf_end"))
                                         if c in rf.columns},
                         "any_flag_share": round(float(TF.any_flag(rf).mean()), 4),
                         "queue_top": queue.head(10).to_dict(orient="records")}
    (args.out_dir / "TRIGGER_FUSION.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")

    v = res["gtsinger_validation"]["all_views"]["triggers"]
    print("GTSinger validation (units=%s, gap coverage %.1f%%):" % (
        f"{res['gtsinger_validation']['units']:,}", 100 * res["gtsinger_validation"]["gap_coverage"]))
    for label, blk in v.items():
        print(f"   target {label}: prevalence={blk['prevalence']:.3f} n={blk['n']:,}")
        for name in ("inversion", "low_conf_end", "high_entropy_end", "gap_residual",
                     "fused_mean_rank", "any_flag_boolean"):
            e = blk.get(name)
            if not e:
                continue
            print(f"      {name:18s} auc={e['auc']} " + " ".join(
                f"r@{int(b*100)}%={100*e[f'recall_at_{int(b*100)}pct_budget']:.1f}%" for b in TF.BUDGETS)
                + " | " + " ".join(f"p@{int(b*100)}%={100*e[f'precision_at_{int(b*100)}pct_budget']:.1f}%"
                                   for b in TF.BUDGETS))
    pv = res["gtsinger_validation"]["production_view"]["triggers"].get("truncated_end", {})
    print("\n   production view (truncated_end): " + json.dumps(
        {k: pv[k] for k in pv if k in ("inversion", "gap_residual", "fused_mean_rank", "any_flag_boolean",
                                       "prevalence")}, ensure_ascii=False)[:420])
    print("\nreal songs (no references): units=%s gap coverage %.1f%% flags=%s any=%.3f" % (
        f"{res['real_songs']['units']:,}", 100 * res["real_songs"]["gap_coverage"],
        res["real_songs"]["flag_shares"], res["real_songs"]["any_flag_share"]))
    print("   re-decode queue (top 8 by flagged share):")
    for r in res["real_songs"]["queue_top"][:8]:
        song = str(r["song"])[:18]
        lang = str(r.get("language"))[:10]
        print(f"      {song:18s} {lang:10s} units={int(r['units']):5d} "
              f"flagged={100*float(r['flagged_share']):5.1f}% inv={int(r['inversion_units']):4d} "
              f"gap={int(r['gap_residual_units']):4d} ent={int(r.get('high_entropy_units', 0) or 0):4d} "
              f"median_score={r['median_fused_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
