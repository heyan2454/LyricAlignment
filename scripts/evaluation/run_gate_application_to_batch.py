#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the learned acceptance rates to the product batch and audit what gets waved through.

Two things from earlier rounds shape this script:

* absolute entropy thresholds do not transfer between corpora (round 27: a threshold that looked
  sane on GTSinger flagged 68.7 % of the product batch), so the only honest way to apply the
  GTSinger-learned policy here is to **match the acceptance rate** with a within-batch quantile;
* the batch has no ground truth, so the accepted set cannot be scored for accuracy.  What it *can*
  be scored for, without labels, is **structural safety**: zero-length / overshoot / overlap /
  start-regression violations, window-anchor pinning, and raw inversions.  If the gate's accepted
  set is structurally as clean as the whole batch, the rate-matched policy is at least not
  concentrating obvious breakage; if it is cleaner, the score carries real information.

Reads the shipped batch artifacts plus the round-26 gap features. No forwards, no GPU.

    PYTHONPATH=src python scripts/evaluation/run_gate_application_to_batch.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import structural_compliance as SC
from lyricalign.analysis import trigger_fusion as TF

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_gate_batch_application"
BATCH = RUNS / "20260814_ktv_current_silence"

# acceptance rates learned on GTSinger at the 200 ms edge under a 5 % false-safe budget (round 38)
RATES = {"r1_entropy": 0.7630, "r3_entropy_inversion_gap": 0.8501}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    sel, _meta = SC.load_batch(args.batch, stage="selected")
    raw, _ = SC.load_batch(args.batch, stage="raw")
    frame = sel[["song", "language", "unit_index", "start_sec", "end_sec",
                 "ent_start", "ent_end"]].rename(columns={"ent_end": "raw_entropy_end",
                                                          "ent_start": "raw_entropy_start",
                                                          "start_sec": "pred_start_sec",
                                                          "end_sec": "pred_end_sec"})
    frame = frame.merge(raw[["song", "unit_index", "start_sec", "end_sec"]].rename(
        columns={"start_sec": "raw_start_sec", "end_sec": "raw_end_sec"}),
        on=["song", "unit_index"], how="inner")
    gaps = pd.read_csv(RUNS / "20260912_gap_shape/real_song_gap_features.csv.gz")
    frame = frame.merge(gaps[["song", "unit_index", "gap_over_core"]],
                        on=["song", "unit_index"], how="left")
    feats = TF.build_features(frame)
    ent = TF._num(feats, "raw_entropy_end").rank(pct=True)
    inv = TF._num(feats, "f_inversion").fillna(0.0)
    gap = TF._num(feats, "gap_over_core").rank(pct=True)
    feats["r1_entropy"] = ent
    feats["r3_entropy_inversion_gap"] = pd.concat([ent, inv, gap], axis=1).mean(axis=1, skipna=True)

    # structural violations are measured per song on the shipped timeline, by the module's own helper
    viol = SC.flag_violations(sel)
    FLAG_COLS = ["flag_zero_or_negative", "flag_overshoot", "flag_overlaps_next",
                 "flag_start_regression", "is_illegal"]
    viol = viol.reset_index(drop=True)
    feats = feats.reset_index(drop=True)
    base = {c: round(float(viol[c].mean()), 4) for c in FLAG_COLS}
    res: dict[str, Any] = {"schema": "gate_batch_application_v1",
                           "discipline": "no ground truth on this batch: acceptance rates are "
                                         "rate-matched from GTSinger (absolute thresholds do not "
                                         "transfer, round 27) and the accepted set is audited for "
                                         "STRUCTURAL safety only; nothing here is an accuracy claim",
                           "batch": str(args.batch), "units": int(len(feats)),
                           "gap_feature_coverage": round(float(
                               TF._num(feats, "gap_over_core").notna().mean()), 4),
                           "whole_batch_violations": base, "policies": {}}

    for rung, rate in RATES.items():
        score = pd.to_numeric(feats[rung], errors="coerce")
        cut = score.quantile(rate)   # accept the least-suspicious `rate` fraction
        accepted = score <= cut
        sub = viol[accepted.to_numpy(dtype=bool)]
        rejected = viol[(~accepted).to_numpy(dtype=bool)]
        per_lang = {}
        for lang, g in feats.assign(_acc=accepted.to_numpy(dtype=bool)).groupby("language", observed=True):
            per_lang[str(lang)] = {"units": int(len(g)), "accepted_share": round(float(g["_acc"].mean()), 4)}
        per_song = (feats.assign(_acc=accepted.to_numpy(dtype=bool))
                    .groupby(["song", "language"], observed=True)["_acc"].agg(["size", "mean"]))
        worst = per_song.sort_values("mean").head(8)
        res["policies"][rung] = {
            "target_accept_rate": rate, "realised_accept_rate": round(float(accepted.mean()), 4),
            "threshold_within_batch": round(float(cut), 4),
            "accepted_violations": {c: round(float(sub[c].mean()), 4) for c in base},
            "rejected_violations": {c: round(float(rejected[c].mean()), 4) for c in base},
            "safety_lift_accepted_vs_rejected": {
                c: round(float(rejected[c].mean() - sub[c].mean()), 4) for c in base},
            "by_language": per_lang,
            "review_budget_concentration": {
                "songs_fully_rejected": int((per_song["mean"] <= 1e-9).sum()),
                "least_accepted_songs": [{"song": str(i[0]), "language": str(i[1]),
                                          "units": int(s), "accepted_share": round(float(m), 4)}
                                         for i, (s, m) in worst.iterrows()]},
        }
    # agreement between the two rungs: which units does the richer policy newly accept?
    s1 = pd.to_numeric(feats["r1_entropy"], errors="coerce")
    s3 = pd.to_numeric(feats["r3_entropy_inversion_gap"], errors="coerce")
    a1 = (s1 <= s1.quantile(RATES["r1_entropy"])).to_numpy(dtype=bool)
    a3 = (s3 <= s3.quantile(RATES["r3_entropy_inversion_gap"])).to_numpy(dtype=bool)
    newly = (~a1) & a3
    withdrawn = a1 & (~a3)
    res["rung_agreement"] = {
        "both_accept": int((a1 & a3).sum()), "newly_accepted_by_r3": int(newly.sum()),
        "withdrawn_by_r3": int(withdrawn.sum()),
        "jaccard": round(float((a1 & a3).sum() / max((a1 | a3).sum(), 1)), 4),
        "newly_accepted_violations": {c: round(float(viol[newly][c].mean()), 4) for c in base},
        "withdrawn_violations": {c: round(float(viol[withdrawn][c].mean()), 4) for c in base},
        "gap_coverage_among_newly_accepted": (round(float(np.isfinite(
            TF._num(feats, "gap_over_core").to_numpy(dtype=float)[newly]).mean()), 4)
            if newly.any() else None)}
    (args.out_dir / "GATE_BATCH_APPLICATION.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"batch units={res['units']:,} gap-feature coverage={100 * res['gap_feature_coverage']:.1f}%")
    print("whole-batch structural violations:", json.dumps(base, ensure_ascii=False))
    for rung, blk in res["policies"].items():
        print(f"\n== {rung}: realised accept {100 * blk['realised_accept_rate']:.2f}% "
              f"(target {100 * blk['target_accept_rate']:.2f}%) ==")
        for c in list(base)[:4]:
            print(f"   {c:28s} accepted={100 * blk['accepted_violations'][c]:5.2f}% "
                  f"rejected={100 * blk['rejected_violations'][c]:5.2f}% "
                  f"lift={100 * blk['safety_lift_accepted_vs_rejected'][c]:+5.2f}pp")
        print("   by language: " + ", ".join(f"{k}:{100*v['accepted_share']:.1f}%({v['units']})"
                                             for k, v in blk["by_language"].items()))
        print("   least-accepted songs: " + ", ".join(
            f"{x['song'][:14]}({x['language'][:3]}) {100*x['accepted_share']:.0f}%"
            for x in blk["review_budget_concentration"]["least_accepted_songs"][:5]))
    ag = res["rung_agreement"]
    print(f"\nrung agreement: both={ag['both_accept']:,} newly_by_r3={ag['newly_accepted_by_r3']:,} "
          f"withdrawn={ag['withdrawn_by_r3']:,} jaccard={ag['jaccard']}")
    for c in list(base)[:3]:
        print(f"   {c:28s} newly={100 * ag['newly_accepted_violations'][c]:5.2f}% "
              f"withdrawn={100 * ag['withdrawn_violations'][c]:5.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
