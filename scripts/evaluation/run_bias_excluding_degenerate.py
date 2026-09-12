#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does the cross-domain flip in long-note end bias survive removing the collapsed units?

Round 21 measured long-note endings as early in studio material (GTSinger) and late in accompanied
material (MIR-1K), which is why a global offset correction was ruled out.  Rounds 45-50 then showed
that a few percent of every prediction has no duration at all, and a zero-length prediction sits
wherever the upstream repair put it — so the medians could be partly describing that damage.

Recompute the same strata with and without the degenerate units; the conclusion is only kept if the
sign flip survives.

    PYTHONPATH=src python scripts/evaluation/run_bias_excluding_degenerate.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import decodability_ceiling as DC
from lyricalign.analysis import gtsinger_gt_deep as GG

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_bias_excluding_degenerate"
MIR_PREDICTOR = "r2_full_20260723"


def bias_view(frame: pd.DataFrame, *, label: str) -> dict[str, Any]:
    """Signed end/start bias for the same strata, with and without degenerate units."""
    out: dict[str, Any] = {"units": int(len(frame))}
    degenerate = (pd.to_numeric(frame["pred_end_sec"], errors="coerce")
                  - pd.to_numeric(frame["pred_start_sec"], errors="coerce") <= 1e-9)
    for name, keep in (("all", pd.Series(True, index=frame.index)),
                       ("excluding_degenerate", ~degenerate),
                       ("degenerate_only", degenerate)):
        sub = frame[keep.to_numpy(dtype=bool)]
        if len(sub) < 10:
            out[name] = {"units": int(len(sub)), "note": "too few units"}
            continue
        strata = {"all_units": np.ones(len(sub), dtype=bool)}
        dur = pd.to_numeric(sub["gt_dur_sec"], errors="coerce")
        strata["long_note"] = (dur >= 1.0).fillna(False).to_numpy(dtype=bool)
        strata["short_note"] = (dur < 0.3).fillna(False).to_numpy(dtype=bool)
        per = DC.bias_by_stratum(sub, strata=strata)
        entry: dict[str, Any] = {"units": int(len(sub)),
                                 "degenerate_share_of_slice": round(float(degenerate[keep].mean()), 4)}
        for stratum, block in (per or {}).items():
            end = block.get("end") or {}
            if end.get("available"):
                entry[stratum] = {"units_in_stratum": int(block.get("units", 0)),
                                  "median_ms": end.get("median_ms"),
                                  "mean_ms": end.get("mean_ms"),
                                  "late_share": end.get("late_share")}
        out[name] = entry
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    studio = panel[(panel["pipeline"] == "official") & (panel["model"] == "r2")].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec", "gt_dur_sec"])

    mir = pd.read_csv(RUNS / "20260912_mir1k_natural_panel/panel.csv.gz")
    target = mir[mir["predictor"] == MIR_PREDICTOR].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec", "gt_dur_sec"])

    pooled = panel[panel["pipeline"] == "official"].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec", "gt_dur_sec"])
    studio_view = bias_view(studio, label="studio")
    pooled_view = bias_view(pooled, label="studio_pooled")
    target_view = bias_view(target, label="target")
    res: dict[str, Any] = {"schema": "bias_excluding_degenerate_v2",
                           "predictor": "gtsinger official r2 (all items) / mir1k " + MIR_PREDICTOR,
                           "studio_gtsinger_r2_only": studio_view,
                           "studio_gtsinger_all_checkpoints": pooled_view,
                           "target_mir1k": target_view}

    def pick(view: dict, name: str, stratum: str, key: str):
        block = view.get(name) or {}
        s = block.get(stratum) or {}
        return s.get(key)
    res["verdict"] = {
        "long_note_median_ms": {
            "studio": {"all": pick(studio_view, "all", "long_note", "median_ms"),
                       "excluding_degenerate": pick(studio_view, "excluding_degenerate",
                                                    "long_note", "median_ms")},
            "target": {"all": pick(target_view, "all", "long_note", "median_ms"),
                       "excluding_degenerate": pick(target_view, "excluding_degenerate",
                                                    "long_note", "median_ms")}},
        "sign_flip_survives": None,
    }
    res["verdict_pooled"] = {
        "long_note_median_ms": {
            "studio_all_checkpoints": {"all": (pooled_view.get("all", {}) or {}).get(
                "long_note", {}).get("median_ms"),
                "excluding_degenerate": (pooled_view.get("excluding_degenerate", {}) or {}).get(
                    "long_note", {}).get("median_ms")},
            "target": {"all": (target_view.get("all", {}) or {}).get("long_note", {}).get("median_ms"),
                       "excluding_degenerate": (target_view.get("excluding_degenerate", {}) or {}).get(
                           "long_note", {}).get("median_ms")}}}
    sv = res["verdict"]["long_note_median_ms"]["studio"]["excluding_degenerate"]
    tv = res["verdict"]["long_note_median_ms"]["target"]["excluding_degenerate"]
    # studio early (negative) vs accompanied late (positive) is precisely the flip; the first draft of
    # this line compared the two booleans with != and therefore reported the flip as gone
    if sv is not None and tv is not None:
        res["verdict"]["sign_flip_survives"] = bool(sv < 0 and tv > 0)
    (args.out_dir / "BIAS_EXCLUDING_DEGENERATE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name, view in (("GTSinger studio r2", studio_view),
                       ("GTSinger studio all checkpoints (round-21 frame)", pooled_view),
                       ("MIR-1K " + MIR_PREDICTOR, target_view)):
        print(f"== {name} ==")
        for part in ("all", "excluding_degenerate", "degenerate_only"):
            blk = view.get(part) or {}
            if "note" in blk:
                print(f"   {part:22s} units={blk.get('units')} {blk['note']}")
                continue
            row = "、".join(f"{s}: median={blk.get(s, {}).get('median_ms')}ms "
                            f"late={100 * (blk.get(s, {}).get('late_share') or 0):.1f}%"
                            for s in ("all_units", "long_note", "short_note"))
            print(f"   {part:22s} units={blk['units']:6,} deg_share={blk.get('degenerate_share_of_slice')} | {row}")
    print("verdict: " + json.dumps(res["verdict"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
