"""Gap-shape discriminator: does the energy in an inter-unit gap rise (next onset) or fall (this
unit's own tail, i.e. the timeline truncated the note)?

Round 24 left three explanations for the large residual energy measured inside true inter-unit gaps:
(a) voice reverb tail, (b) the next unit's onset falling into the gap, (c) the assigned end is too
early and the residual *is* this unit's own voice.  (b) and (c) are separable by shape alone: a gap
that leads into the next unit rises, while a truncated note decays.  Shape needs no ground truth, so
if it predicts truncation on data where a reference exists, it becomes a free trigger.

Validation discipline: the rule is fitted and validated on **GTSinger** (human word-level GT, not a
test set), and only then applied frozen to the 33 real accompanied songs, where no reference exists
and the numbers are reported as prevalence, not accuracy.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MIN_GAP_SEC = 0.05
LEAD_SEC = 0.30
TRUNCATION_TOL_SEC = 0.08      # one decoder bin: "true end is later than the assigned end"
GUARD_SEC = 0.03               # skip this much after the boundary before measuring the gap


# Why the guard exists: the envelope is computed with a 25 ms window, so a frame centred exactly on
# the boundary still contains the previous unit's energy.  Without the guard a *steady* residual is
# measured as decaying (verified on a synthetic constant-level signal), which would bias every
# shape statistic toward "falling".


def shape_features(t: np.ndarray, env: np.ndarray, *, gap_lo: float, gap_hi: float,
                   core_rms: float | None = None) -> dict[str, float]:
    """Rise/fall statistics of the envelope inside one gap window."""
    m = (t >= gap_lo) & (t <= gap_hi)
    seg = env[m]
    out = {"gap_sec": float(gap_hi - gap_lo), "gap_rms": float("nan"),
           "rise_ratio": float("nan"), "log_slope_per_sec": float("nan")}
    if seg.size < 4 or gap_hi - gap_lo < MIN_GAP_SEC:
        return out
    third = max(1, seg.size // 3)
    head = float(np.sqrt(np.mean(seg[:third] ** 2)))
    tail = float(np.sqrt(np.mean(seg[-third:] ** 2)))
    out["gap_rms"] = float(np.sqrt(np.mean(seg ** 2)))
    out["rise_ratio"] = tail / head if head > 1e-9 else float("nan")
    x = (t[m] - gap_lo).astype(float)
    y = np.log(np.clip(seg, 1e-9, None))
    if x.size >= 4 and np.std(x) > 0:
        out["log_slope_per_sec"] = float(np.polyfit(x, y, 1)[0])
    if core_rms and core_rms > 1e-9:
        out["gap_over_core"] = out["gap_rms"] / core_rms
    return out


def classify(shape: dict[str, float], *, rising_threshold: float = 1.15,
             falling_threshold: float = 0.87) -> str:
    """'rising' (next onset), 'falling' (own decaying tail) or 'flat'."""
    rr = shape.get("rise_ratio")
    if rr is None or not np.isfinite(rr):
        return "unknown"
    if rr >= rising_threshold:
        return "rising"
    if rr <= falling_threshold:
        return "falling"
    return "flat"


def gap_rows(pred: pd.DataFrame, envelopes: dict[str, tuple[np.ndarray, np.ndarray]], *,
             seq_cols: list[str], audio_col: str = "audio_path",
             end_col: str = "pred_end_sec", start_col: str = "pred_start_sec") -> pd.DataFrame:
    """One row per unit that has a measurable gap before the next unit's assigned start."""
    rows: list[dict[str, Any]] = []
    for (_seq), sub in pred.groupby(seq_cols, observed=True):
        s = sub.sort_values("unit_index")
        idx = s.index.to_numpy()
        starts = s[start_col].to_numpy(dtype=float)
        ends = s[end_col].to_numpy(dtype=float)
        gt_ends = pd.to_numeric(s.get("gt_end_sec"), errors="coerce").to_numpy(dtype=float) \
            if "gt_end_sec" in s.columns else np.full(len(s), np.nan)
        gt_starts = pd.to_numeric(s.get("gt_start_sec"), errors="coerce").to_numpy(dtype=float) \
            if "gt_start_sec" in s.columns else np.full(len(s), np.nan)
        audio = s[audio_col].astype(str).to_numpy()
        for i in range(len(s)):
            env = envelopes.get(audio[i])
            if env is None or not np.isfinite(ends[i]):
                continue
            nxt = starts[i + 1] if i + 1 < len(starts) else float("inf")
            gap_lo = float(ends[i]) + GUARD_SEC
            gap_hi = min(float(ends[i]) + LEAD_SEC, float(nxt))
            if gap_hi - gap_lo < MIN_GAP_SEC - GUARD_SEC:
                continue
            t, v = env
            core_lo, core_hi = (starts[i], ends[i]) if np.isfinite(starts[i]) else (ends[i], ends[i])
            cm = (t >= core_lo) & (t <= core_hi)
            core_rms = float(np.sqrt(np.mean(v[cm] ** 2))) if cm.any() else None
            sh = shape_features(t, v, gap_lo=gap_lo, gap_hi=gap_hi, core_rms=core_rms)
            rows.append({**{c: s.iloc[0][c] for c in seq_cols if c in s.columns},
                         "unit_index": int(s["unit_index"].iloc[i]),
                         "gt_end_sec": gt_ends[i], "gt_start_sec": gt_starts[i],
                         "pred_end_sec": ends[i], "pred_start_sec": starts[i],
                         "gt_dur_sec": (gt_ends[i] - gt_starts[i]) if np.isfinite(gt_ends[i]) else float("nan"),
                         "is_last_unit": i == len(s) - 1, **sh})
    return pd.DataFrame(rows)


