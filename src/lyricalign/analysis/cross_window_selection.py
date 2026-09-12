"""Can cross-window attempts be combined *without* ground truth? (long-form multi-view selection)

Round 5 showed that consensus across inference configurations of the *same* whole-item pass buys
~0.3 pp on natural Mandarin, while round 7's attempt/unit correction showed that on real long-form
timelines a lyric unit is predicted by up to 24 different windows and the best attempt beats the
median attempt by ~3.2 pp hit@100.  Different windows are genuinely different views (different audio
crops, different left context), so this is the setting where multi-view selection should pay — and
the question worth answering before spending GPU is whether a *label-free* selector can capture any
of that headroom.

Everything here runs on retained evidence (per-attempt boundaries plus recorded entropies/margins);
no new forwards.  The reference used to score selectors is the signed ground truth reconstructed and
verified in :mod:`lyricalign.analysis.longform_signed_gt` (max deviation 0.0 against the frozen
absolute errors), never the panel's fabricated-axis ``gt_*`` columns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DATA = Path("/home/hyan/Data/lyricalign")
PANEL = DATA / "runs/20260912_m4_longform_weakgt/longform_units.jsonl.gz"
SIGNED_GT = DATA / "runs/20260912_m4_longform_weakgt/signed_gt.pkl"
UNIT_KEY = ["view_id", "song", "canonical_unit_id"]
TOLS = (0.100, 0.200, 0.250)
SEED = 20260912
N_BOOT = 400


def load_attempts() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Per-attempt rows (one window's prediction of one lyric unit) with the signed reference."""
    panel = pd.read_json(PANEL, lines=True, compression="infer")
    gt = pd.read_pickle(SIGNED_GT)
    gt_key = ["song", "canonical_unit_id"]
    g = gt.drop_duplicates(subset=gt_key)[gt_key + ["gt_start_sec", "gt_end_sec"]]
    d = panel.merge(g, on=gt_key, how="inner", suffixes=("", "_ref"))
    if "gt_start_sec_ref" not in d:
        raise RuntimeError("signed reference join failed")
    d = d.rename(columns={"gt_start_sec_ref": "ref_start_sec", "gt_end_sec_ref": "ref_end_sec"})
    d = d.dropna(subset=["raw_start_sec", "raw_end_sec", "ref_start_sec", "ref_end_sec"])
    d["attempt_both_err"] = np.maximum((d["raw_start_sec"] - d["ref_start_sec"]).abs(),
                                       (d["raw_end_sec"] - d["ref_end_sec"]).abs())
    info = {"schema": "cross_window_selection_v1", "rows": int(len(d)),
            "units": int(d.groupby(UNIT_KEY, observed=True).ngroups),
            "reference": "signed GT reconstructed from segment labels + timeline offsets "
                         "(verified: max deviation 0.0 vs frozen absolute errors)",
            "reference_quantisation_sec": 0.08}
    per_unit = d.groupby(UNIT_KEY, observed=True).size()
    info["attempts_per_unit"] = {"median": int(per_unit.median()), "p90": float(per_unit.quantile(.9)),
                                 "max": int(per_unit.max()),
                                 "units_with_ge2": int((per_unit >= 2).sum()),
                                 "units_with_ge3": int((per_unit >= 3).sum())}
    return d, info


