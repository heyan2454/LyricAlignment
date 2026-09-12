"""Replay alternative boundary post-processing rules on the GTSinger GT panel.

Motivation (2026-09-12 deep analysis, finding 2): the shipped ``official`` post-processor is net
*negative* against real ground truth (paired hit@100 -1.66pp), and 98.3% of the starts it pushes
later land exactly on the previous unit's end — i.e. the harmful part is the overlap-resolution
rule, while its end-trimming half is mostly a repair.  Before touching the implementation, the
question is answerable offline: we already recorded ``raw_*`` (pre-post-processing) and
``selected_*`` (post) boundaries for every unit, together with ground truth.

This module therefore

1. **reconstructs** the shipped rule from data (which side of an overlap moves, as a function of
   overlap size, unit duration and decoder confidence) and reports how exactly it is reproduced;
2. **replays** a small, pre-registered family of alternative rules (never trim / never push /
   proportional split / confidence-weighted split / thresholded resolution / GT-oracle pick);
3. scores every rule against ground truth with the *frozen* tolerances from the previous round
   (100/200 ms), including the strata that aggregate means hide (segment start, onsetless
   syllables), with paired per-segment differences and a segment cluster bootstrap.

No model forward, no audio decoding: pure replay over the recorded evidence panel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

TOL_PRIMARY = 0.100
TOL_SECONDARY = 0.200
N_BOOT = 2000
SEED = 20260912
EPS = 1e-9
SEQ_KEYS = ["pipeline", "item", "model", "audio_input", "mode"]


# ---------------------------------------------------------------------------
# rules: each takes (starts, ends, extras) -> (starts, ends)
# ---------------------------------------------------------------------------

def rule_identity(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    return s.copy(), e.copy()


def rule_sanitize(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    out = e.copy()
    return s.copy(), np.maximum(out, s)


def rule_end_trim(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Resolve overlaps by pulling the *earlier* unit's end back to the next start."""
    S, E = s.astype(float).copy(), e.astype(float).copy()
    for i in range(len(S) - 1, 0, -1):
        if E[i - 1] > S[i] + EPS:
            E[i - 1] = S[i]
    E = np.maximum(E, S)
    return S, E


