#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end shadow of the recommended fix: targeted repair -> existing legalisation.

Round 46 measured the two halves separately.  This runs them in the recommended order and reports the
combined outcome on data with a reference (GTSinger, human GT) and on the product batch (structure
only), so the mainline gets one number per variant instead of two partial ones.

    PYTHONPATH=src python scripts/evaluation/run_combined_repair_shadow.py
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
OUT = RUNS / "20260912_combined_repair_shadow"
BATCH = RUNS / "20260814_ktv_current_silence"
TOLS = (0.10, 0.20, 0.25)


def score(err: np.ndarray, zero: np.ndarray) -> dict:
    e = err[np.isfinite(err)]
    out = {"units": int(e.size), "median_err_ms": round(float(np.median(e)) * 1000, 1),
           "zero_length_share": round(float(zero[np.isfinite(err)].mean()), 4)}
    for tol in TOLS:
        out[f"hit_at_{int(tol * 1000)}ms"] = round(float((e <= tol).mean()), 4)
    return out


def legalise(frame: pd.DataFrame, *, song_col: str) -> tuple[pd.DataFrame, dict]:
    """Run the existing joint legalisation and return it in the same column names as the input.

    `SC.repair` writes `repaired_start_sec`/`repaired_end_sec` and needs `audio_duration_sec`; the
    caller here only has start/end, so the audio length is taken as the last end plus one second.
    """
    work = frame.rename(columns={song_col: "song"}).copy()
    work["unit_index"] = np.arange(len(work))
    work["audio_duration_sec"] = float(np.nanmax(work["end_sec"].to_numpy(dtype=float)) + 1.0)
    flagged = SC.flag_violations(work)
    repaired, rep = SC.repair(flagged, use_confidence=False)
    out = repaired.copy()
    out["start_sec"] = out["repaired_start_sec"]
    out["end_sec"] = out["repaired_end_sec"]
    return out, rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"schema": "combined_repair_shadow_v1",
                 "order": ["targeted_block_repair", "existing_joint_legalisation"],
                 "discipline": "read-only shadow; never written back to the product path",
                 "tolerances_sec": list(TOLS), "panels": {}}

    # ---- GTSinger: does the combination keep the accuracy gain from round 46?
    panel = GG.load_panel(RUNS / "20260912_gtsinger_gt_deep/unit_evidence.jsonl.gz")
    off = panel[panel["pipeline"] == "official"].dropna(
        subset=["raw_start_sec", "raw_end_sec", "pred_start_sec", "pred_end_sec",
                "gt_start_sec", "gt_end_sec"]).copy().reset_index(drop=True)
    keys = ["item", "model", "audio_input", "mode"]
    tgt_s = np.full(len(off), np.nan)
    tgt_e = np.full(len(off), np.nan)
    all_s = np.full(len(off), np.nan)
    all_e = np.full(len(off), np.nan)
    for _, idx in off.groupby(keys, observed=True).groups.items():
        sub = off.loc[idx]
        dur = float(np.nanmax(sub["pred_end_sec"].to_numpy(dtype=float)) + 1.0)
        rep = MR.repair_targeted_blocks(sub["raw_start_sec"].to_numpy(dtype=float),
                                        sub["raw_end_sec"].to_numpy(dtype=float), duration=dur)
        tgt_s[idx.to_numpy()] = rep["starts"]
        tgt_e[idx.to_numpy()] = rep["ends"]
        # recommended chain: collapsed blocks first, then only the units that still overlap
        chain = MR.repair_all_targeted(sub["raw_start_sec"].to_numpy(dtype=float),
                                       sub["raw_end_sec"].to_numpy(dtype=float), duration=dur)
        all_s[idx.to_numpy()] = chain["starts"]
        all_e[idx.to_numpy()] = chain["ends"]
    gs_frame = off.assign(start_sec=tgt_s, end_sec=tgt_e,
                          song=off[keys].astype(str).agg("|".join, axis=1))
    legal, rep_info = legalise(gs_frame[["song", "start_sec", "end_sec", "gt_start_sec",
                                         "gt_end_sec"]], song_col="song")
    gs: dict = {"units": int(len(off)), "legalisation": rep_info.get("solve_statuses", {})}
    for name, s, e in (("upstream_repaired_shipped", off["pred_start_sec"], off["pred_end_sec"]),
                       ("shadow_targeted_only", pd.Series(tgt_s), pd.Series(tgt_e)),
                       ("shadow_targeted_then_legalised",
                        legal["start_sec"].reset_index(drop=True),
                        legal["end_sec"].reset_index(drop=True)),
                       ("shadow_all_targeted_recommended", pd.Series(all_s), pd.Series(all_e))):
        err = np.maximum((pd.Series(s).reset_index(drop=True) - off["gt_start_sec"]).abs(),
                         (pd.Series(e).reset_index(drop=True) - off["gt_end_sec"]).abs()).to_numpy(dtype=float)
        zero = (pd.Series(e).reset_index(drop=True)
                - pd.Series(s).reset_index(drop=True)).to_numpy(dtype=float) <= 1e-9
        gs[name] = score(err, zero)
    gs["deltas_pp_vs_shipped"] = {
        f"{v}_minus_shipped@{int(t * 1000)}ms": round(
            100.0 * (gs[v][f"hit_at_{int(t * 1000)}ms"] - gs["upstream_repaired_shipped"][f"hit_at_{int(t * 1000)}ms"]), 2)
        for v in ("shadow_targeted_only", "shadow_targeted_then_legalised",
                  "shadow_all_targeted_recommended") for t in TOLS}
    res["panels"]["gtsinger_human_gt"] = gs

    # ---- product batch: structure of the combined chain, starting from raw
    raw, _m = SC.load_batch(args.batch, stage="raw")
    raw = SC.flag_violations(raw)
    tgt_frame, tgt_diag = MR.repair_stage_frame(
        raw[["song", "unit_index", "start_sec", "end_sec"]].copy(), repair=MR.repair_targeted_blocks)
    chain_frame, chain_diag = MR.repair_stage_frame(
        raw[["song", "unit_index", "start_sec", "end_sec"]].copy(), repair=MR.repair_all_targeted)
    legal2, rep2 = legalise(tgt_frame[["song", "start_sec", "end_sec"]], song_col="song")
    legal2 = SC.flag_violations(legal2)
    shipped = SC.flag_violations(SC.load_batch(args.batch, stage="selected")[0])
    prod: dict = {"units": int(len(shipped))}
    for name, frame in (("shipped", shipped),
                        ("shadow_targeted_only", SC.flag_violations(tgt_frame)),
                        ("shadow_all_targeted_recommended", SC.flag_violations(chain_frame)),
                        ("shadow_targeted_then_legalised", legal2)):
        prod[name] = {
            "zero_length_share": round(float(frame["flag_zero_or_negative"].mean()), 4),
            "illegal_share": round(float(frame["is_illegal"].mean()), 4),
            "overlap_share": round(float(frame["flag_overlaps_next"].mean()), 4),
            "identical_start_blocks": SC.identical_start_blocks(frame)}
    prod["legalisation_statuses"] = rep2.get("solve_statuses", {})
    res["panels"]["product_batch_structural"] = prod

    (args.out_dir / "COMBINED_REPAIR_SHADOW.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("== GTSinger (human GT) ==")
    for name in ("upstream_repaired_shipped", "shadow_targeted_only",
                 "shadow_all_targeted_recommended", "shadow_targeted_then_legalised"):
        v = gs[name]
        print(f"   {name:32s} median={v['median_err_ms']}ms zero={100 * v['zero_length_share']:.2f}% "
              + " ".join(f"hit@{int(t * 1000)}={100 * v[f'hit_at_{int(t * 1000)}ms']:.2f}%" for t in TOLS))
    print("   deltas: " + json.dumps(gs["deltas_pp_vs_shipped"], ensure_ascii=False))
    print("== product batch ==")
    for name in ("shipped", "shadow_targeted_only", "shadow_all_targeted_recommended",
                 "shadow_targeted_then_legalised"):
        v = prod[name]
        print(f"   {name:32s} zero={100 * v['zero_length_share']:.2f}% illegal={100 * v['illegal_share']:.2f}% "
              f"overlap={100 * v['overlap_share']:.2f}% blocks={v['identical_start_blocks']['blocks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
