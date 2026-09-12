"""Measurement validity: how much of a reported boundary metric is the clamp, not the model?

Round 16 found that ``append_strict_core_commits`` clamps ``end := max(end, start)`` before overlap
handling, so a decoder start/end inversion is silently converted into a zero-length unit.  The same
code path produced the evaluation panels used earlier in this session, so every "end accuracy"
number needs a contamination bound: how much of it changes if degenerate (zero-length) units are
excluded, and how the inverted units behave on their own.

This module only re-reads existing panels; it introduces no new decoding and changes no metric
definition (the canonical ``both_abs_err = max(|start_err|, |end_err|)``口径 is reused).
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd


def _num(frame: pd.DataFrame, col: str) -> np.ndarray:
    if col not in frame.columns:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float)


def stage_shape(frame: pd.DataFrame, start_col: str, end_col: str) -> dict[str, Any]:
    """Negative / zero-length shares of one boundary stage, as stored in the panel."""
    s, e = _num(frame, start_col), _num(frame, end_col)
    ok = np.isfinite(s) & np.isfinite(e)
    if not ok.any():
        return {"available": False, "column": f"{start_col}/{end_col}"}
    d = e[ok] - s[ok]
    return {"available": True, "column": f"{start_col}/{end_col}", "n": int(ok.sum()),
            "negative_share": round(float(np.mean(d < -1e-6)), 5),
            "zero_share": round(float(np.mean(np.abs(d) <= 1e-6)), 5),
            "negative_units": int(np.sum(d < -1e-6)), "zero_units": int(np.sum(np.abs(d) <= 1e-6))}


def clamp_signature(frame: pd.DataFrame, upstream: tuple[str, str],
                    downstream: tuple[str, str]) -> dict[str, Any]:
    """Evidence that a silent clamp sits between two stages: negatives upstream, none downstream."""
    up, down = stage_shape(frame, *upstream), stage_shape(frame, *downstream)
    if not up["available"] or not down["available"]:
        return {"available": False, "upstream": up, "downstream": down}
    return {"available": True,
            "upstream_negative_share": up["negative_share"],
            "downstream_negative_share": down["negative_share"],
            "upstream_zero_share": up["zero_share"],
            "downstream_zero_share": down["zero_share"],
            "clamp_present": bool(up["negative_units"] > 0 and down["negative_units"] == 0),
            "extra_zero_downstream_units": int(down["zero_units"] - up["zero_units"])}


def metric_impact(frame: pd.DataFrame, *, pred_start: str, pred_end: str,
                  gt_start: str, gt_end: str, tol_sec: float = 0.1,
                  exclude_zero: bool = True) -> dict[str, Any]:
    """Headline metric with and without degenerate units: the contamination bound."""
    ps, pe = _num(frame, pred_start), _num(frame, pred_end)
    gs, ge = _num(frame, gt_start), _num(frame, gt_end)
    ok = np.isfinite(ps) & np.isfinite(pe) & np.isfinite(gs) & np.isfinite(ge)
    if not ok.any():
        return {"available": False}
    err = np.maximum(np.abs(ps - gs), np.abs(pe - ge))
    dur = pe - ps
    res: dict[str, Any] = {"available": True, "n": int(ok.sum()),
                           "hit_at_tol": round(float(np.mean(err[ok] <= tol_sec)), 4),
                           "mae_end_sec": round(float(np.mean(np.abs(pe[ok] - ge[ok]))), 4),
                           "tolerance_sec": tol_sec}
    degenerate = np.abs(dur) <= 1e-6
    res["degenerate_units"] = int(np.sum(ok & degenerate))
    res["degenerate_share"] = round(float(np.mean(degenerate[ok])), 4)
    if exclude_zero:
        keep = ok & ~degenerate
        if keep.any():
            res["hit_at_tol_excluding_degenerate"] = round(float(np.mean(err[keep] <= tol_sec)), 4)
            res["mae_end_sec_excluding_degenerate"] = round(
                float(np.mean(np.abs(pe[keep] - ge[keep]))), 4)
            res["contamination_bound_pp"] = round(
                100.0 * (res["hit_at_tol_excluding_degenerate"] - res["hit_at_tol"]), 3)
    # the inverted sub-population, reported on its own
    inv = ok & (dur < -1e-6)
    if inv.any():
        res["inverted_units"] = int(inv.sum())
        res["inverted_hit_at_tol"] = round(float(np.mean(err[inv] <= tol_sec)), 4)
        res["inverted_mae_end_sec"] = round(float(np.mean(np.abs(pe[inv] - ge[inv]))), 4)
    return res
