#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Solve the joint cleanup LP and compare it against the shipped and sequential rules.

Two panels, two different questions:

* real songs (no ground truth)  -> structure and destruction only;
* GTSinger (human per-word ground truth) -> accuracy, to make sure a structurally nicer
  rule does not quietly cost accuracy.

    PYTHONPATH=src python scripts/evaluation/solve_joint_cleanup.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import cleanup_simulation as CS
from lyricalign.analysis import gtsinger_gt_deep as G
from lyricalign.analysis import joint_cleanup as J
from lyricalign.analysis import real_song_views as RV

REAL_DIR = Path("/home/hyan/Data/lyricalign/runs/20260912_real_song_views")
GTS_DIR = Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep")
OUT_DIR = REAL_DIR


def _mass(s, e):
    return float(np.nansum(np.clip(np.asarray(e, dtype=float) - np.asarray(s, dtype=float),
                                   0, J.MAX_DUR_SEC)))


def _structure_and_cost(S, E, s_raw, e_raw, groups, label, base_mass=None, extra=None):
    st = J.structure_metrics(S, E, groups)
    if base_mass:
        st["plausible_mass_lost_share"] = round(1 - st["plausible_mass_sec"] / base_mass, 4)
    shift = np.maximum(np.abs(S - s_raw), np.abs(E - e_raw))
    moved = shift > 1e-3
    out = {"rule": label, **st,
           "share_units_moved": round(float(moved.mean()), 4),
           "median_shift_sec": round(float(np.median(shift[moved])), 4) if moved.any() else None,
           "p90_shift_sec": round(float(np.percentile(shift[moved], 90)), 4) if moved.any() else None}
    if extra:
        out.update(extra)
    return out


def run_real_songs(alpha: float) -> dict:
    df = RV.load_frame(REAL_DIR / "real_song_views.jsonl.gz")
    view = "b4_60s_windowed"
    d = df.dropna(subset=[f"{view}__rs", f"{view}__re", f"{view}__s", f"{view}__e"]).sort_values(
        ["song", "unit_index"]).reset_index(drop=True)
    s_raw = d[f"{view}__rs"].to_numpy(dtype=float)
    e_raw = d[f"{view}__re"].to_numpy(dtype=float)
    groups = d["song"].to_numpy()
    audio_dur = d.groupby("song", observed=True)["audio_dur_b4"].transform("max").to_numpy(dtype=float)
    ent_s = d[f"{view}__ent_s"].to_numpy(dtype=float)
    ent_e = d[f"{view}__ent_e"].to_numpy(dtype=float)

    base_mass = _mass(s_raw, e_raw)
    rows = []
    rows.append(_structure_and_cost(s_raw.copy(), e_raw.copy(), s_raw, e_raw, groups, "R0_none",
                                   base_mass))
    rows.append(_structure_and_cost(d[f"{view}__s"].to_numpy(dtype=float),
                                    d[f"{view}__e"].to_numpy(dtype=float),
                                    s_raw, e_raw, groups, "R1_shipped", base_mass))
    ctx = {"target": (d[f"{view}__s"].to_numpy(dtype=float), d[f"{view}__e"].to_numpy(dtype=float)),
           "ent_start": ent_s, "ent_end": ent_e}
    for name in ("R3_end_trim_min0.05s", "R6_clip_then_trim", "R7_clip_only"):
        S, E = CS.RULES[name](s_raw, e_raw, ctx)
        rows.append(_structure_and_cost(S, E, s_raw, e_raw, groups, name, base_mass))
    S, E, rep = J.solve_frame(d, s_col=f"{view}__rs", e_col=f"{view}__re",
                              ent_s_col=f"{view}__ent_s", ent_e_col=f"{view}__ent_e",
                              group_cols=("song",), dur_col="audio_dur_b4", alpha=alpha)
    base_mass = float(np.nansum(np.clip(e_raw - s_raw, 0, J.MAX_DUR_SEC)))
    ent_med = float(np.nanmedian(np.concatenate([ent_s, ent_e])))
    conf_share = None
    moved_end = np.abs(E - e_raw) > 1e-3
    moved_start = np.abs(S - s_raw) > 1e-3
    tot = float(moved_end.sum() + moved_start.sum())
    if tot:
        conf_share = round(float(((moved_end & (ent_e <= ent_med)).sum()
                                  + (moved_start & (ent_s <= ent_med)).sum()) / tot), 4)
    entry = _structure_and_cost(S, E, s_raw, e_raw, groups, "R8_joint_lp", base_mass,
                                extra={"solve": rep,
                                       "share_moved_boundaries_that_were_confident": conf_share,
                                       "alpha": alpha})
    rows.append(entry)
    # same solve without the confidence weighting, to isolate what the weights contribute
    S2, E2, rep2 = J.solve_frame(d, s_col=f"{view}__rs", e_col=f"{view}__re",
                                 group_cols=("song",), dur_col="audio_dur_b4", alpha=0.0)
    rows.append(_structure_and_cost(S2, E2, s_raw, e_raw, groups, "R8b_joint_unweighted", base_mass,
                                    extra={"solve": rep2, "alpha": 0.0}))
    return {"panel": {"units": int(len(d)), "songs": int(d["song"].nunique()), "view": view},
            "rules": rows}


