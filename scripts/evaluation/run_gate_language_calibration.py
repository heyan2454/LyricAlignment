#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Global vs per-language acceptance thresholds: capture efficiency versus review-burden equity.

Round 39 showed that one global quantile silently allocates the review budget by language
(Mandarin accepted 94.1 %, Japanese 27.1 %).  The intuitive fix — equalise the acceptance rate
inside each language — is a fairness change, not an accuracy change, and it is not free: the
structural evidence is concentrated in exactly the languages the global rule already scrutinises.
This script measures both policies at the same total acceptance rate and reports the trade-off in
the only units available without ground truth: share of structurally illegal units caught in the
review queue, and how the queue is distributed across languages.

    PYTHONPATH=src python scripts/evaluation/run_gate_language_calibration.py
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
OUT = RUNS / "20260912_gate_language_calibration"
BATCH = RUNS / "20260814_ktv_current_silence"
RATES = (0.70, 0.763, 0.85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    sel, _meta = SC.load_batch(args.batch, stage="selected")
    raw, _ = SC.load_batch(args.batch, stage="raw")
    frame = sel[["song", "language", "unit_index", "start_sec", "end_sec", "ent_end"]].rename(
        columns={"ent_end": "raw_entropy_end"}).copy()
    frame = frame.merge(raw[["song", "unit_index", "start_sec", "end_sec"]].rename(
        columns={"start_sec": "raw_start_sec", "end_sec": "raw_end_sec"}),
        on=["song", "unit_index"], how="inner")
    gaps = pd.read_csv(RUNS / "20260912_gap_shape/real_song_gap_features.csv.gz")
    frame = frame.merge(gaps[["song", "unit_index", "gap_over_core"]], on=["song", "unit_index"],
                        how="left")
    feats = TF.build_features(frame).reset_index(drop=True)
    score = pd.to_numeric(feats["raw_entropy_end"], errors="coerce").rank(pct=True).to_numpy(dtype=float)
    langs = feats["language"].astype(str)
    viol = SC.flag_violations(sel.reset_index(drop=True))
    illegal = viol["is_illegal"].to_numpy(dtype=bool)
    zero = viol["flag_zero_or_negative"].to_numpy(dtype=bool)
    per_lang_illegal = {str(k): round(float(illegal[(langs == k).to_numpy()].mean()), 4)
                        for k in sorted(langs.unique())}

    # third policy: equalise the *risk* inside each language's accepted set instead of the rate.
    # The target is whatever the global rule achieves, and the per-language illegal rates used to
    # hit it come from the structural labels themselves, so this is a frontier reference
    # (what equal risk would cost), not a deployable rule.
    global_illegal_in_accepted = None
    res: dict[str, Any] = {"schema": "gate_language_calibration_v2",
                           "discipline": "no ground truth: everything is structural. Both policies "
                                         "are applied at the same total acceptance rate, so the only "
                                         "difference is which units (and whose) are reviewed",
                           "batch": str(args.batch), "units": int(len(feats)),
                           "batch_illegal_share": round(float(illegal.mean()), 4),
                           "batch_zero_length_share": round(float(zero.mean()), 4),
                           "illegal_share_by_language": per_lang_illegal,
                           "policies": {}}
    for rate in RATES:
        global_cut = np.nanquantile(score, rate)
        acc_global = score <= global_cut
        acc_lang = np.zeros(len(score), dtype=bool)
        cuts = {}
        for k in sorted(langs.unique()):
            m = (langs == k).to_numpy()
            c = np.nanquantile(score[m], rate)
            cuts[k] = round(float(c), 4)
            acc_lang[m] = score[m] <= c
        g = SC.policy_audit(acc_global, viol, langs)
        l = SC.policy_audit(acc_lang, viol, langs)
        g["illegal_capture_zero_length"] = round(float(zero[(~acc_global)].sum() / max(zero.sum(), 1)), 4)
        l["illegal_capture_zero_length"] = round(float(zero[(~acc_lang)].sum() / max(zero.sum(), 1)), 4)
        g["threshold_within_batch"] = round(float(global_cut), 4)
        global_illegal_in_accepted = float(illegal[acc_global].mean())
        acc_risk = np.zeros(len(score), dtype=bool)
        lang_targets = {}
        for k in sorted(langs.unique()):
            m = (langs == k).to_numpy()
            order = np.argsort(score[m], kind="stable")
            s_sub, i_sub = score[m][order], illegal[m][order]
            cum_bad = np.cumsum(i_sub)
            n_sub = np.arange(1, s_sub.size + 1)
            feasible = cum_bad / n_sub <= max(global_illegal_in_accepted, 1e-9)
            take = int(np.argmax(~feasible)) if (~feasible).any() else s_sub.size
            idx = np.zeros(s_sub.size, dtype=bool)
            idx[:take] = True
            acc_risk[m] = idx[order]
            lang_targets[k] = {"accept_share": round(float(idx.mean()), 4),
                               "illegal_in_accepted": round(
                                   float(illegal[m][idx].mean()), 4) if idx.any() else None}
        l["threshold_per_language"] = cuts
        res["policies"][f"{int(rate * 100)}pct"] = {
            "global": g, "per_language": l,
            "risk_parity_units": int(acc_risk.sum()),
        "per_language_targets_risk_parity": lang_targets,
        **{"risk_parity": SC.policy_audit(acc_risk, viol, langs)},
        "delta_capture_pp": round(100.0 * (l["illegal_capture_of_all_illegal"]
                                               - g["illegal_capture_of_all_illegal"]), 2),
            "delta_zero_capture_pp": round(100.0 * (l["illegal_capture_zero_length"]
                                                    - g["illegal_capture_zero_length"]), 2),
            "max_abs_review_share_difference_by_language": {
                k: round(abs(l["review_share_by_language"][k] - g["review_share_by_language"][k]), 4)
                for k in g["review_share_by_language"]}}
    (args.out_dir / "LANGUAGE_CALIBRATION.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"batch units={res['units']:,} illegal={100 * res['batch_illegal_share']:.2f}% "
          f"zero-length={100 * res['batch_zero_length_share']:.2f}%")
    print("illegal share by language:", json.dumps(per_lang_illegal, ensure_ascii=False))
    for key, blk in res["policies"].items():
        g, l = blk["global"], blk["per_language"]
        print(f"\n== total accept {key} ==")
        print(f"   global      : review={100 * g['review_share']:5.2f}%  illegal capture={100 * g['illegal_capture_of_all_illegal']:5.1f}%  "
              f"zero capture={100 * g['illegal_capture_zero_length']:5.1f}%  "
              f"队列语言构成={ {k: round(100 * v, 1) for k, v in g['review_share_by_language'].items()} }")
        print(f"   per-language: review={100 * l['review_share']:5.2f}%  illegal capture={100 * l['illegal_capture_of_all_illegal']:5.1f}%  "
              f"zero capture={100 * l['illegal_capture_zero_length']:5.1f}%  "
              f"队列语言构成={ {k: round(100 * v, 1) for k, v in l['review_share_by_language'].items()} }")
        rp = blk.get("risk_parity") or {}
        if rp:
            rp["illegal_capture_zero_length"] = round(
                float(zero[~acc_risk].sum() / max(zero.sum(), 1)), 4)
            print(f"   risk-parity : accept={100 * rp['accept_share']:5.2f}%  review={100 * rp['review_share']:5.2f}%  "
                  f"illegal capture={100 * rp['illegal_capture_of_all_illegal']:5.1f}%  "
                  f"复核率按语言={ {k: round(100 * v, 1) for k, v in rp['review_share_by_language'].items()} }")
            print(f"      (equal-risk target = global 的放行集合非法率 {100 * global_illegal_in_accepted:.2f}%)")
        print(f"   Δcapture(per-lang − global) {blk['delta_capture_pp']:+.2f}pp, Δzero {blk['delta_zero_capture_pp']:+.2f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
