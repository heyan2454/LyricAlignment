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


def unreachable_geometry(frame: pd.DataFrame, *, pred_sec: str, top2cls: str, gt_sec: str,
                         entropy_col: str | None = None, margin_col: str | None = None,
                         tol_bins: int = 1) -> dict[str, Any]:
    """Split the unreachable cases into *between the two candidates* and *outside their span*.

    This is the decision-relevant refinement of `containment`: if the ground-truth bin lies between
    the top-1 and the runner-up, a constrained/monotone decode (or an interpolation over the two
    candidate classes) can still reach it without new evidence; if it lies outside the span, no
    reshuffling of these candidates helps and the fix must produce new candidates (longer right
    context, a different window split, or more training signal).

    Distance is measured in bins of ``TIMESTAMP_STEP_SEC``; ``tol_bins`` widens "reachable by span"
    by that many bins on each side to absorb grid rounding.
    """
    pred_bin = _bin_index(pd.to_numeric(frame[pred_sec], errors="coerce").to_numpy(dtype=float))
    # top2cls is already a bin/class index; converting it again (as an earlier draft did) inflates
    # the candidate span by 1/step and makes every GT look "left" of the span
    second = pd.to_numeric(frame[top2cls], errors="coerce").to_numpy(dtype=float)
    gt_bin = _bin_index(pd.to_numeric(frame[gt_sec], errors="coerce").to_numpy(dtype=float))
    ok = np.isfinite(pred_bin) & np.isfinite(second) & np.isfinite(gt_bin)
    if not ok.any():
        return {"available": False}
    pb, sb, gb = pred_bin[ok], second[ok], gt_bin[ok]
    lo, hi = np.minimum(pb, sb), np.maximum(pb, sb)
    exact_hit = (np.abs(pb - gb) <= 1e-9) | (np.abs(sb - gb) <= 1e-9)
    within_tol = (np.abs(pb - gb) <= tol_bins) | (np.abs(sb - gb) <= tol_bins)
    unreachable = ~within_tol
    between = unreachable & (gb >= lo - tol_bins) & (gb <= hi + tol_bins)
    left = unreachable & (gb < lo - tol_bins)
    right = unreachable & (gb > hi + tol_bins)
    n = int(unreachable.sum())
    out: dict[str, Any] = {
        "available": True, "units": int(ok.sum()), "tol_bins": tol_bins,
        "exact_hit_share": round(float(exact_hit.mean()), 4),
        "within_tol_share": round(float(within_tol.mean()), 4),
        "unreachable_units": n, "unreachable_share": round(n / max(int(ok.sum()), 1), 4),
        "between_candidates_share_of_unreachable": round(float(between.sum() / n), 4) if n else None,
        "outside_span_share_of_unreachable": round(float((left.sum() + right.sum()) / n), 4) if n else None,
        "outside_left_share_of_unreachable": round(float(left.sum() / n), 4) if n else None,
        "outside_right_share_of_unreachable": round(float(right.sum() / n), 4) if n else None,
        "candidate_span_bins_when_unreachable": {},
        "distance_outside_bins": {},
    }
    span = (hi - lo)[unreachable]
    if span.size:
        out["candidate_span_bins_when_unreachable"] = {
            "median": float(np.median(span)), "p90": float(np.percentile(span, 90)),
            "median_sec": round(float(np.median(span)) * TIMESTAMP_STEP_SEC, 3)}
    dist = np.where(left, lo - gb, np.where(right, gb - hi, 0.0))[unreachable]
    if dist.size:
        out["distance_outside_bins"] = {"median_when_outside": float(np.median(dist[dist > 0]))
                                        if (dist > 0).any() else 0.0,
                                        "p90_when_outside": float(np.percentile(dist[dist > 0], 90))
                                        if (dist > 0).any() else 0.0,
                                        "median_sec_when_outside": round(
                                            float(np.median(dist[dist > 0])) * TIMESTAMP_STEP_SEC, 3)
                                        if (dist > 0).any() else 0.0}
    # can the decoder's own uncertainty tell "interpolate" from "re-decode"?
    for col, key in ((entropy_col, "entropy"), (margin_col, "margin")):
        if not col or col not in frame.columns:
            continue
        v = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float)[ok]
        good = np.isfinite(v)
        if good.sum() < 40 and (between | (left | right)).sum() == 0:
            continue
        b, o = v[good & between[good] if len(v[good]) == good.sum() else good], None
        # index the label arrays with the same mask used for v
        labels_bt = between & good
        labels_ot = (left | right) & good
        vb, vo = v[labels_bt], v[labels_ot]
        if vb.size >= 20 and vo.size >= 20:
            out[f"{key}_between_candidates_median"] = round(float(np.median(vb)), 4)
            out[f"{key}_outside_span_median"] = round(float(np.median(vo)), 4)
            from lyricalign.realign_gate.gate_features import roc_auc
            lab = np.zeros(int(labels_bt.sum() + labels_ot.sum()))
            sc = np.concatenate([vb, vo])
            lab[: int(labels_bt.sum())] = 1.0
            auc = roc_auc(lab, sc)
            if auc is not None:
                out[f"auc_{key}_predicts_between_candidates"] = round(auc, 4)
    return out


