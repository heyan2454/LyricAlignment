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
