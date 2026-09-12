#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Weak signal or weak label? Quantisation-aware AUC diagnostics on two corpora.

    PYTHONPATH=src python scripts/evaluation/run_label_noise_ceiling.py
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
from lyricalign.analysis import label_noise_ceiling as LN

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_label_noise_ceiling"
M4_QUANTUM_SEC = 0.08
GS_QUANTUM_SEC = 0.08


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, Any] = {"schema": "label_noise_ceiling_v1",
                           "question": "is the weaker AUC on M4Singer a weaker signal or a coarser label?",
                           "corpora": {}}

    # ---- M4Singer: replication frame (already computed in round 30)
    m4 = pd.read_csv(RUNS / "20260912_trigger_replication/m4_gap_features.csv.gz").dropna(
        subset=["pred_err_sec", "end_entropy"])
    # neighbours that are far apart give the least ambiguous boundaries
    panel = pd.read_json(RUNS / "20260912_m4_longform_weakgt/longform_units.jsonl.gz", lines=True)
    p2 = panel.sort_values(["source_segment_id", "source_unit_index"]).copy()
    p2["next_gap"] = p2.groupby("source_segment_id")["off_start_sec"].shift(-1) - p2["off_end_sec"]
    gapmap = p2.set_index(["source_segment_id", "source_unit_index"])["next_gap"].to_dict()
    m4["next_gap_sec"] = [gapmap.get((str(s), int(i))) for s, i in
                          zip(m4.get("segment", []), m4.groupby("segment").cumcount())] \
        if "segment" in m4.columns else np.nan
    res["corpora"]["m4_weak_labels"] = {
        "label_kind": "rule_validated weak labels, 80 ms quantised",
        "units": int(len(m4)),
        "threshold_sensitivity_entropy": LN.threshold_sensitivity(m4["pred_err_sec"], m4["end_entropy"]),
        "threshold_sensitivity_gap": LN.threshold_sensitivity(m4["pred_err_sec"], m4["gap_over_core"]),
        "ambiguous_exclusion_entropy": LN.ambiguous_label_impact(
            m4["pred_err_sec"], m4["end_entropy"], threshold=0.1,
            label_quantum_sec=M4_QUANTUM_SEC),
        "slices": LN.slice_decomposition(m4, err_col="pred_err_sec", score_col="end_entropy",
                                        slices={
                                            "all": np.ones(len(m4), dtype=bool),
                                            "baseline_legal_only": (m4["family"] == "baseline_legal").to_numpy(dtype=bool),
                                            "train_split": (m4["split"] == "train").to_numpy(dtype=bool),
                                            "validation_split": (m4["split"] == "validation").to_numpy(dtype=bool),
                                            "unambiguous_neighbours": (
                                                pd.to_numeric(m4.get("next_gap_sec"), errors="coerce")
                                                >= 0.24).fillna(False).to_numpy(dtype=bool),
                                            "long_note": (m4["gt_dur_sec"] >= 1.0).to_numpy(dtype=bool)})}

    # ---- GTSinger: human word-level GT
    g = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    go = g[g["pipeline"] == "official"].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec"]).copy()
    go["pred_err_sec"] = np.maximum((go["pred_start_sec"] - go["gt_start_sec"]).abs(),
                                     (go["pred_end_sec"] - go["gt_end_sec"]).abs())
    res["corpora"]["gtsinger_human_gt"] = {
        "label_kind": "human word-level GT",
        "units": int(len(go)),
        "threshold_sensitivity_entropy": LN.threshold_sensitivity(go["pred_err_sec"],
                                                                 go["raw_entropy_end"]),
        "ambiguous_exclusion_entropy": LN.ambiguous_label_impact(
            go["pred_err_sec"], go["raw_entropy_end"], threshold=0.1,
            label_quantum_sec=GS_QUANTUM_SEC),
        "slices": LN.slice_decomposition(go, err_col="pred_err_sec", score_col="raw_entropy_end",
                                        slices={
                                            "all": np.ones(len(go), dtype=bool),
                                            "production_view": ((go["model"] == "r2")
                                                                & (go["audio_input"] == "vocal")
                                                                & (go["mode"] == "windowed")).to_numpy(dtype=bool),
                                            "long_note": (pd.to_numeric(go["gt_dur_sec"], errors="coerce")
                                                          >= 1.0).fillna(False).to_numpy(dtype=bool)})}

    (args.out_dir / "LABEL_NOISE.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    for name, blk in res["corpora"].items():
        c = blk["threshold_sensitivity_entropy"]["by_threshold"]
        print(f"\n== {name} ({blk['units']:,} units, {blk['label_kind']}) ==")
        print("   AUC(entropy -> err>tol) by tolerance: "
              + "  ".join(f"{k}:{(v['auc'] if v['auc'] is not None else '—')}({100*v['prevalence']:.0f}%)"
                          for k, v in c.items()))
        ex = blk["ambiguous_exclusion_entropy"]
        print(f"   label-quantum-ambiguous units {ex['ambiguous_units']:,} ({100*ex['ambiguous_share']:.1f}%): "
              f"AUC all {ex['auc_all']} -> excluding {ex['auc_excluding_ambiguous']} "
              f"(Δ {ex['auc_change']:+})" if ex.get("available") else "   n/a")
        for k, v in blk["slices"].items():
            print(f"   slice {k:24s} units={v['units']:7,} prevalence={v.get('prevalence')} "
                  f"median_err={v.get('median_err_ms')}ms auc={v.get('auc')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
