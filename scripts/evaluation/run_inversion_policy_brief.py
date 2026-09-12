#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Price the candidate inversion-handling policies against ground truth (shadow-only).

    PYTHONPATH=src python scripts/evaluation/run_inversion_policy_brief.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import inversion_policy as P

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_inversion_policy"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, object] = {"schema": "inversion_policy_brief_v1",
                              "discipline": "per-unit policy application on inverted units only; "
                                            "shadow-only, no production behaviour changed",
                              "panels": {}}

    g = pd.read_json(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz", lines=True)
    gr = g[g["pipeline"] == "raw"].copy()
    res["panels"]["gtsinger_raw_human_gt"] = P.evaluate_policies(
        gr, start_col="raw_start_sec", end_col="raw_end_sec",
        gt_start="gt_start_sec", gt_end="gt_end_sec", seq_col="item")
    res["panels"]["gtsinger_raw_human_gt"]["decision"] = P.decision_summary(
        res["panels"]["gtsinger_raw_human_gt"])

    L = pd.read_json(RUNS / "20260912_m4_longform_weakgt/longform_units.jsonl.gz", lines=True)
    blk = P.evaluate_policies(L, start_col="raw_start_sec", end_col="raw_end_sec",
                              gt_start="gt_start_sec", gt_end="gt_end_sec",
                              seq_col="request_identity")
    blk["decision"] = P.decision_summary(blk)
    blk["label_kind"] = "weak (signed GT rebuilt from segment labels, 80 ms quantised)"
    blk["by_split"] = {str(k): P.evaluate_policies(sub, seq_col="request_identity")["inverted_units"]
                       for k, sub in L.groupby("split", observed=True)}
    res["panels"]["m4_longform_weak_gt"] = blk

    from lyricalign.analysis import structural_compliance as SC
    batch = RUNS / "20260814_ktv_current_silence"
    if batch.exists():
        sel, _meta_s = SC.load_batch(batch, stage="selected")
        raw, _meta_r = SC.load_batch(batch, stage="raw")
        merged = sel[["song", "unit_index", "start_sec", "end_sec", "audio_duration_sec"]].merge(
            raw[["song", "unit_index", "start_sec", "end_sec"]]
            .rename(columns={"start_sec": "raw_s", "end_sec": "raw_e"}),
            on=["song", "unit_index"], how="inner")
        struct = P.structural_consequence(merged)
        struct["batch"] = str(batch)
        (args.out_dir / "STRUCTURAL_CONSEQUENCE.json").write_text(
            json.dumps(struct, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n== structural consequence ({batch.name}) ==")
        print(f"   inverted {struct['inverted_units']} ({100*struct['inverted_share']:.2f}%), "
              f"gap median {struct['inversion_gap_median_sec']}s p90 {struct['inversion_gap_p90_sec']}s")
        for k, v in struct["policies"].items():
            print(f"   {k:28s} illegal={100*v['illegal_share']:5.2f}% zero={100*v['degenerate_share']:5.2f}% "
                  f"overlap={100*v['overlap_share']:5.2f}% regression={100*v['regression_share']:5.2f}%")
    (args.out_dir / "INVERSION_POLICY.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, blk in res["panels"].items():
        print(f"\n== {name}: units={blk['units']:,} inverted={blk['inverted_units']:,} "
              f"({100*blk['inverted_share']:.3f}%) ==")
        d = blk.get("decision", {})
        if not d.get("available"):
            print("   no inverted units with GT")
            continue
        print(f"   best policy: {d['best_policy']}  gain vs shipped {d['gain_vs_shipped_pp']:+.2f}pp")
        print(f"   {'policy':28s} {'hit@100':>8s} {'MAE(end)':>9s} {'bias(end)':>10s} {'zero-len':>9s} {'illegal':>8s}")
        for r in d["ranking"]:
            print(f"   {r['policy']:28s} {100*r['hit_at_tol']:7.2f}% {r['mae_end_sec']*1000:8.1f}ms "
                  f"{r['bias_end_sec']*1000:+9.1f}ms {100*r['zero_length_share']:8.2f}% "
                  f"{100*r['duration_violation_share']:7.2f}%")
        print(f"   trigger cost (flag share if policy = mark-and-redecode): {100*d['trigger_cost_share']:.3f}%")
    print("\nM4 inverted units by split:", json.dumps(res["panels"]["m4_longform_weak_gt"]["by_split"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