def run_gtsinger(alpha: float) -> dict:
    panel = G.panel_only(G.load_panel(GTS_DIR / "unit_evidence.jsonl.gz"))
    d = panel[panel["pipeline"] == "official"].dropna(
        subset=["raw_start_sec", "raw_end_sec", "pred_start_sec", "pred_end_sec",
                "gt_start_sec", "gt_end_sec"]).sort_values(
        ["item", "model", "audio_input", "mode", "unit_index"]).reset_index(drop=True)
    groups = (d["item"].astype(str) + "|" + d["model"].astype(str) + "|"
              + d["audio_input"].astype(str) + "|" + d["mode"].astype(str)).to_numpy()
    s_raw = d["raw_start_sec"].to_numpy(dtype=float)
    e_raw = d["raw_end_sec"].to_numpy(dtype=float)
    ent_s = d["raw_entropy_start"].to_numpy(dtype=float)
    ent_e = d["raw_entropy_end"].to_numpy(dtype=float)
    gt_s = d["gt_start_sec"].to_numpy(dtype=float)
    gt_e = d["gt_end_sec"].to_numpy(dtype=float)
    dur = d.groupby(groups)["audio_dur_sec"].transform("max").to_numpy(dtype=float)

    def acc(name, S, E, extra=None):
        out = {"rule": name, **J.evaluate_against_ground_truth(S, E, gt_s, gt_e),
               **J.structure_metrics(S, E, groups),
               "share_units_moved_vs_raw": round(float(
                   np.mean(np.maximum(np.abs(S - s_raw), np.abs(E - e_raw)) > 1e-3)), 4)}
        if extra:
            out.update(extra)
        return out

    rows = [acc("raw_none", s_raw.copy(), e_raw.copy())]
    rows.append(acc("shipped_official", d["pred_start_sec"].to_numpy(dtype=float),
                    d["pred_end_sec"].to_numpy(dtype=float)))
    # round-2 winner: trim earlier tail only, 0.05 s minimum duration
    S, E = CS.rule_end_trim(s_raw, e_raw, {})
    rows.append(acc("V9_end_trim_min0.05s", S, E))
    frame = pd.DataFrame({"grp": groups, "s": s_raw, "e": e_raw, "es": ent_s, "ee": ent_e, "dur": dur})
    out = {}
    for a_val in (0.0, 2.0, alpha, 8.0):
        res_s = np.empty(len(frame))
        res_e = np.empty(len(frame))
        statuses: dict[str, int] = {}
        for _k, sub in frame.groupby("grp", observed=True):
            pos = frame.index.get_indexer(sub.index)
            Ss, Ee, rep = J.solve_block(sub["s"].to_numpy(dtype=float), sub["e"].to_numpy(dtype=float),
                                        ent_start=sub["es"].to_numpy(dtype=float),
                                        ent_end=sub["ee"].to_numpy(dtype=float),
                                        audio_dur=float(np.nanmax(sub["dur"].to_numpy(dtype=float))),
                                        alpha=a_val)
            res_s[pos] = Ss
            res_e[pos] = Ee
            statuses[rep.status] = statuses.get(rep.status, 0) + 1
        out[a_val] = acc(f"R8_joint_lp_alpha{a_val:g}", res_s, res_e,
                         extra={"alpha": a_val, "solve_statuses": statuses})
        rows.append(out[a_val])
    return {"panel": {"units": int(len(d)), "sequences": int(len(np.unique(groups))),
                      "reference": "human GTSinger word-level GT (round-1 panel)"},
            "rules": rows}


