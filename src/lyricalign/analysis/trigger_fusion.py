"""Fuse the reference-free triggers into one re-decode flag, and turn it into a per-song queue.

Three cheap signals have been validated separately in this session:

* **inversion** — the decoder emitted ``end`` before ``start`` at the raw stage (round 15: units that
  later collapse have ~8–10x the rate of these; round 16: they are silently clamped to zero length);
* **low confidence** — small top-1 boundary probability / large entropy at a boundary (round 19:
  confidence tracks whether the ground-truth bin is even a candidate, AUC 0.79 overall);
* **residual gap energy** — ``gap_over_core``, the energy still present in the inter-unit gap
  relative to the unit's own core energy (round 26: AUC 0.87 on the production view for
  "the note was cut early").

This module joins them per unit, measures each one and their combination against ground-truth
failure modes on GTSinger (human labels, not a test set), reports **recall at a review budget** so the
cost of acting on the flag is explicit, and then applies the frozen rule set to a batch without
references, where the output is a re-decode queue rather than an accuracy claim.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

TRUNCATION_TOL_SEC = 0.08
ERROR_TOL_SEC = 0.1
BUDGETS = (0.05, 0.10, 0.20)
ENTROPY_FLAG_QUANTILE = 0.8   # within-batch rank, because an *absolute* entropy threshold does not
                              # transfer: frozen at 1.0 nats it flagged 68.7 % of the product batch
GAP_RESIDUAL_FLAG = 0.5   # gap energy >= half the unit's own core energy (round 26 flat/falling split)
LOW_CONF_FLAG = 0.5       # 1 - top1_prob >= 0.5, i.e. the winning boundary class holds <= 50 % mass



def _num(d: pd.DataFrame, name: str) -> pd.Series:
    """Numeric column as a float Series of the right length; absent columns become all-NaN."""
    if name not in d.columns:
        return pd.Series(np.nan, index=d.index, dtype=float)
    return pd.to_numeric(d[name], errors="coerce")


def _rank_pct(x: pd.Series) -> pd.Series:
    return x.rank(pct=True, na_option="keep")


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Reference-free per-unit features and boolean flags from whichever signals a batch records.

    Continuous features (higher = more suspicious): ``f_inversion`` (0/1), ``f_low_conf_end``
    (= 1 − top-1 probability, when the batch records it), ``f_entropy_end`` (boundary entropy),
    ``f_gap_residual`` (``gap_over_core``, round 26). ``fused_mean_rank`` averages the rank
    percentiles of the features that are actually present, so a batch that records fewer signals
    degrades instead of getting invented values.
    """
    d = frame.copy()
    rs, re_ = _num(d, "raw_start_sec"), _num(d, "raw_end_sec")
    d["f_inversion"] = np.where(rs.notna() & re_.notna(), (re_ - rs < -1e-6).astype(float), np.nan)
    t1e = _num(d, "raw_top1_end")
    if t1e.notna().any():
        d["f_low_conf_end"] = np.where(t1e.notna(), 1.0 - t1e.to_numpy(dtype=float), np.nan)
    ent = _num(d, "raw_entropy_end")
    if ent.notna().any():
        d["f_entropy_end"] = ent.to_numpy(dtype=float)
    g = _num(d, "gap_over_core")
    d["f_gap_residual"] = np.where(g.notna(), g.to_numpy(dtype=float), np.nan)

    d["flag_inversion"] = d["f_inversion"] == 1.0
    if "f_gap_residual" in d.columns:
        d["flag_gap_residual"] = d["f_gap_residual"] >= GAP_RESIDUAL_FLAG   # round 26: flat ~ core level
    if "f_entropy_end" in d.columns:
        e = _rank_pct(d["f_entropy_end"])
        d["flag_high_entropy_end"] = e >= ENTROPY_FLAG_QUANTILE
    if "f_low_conf_end" in d.columns:
        d["flag_low_conf_end"] = d["f_low_conf_end"] >= LOW_CONF_FLAG       # top-1 prob <= 0.5

    parts = {name: _rank_pct(_num(d, name)) for name in
             ("f_inversion", "f_low_conf_end", "f_entropy_end", "f_gap_residual")
             if name in d.columns and _num(d, name).notna().any()}
    if parts:
        d["fused_mean_rank"] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    return d


FLAG_COLUMNS = ("flag_inversion", "flag_gap_residual", "flag_high_entropy_end", "flag_low_conf_end")


def any_flag(d: pd.DataFrame) -> pd.Series:
    cols = [c for c in FLAG_COLUMNS if c in d.columns]
    if not cols:
        return pd.Series(False, index=d.index)
    return pd.concat([_num(d.assign(**{c: d[c].astype(float)}), c) for c in cols],
                     axis=1).fillna(0).max(axis=1) >= 0.5


