#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does the joint constrained solve help or hurt the LAST unit of a sequence? (human GT)

Round 4/5 located the Mandarin failure layer on the last character of an item (long sustained notes).
Round 7 showed the joint solve improves overall accuracy on GTSinger, but never reported the
last-unit stratum, which is the stratum that decides whether the solve is safe to ship.

    PYTHONPATH=src python scripts/evaluation/run_last_unit_validation.py
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
from lyricalign.analysis import joint_cleanup as J
from lyricalign.analysis import longform_signed_gt as G

OUT = Path("/home/hyan/Data/lyricalign/runs/20260912_last_unit_validation")


def _metrics(gt_s, gt_e, s, e, tol=0.1):
    err = np.maximum(np.abs(s - gt_s), np.abs(e - gt_e))
    ok = np.isfinite(err)
    return {"n": int(ok.sum()),
            "hit100": round(float(np.mean(err[ok] <= tol)), 4),
            "hit250": round(float(np.mean(err[ok] <= 0.25)), 4),
            "mae_end_sec": round(float(np.mean(np.abs(e[ok] - gt_e[ok]))), 4),
            "median_signed_end_sec": round(float(np.median((e[ok] - gt_e[ok]))), 4)}


def gtsinger(alpha: float) -> dict[str, Any]:
    df = GG.load_panel(Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep"
                            "/unit_evidence.jsonl.gz"))
    d = df[(df["pipeline"] == "official")].dropna(
        subset=["raw_start_sec", "raw_end_sec", "pred_start_sec", "pred_end_sec",
                "gt_start_sec", "gt_end_sec"]).copy()
    # a sequence is one (run, item, model, audio_input, mode): the same unit also appears in other
    # runs, and mixing runs inside a group makes the monotone constraint scramble the timeline
    SEQ = ["run", "item", "model", "audio_input", "mode"]
    last_of_item = d.groupby(SEQ, observed=True)["unit_index"].transform("max")
    # sorting first is essential: the solve enforces monotone starts, so feeding a group in panel
    # order (not time order) would make it "repair" an artificial permutation instead of the timeline
    d = d.sort_values(["run", "item", "model", "audio_input", "mode", "unit_index"]).reset_index(drop=True)
    d["is_last_unit"] = d["unit_index"].to_numpy() == last_of_item.to_numpy()
    d["is_first_unit"] = d.groupby(SEQ, observed=True)["unit_index"].transform("min").to_numpy() == \
        d["unit_index"].to_numpy()
    groups = (d[SEQ[0]].astype(str) + "|" + d[SEQ[1]].astype(str) + "|" + d[SEQ[2]].astype(str) +
              "|" + d[SEQ[3]].astype(str) + "|" + d[SEQ[4]].astype(str)).to_numpy(dtype=object)
    frame = pd.DataFrame({"grp": groups, "s": d["raw_start_sec"].to_numpy(dtype=float),
                          "e": d["raw_end_sec"].to_numpy(dtype=float),
                          "es": d["raw_entropy_start"].to_numpy(dtype=float),
                          "ee": d["raw_entropy_end"].to_numpy(dtype=float),
                          "dur": d["audio_dur_sec"].to_numpy(dtype=float)})
    S = np.empty(len(frame))
    E = np.empty(len(frame))
    for _k, sub in frame.groupby("grp", observed=True):
        pos = frame.index.get_indexer(sub.index)
        s_arr, e_arr, _rep = J.solve_block(sub["s"].to_numpy(dtype=float),
                                          sub["e"].to_numpy(dtype=float),
                                          ent_start=sub["es"].to_numpy(dtype=float),
                                          ent_end=sub["ee"].to_numpy(dtype=float),
                                          audio_dur=float(np.nanmax(sub["dur"].to_numpy(dtype=float))),
                                          alpha=alpha)
        S[pos] = s_arr
        E[pos] = e_arr
    gt_s = d["gt_start_sec"].to_numpy(dtype=float)
    gt_e = d["gt_end_sec"].to_numpy(dtype=float)
    out: dict[str, Any] = {"panel": {"units": int(len(d)), "sequences": int(len(set(groups))),
                                     "reference": "human GTSinger word-level GT",
                                     "last_units": int(d["is_last_unit"].sum()),
                                     "long_last_units": int((d["is_last_unit"] &
                                                             (d["gt_dur_sec"] >= 1.0)).sum())}}
    strata = {"all_units": np.ones(len(d), dtype=bool),
              "first_unit": d["is_first_unit"].to_numpy(dtype=bool),
              "last_unit": d["is_last_unit"].to_numpy(dtype=bool),
              "last_unit_long_note": (d["is_last_unit"] & (d["gt_dur_sec"] >= 1.0)).to_numpy(dtype=bool),
              "middle_units": (~d["is_first_unit"] & ~d["is_last_unit"]).to_numpy(dtype=bool)}
    systems = {"raw_none": (d["raw_start_sec"].to_numpy(dtype=float), d["raw_end_sec"].to_numpy(dtype=float)),
               "shipped_official": (d["pred_start_sec"].to_numpy(dtype=float),
                                    d["pred_end_sec"].to_numpy(dtype=float)),
               f"joint_solve_alpha{alpha:g}": (S, E)}
    out["systems"] = {name: {label: _metrics(gt_s[m], gt_e[m], s[m], e[m])
                             for label, m in strata.items()}
                      for name, (s, e) in systems.items()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.0)
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res = {"schema": "last_unit_validation_v1", "gtsinger": gtsinger(args.alpha)}
    (args.out_dir / "LAST_UNIT.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    g = res["gtsinger"]
    print(f"GTSinger: {g['panel']['units']:,} units / {g['panel']['sequences']} sequences; "
          f"last units={g['panel']['last_units']:,}, long-note last units={g['panel']['long_last_units']}")
    labels = ["all_units", "first_unit", "middle_units", "last_unit", "last_unit_long_note"]
    print(f"\n{'system':26s} " + " ".join(f"{l[:11]:>12s}" for l in labels))
    for name, strata in g["systems"].items():
        print(f"{name:26s} " + " ".join(f"{100*strata[l]['hit100']:11.2f}%" for l in labels))
    print("\nMAE(end) by stratum:")
    for name, strata in g["systems"].items():
        print(f"  {name:26s} " + " ".join(f"{l[:11]}={strata[l]['mae_end_sec']:.4f}" for l in labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