def rule_start_push(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Resolve overlaps by pushing the *later* unit's start forward to the previous end."""
    S, E = s.astype(float).copy(), e.astype(float).copy()
    for i in range(1, len(S)):
        if S[i] < E[i - 1] - EPS:
            S[i] = E[i - 1]
        E[i] = max(E[i], S[i])
    return S, E


def rule_half_split(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Give both sides half of the overlap (boundary placed at the midpoint)."""
    S, E = s.astype(float).copy(), e.astype(float).copy()
    for i in range(1, len(S)):
        if S[i] < E[i - 1] - EPS:
            mid = (E[i - 1] + S[i]) / 2.0
            E[i - 1] = mid
            S[i] = mid
    E = np.maximum(E, S)
    return S, E


def rule_conf_split(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Confidence-weighted split: the side whose boundary the decoder was less sure about moves.

    Weights use only recorded decoder posteriors (never ground truth): the end of unit i-1 moves by
    ``w_end * overlap`` and the start of unit i by ``w_start * overlap`` with
    ``w_start = conf_start / (conf_start + conf_end)``.
    """
    S, E = s.astype(float).copy(), e.astype(float).copy()
    c_start = ex["conf_start"]
    c_end = ex["conf_end"]
    for i in range(1, len(S)):
        if S[i] < E[i - 1] - EPS:
            overlap = E[i - 1] - S[i]
            denom = c_start[i] + c_end[i - 1]
            w_start = c_start[i] / denom if denom > EPS else 0.5
            # the *more confident* side moves less: start moves with its own confidence weight
            E[i - 1] = E[i - 1] - overlap * w_start
            S[i] = S[i] + overlap * (1.0 - w_start)
            if S[i] > E[i - 1]:                     # over-rotation guard
                mid = (E[i - 1] + S[i]) / 2.0
                E[i - 1] = mid
                S[i] = mid
    E = np.maximum(E, S)
    return S, E


def _thresholded_resolver(kind: str, max_overlap_sec: float) -> Callable:
    """Resolve only overlaps up to ``max_overlap_sec``; leave bigger ones untouched.

    Rationale: a large overlap usually means one of the two boundaries is badly wrong, and forcing
    them together manufactures a second error, while a small overlap is display-level noise.
    ``kind`` selects who yields: ``end`` (trim earlier tail), ``start`` (push later onset) or
    ``half`` (split the difference).
    """

    def rule(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        S, E = s.astype(float).copy(), e.astype(float).copy()
        for i in range(1, len(S)):
            ov = E[i - 1] - S[i]
            if ov <= EPS or ov > max_overlap_sec:
                continue
            if kind == "end":
                E[i - 1] = S[i]
            elif kind == "start":
                S[i] = E[i - 1]
            else:
                mid = (E[i - 1] + S[i]) / 2.0
                E[i - 1], S[i] = mid, mid
        E = np.maximum(E, S)
        return S, E

    rule.__name__ = f"thresholded_{kind}_le{max_overlap_sec}s"
    return rule


def _end_trim_with_min_duration(min_dur_sec: float) -> Callable:
    """End-trim overlaps, but never below a displayable minimum unit duration.

    A zero-length lyric unit cannot be highlighted in a karaoke UI, so a pure end-trim rule has to
    stop at some minimum and leave the residual overlap to the renderer.  This is the production
    variant of ``V2``: it keeps the (helpful) tail correction without manufacturing zero durations.
    """

    def rule(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        S, E = s.astype(float).copy(), e.astype(float).copy()
        for i in range(len(S) - 1, 0, -1):
            if E[i - 1] > S[i] + EPS:
                E[i - 1] = max(S[i], S[i - 1] + min_dur_sec)
        E = np.maximum(E, S)
        return S, E

    rule.__name__ = f"end_trim_min{min_dur_sec}s"
    return rule


def rule_oracle_pick(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Reference bound (uses ground truth): per overlap choose the candidate minimising max error."""
    S, E = s.astype(float).copy(), e.astype(float).copy()
    gs, ge = ex["gt_start"], ex["gt_end"]
    for i in range(1, len(S)):
        if S[i] < E[i - 1] - EPS:
            cands = [
                (E[i - 1], S[i]),                       # keep raw (no resolution)
                (S[i], S[i]),                           # end trim
                (E[i - 1], E[i - 1]),                   # start push
                ((E[i - 1] + S[i]) / 2.0,) * 2,         # half split
            ]
            best = min(cands, key=lambda c: max(abs(c[0] - ge[i - 1]), abs(c[1] - gs[i])))
            E[i - 1], S[i] = best
    E = np.maximum(E, S)
    return S, E


def _half_split_with_min_duration(min_dur_sec: float) -> Callable:
    """Midpoint split that refuses to create sub-minimum units (falls back to end-trim)."""

    def rule(s: np.ndarray, e: np.ndarray, ex: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        S, E = s.astype(float).copy(), e.astype(float).copy()
        for i in range(1, len(S)):
            if S[i] < E[i - 1] - EPS:
                mid = (E[i - 1] + S[i]) / 2.0
                if (mid - S[i - 1] >= min_dur_sec) and (E[i] - mid >= min_dur_sec):
                    E[i - 1], S[i] = mid, mid
                else:                                   # midpoint not displayable
                    E[i - 1] = max(S[i], S[i - 1] + min_dur_sec)
        E = np.maximum(E, S)
        return S, E

    rule.__name__ = f"half_split_min{min_dur_sec}s"
    return rule


RULES: dict[str, Callable] = {
    "V0_shipped_official": None,                      # sentinel: use recorded selected boundaries
    "V1_raw_none": rule_identity,
    "V1b_raw_sanitize": rule_sanitize,
    "V2_end_trim_only": rule_end_trim,
    "V3_start_push_only": rule_start_push,
    "V4_half_split": rule_half_split,
    "V5_confidence_split": rule_conf_split,
    "V6_end_trim_le0.30s": _thresholded_resolver("end", 0.30),
    "V7_half_split_le0.30s": _thresholded_resolver("half", 0.30),
    "V7b_end_trim_le0.10s": _thresholded_resolver("end", 0.10),
    "V9_end_trim_min0.05s": _end_trim_with_min_duration(0.05),
    "V10_end_trim_min0.10s": _end_trim_with_min_duration(0.10),
    "V11_half_split_min0.05s": _half_split_with_min_duration(0.05),
    "V99_oracle_pick_uses_gt": rule_oracle_pick,
}
# Only rules that read ground truth are marked; V0 is the shipped reference, not an oracle.
ORACLE_RULES = {"V99_oracle_pick_uses_gt"}


# ---------------------------------------------------------------------------
# panel preparation
# ---------------------------------------------------------------------------

def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one pipeline (official) and attach raw + ground-truth + confidence columns."""
    d = df[df["pipeline"] == "official"].copy()
    d = d.sort_values(SEQ_KEYS + ["unit_index"]).reset_index(drop=True)
    d["conf_start"] = d["raw_top1_start"].astype(float).clip(1e-6, 1.0)
    d["conf_end"] = d["raw_top1_end"].astype(float).clip(1e-6, 1.0)
    return d


def replay_all(d: pd.DataFrame) -> pd.DataFrame:
    """Apply every rule to every sequence; return long-format unit rows.

    Rules consume the *raw decoder* boundaries (``raw_start_sec`` / ``raw_end_sec``) so that all
    variants start from the identical measured quantity; ``V0`` is the recorded shipped output, which
    lets us verify the reconstruction instead of trusting it.
    """
    frames = []
    for (keys, grp) in d.groupby(SEQ_KEYS, observed=True, sort=False):
        g = grp.sort_values("unit_index")
        s_raw = g["raw_start_sec"].to_numpy(dtype=float)
        e_raw = g["raw_end_sec"].to_numpy(dtype=float)
        ex = {
            "conf_start": g["conf_start"].to_numpy(dtype=float),
            "conf_end": g["conf_end"].to_numpy(dtype=float),
            "gt_start": g["gt_start_sec"].to_numpy(dtype=float),
            "gt_end": g["gt_end_sec"].to_numpy(dtype=float),
        }
        out = {"unit_index": g["unit_index"].to_numpy()}
        for kc in SEQ_KEYS:
            out[kc] = g[kc].to_numpy()
        for name, fn in RULES.items():
            if name == "V0_shipped_official":
                S, E = g["pred_start_sec"].to_numpy(dtype=float), g["pred_end_sec"].to_numpy(dtype=float)
            else:
                S, E = fn(s_raw, e_raw, ex)
            out[f"{name}__s"] = S
            out[f"{name}__e"] = E
        frames.append(pd.DataFrame(out))
    long = pd.concat(frames, ignore_index=True)
    key_cols = SEQ_KEYS + ["unit_index", "group", "singer", "gt_start_sec", "gt_end_sec",
                           "gt_dur_sec", "gt_is_multi_phoneme", "raw_top1_start", "raw_top1_end"]
    merged = d[key_cols].merge(long, on=SEQ_KEYS + ["unit_index"], how="left")
    return merged


def score(merged: pd.DataFrame) -> pd.DataFrame:
    """Unit-level absolute errors for every rule (long -> one row per (unit, rule))."""
    gs, ge = merged["gt_start_sec"].to_numpy(dtype=float), merged["gt_end_sec"].to_numpy(dtype=float)
    rows = []
    for name in RULES:
        S = merged[f"{name}__s"].to_numpy(dtype=float)
        E = merged[f"{name}__e"].to_numpy(dtype=float)
        err = np.maximum(np.abs(S - gs), np.abs(E - ge))
        cols = (["item", "model", "audio_input", "mode", "pipeline", "unit_index", "group",
                 "singer", "gt_dur_sec", "raw_top1_start", "raw_top1_end"]
                + (["gt_is_multi_phoneme"] if "gt_is_multi_phoneme" in merged.columns else []))
        sub = merged[cols].copy()
        sub["rule"] = name
        sub["uses_gt"] = name in ORACLE_RULES
        sub["start_abs"] = np.abs(S - gs)
        sub["end_abs"] = np.abs(E - ge)
        sub["both_abs"] = err
        sub["hit100"] = (err <= TOL_PRIMARY).astype(float)
        sub["hit200"] = (err <= TOL_SECONDARY).astype(float)
        sub["iou"] = _iou(S, E, gs, ge)
        sub["zero_dur"] = ((E - S) <= EPS).astype(float)
        sub["neg_dur"] = ((E - S) < -EPS).astype(float)
        rows.append(sub)
    return pd.concat(rows, ignore_index=True)


def _iou(s: np.ndarray, e: np.ndarray, gs: np.ndarray, ge: np.ndarray) -> np.ndarray:
    inter = np.clip(np.minimum(e, ge) - np.maximum(s, gs), 0, None)
    union = np.maximum(e, ge) - np.minimum(s, gs)
    return np.where(union > EPS, inter / np.maximum(union, EPS), 0.0)


# ---------------------------------------------------------------------------
# rule-reconstruction forensics
# ---------------------------------------------------------------------------

def reconstruct_shipped_rule(d: pd.DataFrame) -> dict[str, Any]:
    """Which side of an overlap does the shipped post-processor move, and why?"""
    g = d.sort_values(SEQ_KEYS + ["unit_index"])
    grp = g.groupby(SEQ_KEYS, observed=True)
    prev_end_raw = grp["raw_end_sec"].shift(1).to_numpy(dtype=float)
    prev_end_sel = grp["pred_end_sec"].shift(1).to_numpy(dtype=float)
    raw_s = g["raw_start_sec"].to_numpy(dtype=float)
    raw_e = g["raw_end_sec"].to_numpy(dtype=float)
    sel_s = g["pred_start_sec"].to_numpy(dtype=float)
    sel_e = g["pred_end_sec"].to_numpy(dtype=float)
    first = g["unit_index"].to_numpy() > 0
    overlap = np.where(first, prev_end_raw - raw_s, -1.0)
    has_overlap = overlap > 1e-3
    start_moved = np.abs(sel_s - raw_s) > 1e-3
    end_moved = np.abs(sel_e - raw_e) > 1e-3
    out: dict[str, Any] = {"n_units": int(len(g)), "n_overlaps": int(has_overlap.sum()),
                           "overlap_rate": round(float(has_overlap.mean()), 4)}
    hs = has_overlap & start_moved & ~end_moved
    he = has_overlap & end_moved & ~start_moved
    hb = has_overlap & start_moved & end_moved
    hn = has_overlap & ~start_moved & ~end_moved
    out["overlap_outcome"] = {
        "start_pushed_only": int(hs.sum()), "end_trimmed_only": int(he.sum()),
        "both_moved": int(hb.sum()), "neither_moved": int(hn.sum())}
    if hs.any():
        out["overlap_and_start_moved"] = {
            "n": int(hs.sum()),
            "share_pinned_to_prev_raw_end": round(float((np.abs(sel_s[hs] - prev_end_raw[hs]) <= 2e-3).mean()), 4),
            "share_pinned_to_prev_selected_end": round(float((np.abs(sel_s[hs] - prev_end_sel[hs]) <= 2e-3).mean()), 4),
            "mean_prev_conf_end": round(float(g["conf_end"].to_numpy(dtype=float)[hs].mean()), 4),
            "mean_own_conf_start": round(float(g["conf_start"].to_numpy(dtype=float)[hs].mean()), 4),
        }
    if he.any():
        out["overlap_and_only_end_moved"] = {
            "n": int(he.sum()),
            "share_end_pinned_to_own_raw_start": round(float((np.abs(sel_e[he] - raw_s[he]) <= 2e-3).mean()), 4),
            "mean_prev_conf_end": round(float(g["conf_end"].to_numpy(dtype=float)[he].mean()), 4),
            "mean_own_conf_start": round(float(g["conf_start"].to_numpy(dtype=float)[he].mean()), 4),
        }
    if hs.any() and he.any():
        conf = g["conf_start"].to_numpy(dtype=float) - g["conf_end"].to_numpy(dtype=float)
        sel = hs | he                                   # overlaps resolved by exactly one side
        label = hs[sel].astype(float)                   # 1 = start pushed, 0 = end trimmed
        feat = conf[sel]
        entry = {
            "n_start_pushed": int(hs.sum()), "n_end_trimmed_only": int(he.sum()),
            "mean_conf_start_minus_prev_end_start_pushed": round(float(conf[hs].mean()), 4),
            "mean_conf_start_minus_prev_end_end_trimmed": round(float(conf[he].mean()), 4),
            "mean_overlap_start_pushed_sec": round(float(overlap[hs].mean()), 4),
            "mean_overlap_end_trimmed_sec": round(float(overlap[he].mean()), 4),
            "auc_conf_gap_predicts_which_side": round(float(_auc_simple(label, feat)), 4),
            "auc_overlap_size_predicts_which_side": round(float(
                _auc_simple(label, overlap[sel])), 4),
        }
        try:  # non-parametric check that the two groups differ at all
            from scipy import stats
            entry["mannwhitney_p_conf_gap"] = float(stats.mannwhitneyu(conf[hs], conf[he]).pvalue)
            entry["mannwhitney_p_overlap_size"] = float(
                stats.mannwhitneyu(overlap[hs], overlap[he]).pvalue)
        except Exception:
            pass
        out["decision_variable"] = entry
    # zero-duration creation: where did the extra zero-length units come from?
    created_zero = ((sel_e - sel_s) <= EPS) & ((raw_e - raw_s) > EPS)
    out["zero_duration"] = {
        "raw_rate": round(float(((raw_e - raw_s) <= EPS).mean()), 4),
        "final_rate": round(float(((sel_e - sel_s) <= EPS).mean()), 4),
        "created_by_postprocess": int(created_zero.sum()),
        "share_created_with_prev_end_equal": round(float(
            (np.abs(sel_s[created_zero] - prev_end_raw[created_zero]) <= 2e-3).mean()), 4)
        if created_zero.any() else None,
    }
    return out


def _auc_simple(y: np.ndarray, s: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    ok = np.isfinite(y) & np.isfinite(s)
    y, s = y[ok], s[ok]
    if y.min() == y.max():
        return 0.5
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

def _breakdowns(scored: pd.DataFrame, reference: str) -> dict[str, Any]:
    """Is the rule ranking stable inside subgroups, or driven by one slice?

    Reports unit-level hit@100 and the paired difference against the reference for every singer,
    technique group and inference configuration.  A recommendation that only holds on one singer
    or one group must not be phrased as a global rule change.
    """
    out: dict[str, Any] = {}
    ref = scored[scored["rule"] == reference]
    for dim in ("singer", "group", "model", "audio_input", "mode"):
        if dim not in scored.columns:
            continue
        rows = {}
        for rule, sub in scored.groupby("rule", observed=True):
            agg_new = sub.groupby(dim, observed=True)["hit100"].agg(["mean", "size"])
            agg_ref = ref.groupby(dim, observed=True)["hit100"].agg(["mean", "size"])
            common = agg_new.index.intersection(agg_ref.index)
            rows[rule] = {
                str(k): {"hit100": round(float(agg_new.loc[k, "mean"]), 4),
                         "delta_vs_ref_pp": round(
                             float((agg_new.loc[k, "mean"] - agg_ref.loc[k, "mean"]) * 100), 3),
                         "n_units": int(agg_new.loc[k, "size"])}
                for k in common}
        out[dim] = rows
    return out


def compare(scored: pd.DataFrame, reference: str = "V0_shipped_official") -> dict[str, Any]:
    seg = scored.groupby(["rule"] + SEQ_KEYS + ["group"], observed=True).agg(
        units=("hit100", "size"), hit100=("hit100", "mean"), hit200=("hit200", "mean"),
        mae_start=("start_abs", "mean"), mae_end=("end_abs", "mean"), iou=("iou", "mean"),
        zero=("zero_dur", "mean")).reset_index()
    out: dict[str, Any] = {"schema": "gtsinger_gt_postprocess_replay_v1",
                           "tolerances_sec": [TOL_PRIMARY, TOL_SECONDARY],
                           "reference": reference,
                           "rules": {}}
    for rule, sub in seg.groupby("rule", observed=True):
        w = sub["units"].to_numpy(dtype=float)
        out["rules"][rule] = {
            "uses_gt": rule in ORACLE_RULES,
            "sequences": int(len(sub)),
            "hit100_macro": round(float(sub["hit100"].mean()), 4),
            "hit100_micro": round(float((sub["hit100"] * w).sum() / w.sum()), 4),
            "hit200_macro": round(float(sub["hit200"].mean()), 4),
            "mae_start_macro": round(float(sub["mae_start"].mean()), 4),
            "mae_end_macro": round(float(sub["mae_end"].mean()), 4),
            "iou_macro": round(float(sub["iou"].mean()), 4),
            "zero_dur_rate": round(float(sub["zero"].mean()), 5),
        }
    # paired per-sequence differences against the reference and against raw_none
    ref = seg[seg["rule"] == reference]
    for rule, sub in seg.groupby("rule", observed=True):
        if rule == reference:
            continue
        m = sub.merge(ref[SEQ_KEYS + ["hit100"]], on=SEQ_KEYS, suffixes=("", "_ref"))
        d = (m["hit100"] - m["hit100_ref"]).to_numpy(dtype=float)
        rng = np.random.default_rng(SEED)
        draws = np.array([d[rng.choice(len(d), len(d), True)].mean() for _ in range(N_BOOT)]) if len(d) > 1 else d
        entry = {
            "vs_reference_hit100_pp": round(float(d.mean() * 100), 3),
            "ci95_pp": [round(float(np.percentile(draws, 2.5) * 100), 3),
                        round(float(np.percentile(draws, 97.5) * 100), 3)],
            "sequences_better": int((d > 0).sum()), "sequences_worse": int((d < 0).sum()),
            "sequences_tied": int((d == 0).sum()),
        }
        iu = sub.merge(ref[SEQ_KEYS + ["iou"]], on=SEQ_KEYS, suffixes=("", "_ref"))
        entry["iou_delta"] = round(float((iu["iou"] - iu["iou_ref"]).mean()), 4)
        zz = sub.merge(ref[SEQ_KEYS + ["zero"]], on=SEQ_KEYS, suffixes=("", "_ref"))
        entry["zero_dur_delta_pp"] = round(float((zz["zero"] - zz["zero_ref"]).mean() * 100), 3)
        out["rules"][rule]["paired_vs_reference"] = entry
    # stratified: segment start, onsetless syllable, long notes (aggregate means hide these)
    strata = {}
    for rule, sub in scored.groupby("rule", observed=True):
        f = sub[sub["unit_index"] == 0]
        long_note = sub[sub["gt_dur_sec"] > 0.6]
        mid = sub[(sub["unit_index"] > 0) & (sub["gt_dur_sec"] <= 0.6)]
        onsetless = sub[sub["gt_is_multi_phoneme"] == 0] if "gt_is_multi_phoneme" in sub else sub.iloc[0:0]
        on_first = onsetless[onsetless["unit_index"] == 0] if len(onsetless) else onsetless
        strata[rule] = {
            "first_unit_hit100": round(float(f["hit100"].mean()), 4) if len(f) else None,
            "long_note_hit100": round(float(long_note["hit100"].mean()), 4),
            "rest_hit100": round(float(mid["hit100"].mean()), 4),
            "onsetless_hit100": round(float(onsetless["hit100"].mean()), 4) if len(onsetless) else None,
            "onsetless_and_first_hit100": (round(float(on_first["hit100"].mean()), 4)
                                           if len(on_first) else None),
            "first_unit_n": int(len(f)),
        }
    out["strata"] = strata
    out["breakdowns"] = _breakdowns(scored, reference)
    out["strata_context"] = {
        "n_units_per_rule": int(len(scored) // len(RULES)),
        "definition": {"first_unit": "unit_index == 0 (GT start is always 0.0 in GTSinger clips)",
                       "long_note": "gt_dur_sec > 0.6", "onsetless": "gt_is_multi_phoneme == 0"}}
    return out


# ---------------------------------------------------------------------------
# reproducibility forensics (same identity, two independent forwards)
# ---------------------------------------------------------------------------

def stage_consistency(df: pd.DataFrame) -> dict[str, Any]:
    """Separate *forward nondeterminism* from *pipeline stage definitions*.

    The official and raw evaluation runs are two independent forwards over identical audio bytes,
    text and model.  Their recorded ``raw`` stages can therefore be compared directly: any
    difference would be nondeterminism and would invalidate content-addressed evidence reuse.
    Their ``selected`` stages additionally differ by definition, which is what this function also
    quantifies so that "raw == no post-processing" is not over-claimed.
    """
    k = ["item", "model", "audio_input", "mode", "unit_index"]
    off = df[df["pipeline"] == "official"][k + ["raw_start_sec", "raw_end_sec",
                                                "pred_start_sec", "pred_end_sec"]]
    raw = df[df["pipeline"] == "raw"][k + ["raw_start_sec", "raw_end_sec",
                                           "pred_start_sec", "pred_end_sec"]]
    merged = off.merge(raw, on=k, how="inner", suffixes=("_o", "_r"))
    if merged.empty:
        return {"available": False}

    def _absmax(a: pd.Series, b: pd.Series) -> np.ndarray:
        return np.maximum((a - b).abs().to_numpy(dtype=float), np.zeros(len(a)))

    fwd = _absmax(merged["raw_start_sec_o"], merged["raw_start_sec_r"])
    fwd = np.maximum(fwd, (merged["raw_end_sec_o"] - merged["raw_end_sec_r"]).abs().to_numpy(dtype=float))
    rawpipe_adj = np.maximum(
        (merged["raw_start_sec_r"] - merged["pred_start_sec_r"]).abs().to_numpy(dtype=float),
        (merged["raw_end_sec_r"] - merged["pred_end_sec_r"]).abs().to_numpy(dtype=float))
    off_adj = np.maximum(
        (merged["raw_start_sec_o"] - merged["pred_start_sec_o"]).abs().to_numpy(dtype=float),
        (merged["raw_end_sec_o"] - merged["pred_end_sec_o"]).abs().to_numpy(dtype=float))
    cross = np.maximum(
        (merged["raw_start_sec_o"] - merged["pred_start_sec_r"]).abs().to_numpy(dtype=float),
        (merged["raw_end_sec_o"] - merged["pred_end_sec_r"]).abs().to_numpy(dtype=float))
    idx = cross > 1e-3
    r_raw_dur = (merged["raw_end_sec_r"] - merged["raw_start_sec_r"]).to_numpy(dtype=float)
    r_sel_dur = (merged["pred_end_sec_r"] - merged["pred_start_sec_r"]).to_numpy(dtype=float)
    r_start_shift = (merged["pred_start_sec_r"] - merged["raw_start_sec_r"]).to_numpy(dtype=float)
    r_end_shift = (merged["pred_end_sec_r"] - merged["raw_end_sec_r"]).to_numpy(dtype=float)
    n_idx = int(idx.sum())
    if n_idx:
        end_only = int((np.abs(r_start_shift[idx]) <= 1e-3).sum())
        neg_clamp = int(((r_raw_dur[idx] < -1e-6) & (np.abs(r_sel_dur[idx]) <= 1e-6)).sum())
        trimmed = int((r_end_shift[idx] < 0).sum())
    else:
        end_only = neg_clamp = trimmed = 0
    return {
        "available": True,
        "n_paired_units": int(len(merged)),
        "forward_determinism": {
            "description": "official.raw stage vs raw-run raw stage (same identity, two forwards)",
            "share_differing_gt_1ms": round(float((fwd > 1e-3).mean()), 6),
            "n_differing_gt_1ms": int((fwd > 1e-3).sum()),
            "max_diff_sec": round(float(fwd.max()), 5),
        },
        "raw_pipeline_self_adjustment": {
            "description": "raw run: its own raw stage vs its selected stage",
            "share_adjusted_gt_1ms": round(float((rawpipe_adj > 1e-3).mean()), 5),
            "n_adjusted": int((rawpipe_adj > 1e-3).sum()),
            "max_diff_sec": round(float(rawpipe_adj.max()), 4),
        },
        "official_pipeline_adjustment": {
            "share_adjusted_gt_1ms": round(float((off_adj > 1e-3).mean()), 5),
            "n_adjusted": int((off_adj > 1e-3).sum()),
        },
        "cross_pipeline_selected_vs_raw": {
            "description": "official.raw vs raw-run selected: the A/B used for the post-processing finding",
            "n_differing": n_idx,
            "share_end_only": round(float(end_only / n_idx), 4) if n_idx else None,
            "n_negative_to_zero_clamps": neg_clamp,
            "share_trimmed_earlier": round(float(trimmed / n_idx), 4) if n_idx else None,
        },
        "interpretation": "forwards are reproducible (evidence reuse by identity is safe); the "
                          "'raw' pipeline is *minimal* post-processing (end-only adjustments), not "
                          "literally no post-processing, so the A/B compares light vs full cleanup",
    }


def main(evidence: Path, out_dir: Path) -> dict[str, Any]:
    from lyricalign.analysis import gtsinger_gt_deep as deep

    out_dir.mkdir(parents=True, exist_ok=True)
    df = deep.panel_only(deep.load_panel(evidence))
    d = prepare(df)
    merged = replay_all(d)
    scored = score(merged)
    cmp = compare(scored)
    cmp["rule_reconstruction"] = reconstruct_shipped_rule(d)
    cmp["stage_consistency"] = stage_consistency(df)
    cmp["panel"] = {"sequences": int(len(d.groupby(SEQ_KEYS, observed=True))),
                    "units": int(len(d)), "evidence": str(evidence)}
    (out_dir / "POLICY_REPLAY.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    rollup_cols = ["rule", "item", "model", "audio_input", "mode"]
    rollup = scored.groupby(rollup_cols, observed=True).agg(
        units=("hit100", "size"), hit100=("hit100", "mean"), hit200=("hit200", "mean"),
        mae_start=("start_abs", "mean"), mae_end=("end_abs", "mean"), iou=("iou", "mean"),
        zero_dur=("zero_dur", "mean")).reset_index()
    rollup.to_csv(out_dir / "policy_replay_by_sequence.csv.gz", index=False,
                  compression="gzip", float_format="%.5f")
    return {"rules": {k: v["hit100_micro"] for k, v in cmp["rules"].items()},
            "artifacts": sorted(p.name for p in out_dir.glob("POLICY_REPLAY.json"))}