def add_features(d: pd.DataFrame) -> pd.DataFrame:
    """Label-free per-attempt features: consensus distance, support, confidence, position."""
    d = d.sort_values(UNIT_KEY + ["request_identity"]).reset_index(drop=True)
    g = d.groupby(UNIT_KEY, observed=True)
    d["n_attempts"] = g["raw_start_sec"].transform("size")
    # leave-one-out consensus of the *other* attempts on the same unit
    for col in ("start", "end"):
        vals = d[f"raw_{col}_sec"].to_numpy(dtype=float)
        d[f"loo_median_{col}"] = np.nan
        for _k, idx in g.indices.items():
            pos = np.asarray(idx, dtype=int)
            for p in pos:
                others = np.delete(vals[pos], np.where(pos == p)[0][0])
                d.at[p, f"loo_median_{col}"] = float(np.median(others)) if others.size else vals[p]
    d["loo_spread"] = np.maximum((d["raw_start_sec"] - d["loo_median_start"]).abs(),
                                 (d["raw_end_sec"] - d["loo_median_end"]).abs())
    # support: how many other attempts agree within 50 ms on both boundaries
    sup = np.zeros(len(d))
    for _k, idx in g.indices.items():
        pos = np.asarray(idx, dtype=int)
        s = d.loc[pos, "raw_start_sec"].to_numpy(dtype=float)
        e = d.loc[pos, "raw_end_sec"].to_numpy(dtype=float)
        for j, p in enumerate(pos):
            other_s = np.delete(s, j)
            other_e = np.delete(e, j)
            if other_s.size == 0:
                sup[p] = 0.0
                continue
            sup[p] = float(np.mean((np.abs(other_s - s[j]) <= 0.05)
                                   & (np.abs(other_e - e[j]) <= 0.05)))
    d["support_50ms"] = sup
    ent_s = pd.to_numeric(d.get("start_entropy"), errors="coerce").to_numpy(dtype=float)
    ent_e = pd.to_numeric(d.get("end_entropy"), errors="coerce").to_numpy(dtype=float)
    d["ent_max"] = np.fmax(ent_s, ent_e)   # fmax ignores NaN
    mar_s = pd.to_numeric(d.get("start_margin"), errors="coerce").to_numpy(dtype=float)
    mar_e = pd.to_numeric(d.get("end_margin"), errors="coerce").to_numpy(dtype=float)
    d["margin_min"] = np.fmin(mar_s, mar_e)
    # position inside the request: units near a window edge are the ones the seam story blames
    d["pos_in_request"] = g["raw_start_sec"].rank(method="first").to_numpy(dtype=float)
    n = d["n_attempts"].to_numpy(dtype=float)
    # rank of this unit within *its own request* (not per unit across requests)
    req_rank = d.groupby(["request_identity", "view_id"], observed=True)["canonical_unit_id"] \
        .rank(method="first").to_numpy(dtype=float)
    req_n = d.groupby(["request_identity", "view_id"], observed=True)["canonical_unit_id"] \
        .transform("size").to_numpy(dtype=float)
    d["rel_pos_in_request"] = (req_rank - 1.0) / np.maximum(req_n - 1.0, 1.0)
    d["edge_distance"] = np.minimum(d["rel_pos_in_request"], 1.0 - d["rel_pos_in_request"])
    return d