def run_m4_longform(alpha: float) -> dict:
    """Second-domain check on natural long-form singing (M4Singer-derived weak GT).

    Two axis lessons from round 3 apply here, so the panel's own ``gt_*`` column is *rejected*
    (it lives on the fabricated uniform axis: raw hit@100 collapses to ~5%) and the ground truth is
    reconstructed from the frozen signed label errors instead.  That reconstruction is then required
    to agree with the independent reconstruction implied by the official stage; only units where both
    stages agree are used for rule comparison, and the disagreement rate is reported.
    """
    from lyricalign.analysis import m4_longform_weakgt as L

    df = L.load_frame(Path("/home/hyan/Data/lyricalign/runs/20260912_m4_longform_weakgt"
                           "/longform_units.jsonl.gz"))
    need = ["raw_start_sec", "raw_end_sec", "label_raw_start_err_sec", "label_raw_end_err_sec",
            "label_raw_both_err_sec", "start_entropy", "end_entropy",
            "view_id", "source_segment_id", "source_unit_index"]
    d = df.dropna(subset=[c for c in need if c in df.columns]).copy()
    d = d.sort_values(["request_identity", "view_id", "canonical_unit_id"]).reset_index(drop=True)
    s_raw = d["raw_start_sec"].to_numpy(dtype=float)
    e_raw = d["raw_end_sec"].to_numpy(dtype=float)
    gt_s = s_raw - d["label_raw_start_err_sec"].to_numpy(dtype=float)
    gt_e = e_raw - d["label_raw_end_err_sec"].to_numpy(dtype=float)
    # sequences are per (request, view): a window request holds a contiguous run of canonical units.
    # (Grouping by segment instead mixed 1-24 attempts of the same unit into one "sequence", which is
    # what made the first long-form run of this comparison meaningless.)
    groups = (d["request_identity"].astype(str) + "|" + d["view_id"].astype(str)).to_numpy(dtype=object)
    ent_s = d["start_entropy"].to_numpy(dtype=float)
    ent_e = d["end_entropy"].to_numpy(dtype=float)

    dev_stage = np.full(len(d), np.inf)
    if {"off_start_sec", "off_end_sec", "label_off_start_err_sec",
            "label_off_end_err_sec"} <= set(d.columns):
        gt_s_off = d["off_start_sec"].to_numpy(dtype=float) \
            - d["label_off_start_err_sec"].to_numpy(dtype=float)
        gt_e_off = d["off_end_sec"].to_numpy(dtype=float) \
            - d["label_off_end_err_sec"].to_numpy(dtype=float)
        dev_stage = np.maximum(np.abs(gt_s - gt_s_off), np.abs(gt_e - gt_e_off))
    agree = np.isfinite(dev_stage) & (dev_stage <= 1e-3)

    frozen = d["label_raw_both_err_sec"].to_numpy(dtype=float)
    recomputed = np.maximum(np.abs(s_raw - gt_s), np.abs(e_raw - gt_e))
    okf = np.isfinite(frozen)
    dev_raw = float(np.nanmax(np.abs(recomputed[okf] - frozen[okf]))) if okf.any() else None

    keep = agree & np.isfinite(gt_s) & np.isfinite(gt_e) & (gt_s >= -1e-6) & (gt_e > gt_s)
    for arr in ():
        pass
    d = d.loc[keep].reset_index(drop=True)
    s_raw, e_raw, gt_s, gt_e = s_raw[keep], e_raw[keep], gt_s[keep], gt_e[keep]
    groups, ent_s, ent_e = groups[keep], ent_s[keep], ent_e[keep]

    def acc(name: str, S, E, extra=None):
        out = {"rule": name, **J.evaluate_against_ground_truth(S, E, gt_s, gt_e),
               **J.structure_metrics(S, E, groups),
               "share_units_moved_vs_raw": round(float(np.mean(
                   np.maximum(np.abs(S - s_raw), np.abs(E - e_raw)) > 1e-3)), 4)}
        if extra:
            out.update(extra)
        return out

    rows = [acc("raw_none", s_raw.copy(), e_raw.copy())]
    if "off_start_sec" in d:
        rows.append(acc("official_stage", d["off_start_sec"].to_numpy(dtype=float),
                        d["off_end_sec"].to_numpy(dtype=float)))
    if "final_start_sec" in d:
        rows.append(acc("final_stage", d["final_start_sec"].to_numpy(dtype=float),
                        d["final_end_sec"].to_numpy(dtype=float)))
    St, Et = CS.rule_end_trim(s_raw, e_raw, {})
    rows.append(acc("V9_end_trim_min0.05s", St, Et))
    for a_val in (0.0, alpha):
        res_s = np.empty(len(d))
        res_e = np.empty(len(d))
        statuses: dict[str, int] = {}
        frame = pd.DataFrame({"grp": groups, "s": s_raw, "e": e_raw, "es": ent_s, "ee": ent_e})
        for _k, sub in frame.groupby("grp", observed=True):
            pos = frame.index.get_indexer(sub.index)
            Ss, Ee, rep = J.solve_block(sub["s"].to_numpy(dtype=float),
                                        sub["e"].to_numpy(dtype=float),
                                        ent_start=sub["es"].to_numpy(dtype=float),
                                        ent_end=sub["ee"].to_numpy(dtype=float), alpha=a_val)
            res_s[pos] = Ss
            res_e[pos] = Ee
            statuses[rep.status] = statuses.get(rep.status, 0) + 1
        rows.append(acc(f"R8_joint_lp_alpha{a_val:g}", res_s, res_e,
                        extra={"alpha": a_val, "solve_statuses": statuses}))
    return {"panel": {"units": int(len(d)), "sequences": int(len(set(groups))),
                      "reference": "M4Singer-derived weak GT reconstructed from frozen signed errors",
                      "reconstruction_check_raw_max_dev_sec":
                          None if dev_raw is None else round(dev_raw, 6),
                      "stage_agreement_share": round(float(agree.mean()), 4),
                      "stage_disagreement_max_sec": round(float(np.nanmax(np.where(
                          np.isfinite(dev_stage), dev_stage, np.nan))), 3)
                      if np.isfinite(dev_stage).any() else None,
                      "rows_dropped_by_stage_disagreement": int((~agree).sum()),
                      "axis_note": "panel gt_* column rejected: fabricated uniform axis (round 3)"},
            "rules": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=J.CONFIDENCE_ALPHA)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--skip-real", action="store_true")
    ap.add_argument("--skip-m4", action="store_true")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"schema": "joint_cleanup_eval_v1", "alpha": args.alpha}
    if not args.skip_real:
        result["real_songs"] = run_real_songs(args.alpha)
    result["gtsinger"] = run_gtsinger(args.alpha)
    if not args.skip_m4:
        result["m4_longform"] = run_m4_longform(args.alpha)
    (args.out_dir / "JOINT_CLEANUP.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if "real_songs" in result:
        print("== real songs (structure; no GT) ==")
        for r in result["real_songs"]["rules"]:
            print(f"  {r['rule']:24s} degen={r['degenerate_share']:.4f} overlap={r['overlap_share']:.4f} "
                  f"regr={r['start_regression_share']:.4f} maxdur={r['max_duration_sec']:8.2f} "
                  f"moved={r['share_units_moved']:.3f} mass_lost={r.get('plausible_mass_lost_share')!s:.5} "
                  f"conf_moved={r.get('share_moved_boundaries_that_were_confident')}")
    if "m4_longform" in result:
        pane = result["m4_longform"]["panel"]
        print(f"== M4 long-form (weak GT; units={pane['units']:,} seqs={pane['sequences']} "
              f"stage_agree={pane['stage_agreement_share']} "
              f"dev_raw={pane['reconstruction_check_raw_max_dev_sec']}) ==")
        for r in result["m4_longform"]["rules"]:
            print(f"  {r['rule']:26s} hit100={r['hit100']:.4f} hit200={r['hit200']:.4f} "
                  f"hit250={r['hit250']:.4f} mae={r['mae_both_sec']:.4f} iou={r['mean_iou']:.4f} "
                  f"degen={r['degenerate_share']:.4f} overlap={r['overlap_share']:.4f} "
                  f"moved={r['share_units_moved_vs_raw']:.3f}")
    print("== GTSinger (human GT) ==")
    for r in result["gtsinger"]["rules"]:
        print(f"  {r['rule']:26s} hit100={r['hit100']:.4f} hit200={r['hit200']:.4f} "
              f"hit250={r['hit250']:.4f} mae={r['mae_both_sec']:.4f} iou={r['mean_iou']:.4f} "
              f"degen={r['degenerate_share']:.4f} overlap={r['overlap_share']:.4f} "
              f"moved={r['share_units_moved_vs_raw']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
