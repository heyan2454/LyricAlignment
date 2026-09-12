#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test the accompaniment-bleed mechanism behind the accompanied-domain late-end bias.

    PYTHONPATH=src python scripts/evaluation/run_accompaniment_leak.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import accompaniment_leak as AL

RUNS = Path("/home/hyan/Data/lyricalign/runs")
STEREO = Path("/home/hyan/Data/datasets/mir1k/raw/MIR-1K/UndividedWavfile")
OUT = RUNS / "20260912_accompaniment_leak"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--predictor", default="r2_full_20260723")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(RUNS / "20260912_mir1k_natural_panel/panel.csv.gz")
    sub = m[(m["predictor"] == args.predictor)].dropna(
        subset=["gt_start_sec", "gt_end_sec", "pred_start_sec", "pred_end_sec"]).copy()
    res = {"schema": "accompaniment_leak_v1", "predictor": args.predictor,
           "stereo_dir": str(STEREO),
           "input_note": "MIR-1K vocal input is channel-selected (ch1 of the original stereo mix), "
                         "not source-separated"}
    res["profile"] = AL.profile_leak(sub, STEREO) if STEREO.exists() else {"available": False}
    auc = (res["profile"] or {}).get("auc_bleed_share_predicts_late", {})
    print("\n  AUC(bleed share -> lands late>100ms): "
          f"all_units={auc.get('all_units')} long_note={auc.get('long_note')} "
          f"(base rate {auc.get('base_rate_late_all')})")
    print("  corr(end_err, vocal_rms@pred_end) all units = "
          f"{(res['profile'] or {}).get('corr_end_err_vs_vocal_rms_at_pred_end_all_units')}")
    # compact per-unit feature table: only the interesting units, no audio copies
    if res["profile"].get("available"):
        keep = res["profile"].get("per_unit")
        if keep is not None:
            pd.DataFrame(keep).to_csv(args.out_dir / "per_unit_features.csv.gz", index=False,
                                      compression="gzip")
    (args.out_dir / "LEAK.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    p = res["profile"]
    if not p.get("available"):
        print(json.dumps(p, ensure_ascii=False))
        return 1
    print(f"predictor={args.predictor} units={p['units']:,} stereo_files={p['stereo_files_used']} "
          f"lead_window={p['lead_window_sec']}s")
    for name, st in p["strata"].items():
        a = st["accomp_at_pred_gt_than_at_gt"]
        v = st["vocal_at_pred_gt_than_at_gt"]
        print(f"\n  {name}: units={st['units']} ends_late={st['ends_late_share']:.3f} "
              f"median_end_err={st['median_end_err_ms']:+.1f}ms hit@100={st['hit100']:.3f}")
        print(f"    accomp energy at pred-end vs gt-end: n={a.get('n')} median_diff={a.get('median_diff')} "
              f"share_higher={a.get('share_higher_in_pred')} rank_biserial={a.get('rank_biserial')} "
              f"p={a.get('sign_test_p_two_sided')}")
        print(f"    vocal   energy at pred-end vs gt-end: n={v.get('n')} median_diff={v.get('median_diff')} "
              f"share_higher={v.get('share_higher_in_pred')} rank_biserial={v.get('rank_biserial')} "
              f"p={v.get('sign_test_p_two_sided')}")
        print(f"    accomp share in lead(0-{p['lead_window_sec']}s after GT end): "
              f"{st.get('median_accomp_share_in_lead')} | accomp_rms {st.get('median_accomp_lead_rms')} "
              f"vs vocal_rms {st.get('median_vocal_lead_rms')}")
        for k in [k for k in st if k.startswith("corr_")]:
            print(f"    {k} = {st[k]}")
    print("\n  accomp share in lead, by outcome:")
    for k, v in p["accomp_share_in_lead_by_outcome"].items():
        print(f"    {k:22s} n={v['n']} median={v['median']} p90={v['p90']}")
    print("\n  caveat:", p["caveat"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
