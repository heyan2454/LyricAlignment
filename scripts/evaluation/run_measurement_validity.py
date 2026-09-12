#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How much of each reported boundary metric is the silent clamp rather than the model?

    PYTHONPATH=src python scripts/evaluation/run_measurement_validity.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as GG
from lyricalign.analysis import measurement_validity as V
from lyricalign.analysis import structural_compliance as SC

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_measurement_validity"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, object] = {"schema": "measurement_validity_v1",
                              "discipline": "re-reads existing panels only; canonical both_abs_err "
                                            "口径 unchanged; no new forwards", "panels": {}}

    df = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    for pl in ("official", "raw"):
        sub = df[df["pipeline"] == pl]
        blk = {"rows": int(len(sub)),
               "stages": {st: V.stage_shape(sub, s, e) for st, (s, e) in (
                   ("model_raw_slots", ("raw_start_sec", "raw_end_sec")),
                   ("shipped_pred", ("pred_start_sec", "pred_end_sec")))},
               "clamp": V.clamp_signature(sub, ("raw_start_sec", "raw_end_sec"),
                                          ("pred_start_sec", "pred_end_sec")),
               "impact": V.metric_impact(sub, pred_start="pred_start_sec", pred_end="pred_end_sec",
                                         gt_start="gt_start_sec", gt_end="gt_end_sec")}
        blk["gt_shape"] = V.stage_shape(sub, "gt_start_sec", "gt_end_sec")
        res["panels"][f"gtsinger_{pl}"] = blk

    m = pd.read_csv(RUNS / "20260912_mir1k_natural_panel/panel.csv.gz")
    res["panels"]["mir1k"] = {
        "rows": int(len(m)), "note": "panel stores shipped predictions only (no raw/fixed columns)",
        "stages": {"shipped_pred": V.stage_shape(m, "pred_start_sec", "pred_end_sec"),
                   "human_gt": V.stage_shape(m, "gt_start_sec", "gt_end_sec")},
        "impact": V.metric_impact(m, pred_start="pred_start_sec", pred_end="pred_end_sec",
                                  gt_start="gt_start_sec", gt_end="gt_end_sec"),
        "by_predictor": {str(k): V.metric_impact(g, pred_start="pred_start_sec",
                                                 pred_end="pred_end_sec",
                                                 gt_start="gt_start_sec", gt_end="gt_end_sec")
                         for k, g in m.groupby("predictor", observed=True)}}

    L = pd.read_json(RUNS / "20260912_m4_longform_weakgt/longform_units.jsonl.gz", lines=True)
    stage_pairs = [("model_raw_slots", ("raw_start_sec", "raw_end_sec")),
                   ("official_fixed", ("official_fixed_start_sec", "official_fixed_end_sec")),
                   ("selected", ("selected_start_sec", "selected_end_sec"))]
    stages = {st: V.stage_shape(L, s, e) for st, (s, e) in stage_pairs
              if s in L.columns and e in L.columns}
    clamp = (V.clamp_signature(L, ("raw_start_sec", "raw_end_sec"),
                               ("official_fixed_start_sec", "official_fixed_end_sec"))
             if "raw_start_sec" in L.columns else {"available": False})
    res["panels"]["m4_longform"] = {"rows": int(len(L)), "stages": stages, "clamp": clamp,
                                    "label_kind": "weak (rule_validated / rebuilt signed GT)"}

    # real accompanied songs: rebuild a comparable frame from the batch artifacts
    frame, meta = SC.load_batch(RUNS / "20260814_ktv_current_silence", stage="selected")
    raw, _ = SC.load_batch(RUNS / "20260814_ktv_current_silence", stage="raw")
    both = frame.merge(raw.rename(columns={"start_sec": "raw_s", "end_sec": "raw_e"}),
                       on=["song", "unit_index"], how="inner")
    both["gt_start_sec"] = both["start_sec"]          # no GT: shape only, self-consistency
    both["gt_end_sec"] = both["end_sec"]
    res["panels"]["real_songs_33"] = {
        "rows": int(len(both)), "note": "no ground truth: shape + clamp evidence only",
        "stages": {"model_raw_slots": V.stage_shape(both, "raw_s", "raw_e"),
                   "shipped_selected": V.stage_shape(both, "start_sec", "end_sec")},
        "clamp": V.clamp_signature(both, ("raw_s", "raw_e"), ("start_sec", "end_sec"))}

    (args.out_dir / "MEASUREMENT_VALIDITY.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, blk in res["panels"].items():
        print(f"\n== {name}: rows={blk['rows']:,} ==")
        for st, v in blk["stages"].items():
            if v.get("available"):
                print(f"   {st:18s} n={v['n']:7,} negative={100*v['negative_share']:6.3f}% "
                      f"zero={100*v['zero_share']:6.3f}%")
        c = blk.get("clamp", {})
        if c.get("available"):
            print(f"   clamp: present={c['clamp_present']} extra_zero_downstream="
                  f"{c['extra_zero_downstream_units']}")
        im = blk.get("impact", {})
        if im.get("available"):
            ex = im.get("hit_at_tol_excluding_degenerate")
            print(f"   impact: hit@100 {100*im['hit_at_tol']:.2f}% -> excluding degenerate "
                  f"{100*(ex if ex is not None else float('nan')):.2f}% "
                  f"(bound {im.get('contamination_bound_pp'):+.2f}pp); "
                  f"degenerate {100*im['degenerate_share']:.2f}%"
                  + (f"; inverted n={im.get('inverted_units')} hit {100*im.get('inverted_hit_at_tol', 0):.1f}%"
                     if im.get("inverted_units") else ""))
    print("\nby_predictor (MIR-1K) contamination bounds:")
    for k, v in res["panels"]["mir1k"]["by_predictor"].items():
        print(f"   {k:20s} hit {100*v['hit_at_tol']:.2f}% -> {100*v.get('hit_at_tol_excluding_degenerate', float('nan')):.2f}% "
              f"({v.get('contamination_bound_pp'):+.2f}pp), degenerate {100*v['degenerate_share']:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
