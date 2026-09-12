"""How much room does multi-decode selection actually have?  Measure the error-correlation structure.

Round 9 found that consensus over multiple views bought only a couple of points, and round 19 explains
why in general terms (the right answer is often not a candidate at all).  This module measures the
missing middle: per unit, **how many of the k decodes are within tolerance**, which separates two very
different situations that an accuracy average hides —

* errors are *decorrelated* (some decode is right on most units) → a selector/realign has real room, and
  the regret of the shipped single view is mostly a selection problem;
* errors are *correlated* (0 of k right on many units) → no selection over these decodes can help;
  the ceiling is the decoders', and only new evidence (different windows, training, re-decode) moves it.

Discipline: on MIR-1K these are retrospective bounds computed on test-only data with human labels.
They are reported as measurements of headroom and are never used to select a checkpoint, a view or a
threshold; deployment decisions come from GTSinger (also human GT, not test) and M4 (weak labels).
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

TOLS_SEC = (0.05, 0.1, 0.2)


def correctness_matrix(long: pd.DataFrame, *, unit_key: Sequence[str], view_col: str,
                       err_col: str = "both_err", tol_sec: float = 0.1) -> tuple[np.ndarray, list[Any]]:
    """Boolean matrix (units × views): is this decode within tolerance on this unit?"""
    d = long.dropna(subset=[err_col, view_col])
    units = pd.Index(sorted(d[unit_key].drop_duplicates().itertuples(index=False, name=None)))
    views = sorted(d[view_col].astype(str).unique())
    u_pos = {k: i for i, k in enumerate(units)}
    v_pos = {v: j for j, v in enumerate(views)}
    m = np.zeros((len(units), len(views)), dtype=bool)
    errs = d[err_col].to_numpy(dtype=float)
    keys = list(d[unit_key].itertuples(index=False, name=None))
    vs = d[view_col].astype(str).to_numpy()
    for i, k in enumerate(keys):
        if np.isfinite(errs[i]):
            m[u_pos[k], v_pos[vs[i]]] = bool(errs[i] <= tol_sec + 1e-9)
    return m, units.tolist()


def _stats(m: np.ndarray, production: int | None) -> dict[str, Any]:
    k = m.shape[1]
    n_correct = m.sum(axis=1)
    total = int(m.shape[0])
    out: dict[str, Any] = {
        "units": total, "views": k,
        "per_view_hit": [round(float(m[:, j].mean()), 4) for j in range(k)],
        "best_single_view_hit": round(float(m.mean(axis=0).max()), 4),   # best *individual* decode
        "union_oracle_hit": round(float((n_correct >= 1).mean()), 4),
        "mean_views_correct": round(float(n_correct.mean()), 3),
        "all_views_correct_share": round(float((n_correct == k).mean()), 4),
        "no_view_correct_share": round(float((n_correct == 0).mean()), 4),
        "correct_count_histogram": {str(i): int((n_correct == i).sum()) for i in range(k + 1)},
    }
    if production is not None:
        prod = m[:, production]
        out["production_view_hit"] = round(float(prod.mean()), 4)
        out["regret_recoverable_by_selection_pp"] = round(
            100.0 * float(((n_correct >= 1) & ~prod).mean()), 2)
        out["hard_ceiling_units"] = int(((n_correct == 0)).sum())
        out["hard_ceiling_share"] = round(float((n_correct == 0).mean()), 4)
        # how correlated are the decodes' mistakes?  (phi correlation between view error vectors)
        if k > 1:
            a = prod.astype(float)
            cors = []
            for j in range(k):
                if j == production:
                    continue
                b = m[:, j].astype(float)
                if a.std() > 0 and b.std() > 0:
                    cors.append(float(np.corrcoef(a, b)[0, 1]))
            out["mean_pairwise_error_correlation_with_production"] = (
                round(float(np.mean(cors)), 3) if cors else None)
    return out


def ceiling_by_stratum(long: pd.DataFrame, *, unit_key: Sequence[str], view_col: str,
                       strata: dict[str, np.ndarray], production_view: str | None = None,
                       err_col: str = "both_err", tol_sec: float = 0.1,
                       view_names: list[str] | None = None) -> dict[str, Any]:
    """Union/regret statistics per stratum, plus the correlation structure that explains them."""
    out: dict[str, Any] = {"tolerance_sec": tol_sec, "strata": {}}
    for tol in TOLS_SEC:
        if tol != tol_sec:
            continue
    views = sorted(long[view_col].astype(str).unique())
    prod_idx = views.index(production_view) if production_view in views else None
    m_all, keys = correctness_matrix(long, unit_key=unit_key, view_col=view_col,
                                     err_col=err_col, tol_sec=tol_sec)
    key_index = {k: i for i, k in enumerate(keys)}
    for name, mask in strata.items():
        rows = np.array([key_index[k] for k in
                         list(long.loc[mask, unit_key].drop_duplicates().itertuples(index=False, name=None))
                         if k in key_index], dtype=int)
        if rows.size == 0:
            continue
        out["strata"][name] = _stats(m_all[rows], prod_idx)
    # tolerance sensitivity on the whole panel (how much of the "ceiling" is just tolerance choice)
    out["tolerance_sensitivity"] = {}
    for tol in TOLS_SEC:
        m_t, _ = correctness_matrix(long, unit_key=unit_key, view_col=view_col,
                                    err_col=err_col, tol_sec=tol)
        nc = m_t.sum(axis=1)
        out["tolerance_sensitivity"][f"{int(tol * 1000)}ms"] = {
            "union_oracle_hit": round(float((nc >= 1).mean()), 4),
            "no_view_correct_share": round(float((nc == 0).mean()), 4),
            "mean_views_correct": round(float(nc.mean()), 3)}
    out["views"] = views
    return out


def build_long_from_wide(frame: pd.DataFrame, *, view_prefix_col: str, unit_key: Sequence[str],
                         gt_start: str, gt_end: str) -> pd.DataFrame:
    """Turn one-row-per-(unit,view) records into the long format this module expects."""
    d = frame.dropna(subset=[view_prefix_col, "pred_start_sec", "pred_end_sec", gt_start, gt_end]).copy()
    d["both_err"] = np.maximum((d["pred_start_sec"] - d[gt_start]).abs(),
                               (d["pred_end_sec"] - d[gt_end]).abs())
    return d