def _labels(d: pd.DataFrame) -> dict[str, np.ndarray]:
    pe = pd.to_numeric(d.get("pred_end_sec"), errors="coerce")
    ps = pd.to_numeric(d.get("pred_start_sec"), errors="coerce")
    ge = pd.to_numeric(d.get("gt_end_sec"), errors="coerce")
    gs = pd.to_numeric(d.get("gt_start_sec"), errors="coerce")
    both = np.maximum((ps - gs).abs().to_numpy(dtype=float), (pe - ge).abs().to_numpy(dtype=float))
    late = (ge - pe).to_numpy(dtype=float)
    return {"truncated_end": late > TRUNCATION_TOL_SEC,
            "any_error_gt_100ms": both > ERROR_TOL_SEC,
            "end_error_gt_100ms": np.abs(late) > ERROR_TOL_SEC}


def evaluate_triggers(d: pd.DataFrame) -> dict[str, Any]:
    """Per-trigger and fused recall at a review budget, against each ground-truth failure mode."""
    from lyricalign.realign_gate.gate_features import roc_auc
    d = d.reset_index(drop=True)
    labels = _labels(d)
    scores: dict[str, pd.Series] = {
        name: _num(d, col) for name, col in
        (("inversion", "f_inversion"), ("low_conf_end", "f_low_conf_end"),
         ("high_entropy_end", "f_entropy_end"), ("gap_residual", "f_gap_residual"),
         ("fused_mean_rank", "fused_mean_rank"))
        if col in d.columns}
    scores["any_flag_boolean"] = any_flag(d).astype(float)
    out: dict[str, Any] = {"triggers": {}, "features_used": sorted(scores)}
    for label, y in labels.items():
        blk: dict[str, Any] = {"prevalence": round(float(np.mean(y)), 4), "n": int(y.sum())}
        for name, sc in scores.items():
            v = pd.to_numeric(sc, errors="coerce").to_numpy(dtype=float)
            ok = np.isfinite(v)
            if ok.sum() < 50 or y[ok].sum() in (0, ok.sum()):
                continue
            auc = roc_auc(y[ok].astype(float), v[ok])
            order = np.argsort(-v[ok])
            entry: dict[str, Any] = {"units_scored": int(ok.sum()),
                                     "auc": round(float(auc), 4) if auc is not None else None}
            for b in BUDGETS:
                top = order[: max(1, int(round(b * ok.sum())))]
                entry[f"recall_at_{int(b * 100)}pct_budget"] = round(
                    float(y[ok][top].sum() / max(y.sum(), 1)), 4)
                # recall over the *scored* subset, so a feature with partial coverage (the gap
                # residual exists only where a measurable inter-unit gap exists) is not read as weak
                entry[f"recall_within_scored_at_{int(b * 100)}pct_budget"] = round(
                    float(y[ok][top].sum() / max(y[ok].sum(), 1)), 4)
                entry[f"precision_at_{int(b * 100)}pct_budget"] = round(float(y[ok][top].mean()), 4)
            blk[name] = entry
        out["triggers"][label] = blk
    return out


def redecode_queue(d: pd.DataFrame, *, group_cols: Sequence[str], review_budget: float = 0.15
                   ) -> pd.DataFrame:
    """Rank units/groups by the fused trigger so re-decode effort goes where the evidence is.

    With references present the queue is a validated detector; without them the columns are
    prevalence-style counts and must be read as "where to look", not as an accuracy estimate.
    """
    d = d.reset_index(drop=True)
    work = d.assign(_score=_num(d, "fused_mean_rank"), _any_flag=any_flag(d).to_numpy(dtype=bool))
    rows: list[dict[str, Any]] = []
    for key, sub in work.groupby(list(group_cols), observed=True):
        if not isinstance(key, tuple):        # pandas yields a scalar for a single group column
            key = (key,)
        thr = sub["_score"].quantile(1.0 - review_budget)
        rows.append({**{c: v for c, v in zip(group_cols, key)},
                     "units": int(len(sub)),
                     "flagged_share": round(float(sub["_any_flag"].mean()), 4),
                     "inversion_units": int(sub.get("flag_inversion", pd.Series(dtype=bool)).sum()
                                             if "flag_inversion" in sub else 0),
                     "gap_residual_units": int(sub["flag_gap_residual"].sum()
                                               if "flag_gap_residual" in sub else 0),
                     "high_entropy_units": int(sub["flag_high_entropy_end"].sum()
                                               if "flag_high_entropy_end" in sub else 0),
                     "low_conf_end_units": int(sub["flag_low_conf_end"].sum()
                                               if "flag_low_conf_end" in sub else 0),
                     "median_fused_score": round(float(np.nanmedian(sub["_score"])), 4),
                     "p90_fused_score": round(float(np.nanpercentile(sub["_score"], 90)), 4),
                     "score_cut_at_budget": round(float(thr), 4) if np.isfinite(thr) else None})
    q = pd.DataFrame(rows)
    if len(q):
        q = q.sort_values(["flagged_share", "median_fused_score"], ascending=False).reset_index(drop=True)
    return q
