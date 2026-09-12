#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the gap-shape truncation detector on GTSinger (human GT), then apply it frozen.

    PYTHONPATH=src python scripts/evaluation/run_gap_shape.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gap_shape as GS
from lyricalign.analysis import gtsinger_gt_deep as GG
from lyricalign.analysis import separation_leakage as SEP
from lyricalign.analysis import structural_compliance as SC
from lyricalign.analysis import tail_acoustics as TA

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_gap_shape"
SEQ = ["item", "model", "audio_input", "mode"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=RUNS / "20260814_ktv_current_silence")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, Any] = {"schema": "gap_shape_v1",
                           "discipline": "detector fitted/validated on GTSinger (human GT, not a test "
                                         "set); applied frozen to the 33 real songs, where the numbers "
                                         "are prevalence only",
                           "thresholds": {"rising": 1.15, "falling": 0.87,
                                          "min_gap_sec": GS.MIN_GAP_SEC,
                                          "truncation_tol_sec": GS.TRUNCATION_TOL_SEC}}

    # ---------- validation on GTSinger ----------
    df = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    v = df[(df["pipeline"] == "official")].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec", "audio_path"]).copy()
    v = v[v["audio_path"].astype(str).map(lambda p: Path(p).exists())]
    envs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for p in sorted(set(v["audio_path"].astype(str))):
        e = TA.load_envelope(p)
        if e.t.size:
            envs[p] = (e.t, e.rms)
    gaps = GS.gap_rows(v, envs, seq_cols=SEQ)
    res["gtsinger_validation"] = {
        "audio_files": len(envs), "gaps_measurable": int(len(gaps)),
        "score_all_views": GS.score_truncation_predictor(gaps),
        "score_production_view": GS.score_truncation_predictor(
            gaps[(gaps["model"] == "r2") & (gaps["audio_input"] == "vocal")
                 & (gaps["mode"] == "windowed")]) if len(gaps) else {"available": False}}
    gaps.to_csv(args.out_dir / "gtsinger_gap_features.csv.gz", index=False, compression="gzip")

    # ---------- frozen application to the real songs (no references) ----------
    units, _meta = SC.load_batch(args.batch, stage="selected")
    stems: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for song in sorted(set(units["song"].astype(str))):
        e = SEP._envelope(str(args.batch / song / "work" / "audio" / "vocals.wav"))
        if e is not None:
            stems[song] = e
    real_gaps = GS.gap_rows(units.rename(columns={"start_sec": "pred_start_sec",
                                                  "end_sec": "pred_end_sec"}),
                            stems, seq_cols=["song"], audio_col="song")
    res["real_songs_frozen"] = {
        "stems_read": len(stems), "gaps_measurable": int(len(real_gaps)),
        "prevalence": GS.prevalence_by_shape(real_gaps)}
    if len(real_gaps):
        lang_map = units.drop_duplicates("song").set_index("song")["language"].to_dict()
        real_gaps["language"] = real_gaps["song"].map(lang_map)
        real_gaps.to_csv(args.out_dir / "real_song_gap_features.csv.gz", index=False, compression="gzip")
        res["real_songs_frozen"]["by_language"] = {
            str(k): GS.prevalence_by_shape(sub)
            for k, sub in real_gaps.groupby("language", observed=True)}

    if len(gaps):
        res["gtsinger_validation"]["grouped_auc"] = {
            f"{score}|by_{grp}": GS.grouped_auc(gaps, score_col=score, group_col=grp)
            for score in ("gap_over_core", "gap_rms", "rise_ratio")
            for grp in ("item", "model")}
    (args.out_dir / "GAP_SHAPE.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    val = res["gtsinger_validation"]["score_all_views"]
    print(f"GTSinger: audio={res['gtsinger_validation']['audio_files']} "
          f"measurable gaps={res['gtsinger_validation']['gaps_measurable']:,}")
    if val.get("available", True) and val.get("units"):
        print(f"   truncated share (gt_end - pred_end > {val['tolerance_sec']}s): {100*val['truncated_share']:.2f}%")
        print(f"   {'shape':10s} {'units':>7s} {'share':>7s} {'truncated':>10s} {'median late ms':>15s} {'gap/core':>9s}")
        for k, vv in val["by_shape"].items():
            print(f"   {k:10s} {vv['units']:7,} {100*vv['share_of_gaps']:6.2f}% "
                  f"{100*vv['truncated_share']:9.2f}% {vv['median_late_ms']:15.1f} "
                  f"{vv.get('median_gap_over_core')}")
        for k, v2 in (val.get("auc_raw_higher_score_more_truncated") or {}).items():
            print(f"   pooled AUC {k:16s} = {v2['auc']}  ({v2['direction']})")
    grp = res["gtsinger_validation"].get("grouped_auc", {})
    if grp:
        print("   grouped AUC (within-group, cluster bootstrap):")
        for k, v3 in grp.items():
            print(f"     {k:28s} pooled={v3.get('pooled_auc')} groups={v3.get('groups_evaluated')} "
                  f"within_median={v3.get('within_group_median_auc')} "
                  f"q25-q75={v3.get('within_group_q25')}-{v3.get('within_group_q75')} "
                  f">0.6={v3.get('share_of_groups_above_0_6')} ci={v3.get('cluster_bootstrap_median_ci95')}")
        print("   long-note subset:", json.dumps(val.get("long_note_subset"), ensure_ascii=False))
    prod = res["gtsinger_validation"]["score_production_view"]
    if prod.get("units"):
        pauc = (prod.get("auc_raw_higher_score_more_truncated") or {}).get("gap_over_core", {})
        print(f"   production view only: units={prod['units']} truncated={100*prod['truncated_share']:.2f}% "
              f"pooled AUC(gap_over_core)={pauc.get('auc')}")
    pr = res["real_songs_frozen"]["prevalence"]
    print(f"\nreal songs: stems={res['real_songs_frozen']['stems_read']} "
          f"measurable gaps={res['real_songs_frozen']['gaps_measurable']:,}")
    if pr.get("available"):
        for k, vv in pr["by_shape"].items():
            print(f"   {k:10s} units={vv['units']:5,} share={100*vv['share']:5.1f}% "
                  f"gap/core={vv.get('median_gap_over_core')} gap_med={vv['median_gap_sec']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