def score_truncation_predictor(gaps: pd.DataFrame, *, tol_sec: float = TRUNCATION_TOL_SEC,
                               min_units: int = 30) -> dict[str, Any]:
    """Does a falling gap predict that the true end is later than the assigned end?"""
    d = gaps.dropna(subset=["gt_end_sec", "pred_end_sec", "rise_ratio"]).copy()
    if len(d) < min_units:
        return {"available": False, "units": int(len(d))}
    d["truncated"] = (d["gt_end_sec"] - d["pred_end_sec"]) > tol_sec
    d["late_by_gt_minus_pred_ms"] = (d["gt_end_sec"] - d["pred_end_sec"]) * 1000.0
    d["shape"] = d.apply(lambda r: classify(r.to_dict()), axis=1)
    out: dict[str, Any] = {"units": int(len(d)), "tolerance_sec": tol_sec,
                           "truncated_share": round(float(d["truncated"].mean()), 4),
                           "by_shape": {}}
    for shape, sub in d.groupby("shape", observed=True):
        out["by_shape"][str(shape)] = {
            "units": int(len(sub)),
            "share_of_gaps": round(float(len(sub) / len(d)), 4),
            "truncated_share": round(float(sub["truncated"].mean()), 4),
            "median_late_ms": round(float(np.median(sub["late_by_gt_minus_pred_ms"])), 1),
            "median_rise_ratio": round(float(np.median(sub["rise_ratio"])), 3),
            "median_gap_over_core": round(float(np.nanmedian(
                pd.to_numeric(sub.get("gap_over_core"), errors="coerce"))), 3)
            if "gap_over_core" in sub else None}
    from lyricalign.realign_gate.gate_features import roc_auc
    y = d["truncated"].to_numpy(dtype=float)
    # report the RAW AUC plus its direction; an earlier draft applied 1-AUC to some columns while
    # still labelling the result "predicts truncation", which inverted the meaning of those numbers
    out["auc_raw_higher_score_more_truncated"] = {}
    for col in ("gap_over_core", "gap_rms", "rise_ratio", "log_slope_per_sec"):
        if col not in d.columns:
            continue
        v = pd.to_numeric(d[col], errors="coerce").to_numpy(dtype=float)
        ok = np.isfinite(v)
        if ok.sum() < min_units or y[ok].sum() in (0, ok.sum()):
            continue
        auc = roc_auc(y[ok], v[ok])
        if auc is None:
            continue
        out["auc_raw_higher_score_more_truncated"][col] = {
            "auc": round(float(auc), 4),
            "direction": "higher score -> more truncated" if auc >= 0.5
            else "higher score -> less truncated (invert the sign to use it)"}
    # long notes only: the stratum round 19/21 showed to be unreachable
    ln = d[d["gt_dur_sec"] >= 1.0]
    if len(ln) >= 10:
        ln = ln.assign(shape=ln.apply(lambda r: classify(r.to_dict()), axis=1))
        sizes = ln.groupby("shape", observed=True).size()
        means = ln.groupby("shape", observed=True)["truncated"].mean()
        out["long_note_subset"] = {
            "units": int(len(ln)),
            "truncated_share": round(float(ln["truncated"].mean()), 4),
            "by_shape_truncated_share": {str(k): round(float(means[k]), 4) for k in sizes.index},
            "by_shape_units": {str(k): int(v) for k, v in sizes.items()}}
    return out


