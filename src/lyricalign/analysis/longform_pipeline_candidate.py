"""Realign-trigger value of cross-window disagreement, and an end-to-end long-form candidate output.

Two questions the mainline needs answered before spending GPU on re-alignment:

1. **Trigger quality.** If a lyric unit is predicted differently by the windows that cover it, is that
   disagreement actually predictive of the unit being wrong, and how much of the error budget sits in
   the most-disagreeing slice?  This decides whether a disagreement-triggered re-decode is worth a
   forward pass at all.

2. **What should the pipeline output?** Candidate: take the cross-window consensus boundary for each
   unit, then pass the resulting sequence through the round-7 joint constrained solve.  Compared
   against (a) an arbitrary single window, (b) the raw stage as recorded, (c) the shipped official
   stage — on the *verified signed* reference from :mod:`longform_signed_gt`, judging accuracy and
   structure together.

Everything is offline: it reuses the per-attempt evidence already on disk (no new forwards), and every
claim here is weak-GT (`rule_validated`, 80 ms quantised, model-derived) — never human GT.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from lyricalign.analysis import cross_window_selection as X
from lyricalign.analysis import joint_cleanup as J

UNIT_KEY = X.UNIT_KEY
BUDGETS = (0.05, 0.10, 0.20, 0.30)


def _auc(y: np.ndarray, s: np.ndarray, min_n: int = 50) -> float | None:
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    ok = np.isfinite(y) & np.isfinite(s)
    y, s = y[ok], s[ok]
    if y.size < min_n or y.min() == y.max():
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(s.size, dtype=float)
    ranks[order] = np.arange(1, s.size + 1)
    n_pos = float(y.sum())
    n_neg = float(y.size - n_pos)
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def build_unit_table(d: pd.DataFrame) -> pd.DataFrame:
    """One row per lyric unit: GT-free disagreement features + (for scoring only) the reference error."""
    g = d.groupby(UNIT_KEY, observed=True)

    def per_unit(x: pd.DataFrame) -> pd.Series:
        s = x["raw_start_sec"].to_numpy(dtype=float)
        e = x["raw_end_sec"].to_numpy(dtype=float)
        spread = float(np.max(s) - np.min(s)) if s.size > 1 else 0.0
        spread_e = float(np.max(e) - np.min(e)) if e.size > 1 else 0.0
        return pd.Series({
            "attempts": int(len(x)),
            "start_spread": spread, "end_spread": spread_e,
            "disagreement": max(spread, spread_e),
            "support_max": float(x["support_50ms"].max()) if "support_50ms" in x else np.nan,
            "loo_spread_min": float(x["loo_spread"].min()) if "loo_spread" in x else np.nan,
            "consensus_start": float(np.median(s)), "consensus_end": float(np.median(e)),
            "err_median_attempt": float(x["attempt_both_err"].median()),
            "err_first_attempt": float(x["attempt_both_err"].iloc[0]),
            "err_best_attempt": float(x["attempt_both_err"].min()),
            "err_worst_attempt": float(x["attempt_both_err"].max()),
            "ent_min": float(np.nanmin(x["ent_max"])) if "ent_max" in x else np.nan,
            # view_id / song / canonical_unit_id come back from the group keys via reset_index
            # (``include_groups=False`` removes them from the frame handed to the callable)
        })

    return g.apply(per_unit, include_groups=False).reset_index()


def trigger_discrimination(units: pd.DataFrame) -> dict[str, Any]:
    """Does disagreement predict a bad unit, and what does a review budget buy?"""
    out: dict[str, Any] = {"schema": "longform_realign_trigger_v1",
                           "reference_note": "scored against the verified signed weak reference"}
    multi = units[units["attempts"] >= 2].copy()
    out["coverage"] = {"units_total": int(len(units)), "units_multi_attempt": int(len(multi)),
                       "share_multi_attempt": round(float(len(multi) / max(len(units), 1)), 4),
                       "median_attempts": float(units["attempts"].median()),
                       "max_attempts": int(units["attempts"].max())}
    for tol, tag in ((0.1, "bad100"), (0.25, "bad250")):
        y = (multi["err_median_attempt"].to_numpy(dtype=float) > tol).astype(float)
        entry: dict[str, Any] = {"positive_rate": round(float(y.mean()), 4)}
        for feat in ("disagreement", "support_max", "loo_spread_min", "ent_min", "attempts"):
            s = multi[feat].to_numpy(dtype=float)
            a = _auc(y, s)
            if feat == "support_max":                      # higher support = *better*, flip
                a = _auc(y, -s)
            entry[f"auc_{feat}"] = None if a is None else round(a, 4)
        curves: dict[str, Any] = {}
        score = multi["disagreement"].to_numpy(dtype=float)
        err_med = multi["err_median_attempt"].to_numpy(dtype=float)
        err_best = multi["err_best_attempt"].to_numpy(dtype=float)
        err_first = multi["err_first_attempt"].to_numpy(dtype=float)
        for frac in BUDGETS:
            thr = float(np.quantile(score, 1 - frac))
            flagged = score >= thr
            if not flagged.any():
                continue
            curves[f"top_{int(frac * 100)}pct"] = {
                "threshold_sec": round(thr, 3),
                "flagged_units": int(flagged.sum()),
                "precision_bad100": round(float(y[flagged].mean()), 4),
                "recall_bad100": round(float(y[flagged].sum() / max(y.sum(), 1)), 4),
                "hit100_of_flagged_after_consensus": round(float(np.mean(err_med[flagged] <= 0.1)), 4),
                "hit100_of_flagged_if_rechosen": round(float(np.mean(err_best[flagged] <= 0.1)), 4),
                "overall_hit100_if_only_flagged_rechosen": round(float(np.mean(
                    np.where(flagged, err_best <= 0.1, err_first <= 0.1))), 4),
                "gain_pp_vs_single_window": round(float(np.mean(
                    np.where(flagged, err_best <= 0.1, err_first <= 0.1))
                    - np.mean(err_first <= 0.1)) * 100, 3),
            }
        entry["review_budget_curve"] = curves
        out[tag] = entry
    # how much of the whole error budget lives in the disagreeing tail
    score = multi["disagreement"].to_numpy(dtype=float)
    bad = (multi["err_first_attempt"].to_numpy(dtype=float) > 0.1)
    order = np.argsort(-score)
    cum = np.cumsum(bad[order]) / max(bad.sum(), 1)
    out["error_capture_curve"] = {f"top_{int(f * 100)}pct": round(float(cum[min(int(f * len(order)) - 1,
                                                                            len(cum) - 1)]), 4)
                                  for f in (0.05, 0.1, 0.2, 0.3, 0.5)}
    return out


def end_to_end(d: pd.DataFrame, units: pd.DataFrame) -> dict[str, Any]:
    """Compare the candidate output (cross-window consensus + joint solve) with recorded stages."""
    out: dict[str, Any] = {"schema": "longform_pipeline_candidate_v1", "systems": {}}
    key = UNIT_KEY
    # ordering must not depend on the predicted value: sorting by raw_start_sec and taking the head
    # silently selected the earliest-starting attempt, which peeked at the answer direction
    d = d.sort_values(key + ["request_identity", "raw_start_sec"]).reset_index(drop=True)

    def unit_err(s: np.ndarray, e: np.ndarray) -> np.ndarray:
        pos = np.full(len(units), np.nan)
        tmp = pd.DataFrame({**{k: units[k].to_numpy() for k in key}, "s": s, "e": e})
        merged = tmp.merge(d[key + ["ref_start_sec", "ref_end_sec"]].drop_duplicates(subset=key),
                           on=key, how="left")
        return np.maximum(np.abs(merged["s"].to_numpy(dtype=float)
                                 - merged["ref_start_sec"].to_numpy(dtype=float)),
                          np.abs(merged["e"].to_numpy(dtype=float)
                                 - merged["ref_end_sec"].to_numpy(dtype=float)))

    def score(name: str, s: np.ndarray, e: np.ndarray, seq_ok: bool = True, note: str = "") -> None:
        err = unit_err(s, e)
        ok = np.isfinite(err)
        entry: dict[str, Any] = {"units": int(ok.sum()),
                                 "hit100": round(float(np.mean(err[ok] <= 0.1)), 4),
                                 "hit200": round(float(np.mean(err[ok] <= 0.2)), 4),
                                 "hit250": round(float(np.mean(err[ok] <= 0.25)), 4),
                                 "mae_both_sec": round(float(np.mean(err[ok])), 4),
                                 "median_both_sec": round(float(np.median(err[ok])), 4)}
        if seq_ok:
            # structure on the natural per-(view, song) sequence order
            order = np.lexsort((units["canonical_unit_id"].to_numpy(dtype=float),
                                pd.factorize(units["song"].to_numpy())[0],
                                pd.factorize(units["view_id"].to_numpy())[0]))
            groups = (units["view_id"].astype(str) + "|" + units["song"].astype(str)).to_numpy()[order]
            st = J.structure_metrics(s[order], e[order], groups)
            entry["structure"] = st
        if note:
            entry["note"] = note
        out["systems"][name] = entry

    ukey = key

    def align_to_units(frame: pd.DataFrame, col_s: str, col_e: str) -> tuple[np.ndarray, np.ndarray]:
        m = units.merge(frame[ukey + [col_s, col_e]].drop_duplicates(subset=ukey),
                        on=ukey, how="left")
        return m[col_s].to_numpy(dtype=float), m[col_e].to_numpy(dtype=float)

    raw_s, raw_e = align_to_units(d, "raw_start_sec", "raw_end_sec")
    score("A_single_window_arbitrary_attempt", raw_s, raw_e,
          note="the first window that covered the unit (request order, value-agnostic)")
    off_s, off_e = align_to_units(d, "off_start_sec", "off_end_sec")
    score("B_shipped_official_same_attempt", off_s, off_e,
          note="official stage of that same single window")
    cons_s = units["consensus_start"].to_numpy(dtype=float)
    cons_e = units["consensus_end"].to_numpy(dtype=float)
    score("C_cross_window_consensus", cons_s, cons_e, note="median boundary over covering windows")

    # consensus fed through the joint constrained solve, per (view, song) timeline sequence
    tmp = units[["view_id", "song", "canonical_unit_id", "consensus_start", "consensus_end"]].copy()
    tmp = tmp.sort_values(["view_id", "song", "canonical_unit_id"]).reset_index(drop=True)
    statuses: dict[str, int] = {}
    caps = {}
    for cap in (3.0, 6.0, 12.0):
        res_s = np.empty(len(tmp))
        res_e = np.empty(len(tmp))
        for _k, sub in tmp.groupby(["view_id", "song"], observed=True):
            pos = sub.index.to_numpy()
            S, E, rep = J.solve_block(sub["consensus_start"].to_numpy(dtype=float),
                                      sub["consensus_end"].to_numpy(dtype=float),
                                      min_dur=J.MIN_DUR_SEC, max_dur=cap)
            res_s[pos] = S
            res_e[pos] = E
            statuses[rep.status] = statuses.get(rep.status, 0) + 1
        back = tmp[["view_id", "song", "canonical_unit_id"]].copy()
        back[f"lp{int(cap)}_start_sec"] = res_s
        back[f"lp{int(cap)}_end_sec"] = res_e
        caps[cap] = align_to_units(back, f"lp{int(cap)}_start_sec", f"lp{int(cap)}_end_sec")
        name = ("D_consensus_plus_joint_solve" if cap == 3.0
                else f"D{int(cap)}_consensus_plus_solve_max{int(cap)}s")
        score(name, caps[cap][0], caps[cap][1],
              note=f"consensus then one constrained solve per timeline (max_dur {cap}s)",
              seq_ok=True)
    out["solve_statuses"] = statuses
    out["max_dur_sensitivity"] = {str(c): out["systems"].get(
        "D_consensus_plus_joint_solve" if c == 3.0 else f"D{int(c)}_consensus_plus_solve_max{int(c)}s"
        )["hit100"] for c in caps}

    # best-possible: oracle attempt per unit (upper bound, uses GT)
    orc_s, orc_e = align_to_units(
        d.loc[d.groupby(ukey, observed=True)["attempt_both_err"].idxmin()],
        "raw_start_sec", "raw_end_sec")
    score("E_oracle_attempt_per_unit", orc_s, orc_e, seq_ok=False,
          note="upper bound: pick the best attempt with GT (not deployable)")
    a, c, dd = (out["systems"]["A_single_window_arbitrary_attempt"],
                out["systems"]["C_cross_window_consensus"],
                out["systems"]["D_consensus_plus_joint_solve"])
    out["summary"] = {
        "gain_consensus_vs_single_pp": round((c["hit100"] - a["hit100"]) * 100, 3),
        "gain_consensus_solve_vs_single_pp": round((dd["hit100"] - a["hit100"]) * 100, 3),
        "structure_before_after_solve": {
            "consensus": c.get("structure"), "consensus_plus_solve": dd.get("structure")},
        "oracle_ceiling_pp": round(
            (out["systems"]["E_oracle_attempt_per_unit"]["hit100"] - a["hit100"]) * 100, 3),
        "note_on_cap": ("the 3 s duration cap costs accuracy on long-note material; "
                        "max_dur should be derived from the note/syllable prior, not a constant"),
    }
    return out