def signed_bias(frame: pd.DataFrame, *, pred_col: str, gt_col: str) -> dict[str, Any]:
    """Median/mean signed error (prediction minus reference) and the share of late predictions."""
    d = (pd.to_numeric(frame[pred_col], errors="coerce")
         - pd.to_numeric(frame[gt_col], errors="coerce")).to_numpy(dtype=float)
    ok = np.isfinite(d)
    if not ok.any():
        return {"available": False}
    d = d[ok]
    return {"available": True, "n": int(d.size),
            "median_ms": round(float(np.median(d)) * 1000, 1),
            "mean_ms": round(float(np.mean(d)) * 1000, 1),
            "late_share": round(float(np.mean(d > 0)), 4),
            "abs_median_ms": round(abs(float(np.median(d))) * 1000, 1)}


def bias_by_stratum(frame: pd.DataFrame, *, strata: dict[str, "np.ndarray"],
                    end_pred: str = "pred_end_sec", end_gt: str = "gt_end_sec",
                    start_pred: str = "pred_start_sec", start_gt: str = "gt_start_sec"
                    ) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, mask in strata.items():
        sub = frame[mask]
        if not len(sub):
            continue
        out[name] = {"units": int(len(sub)),
                     "end": signed_bias(sub, pred_col=end_pred, gt_col=end_gt),
                     "start": signed_bias(sub, pred_col=start_pred, gt_col=start_gt)}
    return out


def transfer_direction_check(studio: dict[str, Any], target: dict[str, Any],
                            stratum: str = "long_note") -> dict[str, Any]:
    """Would a bias correction calibrated on one domain help the other?  Compare signs, not sizes.

    A global offset correction can only transfer when the two domains err in the same direction.  If
    the signs disagree, a studio-calibrated shift actively hurts real accompanied recordings — which
    is exactly what was measured on 2026-09-12 and why that idea is recorded as closed.
    """
    a = (studio.get(stratum) or {}).get("end", {})
    b = (target.get(stratum) or {}).get("end", {})
    if not a.get("available") or not b.get("available"):
        return {"available": False}
    direction_a = np.sign(a["median_ms"]) if abs(a["median_ms"]) > 1.0 else 0.0
    direction_b = np.sign(b["median_ms"]) if abs(b["median_ms"]) > 1.0 else 0.0
    late_a, late_b = a["late_share"], b["late_share"]
    return {"available": True, "stratum": stratum,
            "studio_median_ms": a["median_ms"], "target_median_ms": b["median_ms"],
            "studio_late_share": late_a, "target_late_share": late_b,
            "same_direction": bool(direction_a == direction_b and direction_a != 0.0),
            "late_share_gap": round(abs(late_a - late_b), 4),
            "verdict": ("transferable" if direction_a == direction_b and direction_a != 0.0
                        else "NOT transferable: the two domains err in opposite directions, "
                             "so a global offset calibrated on one would hurt the other")}
