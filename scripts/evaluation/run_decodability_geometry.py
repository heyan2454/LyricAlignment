#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is the unreachable ground truth *between* the candidates or *outside* them? And which way?

    PYTHONPATH=src python scripts/evaluation/run_decodability_geometry.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import decodability_ceiling as D
from lyricalign.analysis import gtsinger_gt_deep as GG

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_decodability_ceiling"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    g = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    d = g[g["pipeline"] == "official"].dropna(
        subset=["raw_start_sec", "raw_end_sec", "raw_top2cls_start", "raw_top2cls_end",
                "gt_start_sec", "gt_end_sec", "pred_start_sec", "pred_end_sec"]).copy()
    dur = pd.to_numeric(d["gt_dur_sec"], errors="coerce").to_numpy(dtype=float)
    grp = d.groupby(["item", "model", "audio_input", "mode"], observed=True)["unit_index"]
    strata = {"all_units": np.ones(len(d), dtype=bool),
              "long_note": dur >= 1.0, "short_note": dur < 0.4,
              "first_unit": (grp.transform("min") == d["unit_index"]).to_numpy(dtype=bool),
              "last_unit": (grp.transform("max") == d["unit_index"]).to_numpy(dtype=bool)}
    geometry = {}
    for name, mask in strata.items():
        sub = d[mask]
        geometry[name] = {
            "units": int(len(sub)),
            "end": D.unreachable_geometry(sub, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                                          gt_sec="gt_end_sec", entropy_col="raw_entropy_end",
                                          margin_col="raw_margin_end"),
            "start": D.unreachable_geometry(sub, pred_sec="raw_start_sec", top2cls="raw_top2cls_start",
                                            gt_sec="gt_start_sec", entropy_col="raw_entropy_start",
                                            margin_col="raw_margin_start")}
    studio_bias = D.bias_by_stratum(d, strata=strata)

    m = pd.read_csv(RUNS / "20260912_mir1k_natural_panel/panel.csv.gz")
    mr = m[m["predictor"] == "r2_full_20260723"].copy()
    mdur = pd.to_numeric(mr["gt_dur_sec"], errors="coerce").to_numpy(dtype=float)
    mstrata = {"all_units": np.ones(len(mr), dtype=bool),
               "long_note": mdur >= 1.0, "short_note": mdur < 0.4,
               "last_unit": mr["is_last_char"].to_numpy(dtype=float) == 1.0,
               "first_unit": mr["is_first_char"].to_numpy(dtype=float) == 1.0}
    target_bias = D.bias_by_stratum(mr, strata=mstrata)

    check = D.transfer_direction_check(studio_bias, target_bias, "long_note")
    res = {"schema": "decodability_geometry_v1",
           "discipline": "GTSinger (human GT, not test) drives the conclusion; MIR-1K is test-only "
                         "and is used here only to report the *direction* of its own bias, never to "
                         "calibrate anything",
           "timestamp_step_sec": D.TIMESTAMP_STEP_SEC, "geometry": geometry,
           "studio_end_bias_gtsinger": studio_bias, "target_end_bias_mir1k": target_bias,
           "transfer_check_long_note_end": check}
    (args.out_dir / "GEOMETRY.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    print(f"{'stratum':12s} {'units':>6s} {'unreach%':>9s} {'between%':>9s} {'outside%':>9s} "
          f"{'L%':>5s} {'R%':>5s} {'span_med':>8s} {'outdist':>8s}")
    for name, blk in geometry.items():
        ee = blk["end"]
        print(f"{name:12s} {blk['units']:6,} {100 * ee['unreachable_share']:8.2f}% "
              f"{100 * (ee['between_candidates_share_of_unreachable'] or 0):8.2f}% "
              f"{100 * (ee['outside_span_share_of_unreachable'] or 0):8.2f}% "
              f"{100 * (ee['outside_left_share_of_unreachable'] or 0):4.1f}% "
              f"{100 * (ee['outside_right_share_of_unreachable'] or 0):4.1f}% "
              f"{ee['candidate_span_bins_when_unreachable'].get('median_sec')}s "
              f"{ee['distance_outside_bins'].get('median_sec_when_outside')}s")
    print("\nend-bias direction (pred - human GT):")
    for tag, blk in (("GTSinger r2 (studio)", studio_bias), ("MIR-1K r2_full (accompanied)", target_bias)):
        for name, v in blk.items():
            e = v["end"]
            print(f"   {tag:28s} {name:11s} n={v['units']:6,} median {e['median_ms']:+7.1f}ms "
                  f"mean {e['mean_ms']:+7.1f}ms late-share {e['late_share']:.3f}")
    print("\ntransfer verdict:", json.dumps(check, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