def prevalence_by_shape(gaps: pd.DataFrame) -> dict[str, Any]:
    """Frozen-shape prevalence for data without references (reported as prevalence, never accuracy)."""
    d = gaps.dropna(subset=["rise_ratio"]).copy()
    if not len(d):
        return {"available": False}
    d["shape"] = d.apply(lambda r: classify(r.to_dict()), axis=1)
    out = {"available": True, "units": int(len(d)), "by_shape": {}}
    for shape, sub in d.groupby("shape", observed=True):
        out["by_shape"][str(shape)] = {
            "units": int(len(sub)), "share": round(float(len(sub) / len(d)), 4),
            "median_gap_over_core": round(float(np.nanmedian(pd.to_numeric(
                sub.get("gap_over_core"), errors="coerce"))), 3) if "gap_over_core" in sub else None,
            "median_gap_sec": round(float(np.median(sub["gap_sec"])), 3)}
    return out


def grouped_auc(gaps: pd.DataFrame, *, score_col: str, group_col: str,
                tol_sec: float = TRUNCATION_TOL_SEC, min_units: int = 20,
                label_col: str = "truncated") -> dict[str, Any]:
    """AUC computed **within each group** (clip or view), then summarised.

    Pooling repeated measurements of the same clip (this project's panels hold several views per
    clip) lets a predictor score high on between-clip variance alone, so the pooled AUC is reported
    next to the within-group distribution and a cluster bootstrap over groups.
    """
    from lyricalign.realign_gate.gate_features import roc_auc
    d = gaps.dropna(subset=[score_col]).copy()
    if "truncated" not in d.columns and {"gt_end_sec", "pred_end_sec"} <= set(d.columns):
        d["truncated"] = (pd.to_numeric(d["gt_end_sec"], errors="coerce")
                          - pd.to_numeric(d["pred_end_sec"], errors="coerce")) > tol_sec
    per_group: dict[str, float] = {}
    sizes: dict[str, int] = {}
    for key, sub in d.groupby(group_col, observed=True):
        if len(sub) < min_units:
            continue
        y = sub[label_col].to_numpy(dtype=float)
        v = pd.to_numeric(sub[score_col], errors="coerce").to_numpy(dtype=float)
        ok = np.isfinite(v)
        y, v = y[ok], v[ok]
        if y.size < min_units or y.sum() in (0, y.size):
            continue
        a = roc_auc(y, v)
        if a is None:
            continue
        per_group[str(key)] = round(float(a), 4)
        sizes[str(key)] = int(y.size)
    pooled_y = d[label_col].to_numpy(dtype=float)
    pooled_v = pd.to_numeric(d[score_col], errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(pooled_v)
    pooled = roc_auc(pooled_y[ok], pooled_v[ok]) if ok.any() else None
    out: dict[str, Any] = {"score_col": score_col, "group_col": group_col,
                           "pooled_auc": round(float(pooled), 4) if pooled is not None else None,
                           "groups_evaluated": len(per_group),
                           # per-group values: the honest view when groups differ in base rate
                           "per_group_auc": per_group, "per_group_units": sizes}
    if per_group:
        vals = np.array(list(per_group.values()), dtype=float)
        out.update({"within_group_median_auc": round(float(np.median(vals)), 4),
                    "within_group_q25": round(float(np.percentile(vals, 25)), 4),
                    "within_group_q75": round(float(np.percentile(vals, 75)), 4),
                    "within_group_min": round(float(vals.min()), 4),
                    "within_group_max": round(float(vals.max()), 4),
                    "share_of_groups_above_0_6": round(float(np.mean(vals > 0.6)), 4),
                    "median_group_units": int(np.median(list(sizes.values())))})
        # cluster bootstrap over groups (resample groups, not units)
        rng = np.random.default_rng(20260912)
        boots = []
        for _ in range(400):
            pick = rng.integers(0, vals.size, vals.size)
            boots.append(float(np.mean(vals[pick])))
        out["cluster_bootstrap_median_ci95"] = [round(float(np.percentile(boots, 2.5)), 4),
                                                round(float(np.percentile(boots, 97.5)), 4)]
    return out
