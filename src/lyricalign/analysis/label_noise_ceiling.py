"""Is a weak trigger a weak signal, or a weak label?  Quantisation-aware diagnostics.

Round 30 replicated the boundary-confidence trigger on M4Singer at AUC 0.66 versus 0.85 on GTSinger,
but the two corpora differ in label quality as well as in acoustics: M4's references are
rule-validated weak labels quantised to the 80 ms TextGrid grid, so a unit whose true error sits
within one quantisation step of the decision threshold can have its binary label flipped by the
label, not by the model.  Reporting a single AUC there mixes "the signal is weaker" with
"the label is coarser".

This module separates the two:

* threshold sensitivity — AUC as the tolerance moves, on both corpora;
* ambiguous-label exclusion — drop units whose |error| is within one label quantum of the threshold
  and recompute; if the AUC jumps toward the other corpus's value, the gap was largely label noise;
* slice decomposition — AUC within the label-reliable subsets (original, non-mutated timelines,
  unambiguous neighbours, train/validation splits).
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from lyricalign.realign_gate.gate_features import roc_auc


def _auc(y: np.ndarray, score: np.ndarray) -> float | None:
    ok = np.isfinite(score) & np.isfinite(y)
    if ok.sum() < 30 or y[ok].sum() in (0, ok.sum()):
        return None
    a = roc_auc(y[ok], score[ok])
    return None if a is None else round(float(a), 4)


def threshold_sensitivity(err: pd.Series, score: pd.Series, *,
                          thresholds: Sequence[float] = (0.08, 0.1, 0.12, 0.16, 0.2, 0.25)
                          ) -> dict[str, Any]:
    """AUC of a score against ``error > threshold`` for several thresholds."""
    e = pd.to_numeric(err, errors="coerce").to_numpy(dtype=float)
    s = pd.to_numeric(score, errors="coerce").to_numpy(dtype=float)
    out: dict[str, Any] = {"units": int(np.isfinite(e).sum()), "by_threshold": {}}
    for tol in thresholds:
        y = np.where(np.isfinite(e), (e > tol).astype(float), np.nan)
        out["by_threshold"][f"{int(tol * 1000)}ms"] = {
            "prevalence": round(float(np.nanmean(y)), 4) if np.isfinite(y).any() else None,
            "auc": _auc(np.nan_to_num(y, nan=0.0), s)}
    return out


def ambiguous_label_impact(err: pd.Series, score: pd.Series, *, threshold: float,
                           label_quantum_sec: float) -> dict[str, Any]:
    """Recompute the AUC after dropping units whose label could flip under one quantisation step."""
    e = pd.to_numeric(err, errors="coerce").to_numpy(dtype=float)
    s = pd.to_numeric(score, errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(e) & np.isfinite(s)
    if not ok.any():
        return {"available": False}
    e, s = e[ok], s[ok]
    ambiguous = np.abs(e - threshold) <= label_quantum_sec
    y_all = (e > threshold).astype(float)
    keep = ~ambiguous
    y_keep = (e[keep] > threshold).astype(float)
    return {
        "available": True, "units": int(ok.sum()), "threshold_sec": threshold,
        "label_quantum_sec": label_quantum_sec,
        "ambiguous_units": int(ambiguous.sum()),
        "ambiguous_share": round(float(ambiguous.mean()), 4),
        "auc_all": _auc(y_all, s),
        "auc_excluding_ambiguous": _auc(y_keep, s[keep]),
        "auc_change": (None if _auc(y_all, s) is None or _auc(y_keep, s[keep]) is None
                       else round(_auc(y_keep, s[keep]) - _auc(y_all, s), 4)),
        "prevalence_all": round(float(y_all.mean()), 4),
        "prevalence_excluding_ambiguous": round(float(y_keep.mean()), 4) if keep.any() else None,
    }


def slice_decomposition(frame: pd.DataFrame, *, err_col: str, score_col: str,
                        slices: dict[str, "np.ndarray"]) -> dict[str, Any]:
    """Same score and target, restricted to label-quality strata."""
    out: dict[str, Any] = {}
    for name, mask in slices.items():
        sub = frame[mask]
        if len(sub) < 50:
            out[name] = {"units": int(len(sub)), "note": "too few units"}
            continue
        y = (pd.to_numeric(sub[err_col], errors="coerce") > 0.1).to_numpy(dtype=float)
        out[name] = {"units": int(len(sub)),
                     "prevalence": round(float(np.nanmean(y)), 4),
                     "median_err_ms": round(float(np.nanmedian(
                         pd.to_numeric(sub[err_col], errors="coerce"))) * 1000, 1),
                     "auc": _auc(np.nan_to_num(y, nan=0.0),
                                 pd.to_numeric(sub[score_col], errors="coerce").to_numpy(dtype=float))}
    return out


def metric_stability(err: pd.Series, *, tolerances: Sequence[float] = (0.05, 0.1, 0.2, 0.25),
                     label_quantum_sec: float = 0.08,
                     prediction_quantum_sec: float = 0.08) -> dict[str, Any]:
    """How much of a hit@tolerance number is decided by grid rounding rather than by quality?

    A unit is *flippable* at tolerance t if moving either side of the comparison by one quantum
    (label or prediction grid) changes hit <-> miss.  The flippable share is the honest floor on
    detectable improvement: **two systems whose hit@t differs by less than the flippable share are
    not separated by this metric**, and any difference below it must be reported as unproven.
    """
    e = pd.to_numeric(err, errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(e)
    e = e[ok]
    out: dict[str, Any] = {"units": int(e.size), "label_quantum_sec": label_quantum_sec,
                           "prediction_quantum_sec": prediction_quantum_sec, "by_tolerance": {}}
    if not e.size:
        out["note"] = "no finite errors"
        return out
    quantum = max(label_quantum_sec, prediction_quantum_sec)
    for tol in tolerances:
        inside = e <= tol
        flippable = np.abs(e - tol) <= quantum
        # a unit only counts as truly ambiguous if the flip would change the verdict either way
        strictly_inside = (e > tol) & (e <= tol + quantum)
        strictly_outside = (e <= tol) & (e > tol - quantum)
        out["by_tolerance"][f"{int(tol * 1000)}ms"] = {
            "hit_share": round(float(inside.mean()), 4),
            "flippable_share": round(float(flippable.mean()), 4),
            "flippable_units": int(flippable.sum()),
            "would_flip_to_hit_units": int(strictly_outside.sum()),
            "would_flip_to_miss_units": int(strictly_inside.sum()),
            # two different, precisely-named bounds:
            # (a) systematic one-quantum bias in the same direction for every unit
            # (b) share of units whose verdict is decided by less than one quantum of slack
            "hit_share_if_errors_shifted_minus_quantum": round(
                float((e <= tol - quantum).mean()), 4),
            "hit_share_if_errors_shifted_plus_quantum": round(
                float((e <= tol + quantum).mean()), 4),
            "systematic_shift_bound_pp": round(
                100.0 * float((e <= tol + quantum).mean() - (e <= tol - quantum).mean()), 2),
            "knife_edge_share": round(float(flippable.mean()), 4),
        }
    return out


def compare_with_stability(a_err: pd.Series, b_err: pd.Series, *, tol: float,
                           label_quantum_sec: float = 0.08,
                           prediction_quantum_sec: float = 0.08) -> dict[str, Any]:
    """Is the difference between two systems bigger than what grid rounding can manufacture?"""
    a = pd.to_numeric(a_err, errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(b_err, errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 30:
        return {"available": False}
    a, b = a[ok], b[ok]
    qa = (a > tol).astype(float) * (a <= tol + max(label_quantum_sec, prediction_quantum_sec)).astype(float)
    qb = (b > tol).astype(float) * (b <= tol + max(label_quantum_sec, prediction_quantum_sec)).astype(float)
    hits_a = float((a <= tol).mean())
    hits_b = float((b <= tol).mean())
    flip_share = float(np.mean((np.abs(a - tol) <= max(label_quantum_sec, prediction_quantum_sec)) |
                               (np.abs(b - tol) <= max(label_quantum_sec, prediction_quantum_sec))))
    return {"available": True, "units": int(ok.sum()), "tolerance_sec": tol,
            "hit_a": round(hits_a, 4), "hit_b": round(hits_b, 4),
            "gap_pp": round(100.0 * (hits_a - hits_b), 2),
            "either_side_flippable_share": round(flip_share, 4),
            "min_detectable_gap_pp": round(100.0 * flip_share, 2),
            "gap_is_beyond_grid_rounding": bool(abs(hits_a - hits_b) * 100.0 > 100.0 * flip_share),
            "a_flippable_to_hit_units": int(qb.sum() - qa.sum()) if (qb.sum() - qa.sum()) > 0 else 0}


def gap_artifact_bound(a_err: pd.Series, b_err: pd.Series, *, tol: float,
                       quantum_sec: float = 0.08) -> dict[str, Any]:
    """How much of an A-vs-B hit-rate gap could be pure grid rounding.

    The one-quantum *systematic shift* bound is too pessimistic for this comparison: both systems are
    scored against the **same** labels, so a common label shift moves both hit rates together and
    largely cancels in the difference.  The gap can only be inflated by units where the two systems
    disagree **and** the losing side misses by less than one quantum (its verdict would flip if its
    own boundary were rounded by one grid step).  Counting those gives a tight, directly comparable
    upper bound on the spurious part of the gap.
    """
    a = pd.to_numeric(a_err, errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(b_err, errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 30:
        return {"available": False}
    a, b = a[ok], b[ok]
    n = a.size
    hit_a, hit_b = a <= tol, b <= tol
    a_wins_grid_slack = (hit_a & ~hit_b & (b <= tol + quantum_sec)).sum()
    b_wins_grid_slack = (hit_b & ~hit_a & (a <= tol + quantum_sec)).sum()
    solid_a = (hit_a & ~hit_b & (b > tol + quantum_sec)).sum()
    solid_b = (hit_b & ~hit_a & (a > tol + quantum_sec)).sum()
    gap_pp = 100.0 * (hit_a.mean() - hit_b.mean())
    spurious_pp = 100.0 * (a_wins_grid_slack + b_wins_grid_slack) / n
    return {"available": True, "units": int(n), "tolerance_sec": tol, "quantum_sec": quantum_sec,
            "hit_a": round(float(hit_a.mean()), 4), "hit_b": round(float(hit_b.mean()), 4),
            "gap_pp": round(gap_pp, 2),
            "a_ahead_by_grid_slack_units": int(a_wins_grid_slack),
            "b_ahead_by_grid_slack_units": int(b_wins_grid_slack),
            "a_ahead_solid_units": int(solid_a), "b_ahead_solid_units": int(solid_b),
            "max_spurious_gap_pp": round(spurious_pp, 2),
            "gap_exceeds_grid_slack": bool(abs(gap_pp) > spurious_pp),
            "solid_disagreement_units": int(solid_a + solid_b)}
