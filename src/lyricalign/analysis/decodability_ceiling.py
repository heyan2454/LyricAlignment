"""Decodability ceiling: is the ground-truth boundary even inside the model's candidate set?

Every previous round asks "how good is the boundary we picked?".  This asks the prior question:
for the *hard* strata (long notes, last unit of a phrase) is the correct quantised boundary class
available at all — as the top-1 class, or even as the runner-up?  If it is not, no selector, gate or
consensus rule over these decodes can reach it, and the fix belongs on the training/data side (or a
wider re-decode), not in post-processing.

Available per-boundary evidence in the GTSinger panels (see analysis/gtsinger_gt_evidence.py):
``raw_top1_*`` (probability), ``raw_margin_*`` (top1 minus top2 probability),
``raw_entropy_*``, and ``raw_top2cls_*`` (the runner-up class index).  The winning class index is
recoverable as ``raw_*_sec / timestamp_step_sec`` because the decoder emits bin indices.  So exact
containment can be measured for k=1 and k=2 only; k>=3 is reported as unknown, not guessed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TIMESTAMP_STEP_SEC = 0.08
TOLERANCE_BINS = (0, 1)     # 0 = exact bin, 1 = within one bin (80 ms) of a candidate


def _bin_index(sec: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(sec, dtype=float) / TIMESTAMP_STEP_SEC)


def containment(frame: pd.DataFrame, *, pred_sec: str, top2cls: str, gt_sec: str,
                top1_prob: str | None = None) -> dict[str, Any]:
    """Share of units whose GT bin equals the top-1 or the top-2 predicted bin."""
    n = len(frame)
    if n == 0:
        return {"units": 0}
    pred_bin = _bin_index(pd.to_numeric(frame[pred_sec], errors="coerce").to_numpy(dtype=float))
    second = pd.to_numeric(frame[top2cls], errors="coerce").to_numpy(dtype=float)
    gt_bin = _bin_index(pd.to_numeric(frame[gt_sec], errors="coerce").to_numpy(dtype=float))
    ok = np.isfinite(pred_bin) & np.isfinite(gt_bin) & np.isfinite(second)
    if not ok.any():
        return {"units": 0}
    pb, sb, gb = pred_bin[ok], second[ok], gt_bin[ok]
    out: dict[str, Any] = {"units": int(ok.sum())}
    for tol in TOLERANCE_BINS:
        hit1 = np.abs(pb - gb) <= tol
        hit2 = np.abs(sb - gb) <= tol
        out[f"top1_within_{tol}bins"] = round(float(hit1.mean()), 4)
        out[f"top2_within_{tol}bins"] = round(float(hit2.mean()), 4)
        out[f"in_top2_union_within_{tol}bins"] = round(float((hit1 | hit2).mean()), 4)
        out[f"outside_top2_within_{tol}bins"] = round(float((~(hit1 | hit2)).mean()), 4)
    dist = np.minimum(np.abs(pb - gb), np.abs(sb - gb))
    out["distance_to_nearest_candidate_bins"] = {
        "median": float(np.median(dist)), "p90": float(np.percentile(dist, 90)),
        "max": float(dist.max()), "mean": round(float(np.mean(dist)), 2)}
    out["distance_to_nearest_candidate_sec"] = {
        "median": round(float(np.median(dist)) * TIMESTAMP_STEP_SEC, 3),
        "p90": round(float(np.percentile(dist, 90)) * TIMESTAMP_STEP_SEC, 3)}
    if top1_prob and top1_prob in frame.columns:
        p = pd.to_numeric(frame[top1_prob], errors="coerce").to_numpy(dtype=float)[ok]
        near = (np.abs(pb - gb) <= 1)
        if near.any() and (~near).any():
            out["top1_prob_when_gt_in_candidates"] = round(float(np.mean(p[near])), 4)
            out["top1_prob_when_gt_outside_candidates"] = round(float(np.mean(p[~near])), 4)
        # Can the decoder's own confidence tell us "the GT is not even a candidate"?  If it can, that
        # is a reference-free realign trigger.  Reported in the positive orientation (label = GT is
        # within one bin of some candidate) so the direction cannot be misread; the earlier version
        # labelled the complement, which made an informative signal look like AUC < 0.5 nonsense.
        from lyricalign.realign_gate.gate_features import roc_auc
        inside = ((np.abs(pb - gb) <= 1) | (np.abs(sb - gb) <= 1)).astype(float)
        auc = roc_auc(inside, p)
        if auc is not None:
            out["auc_top1_prob_predicts_gt_within_1bin_of_candidate"] = round(auc, 4)
            out["auc_orientation"] = ("label=1 means the GT bin is within one bin of the top-1 or "
                                      "top-2 candidate; higher AUC = confidence tracks reachability")
    return out


def strata_analysis(frame: pd.DataFrame, *, seq_col: str = "item",
                    strides: tuple[str, ...] = ("all_units", "long_note", "last_unit",
                                                "first_unit", "middle_units", "short_note")
                    ) -> dict[str, Any]:
    """Containment by stratum, with the GT side used per boundary kind."""
    df = frame.reset_index(drop=True)
    gt_dur = pd.to_numeric(df["gt_dur_sec"], errors="coerce").to_numpy(dtype=float)
    pos = df.groupby(seq_col, observed=True).cumcount().to_numpy()
    last_pos = df.groupby(seq_col, observed=True)[seq_col].transform("size").to_numpy() - 1
    masks = {
        "all_units": np.ones(len(df), dtype=bool),
        "long_note": gt_dur >= 1.0,
        "short_note": gt_dur < 0.4,
        "first_unit": pos == 0,
        "last_unit": pos == last_pos,
        "middle_units": (pos > 0) & (pos < last_pos),
    }
    out: dict[str, Any] = {}
    for name in strides:
        mask = masks.get(name)
        if mask is None or not mask.any():
            continue
        sub = df[mask]
        out[name] = {"units": int(len(sub)),
                     "gt_dur_median_sec": round(float(np.nanmedian(gt_dur[mask])), 3),
                     "start": containment(sub, pred_sec="raw_start_sec", top2cls="raw_top2cls_start",
                                          gt_sec="gt_start_sec", top1_prob="raw_top1_start"),
                     "end": containment(sub, pred_sec="raw_end_sec", top2cls="raw_top2cls_end",
                                        gt_sec="gt_end_sec", top1_prob="raw_top1_end")}
    return out


def compare_checkpoints(frame: pd.DataFrame, *, by: str = "model") -> dict[str, Any]:
    """Does LoRA training put the GT bin into the candidate set more often?"""
    out: dict[str, Any] = {}
    for label, sub in frame.groupby(by, observed=True):
        s = strata_analysis(sub)
        entry: dict[str, Any] = {"units": int(len(sub))}
        for stratum, blk in s.items():
            entry[stratum] = {
                "units": blk["units"],
                "end_top1_exact": blk["end"].get("top1_within_0bins"),
                "end_in_top2_exact": blk["end"].get("in_top2_union_within_0bins"),
                "end_outside_top2_exact": blk["end"].get("outside_top2_within_0bins"),
                "end_top1_within1": blk["end"].get("top1_within_1bins"),
                "end_in_top2_within1": blk["end"].get("in_top2_union_within_1bins"),
                "start_top1_exact": blk["start"].get("top1_within_0bins"),
                "start_in_top2_exact": blk["start"].get("in_top2_union_within_0bins"),
            }
        out[str(label)] = entry
    return out