def _score(err: np.ndarray, groups: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {"units": int(err.size)}
    for tol in TOLS:
        out[f"hit{int(tol * 1000)}"] = round(float(np.mean(err <= tol + 1e-9)), 4)
    out["mae_both_sec"] = round(float(np.mean(err)), 4)
    out["median_both_sec"] = round(float(np.median(err)), 4)
    out["p90_both_sec"] = round(float(np.percentile(err, 90)), 4)
    uniq = np.unique(groups)
    idx = {g: np.flatnonzero(groups == g) for g in uniq}
    rng = np.random.default_rng(SEED)
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        picked = rng.choice(uniq, len(uniq), True)
        draws[i] = err[np.concatenate([idx[g] for g in picked])].mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    out["mae_ci95_song_boot"] = [round(float(lo), 4), round(float(hi), 4)]
    return out


def run_selectors(d: pd.DataFrame) -> dict[str, Any]:
    """Evaluate label-free selectors against the verified signed reference, plus the oracle bound."""
    g = d.groupby(UNIT_KEY, observed=True)
    out: dict[str, Any] = {"schema": "cross_window_selection_results_v1", "selectors": {}}
    err = d["attempt_both_err"].to_numpy(dtype=float)

    def unit_series(name: str, sel_pos: np.ndarray, note: str = "",
                    bounds: tuple[np.ndarray, np.ndarray] | None = None) -> None:
        e = d["attempt_both_err"].to_numpy(dtype=float)[sel_pos]
        song = d["song"].to_numpy()[sel_pos]
        entry = _score(e, song)
        entry["note"] = note
        out["selectors"][name] = entry

    # baselines
    first_pos = d.index.get_indexer(pd.Index(g.head(1).index.to_numpy()))
    unit_series("A_first_attempt", first_pos, "single pass (arbitrary window)")
    med_err = g["attempt_both_err"].median().to_numpy()
    worst_err = g["attempt_both_err"].max().to_numpy()
    best_err = g["attempt_both_err"].min().to_numpy()
    songs_rep = np.asarray([d.loc[idx, "song"].iloc[0] for idx in g.indices.values()], dtype=object)

    def summ(vals: np.ndarray) -> dict[str, Any]:
        return _score(vals, songs_rep)
    out["aggregates"] = {
        "unit_median_of_attempts": summ(med_err),
        "unit_worst_of_attempts": summ(worst_err),
        "unit_best_of_attempts_oracle": summ(best_err),
    }
    # median-of-attempt boundaries (a consensus output, not an attempt)
    def _consensus_err(x: pd.DataFrame) -> float:
        return float(max(abs(x["raw_start_sec"].median() - x["ref_start_sec"].iloc[0]),
                         abs(x["raw_end_sec"].median() - x["ref_end_sec"].iloc[0])))

    cs = g.apply(_consensus_err, include_groups=False).to_numpy(dtype=float)
    out["aggregates"]["B_consensus_median_boundaries"] = summ(cs)

    # label-free selectors: pick one attempt per unit
    sel_specs = {
        "C_closest_to_consensus": ("loo_spread", "min"),
        "D_max_support": ("support_50ms", "max"),
        "E_min_entropy": ("ent_max", "min"),
        "F_max_margin": ("margin_min", "max"),
        "G_most_central_in_request": ("edge_distance", "max"),
    }
    for name, (col, how) in sel_specs.items():
        idx = (g[col].idxmin() if how == "min" else g[col].idxmax())
        pos = d.index.get_indexer(pd.Index(idx.to_numpy()))
        unit_series(name, pos, f"pick attempt by {col} ({how})")
    # combined: restrict to attempts agreeing with consensus within 100 ms, then most confident
    pool = d[d["loo_spread"] <= 0.1].copy()
    if len(pool):
        gp = pool.groupby(UNIT_KEY, observed=True)
        idx = gp["ent_max"].idxmin()
        keep = d.index.get_indexer(pd.Index(idx.to_numpy()))
        covered = len(idx) / max(len(g), 1)
        e = d["attempt_both_err"].to_numpy(dtype=float)[keep]
        entry = _score(e, d["song"].to_numpy()[keep])
        entry["note"] = f"consensus-gated (<=100ms) then lowest entropy; covers {covered:.2f} of units"
        out["selectors"]["H_gated_then_confident"] = entry
    out["oracle"] = {"unit_best_attempt": summ(best_err)}

    # how much of the headroom does each selector close?
    base = out["aggregates"]["unit_median_of_attempts"]["hit100"]
    top = out["aggregates"]["unit_best_of_attempts_oracle"]["hit100"]
    gap = max(top - base, 1e-9)
    out["gap_closed_vs_oracle"] = {}
    all_entries = {**{k: v for k, v in out["selectors"].items()},
                   "median_of_attempts": out["aggregates"]["unit_median_of_attempts"],
                   "consensus_median_boundaries": out["aggregates"]["B_consensus_median_boundaries"]}
    for k, v in all_entries.items():
        h = v.get("hit100")
        if h is None:
            continue
        out["gap_closed_vs_oracle"][k] = {
            "hit100": h, "delta_pp_vs_median_attempt": round((h - base) * 100, 2),
            "share_of_oracle_gap_closed": round((h - base) / gap, 3)}
    out["reference_headroom"] = {"median_attempt_hit100": base, "oracle_hit100": top,
                                 "headroom_pp": round((top - base) * 100, 2)}
    return out
