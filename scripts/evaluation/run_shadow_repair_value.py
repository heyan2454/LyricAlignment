#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How much does the upstream collapse cost?  Measure the shadow repair against references.

Two measurements, both CPU-only and read-only:

* **GTSinger (human word-level GT)**: compare three decodes per unit — our raw argmax, the upstream
  processor output (shipped ``fixed_*``, i.e. with `_fix_timestamps`), and the shadow repair applied
  to the raw values.  This answers "would dropping the collapse help, on data where we know the
  answer?" with absolute error and hit rates at sound tolerances.
* **product batch (no GT)**: structural outcomes only — zero-length share, illegal share and the
  count of blocks sharing one timestamp.

    PYTHONPATH=src python scripts/evaluation/run_shadow_repair_value.py
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
from lyricalign.analysis import monotone_repair as MR
from lyricalign.analysis import structural_compliance as SC

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_shadow_repair_value"
BATCH = RUNS / "20260814_ktv_current_silence"
TOLS = (0.10, 0.20, 0.25)


def metrics(err: np.ndarray, zero: np.ndarray) -> dict:
    finite = np.isfinite(err)
    e = err[finite]
    out = {"units": int(e.size), "median_err_ms": round(float(np.median(e)) * 1000, 1),
           "p90_err_ms": round(float(np.percentile(e, 90)) * 1000, 1),
           "zero_length_share": round(float(zero[finite].mean()), 4)}
    for tol in TOLS:
        out[f"hit_at_{int(tol * 1000)}ms"] = round(float((e <= tol).mean()), 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"schema": "shadow_repair_value_v1",
                 "discipline": "read-only: the shadow repair is never written back; GTSinger has human "
                               "GT, the product batch is scored structurally only",
                 "tolerances_sec": list(TOLS), "panels": {}}

    # ---- GTSinger: raw vs upstream-repaired vs shadow-repaired, against human GT
    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    off = panel[panel["pipeline"] == "official"].dropna(
        subset=["raw_start_sec", "raw_end_sec", "pred_start_sec", "pred_end_sec",
                "gt_start_sec", "gt_end_sec"]).copy().reset_index(drop=True)
    gs: dict = {"units": int(len(off)), "variants": {}}
    seq_keys = ["item", "model", "audio_input", "mode"]
    shadow_s = np.full(len(off), np.nan)
    shadow_e = np.full(len(off), np.nan)
    for _, idx in off.groupby(seq_keys, observed=True).groups.items():
        sub = off.loc[idx]
        rep = MR.repair_monotone_min_duration(sub["raw_start_sec"].to_numpy(dtype=float),
                                             sub["raw_end_sec"].to_numpy(dtype=float),
                                             duration=float(np.nanmax(sub["pred_end_sec"].to_numpy(dtype=float))
                                                            + 1.0))
        shadow_s[idx.to_numpy()] = rep["starts"]
        shadow_e[idx.to_numpy()] = rep["ends"]
    tgt_s = np.full(len(off), np.nan)
    tgt_e = np.full(len(off), np.nan)
    for _, idx in off.groupby(seq_keys, observed=True).groups.items():
        sub = off.loc[idx]
        rep = MR.repair_targeted_blocks(sub["raw_start_sec"].to_numpy(dtype=float),
                                        sub["raw_end_sec"].to_numpy(dtype=float),
                                        duration=float(np.nanmax(sub["pred_end_sec"].to_numpy(dtype=float))
                                                       + 1.0))
        tgt_s[idx.to_numpy()] = rep["starts"]
        tgt_e[idx.to_numpy()] = rep["ends"]
    for name, s_col, e_col in (("raw_argmax", "raw_start_sec", "raw_end_sec"),
                               ("upstream_repaired_shipped", "pred_start_sec", "pred_end_sec"),
                               ("shadow_min_duration", None, None),
                               ("shadow_targeted_blocks", None, None)):
        if name == "shadow_min_duration":
            s = pd.Series(shadow_s, index=off.index)
            e = pd.Series(shadow_e, index=off.index)
        elif name == "shadow_targeted_blocks":
            s = pd.Series(tgt_s, index=off.index)
            e = pd.Series(tgt_e, index=off.index)
        elif s_col is None:
            s = pd.Series(shadow_s, index=off.index)
            e = pd.Series(shadow_e, index=off.index)
        else:
            s, e = off[s_col], off[e_col]
        err = np.maximum((s - off["gt_start_sec"]).abs(), (e - off["gt_end_sec"]).abs()).to_numpy(dtype=float)
        zero = (e - s).to_numpy(dtype=float) <= 1e-9
        gs["variants"][name] = metrics(err, zero)
    # paired comparison on the subset where all variants exist
    gs["paired_deltas_pp"] = {}
    for a, b in (("shadow_min_duration", "upstream_repaired_shipped"),
                 ("shadow_targeted_blocks", "upstream_repaired_shipped"),
                 ("shadow_targeted_blocks", "raw_argmax"),
                 ("raw_argmax", "upstream_repaired_shipped")):
        for tol in TOLS:
            key = f"hit_at_{int(tol * 1000)}ms"
            gs["paired_deltas_pp"][f"{a}_minus_{b}@{int(tol * 1000)}ms"] = round(
                100.0 * (gs["variants"][a][key] - gs["variants"][b][key]), 2)
    res["panels"]["gtsinger_human_gt"] = gs

    # ---- product batch: structural outcomes only
    frames = {}
    for stage in ("raw", "selected"):
        frame, _m = SC.load_batch(args.batch, stage=stage)
        frames[stage] = SC.flag_violations(frame) if not frame.empty else frame
    prod: dict = {"units": int(len(frames["selected"]))}
    shipped = frames["selected"]
    prod["shipped"] = {
        "zero_length_share": round(float(shipped["flag_zero_or_negative"].mean()), 4),
        "illegal_share": round(float(shipped["is_illegal"].mean()), 4)}
    # shadow repair applied to the raw timestamps, per song
    raw = frames["raw"]
    repaired, diag = MR.repair_stage_frame(raw[["song", "unit_index", "start_sec", "end_sec"]].copy())
    rep_flagged = SC.flag_violations(repaired)
    prod["shadow_from_raw"] = {
        "zero_length_share": round(float(rep_flagged["flag_zero_or_negative"].mean()), 4),
        "illegal_share": round(float(rep_flagged["is_illegal"].mean()), 4),
        "diagnostics": diag}
    tgt_frame, tgt_diag = MR.repair_stage_frame(raw[["song", "unit_index", "start_sec", "end_sec"]].copy(),
                                                repair=MR.repair_targeted_blocks)
    tgt_flagged = SC.flag_violations(tgt_frame)
    prod["shadow_targeted"] = {
        "zero_length_share": round(float(tgt_flagged["flag_zero_or_negative"].mean()), 4),
        "illegal_share": round(float(tgt_flagged["is_illegal"].mean()), 4),
        "diagnostics": tgt_diag}
    # how many characters share one timestamp with >=4 neighbours, per variant
    def identical_blocks(frame: pd.DataFrame) -> dict:
        key = frame.assign(_k=frame["song"].astype(str) + "|"
                           + pd.to_numeric(frame["start_sec"], errors="coerce").round(4).astype(str))
        agg = key.groupby("_k", observed=True)["flag_zero_or_negative"].agg(["size", "sum"])
        big = agg[(agg["size"] >= 5) & (agg["sum"] == agg["size"])]
        return {"blocks": int(len(big)), "units": int(big["size"].sum()),
                "largest": int(big["size"].max()) if len(big) else 0}
    prod["shipped"]["identical_start_blocks"] = identical_blocks(shipped)
    prod["shadow_from_raw"]["identical_start_blocks"] = identical_blocks(rep_flagged)
    prod["shadow_targeted"]["identical_start_blocks"] = identical_blocks(tgt_flagged)
    res["panels"]["product_batch_structural"] = prod

    (args.out_dir / "SHADOW_REPAIR_VALUE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("== GTSinger (human GT) ==")
    for name, v in gs["variants"].items():
        print(f"   {name:26s} units={v['units']:,} median={v['median_err_ms']}ms "
              f"zero={100 * v['zero_length_share']:.2f}% "
              + " ".join(f"hit@{int(t * 1000)}={100 * v[f'hit_at_{int(t * 1000)}ms']:.2f}%"
                         for t in TOLS))
    print("   paired deltas: " + json.dumps(gs["paired_deltas_pp"], ensure_ascii=False))
    print("== product batch (structural only) ==")
    print("   shipped:", json.dumps(prod["shipped"], ensure_ascii=False))
    print("   shadow(all):", json.dumps({k: v for k, v in prod["shadow_from_raw"].items()
                                           if k != "diagnostics"}, ensure_ascii=False))
    print("   shadow(targeted):", json.dumps({k: v for k, v in prod["shadow_targeted"].items()
                                               if k != "diagnostics"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
