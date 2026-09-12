"""Deep analysis over the per-unit GTSinger ground-truth evidence panel.

Sections (each writes one JSON artifact next to the evidence file):

``effects``   Paired factorial effects of the inference configuration
              (model ladder r0/r1/r2, mix vs separated-vocal audio, full vs
              windowed planning, official post-processing vs raw decoder) with a
              cluster bootstrap over segments, so short clips and long clips
              cannot dominate through unequal unit counts.

``signals``   Validation of *no-GT* confidence signals against real ground
              truth: decoder boundary posteriors/margins/entropies and
              leave-one-out cross-configuration boundary disagreement, scored by
              ROC-AUC / PR-AUC for "this unit is wrong by >100/200 ms", plus
              calibration and a song-grouped multivariate gate.

``structure`` Error structure: signed boundary bias, dependence on ground-truth
              duration / melisma / technique flags / position in segment /
              distance to the window seam, and the clustering of errors into
              contiguous blocks (the region-level premise of realign).

The module never writes into the source run directories.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

TOL_PRIMARY = 0.100
TOL_SECONDARY = 0.200
RNG_SEED = 20260912
N_BOOT = 2000

FACTORIAL_RUNS = {
    "official": ("20260816_evaluation_v1_gtsinger_diag_all",
                 "20260816_evaluation_v1_gtsinger_regression_official_all"),
    "raw": ("20260816_evaluation_v1_gtsinger_rawdec_all",
            "20260816_evaluation_v1_gtsinger_regression_rawdec_all"),
}
PANEL_RUNS = tuple(r for runs in FACTORIAL_RUNS.values() for r in runs)

EFFECT_KEYS = ["model", "audio_input", "mode", "pipeline"]


def load_panel(evidence: Path) -> pd.DataFrame:
    df = pd.read_json(evidence, lines=True, compression="infer")
    df["seg_key"] = df["run"] + "|" + df["item"]
    df["unit_key"] = df["seg_key"] + "|" + df["model"] + "|" + df["audio_input"] + "|" + df["mode"]
    return df


def panel_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["run"].isin(PANEL_RUNS)].copy()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _boot_ci(values: np.ndarray, groups: np.ndarray, n_boot: int = N_BOOT,
             seed: int = RNG_SEED) -> tuple[float, tuple[float, float]]:
    """Cluster bootstrap CI of a mean over resampled groups (segments)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    idx_by_group = {g: np.flatnonzero(groups == g) for g in uniq}
    point = float(np.mean(values))
    if len(uniq) < 2:
        return point, (point, point)
    draws = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        picked = rng.choice(uniq, size=len(uniq), replace=True)
        cat = np.concatenate([idx_by_group[g] for g in picked])
        draws[b] = np.mean(values[cat])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return point, (float(lo), float(hi))


def _sign_p(n: int, k: int) -> float | None:
    """Two-sided exact sign-test p-value (ties excluded from ``k`` by callers)."""
    if n == 0:
        return None
    try:
        from scipy import stats
        return float(stats.binomtest(int(k), int(n), 0.5).pvalue)
    except Exception:  # pragma: no cover - scipy is optional at runtime
        z = (k - n / 2) / (0.5 * np.sqrt(n))
        return float(2 * (1 - abs(z) / (abs(z) + 1)))


def _auc(y: np.ndarray, s: np.ndarray) -> float | None:
    mask = np.isfinite(s) & np.isfinite(y)
    y, s = y[mask], s[mask]
    if y.min() == y.max() or len(y) == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    s_sorted = s[order]
    i = 0
    ranks_sorted = np.empty(len(s), dtype=float)
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        ranks_sorted[i:j + 1] = (i + j) / 2.0 + 1
        i = j + 1
    ranks[order] = ranks_sorted
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _grouped_auc(df: pd.DataFrame, y_col: str, s_col: str, group_col: str) -> dict[str, Any]:
    """Pooled (flat) AUC plus a within-segment AUC restricted to comparable units."""
    y = df[y_col].to_numpy(dtype=float)
    s = df[s_col].to_numpy(dtype=float)
    flat = _auc(y, s)
    within_vals, within_n = [], 0
    for _, gdf in df.groupby(group_col, observed=True):
        yy = gdf[y_col].to_numpy(dtype=float)
        ss = gdf[s_col].to_numpy(dtype=float)
        a = _auc(yy, ss)
        if a is not None:
            within_vals.append(a)
            within_n += 1
    return {
        "flat_auc": None if flat is None else round(flat, 4),
        "within_segment_auc_mean": round(float(np.mean(within_vals)), 4) if within_vals else None,
        "within_segment_groups": within_n,
        "n_rows": int(len(df)),
    }


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    mask = np.isfinite(p)
    y, p = y[mask], p[mask]
    if len(y) == 0:
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        sel = idx == b
        if not sel.any():
            continue
        total += sel.mean() * abs(p[sel].mean() - y[sel].mean())
    return float(total)


# ---------------------------------------------------------------------------
# A. factorial effects
# ---------------------------------------------------------------------------

def _seg_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Segment-level rollup: hit rates and mean abs errors per (segment, factors)."""
    d = df.copy()
    d["hit100"] = (d["both_abs_err_sec"] <= TOL_PRIMARY).astype(float)
    d["hit200"] = (d["both_abs_err_sec"] <= TOL_SECONDARY).astype(float)
    d["start_hit100"] = (d["start_abs_err_sec"] <= TOL_PRIMARY).astype(float)
    d["end_hit100"] = (d["end_abs_err_sec"] <= TOL_PRIMARY).astype(float)
    d["pred_zero_dur"] = ((d["pred_end_sec"] - d["pred_start_sec"]) <= 1e-6).astype(float)
    keys = ["run", "item", "seg_key", "model", "audio_input", "mode", "pipeline", "singer", "group"]
    agg = d.groupby(keys, observed=True).agg(
        units=("hit100", "size"),
        hit100=("hit100", "mean"),
        hit200=("hit200", "mean"),
        start_hit100=("start_hit100", "mean"),
        end_hit100=("end_hit100", "mean"),
        mae_both=("both_abs_err_sec", "mean"),
        med_both=("both_abs_err_sec", "median"),
        mae_start=("start_abs_err_sec", "mean"),
        mae_end=("end_abs_err_sec", "mean"),
        iou=("iou", "mean"),
        zero_dur=("pred_zero_dur", "mean"),
    ).reset_index()
    return agg


def compute_effects(df: pd.DataFrame) -> dict[str, Any]:
    seg = _seg_metrics(df)
    out: dict[str, Any] = {"schema": "gtsinger_gt_factorial_effects_v1",
                           "tolerances_sec": [TOL_PRIMARY, TOL_SECONDARY],
                           "bootstrap": {"n": N_BOOT, "cluster": "segment", "seed": RNG_SEED},
                           "notes": "segment-level means, unweighted across segments; "
                                    "CI from cluster bootstrap over segments"}
    levels = {"model": ["r0", "r1", "r2"], "audio_input": ["mix", "vocal"],
              "mode": ["full", "windowed"], "pipeline": ["official", "raw"]}
    out["levels"] = {}
    for factor, vals in levels.items():
        tbl = []
        for v in vals:
            s = seg[seg[factor] == v]
            if s.empty:
                continue
            pooled_units = int(s["units"].sum())
            w = s["units"].to_numpy(dtype=float)
            tbl.append({
                factor: v,
                "segments": int(len(s)),
                "unit_rows": pooled_units,
                "hit100_macro": round(float(s["hit100"].mean()), 4),
                "hit100_micro": round(float((s["hit100"] * w).sum() / w.sum()), 4),
                "hit200_macro": round(float(s["hit200"].mean()), 4),
                "mae_both_macro": round(float(s["mae_both"].mean()), 4),
                "mae_start_macro": round(float(s["mae_start"].mean()), 4),
                "mae_end_macro": round(float(s["mae_end"].mean()), 4),
                "iou_macro": round(float(s["iou"].mean()), 4),
                "zero_dur_rate": round(float(s["zero_dur"].mean()), 5),
            })
        out["levels"][factor] = tbl

    contrasts: dict[str, Any] = {}
    metric = "hit100"
    # within-pipeline contrasts (other factors averaged out by the pivot)
    for pipe in ("official", "raw"):
        sub = seg[seg["pipeline"] == pipe]
        if sub.empty:
            continue
        c: dict[str, Any] = {}
        c["r0_vs_r1"] = _paired_contrast(sub, "model", "r0", "r1", metric)
        c["r1_vs_r2"] = _paired_contrast(sub, "model", "r1", "r2", metric)
        c["r0_vs_r2"] = _paired_contrast(sub, "model", "r0", "r2", metric)
        c["mix_vs_vocal"] = _paired_contrast(sub, "audio_input", "mix", "vocal", metric)
        c["full_vs_windowed"] = _paired_contrast(sub, "mode", "full", "windowed", metric)
        contrasts[pipe] = c
    # cross-pipeline (official post-processing vs raw decoder) paired on item+model+audio+mode
    cross = _cross_pipeline_contrast(seg, metric)
    contrasts["official_vs_raw"] = cross
    out["contrasts_hit100"] = contrasts

    # per-group (technique group) breakdown for the reference config
    ref = seg[(seg["model"] == "r2") & (seg["audio_input"] == "vocal") & (seg["mode"] == "windowed")
              & (seg["pipeline"] == "official")]
    out["group_breakdown_r2_vocal_windowed"] = [
        {"group": g, "singer": sub["singer"].iloc[0], "segments": int(len(sub)),
         "hit100": round(float(sub["hit100"].mean()), 4),
         "hit200": round(float(sub["hit200"].mean()), 4),
         "mae_start": round(float(sub["mae_start"].mean()), 4),
         "mae_end": round(float(sub["mae_end"].mean()), 4)}
        for g, sub in ref.groupby("group", observed=True)
    ]
    out["singer_breakdown_r2_vocal_windowed"] = [
        {"singer": g, "segments": int(len(sub)), "hit100": round(float(sub["hit100"].mean()), 4),
         "hit200": round(float(sub["hit200"].mean()), 4),
         "mae_both": round(float(sub["mae_both"].mean()), 4)}
        for g, sub in ref.groupby("singer", observed=True)
    ]
    return out


def _paired_contrast(seg: pd.DataFrame, factor: str, a: str, b: str, metric: str) -> dict[str, Any]:
    """Paired difference across segments where both factor levels exist with all
    other factors matched (model/audio/mode/pipeline combos aligned)."""
    others = [c for c in ["model", "audio_input", "mode", "pipeline"] if c != factor]
    keys = ["seg_key"] + others
    wide = seg.pivot_table(index=keys, columns=factor, values=metric, aggfunc="mean")
    wide = wide.dropna(subset=[a, b])
    if wide.empty:
        return {"available": False, "reason": "no_paired_cells"}
    d = (wide[a] - wide[b]).to_numpy(dtype=float)
    rng = np.random.default_rng(RNG_SEED)
    uniq = np.arange(len(d))
    draws = np.array([d[rng.choice(uniq, len(d), True)].mean() for _ in range(N_BOOT)]) if len(d) > 1 else d
    return {
        "available": True,
        "factor": factor, "a": a, "b": b,
        "n_paired_cells": int(len(d)),
        "mean_a": round(float(wide[a].mean()), 4),
        "mean_b": round(float(wide[b].mean()), 4),
        "mean_diff": round(float(d.mean()), 4),
        "diff_ci95": [round(float(np.percentile(draws, 2.5)), 4), round(float(np.percentile(draws, 97.5)), 4)],
        "cells_a_better": int(np.sum(d > 0)),
        "cells_tied": int(np.sum(d == 0)),
        "cells_b_better": int(np.sum(d < 0)),
        "sign_p": _sign_p(int(np.sum(d != 0)), int(np.sum(d > 0))),
    }


def _cross_pipeline_contrast(seg: pd.DataFrame, metric: str) -> dict[str, Any]:
    wide = seg.pivot_table(index=["item", "model", "audio_input", "mode"], columns="pipeline",
                           values=metric, aggfunc="mean").dropna()
    if wide.empty or "official" not in wide or "raw" not in wide:
        return {"available": False, "reason": "no_paired_cells"}
    d = (wide["official"] - wide["raw"]).to_numpy(dtype=float)
    rng = np.random.default_rng(RNG_SEED)
    draws = np.array([d[rng.choice(len(d), len(d), True)].mean() for _ in range(N_BOOT)]) if len(d) > 1 else d
    return {
        "available": True, "factor": "pipeline", "a": "official", "b": "raw",
        "n_paired_cells": int(len(d)),
        "mean_official": round(float(wide["official"].mean()), 4),
        "mean_raw": round(float(wide["raw"].mean()), 4),
        "mean_diff": round(float(d.mean()), 4),
        "diff_ci95": [round(float(np.percentile(draws, 2.5)), 4), round(float(np.percentile(draws, 97.5)), 4)],
        "cells_official_better": int(np.sum(d > 0)),
        "cells_tied": int(np.sum(d == 0)),
        "cells_raw_better": int(np.sum(d < 0)),
        "sign_p": _sign_p(int(np.sum(d != 0)), int(np.sum(d > 0))),
    }


# ---------------------------------------------------------------------------
# B. no-GT confidence signals
# ---------------------------------------------------------------------------

# Candidate *no-GT* signals.  ``ORACLE_SIGNALS`` deliberately use ground truth and
# are reported only as an upper reference; they are never gate features.
CONFIDENCE_SIGNALS = [
    "sig_top1_min", "sig_top1_start", "sig_top1_end",
    "sig_margin_min", "sig_margin_start", "sig_margin_end",
    "sig_entropy_max", "sig_entropy_start", "sig_entropy_end",
    "sig_bmm",
    "sig_disagree_loo_start", "sig_disagree_loo_end", "sig_disagree_loo_both",
    "sig_disagree_sd",
    "sig_model_loo_start", "sig_model_loo_end", "sig_model_loo_both",
    "sig_model_sd", "sig_model_range_both",
    "sig_raw_selected_shift", "sig_raw_selected_maxshift",
    "sig_zero_dur", "sig_dur_vs_segment_median_err", "sig_gap_to_next_start",
]
ORACLE_SIGNALS = ["oracle_dur_ratio_err", "oracle_iou"]


def build_confidence_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add no-GT candidate signals + GT labels to the raw-unit frame.

    Disagreement signals use leave-one-out across the *inference configurations*
    of the same segment inside the same pipeline, so the signal for a row never
    sees that row's own prediction.
    """
    d = df.copy()
    d["pred_dur_sec"] = d["pred_end_sec"] - d["pred_start_sec"]
    d["pred_zero_dur"] = (d["pred_dur_sec"] <= 1e-6).astype(float)
    d["sig_top1_min"] = d[["raw_top1_start", "raw_top1_end"]].min(axis=1)
    d["sig_top1_start"] = d["raw_top1_start"]
    d["sig_top1_end"] = d["raw_top1_end"]
    d["sig_margin_min"] = d[["raw_margin_start", "raw_margin_end"]].min(axis=1)
    d["sig_margin_start"] = d["raw_margin_start"]
    d["sig_margin_end"] = d["raw_margin_end"]
    d["sig_entropy_max"] = d[["raw_entropy_start", "raw_entropy_end"]].max(axis=1)
    d["sig_entropy_start"] = d["raw_entropy_start"]
    d["sig_entropy_end"] = d["raw_entropy_end"]
    d["sig_bmm"] = d["raw_boundary_margin_mean"]
    d["sig_zero_dur"] = d["pred_zero_dur"]
    ratio = d["pred_dur_sec"] / d["gt_dur_sec"].replace(0, np.nan)
    d["oracle_dur_ratio_err"] = (ratio - 1).abs()          # GT-dependent: reference only
    d["oracle_iou"] = d["iou"]                              # GT-dependent: reference only
    # honest self-consistency substitutes for the GT duration sanity check
    seg_med = d.groupby(["pipeline", "item"], observed=True)["pred_dur_sec"].transform("median")
    d["sig_dur_vs_segment_median_err"] = (d["pred_dur_sec"] / seg_med.replace(0, np.nan) - 1).abs()
    # predicted silence gap between this unit's end and the next unit's start: a
    # negative gap means an overlap, a large positive gap means a hole.
    order = d.sort_values(["unit_key", "unit_index"])
    gap = (order.groupby("unit_key", observed=True)["pred_start_sec"].shift(-1)
           - order["pred_end_sec"])
    d["sig_gap_to_next_start"] = gap.reindex(d.index)
    # post-processing shift: raw decoder output vs final selection (no GT needed)
    d["sig_raw_selected_shift"] = (d["pred_start_sec"] - d["raw_start_sec"]).abs() + \
        (d["pred_end_sec"] - d["raw_end_sec"]).abs()
    d["sig_raw_selected_maxshift"] = np.maximum((d["pred_start_sec"] - d["raw_start_sec"]).abs(),
                                                (d["pred_end_sec"] - d["raw_end_sec"]).abs())

    # leave-one-out disagreement across configs of the same (pipeline, item, unit_index)
    grp_cols = ["pipeline", "item", "unit_index"]
    for col, name in (("pred_start_sec", "s"), ("pred_end_sec", "e")):
        x = d[col].to_numpy(dtype=float)
        d[f"_sq_{name}"] = np.square(x)
        gg = d.groupby(grp_cols, observed=True)
        cnt = gg[col].transform("count").to_numpy(dtype=float)
        s1 = gg[col].transform("sum").to_numpy(dtype=float)
        s2 = gg[f"_sq_{name}"].transform("sum").to_numpy(dtype=float)
        loo_cnt = cnt - 1.0
        loo_mean = np.where(loo_cnt > 0, (s1 - x) / np.maximum(loo_cnt, 1), np.nan)
        loo_var = np.where(loo_cnt > 1,
                           (s2 - np.square(x)) / np.maximum(loo_cnt - 1, 1) - np.square(loo_mean),
                           np.nan)
        d[f"loo_mean_{name}"] = loo_mean
        d[f"loo_sd_{name}"] = np.sqrt(np.clip(loo_var, 0, None))
        d = d.drop(columns=[f"_sq_{name}"])
    d["sig_disagree_loo_start"] = (d["pred_start_sec"] - d["loo_mean_s"]).abs()
    d["sig_disagree_loo_end"] = (d["pred_end_sec"] - d["loo_mean_e"]).abs()
    d["sig_disagree_loo_both"] = np.maximum(d["sig_disagree_loo_start"], d["sig_disagree_loo_end"])
    d["sig_disagree_sd"] = 1.0 - np.exp(-np.sqrt(
        np.square(d["loo_sd_s"]) + np.square(d["loo_sd_e"])))

    # Model-level disagreement.  The labelled 12-cell matrix collapses to ~3.5
    # distinct prediction vectors per segment (MATRIX_AUDIT), so leave-one-out over
    # all cells underestimates disagreement: the row's own duplicated cell stays in
    # its comparison set.  Restricting the comparison set to one cell per *model*
    # (vocal/windowed) removes that bias; the signal is then defined only there.
    ref_cell = d[(d["audio_input"] == "vocal") & (d["mode"] == "windowed")].copy()
    grp = ["pipeline", "item", "unit_index"]
    for col, name in (("pred_start_sec", "start"), ("pred_end_sec", "end")):
        x = ref_cell[col].to_numpy(dtype=float)
        ref_cell[f"_x_{name}"] = x
        gg = ref_cell.groupby(grp, observed=True)[f"_x_{name}"]
        cnt = gg.transform("count").to_numpy(dtype=float)
        s1 = gg.transform("sum").to_numpy(dtype=float)
        loo = np.where(cnt > 1, (s1 - x) / np.maximum(cnt - 1, 1), np.nan)
        ref_cell[f"_loo_{name}"] = loo
    ref_cell["sig_model_loo_start"] = (ref_cell["pred_start_sec"] - ref_cell["_loo_start"]).abs()
    ref_cell["sig_model_loo_end"] = (ref_cell["pred_end_sec"] - ref_cell["_loo_end"]).abs()
    ref_cell["sig_model_loo_both"] = np.maximum(ref_cell["sig_model_loo_start"],
                                               ref_cell["sig_model_loo_end"])
    agg = ref_cell.groupby(grp, observed=True)[["pred_start_sec", "pred_end_sec"]]
    spread = (agg.max() - agg.min()).sum(axis=1).rename("sig_model_range_both").reset_index()
    sd = agg.std().rename(columns={"pred_start_sec": "_sds", "pred_end_sec": "_sde"}).reset_index()
    sd["sig_model_sd"] = np.sqrt(sd["_sds"] ** 2 + sd["_sde"] ** 2)
    keep = ref_cell[grp + ["model", "audio_input", "mode", "sig_model_loo_start",
                           "sig_model_loo_end", "sig_model_loo_both"]].merge(
        spread, on=grp, how="left").merge(sd[grp + ["sig_model_sd"]], on=grp, how="left")
    d = d.merge(keep, on=["pipeline", "item", "unit_index", "model", "audio_input", "mode"],
                how="left", suffixes=("", "_dup"))
    d["hit100"] = (d["both_abs_err_sec"] <= TOL_PRIMARY).astype(float)
    d["hit200"] = (d["both_abs_err_sec"] <= TOL_SECONDARY).astype(float)
    d["bad100"] = 1.0 - d["hit100"]
    d["bad200"] = 1.0 - d["hit200"]
    return d


def compute_signals(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": "gtsinger_gt_confidence_signals_v1",
                           "definition": {"bad100": f"both_abs_err > {TOL_PRIMARY}s",
                                          "bad200": f"both_abs_err > {TOL_SECONDARY}s",
                                          "disagreement": "leave-one-out |pred - mean(other configs of same "
                                                          "pipeline/item/unit)|"},
                           "signals": {}}
    base = build_confidence_frame(df)
    for scope_name, scope in (("all_configs", base),
                              ("r2_vocal_windowed", base[(base["model"] == "r2") &
                                                         (base["audio_input"] == "vocal") &
                                                         (base["mode"] == "windowed")])):
        tab = {}
        for sig in CONFIDENCE_SIGNALS + ORACLE_SIGNALS:
            if sig not in scope.columns:
                continue
            entry: dict[str, Any] = {}
            for label, col in (("bad100", "bad100"), ("bad200", "bad200")):
                stats = _grouped_auc(scope, col, sig, "seg_key")
                # AUC must be oriented: higher signal -> more confident for
                # confidence signals, more disagreement for error signals; report
                # |AUC-0.5| so orientation never masks strength.
                for key in ("flat_auc", "within_segment_auc_mean"):
                    if stats[key] is not None:
                        v = stats[key]
                        stats[f"{key}_oriented"] = round(v if v >= 0.5 else 1 - v, 4)
                        stats["signal_higher_means_worse"] = bool(v >= 0.5)
                        stats["uses_gt"] = sig.startswith("oracle_")
                entry[label] = stats
            tab[sig] = entry
        out["signals"][scope_name] = tab

    # multivariate gate: logistic regression, grouped CV by segment
    gate = _gate_model(base)
    out["gate_model"] = gate

    # calibration of the raw top-1 boundary probability treated as "boundary correct"
    cal = {}
    for stage, pcol, ecol in (("start", "raw_top1_start", "start_abs_err_sec"),
                              ("end", "raw_top1_end", "end_abs_err_sec")):
        sub = base[[pcol, ecol]].dropna()
        y = (sub[ecol] <= TOL_PRIMARY).to_numpy(dtype=float)
        p = sub[pcol].to_numpy(dtype=float)
        cal[stage] = {
            "n": int(len(sub)),
            "mean_top1_prob": round(float(p.mean()), 4),
            "observed_hit_rate": round(float(y.mean()), 4),
            "gap": round(float(p.mean() - y.mean()), 4),
            "ece_raw": round(_ece(y, p), 4),
            "auc_prob_vs_hit": round((_auc(y, p) or 0.0) + 0.0, 4),
        }
        # reliability by decile
        edges = np.linspace(0, 1, 11)
        idx = np.clip(np.digitize(p, edges[1:-1]), 0, 9)
        rel = []
        for b in range(10):
            sel = idx == b
            if sel.sum() >= 20:
                rel.append({"bin": b, "n": int(sel.sum()), "pred": round(float(p[sel].mean()), 3),
                            "obs": round(float(y[sel].mean()), 3)})
        cal[stage]["reliability_deciles"] = rel
    out["calibration_top1"] = cal
    return out


def _gate_model(base: pd.DataFrame) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, average_precision_score
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    feature_sets = {
        "posterior_only": ["sig_top1_min", "sig_margin_min", "sig_entropy_max", "sig_bmm",
                           "sig_top1_start", "sig_top1_end"],
        "disagreement_all_cells": ["sig_disagree_loo_start", "sig_disagree_loo_end",
                                  "sig_disagree_loo_both", "sig_disagree_sd"],
        "disagreement_per_model": ["sig_model_loo_start", "sig_model_loo_end",
                                   "sig_model_sd", "sig_model_range_both"],
        "structural_only": ["sig_zero_dur", "sig_dur_vs_segment_median_err",
                            "sig_raw_selected_maxshift", "sig_gap_to_next_start"],
        "posterior+disagreement": ["sig_top1_min", "sig_margin_min", "sig_entropy_max", "sig_bmm",
                                   "sig_top1_start", "sig_top1_end",
                                   "sig_model_loo_start", "sig_model_loo_end",
                                   "sig_model_sd", "sig_model_range_both"],
        "all_no_gt": ["sig_top1_min", "sig_margin_min", "sig_entropy_max", "sig_bmm",
                      "sig_top1_start", "sig_top1_end", "sig_model_loo_start",
                      "sig_model_loo_end", "sig_model_loo_both", "sig_model_sd",
                      "sig_model_range_both", "sig_zero_dur", "sig_dur_vs_segment_median_err",
                      "sig_raw_selected_maxshift", "sig_gap_to_next_start"],
        "oracle_reference_uses_gt": ["oracle_dur_ratio_err", "oracle_iou"],
    }
    res: dict[str, Any] = {}
    for name, feats in feature_sets.items():
        # Complete-case only: median imputation would silently invent values for
        # the (large) share of rows where a signal is structurally undefined.
        sub = base[feats + ["bad100", "seg_key"]].replace([np.inf, -np.inf], np.nan).dropna()
        X = sub[feats].to_numpy(dtype=float)
        y = sub["bad100"].to_numpy(dtype=float)
        groups = sub["seg_key"].to_numpy()
        if len(np.unique(groups)) < 5 or y.min() == y.max():
            res[name] = {"available": False, "reason": "insufficient_groups"}
            continue
        pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                         ("sc", StandardScaler()),
                         ("lr", LogisticRegression(max_iter=2000, class_weight=None))])
        gkf = GroupKFold(n_splits=min(5, len(np.unique(groups))))
        oof_p = np.zeros(len(y))
        for tr, te in gkf.split(X, y, groups):
            pipe.fit(X[tr], y[tr])
            oof_p[te] = pipe.predict_proba(X[te])[:, 1]
        entry = {
            "available": True,
            "n_rows": int(len(y)),
            "n_groups": int(len(np.unique(groups))),
            "positive_rate": round(float(y.mean()), 4),
            "oof_auc": round(float(roc_auc_score(y, oof_p)), 4),
            "oof_ap": round(float(average_precision_score(y, oof_p)), 4),
            "oof_ece": round(_ece(y, oof_p), 4),
            "oof_brier": round(float(np.mean(np.square(oof_p - y))), 4),
        }
        # operating points: fixed recall of bad units, and fixed *review budget*
        # (flag rate), the quantity a real realign pass is actually limited by.
        for target_rec in (0.9, 0.95):
            thr = np.quantile(oof_p[y == 1], 1.0 - target_rec) if (y == 1).any() else np.nan
            flagged = oof_p >= thr
            entry[f"recall{int(target_rec*100)}"] = {
                "threshold": round(float(thr), 4),
                "achieved_recall": round(float(flagged[y == 1].mean()), 4),
                "flag_rate": round(float(flagged.mean()), 4),
                "precision": round(float(y[flagged].mean()), 4) if flagged.any() else None,
            }
        budget = {}
        order = np.argsort(-oof_p)
        y_sorted = y[order]
        for frac in (0.05, 0.10, 0.20, 0.30):
            k = max(int(round(frac * len(y))), 1)
            top = y_sorted[:k]
            budget[f"flag_{int(frac*100)}pct"] = {
                "precision": round(float(top.mean()), 4),
                "recall": round(float(top.sum() / max(y.sum(), 1)), 4),
            }
        entry["review_budget_curve"] = budget
        res[name] = entry
    return res


# ---------------------------------------------------------------------------
# C. error structure
# ---------------------------------------------------------------------------

def compute_structure(df: pd.DataFrame) -> dict[str, Any]:
    d = build_confidence_frame(df)
    ref = d[(d["model"] == "r2") & (d["audio_input"] == "vocal") & (d["mode"] == "windowed")
            & (d["pipeline"] == "official")].copy()
    out: dict[str, Any] = {"schema": "gtsinger_gt_error_structure_v1",
                           "reference_config": "r2/vocal/windowed/official",
                           "n_units": int(len(ref))}

    def signed(col: str) -> dict[str, Any]:
        v = ref[col].dropna().to_numpy(dtype=float)
        return {"n": int(len(v)), "mean": round(float(v.mean()), 4),
                "median": round(float(np.median(v)), 4),
                "p05": round(float(np.percentile(v, 5)), 4),
                "p95": round(float(np.percentile(v, 95)), 4),
                "share_late": round(float(np.mean(v > 0.02)), 4),
                "share_early": round(float(np.mean(v < -0.02)), 4)}

    out["signed_bias"] = {"start": signed("start_err_signed_sec"), "end": signed("end_err_signed_sec"),
                          "duration_err": signed("dur_err_sec"),
                          "center": signed("center_offset_sec")}

    # duration-conditioned error (GT duration buckets)
    buckets = [0, 0.15, 0.25, 0.4, 0.6, 1.0, 100]
    ref["dur_bucket"] = pd.cut(ref["gt_dur_sec"], buckets, include_lowest=True)
    tab = ref.groupby("dur_bucket", observed=True).agg(
        n=("hit100", "size"), hit100=("hit100", "mean"), mae_start=("start_abs_err_sec", "mean"),
        mae_end=("end_abs_err_sec", "mean"), mean_dur=("gt_dur_sec", "mean")).reset_index()
    out["by_gt_duration"] = [{"bucket": str(r.dur_bucket), "n": int(r.n),
                              "hit100": round(float(r.hit100), 4),
                              "mae_start": round(float(r.mae_start), 4),
                              "mae_end": round(float(r.mae_end), 4),
                              "mean_gt_dur": round(float(r.mean_dur), 3)} for r in tab.itertuples()]

    # technique / melisma / position effects
    def cond(col: str, values: Iterable[Any]) -> list[dict[str, Any]]:
        rows = []
        for v in values:
            sub = ref[ref[col] == v]
            if len(sub) < 10:
                continue
            rows.append({col: str(v), "n": int(len(sub)),
                         "hit100": round(float(sub["hit100"].mean()), 4),
                         "mae_both": round(float(sub["both_abs_err_sec"].mean()), 4),
                         "mean_gt_dur": round(float(sub["gt_dur_sec"].mean()), 3)})
        return sorted(rows, key=lambda r: r["hit100"])

    out["by_melisma"] = cond("gt_is_melisma", [0, 1])
    out["by_multi_phoneme"] = cond("gt_is_multi_phoneme", [0, 1])
    # onsetless syllables are confounded with segment starts, so cross them out
    ref["_not_first"] = (ref["unit_index"] > 0)
    cross = []
    for (mp, notfirst), sub in ref.groupby(["gt_is_multi_phoneme", "_not_first"], observed=True):
        if len(sub) < 10:
            continue
        cross.append({"gt_is_multi_phoneme": int(mp), "not_first_unit": bool(notfirst),
                      "n": int(len(sub)), "hit100": round(float(sub["hit100"].mean()), 4),
                      "mae_start": round(float(sub["start_abs_err_sec"].mean()), 4)})
    out["melisma_x_position_crosstab"] = sorted(cross, key=lambda r: r["hit100"])
    for flag in ("gt_flag_mix", "gt_flag_falsetto", "gt_flag_breathy", "gt_flag_pharyngeal",
                 "gt_flag_glissando", "gt_flag_vibrato"):
        rows = cond(flag, [0, 1])
        if rows:
            out.setdefault("by_technique_flag", {})[flag] = rows
    out["by_pace"] = cond("pace", sorted(ref["pace"].dropna().unique()))
    out["by_range"] = cond("range", sorted(ref["range"].dropna().unique()))
    out["by_emotion"] = cond("emotion", sorted(ref["emotion"].dropna().unique()))
    out["by_group"] = cond("group", sorted(ref["group"].dropna().unique()))

    pos = pd.cut(ref["unit_pos_frac"], [-0.01, 0.001, 0.1, 0.9, 0.999, 1.01],
                 labels=["first_unit", "early", "middle", "late", "last_unit"])
    ref["pos_bucket"] = pos
    tab = ref.groupby("pos_bucket", observed=True).agg(n=("hit100", "size"), hit100=("hit100", "mean"),
                                                       mae_start=("start_abs_err_sec", "mean"),
                                                       mae_end=("end_abs_err_sec", "mean")).reset_index()
    signed = ref.groupby("pos_bucket", observed=True).agg(
        start_signed=("start_err_signed_sec", "mean"),
        start_signed_med=("start_err_signed_sec", "median"),
        end_signed=("end_err_signed_sec", "mean"),
        share_start_late=("start_err_signed_sec", lambda x: float((x > 0.02).mean())),
        share_start_at_zero=("pred_start_sec", lambda x: float((x.abs() < 1e-6).mean())),
    ).reset_index()
    signed_map = {str(r.pos_bucket): {"start_signed_mean": round(float(r.start_signed), 4),
                                      "start_signed_median": round(float(r.start_signed_med), 4),
                                      "end_signed_mean": round(float(r.end_signed), 4),
                                      "share_start_late": round(float(r.share_start_late), 4),
                                      "share_pred_start_at_zero": round(float(r.share_start_at_zero), 4)}
                  for r in signed.itertuples()}
    out["by_position_in_segment"] = [{"bucket": str(r.pos_bucket), "n": int(r.n),
                                      "hit100": round(float(r.hit100), 4),
                                      "mae_start": round(float(r.mae_start), 4),
                                      "mae_end": round(float(r.mae_end), 4),
                                      **signed_map.get(str(r.pos_bucket), {})} for r in tab.itertuples()]

    # window-seam effects (windowed rows only): distance to committed window end
    w = d[(d["model"] == "r2") & (d["audio_input"] == "vocal") & (d["mode"] == "windowed")
          & (d["pipeline"] == "official")].copy()
    w = w[w["units_from_window_end"].notna()]
    out["seam_analysis"] = {"n_units": int(len(w)),
                            "n_windows": int(w.groupby("seg_key")["window_index"].nunique().sum())}
    if len(w):
        w["seam_bucket"] = pd.cut(w["units_from_window_end"], [-0.5, 0.5, 1.5, 2.5, 4.5, 1e9],
                                  labels=["last_unit_of_window", "2nd_last", "3rd_last",
                                          "4th-5th", "earlier"])
        tab = w.groupby("seam_bucket", observed=True).agg(n=("hit100", "size"), hit100=("hit100", "mean"),
                                                          mae_start=("start_abs_err_sec", "mean"),
                                                          mae_end=("end_abs_err_sec", "mean"),
                                                          mean_dist=("dist_to_window_end_sec", "mean")).reset_index()
        out["seam_analysis"]["by_position_from_window_end"] = [
            {"bucket": str(r.seam_bucket), "n": int(r.n), "hit100": round(float(r.hit100), 4),
             "mae_start": round(float(r.mae_start), 4), "mae_end": round(float(r.mae_end), 4),
             "mean_dist_to_core_end_sec": None if pd.isna(r.mean_dist) else round(float(r.mean_dist), 3)}
            for r in tab.itertuples()]
        w["head_bucket"] = pd.cut(w["units_from_window_start"], [-0.5, 0.5, 1.5, 2.5, 4.5, 1e9],
                                  labels=["first_unit_of_window", "2nd", "3rd", "4th-5th", "later"])
        tab = w.groupby("head_bucket", observed=True).agg(n=("hit100", "size"), hit100=("hit100", "mean"),
                                                          mae_start=("start_abs_err_sec", "mean")).reset_index()
        out["seam_analysis"]["by_position_from_window_start"] = [
            {"bucket": str(r.head_bucket), "n": int(r.n), "hit100": round(float(r.hit100), 4),
             "mae_start": round(float(r.mae_start), 4)} for r in tab.itertuples()]

    # first unit: GTSinger clips start exactly at the first note, so a predicted
    # onset of 0.0 is "free"; the informative question is how often the model
    # hallucinates a lead-in and what that costs.
    first = ref[ref["unit_index"] == 0]
    if len(first):
        pz = (first["pred_start_sec"].abs() < 1e-6).to_numpy(dtype=float)
        gz = (first["gt_start_sec"].abs() < 1e-6).to_numpy(dtype=float)
        block = {"n": int(len(first)), "share_gt_start_zero": round(float(gz.mean()), 4),
                 "share_pred_start_zero": round(float(pz.mean()), 4), "cells": {}}
        for name, sel in (("pred_onset_zero", pz > 0.5), ("pred_onset_positive", pz < 0.5)):
            sub = first[sel]
            if len(sub):
                block["cells"][name] = {
                    "n": int(len(sub)), "hit100": round(float(sub["hit100"].mean()), 4),
                    "mean_pred_start_sec": round(float(sub["pred_start_sec"].mean()), 4),
                    "mean_signed_start_err_sec": round(float(sub["start_err_signed_sec"].mean()), 4),
                    "mean_abs_end_err_sec": round(float(sub["end_abs_err_sec"].mean()), 4),
                    "hit100_excluding_start": round(float(
                        (sub["end_abs_err_sec"] <= TOL_PRIMARY).mean()), 4)}
        out["first_unit_analysis"] = block

    # boundary contagion: forced contiguity means one wrong end drags the next start
    out["contagion"] = _contagion(ref)

    # error clustering: contiguous runs of bad units inside a segment
    out["clustering"] = _clustering(d)
    out["clustering_nulls"] = _clustering_nulls(d)

    # degenerate predictions
    deg = d.assign(z=d["pred_zero_dur"]).groupby(["pipeline", "model", "audio_input", "mode"],
                                                 observed=True)["z"].mean()
    out["zero_duration_rate"] = {f"{i[0]}|{i[1]}|{i[2]}|{i[3]}": round(float(v), 5)
                                 for i, v in deg.items()}
    inv = (d["pred_end_sec"] < d["pred_start_sec"]).astype(float)
    out["negative_duration_rate_max"] = round(float(inv.max()), 5)
    out["interval_monotonic_violation_rate"] = round(float(
        d.sort_values(["unit_key", "unit_index"]).groupby("unit_key", observed=True)
         .apply(lambda g: float((np.diff(g["pred_start_sec"].to_numpy(dtype=float)) < -1e-6).mean()
                                if len(g) > 1 else 0.0), include_groups=False).mean()), 5)
    return out


def _contagion(ref: pd.DataFrame) -> dict[str, Any]:
    """How much of a unit's start error is inherited from the previous unit's end error?

    ``alignment.json`` enforces near-contiguous units, so a single wrong tail
    boundary should drag every following onset with it.  That is one concrete
    mechanism behind the excess of contiguous bad runs (§ clustering).
    """
    g = ref.sort_values(["item", "unit_index"]).groupby("item", observed=True)
    prev_end_err = g["end_err_signed_sec"].shift(1)
    prev_end_abs = g["end_abs_err_sec"].shift(1)
    d = ref.assign(_prev_end_err=prev_end_err.to_numpy(), _prev_end_abs=prev_end_abs.to_numpy(),
                   _gap=(ref["pred_start_sec"].to_numpy(dtype=float)
                         - g["pred_end_sec"].shift(1).to_numpy(dtype=float)))
    d = d[d["unit_index"] > 0]
    out: dict[str, Any] = {"n_pairs": int(len(d))}
    exact = (d["_gap"].abs() <= 1e-6).to_numpy(dtype=float)
    out["share_pred_start_equals_prev_end_exact"] = round(float(exact.mean()), 4)
    out["share_pred_within_10ms_of_prev_end"] = round(float((d["_gap"].abs() <= 0.01).mean()), 4)
    gt_gap = (ref.assign(_p=ref.groupby("item", observed=True)["gt_end_sec"].shift(1))
                 .dropna(subset=["_p"]))
    out["share_gt_contiguous"] = round(float(
        (np.abs(gt_gap["gt_start_sec"] - gt_gap["_p"]) <= 1e-6).mean()), 4)
    both = d.dropna(subset=["start_err_signed_sec", "_prev_end_err"])
    if len(both) > 50:
        inherited = (np.abs(both["start_err_signed_sec"] - both["_prev_end_err"]) <= 0.01)
        out["share_start_err_inherited_from_prev_end"] = round(float(inherited.mean()), 4)
        out["pearson_start_err_vs_prev_end_err"] = round(
            float(np.corrcoef(both["start_err_signed_sec"], both["_prev_end_err"])[0, 1]), 4)
        # conditional: how much worse is a unit whose predecessor's tail is bad?
        bad_prev = (both["_prev_end_abs"] > TOL_PRIMARY)
        good_prev = (both["_prev_end_abs"] <= TOL_PRIMARY)
        out["hit100_given_prev_end_bad"] = round(float(both.loc[bad_prev, "hit100"].mean()), 4)
        out["hit100_given_prev_end_good"] = round(float(both.loc[good_prev, "hit100"].mean()), 4)
        out["n_prev_end_bad"] = int(bad_prev.sum())
        # chain length: consecutive inherited errors
        arr = both.sort_values(["item", "unit_index"])
        inh = inherited.to_numpy(dtype=float)
        idx = arr["unit_index"].to_numpy()
        items = arr["item"].to_numpy()
        runs: list[int] = []
        cur = 0
        for k in range(len(inh)):
            cont = inh[k] > 0.5 and (k > 0 and items[k] == items[k - 1]
                                     and idx[k] == idx[k - 1] + 1)
            if inh[k] > 0.5 and (cur == 0 or cont):
                cur += 1
            else:
                if cur:
                    runs.append(cur)
                cur = 1 if inh[k] > 0.5 else 0
        if cur:
            runs.append(cur)
        if runs:
            out["inherited_chain_len_mean"] = round(float(np.mean(runs)), 3)
            out["inherited_chain_len_max"] = int(np.max(runs))
            out["n_inherited_chains"] = int(len(runs))
    return out


def _run_length_counts(arrays: list[np.ndarray]) -> dict[int, float]:
    counts: dict[int, float] = {}
    for arr in arrays:
        cur = 0
        for v in arr:
            if v:
                cur += 1
            elif cur:
                counts[cur] = counts.get(cur, 0.0) + 1.0
                cur = 0
        if cur:
            counts[cur] = counts.get(cur, 0.0) + 1.0
    return counts


def _clustering_nulls(d: pd.DataFrame, n_sims: int = 400) -> dict[str, Any]:
    """Is the excess of contiguous bad runs explained by observable difficulty?

    Null A treats units as i.i.d. at the marginal bad rate (already reported in
    ``clustering``).  Null B keeps the *per-unit* probability of failure implied by
    observable covariates (ground-truth duration / syllable structure / technique
    group / position, fitted out-of-fold by segment) and only removes the
    residual local dependence.  If the observed run-length profile matches Null B,
    "hard regions" are just clusters of hard units; if it still exceeds Null B,
    there is genuine regional structure that a region-level realign can exploit.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler

    feats = ["gt_dur_sec", "gt_is_multi_phoneme", "gt_is_melisma", "gt_note_count",
             "gt_ph_dur_max_sec", "unit_pos_frac", "units_from_window_start",
             "units_from_window_end"]
    work = d.copy()
    work["is_first"] = (work["unit_index"] == 0).astype(float)
    grp_dummies = pd.get_dummies(work["group"].astype("string"), prefix="grp", dtype=float)
    X = pd.concat([work[[c for c in feats if c in work.columns]],
                   work[["is_first"]], grp_dummies], axis=1)
    X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median(numeric_only=True))
    y = (work["both_abs_err_sec"] > TOL_PRIMARY).to_numpy(dtype=float)
    groups = work["seg_key"].to_numpy()
    scaler = StandardScaler().fit(X.to_numpy(dtype=float))
    Xs = scaler.transform(X.to_numpy(dtype=float))
    gkf = GroupKFold(n_splits=5)
    p_oof = np.zeros(len(y))
    for tr, te in gkf.split(Xs, y, groups):
        lr = LogisticRegression(max_iter=2000, C=1.0)
        lr.fit(Xs[tr], y[tr])
        p_oof[te] = lr.predict_proba(Xs[te])[:, 1]
    work["_p"] = p_oof

    key_cols = ["pipeline", "model", "audio_input", "mode", "item"]
    arrays_obs, arrays_p = [], []
    for _, g in work.sort_values(key_cols + ["unit_index"]).groupby(key_cols, observed=True):
        if len(g) < 2:
            continue
        arrays_obs.append(g["_bad" if "_bad" in g else "both_abs_err_sec"].to_numpy(dtype=float)
                          if "_bad" in g else (g["both_abs_err_sec"].to_numpy(dtype=float) > TOL_PRIMARY))
        arrays_p.append(g["_p"].to_numpy(dtype=float))
    observed = _run_length_counts([a.astype(bool) for a in arrays_obs])
    rng = np.random.default_rng(RNG_SEED)
    sim_totals: dict[int, float] = {}
    sim_share_ge2: list[float] = []
    for _ in range(n_sims):
        sims = [(rng.random(len(p)) < p) for p in arrays_p]
        cnt = _run_length_counts(sims)
        for k, v in cnt.items():
            sim_totals[k] = sim_totals.get(k, 0.0) + v
        tot = sum(cnt.values())
        bad_units = sum(k * v for k, v in cnt.items())
        sim_share_ge2.append(sum(k * v for k, v in cnt.items() if k >= 2) / max(bad_units, 1))
    sim_mean = {int(k): v / n_sims for k, v in sim_totals.items()}
    obs_total = sum(observed.values())
    ks = sorted(set(list(observed) + list(sim_mean)))
    table = {}
    for k in ks:
        if k > 12:
            continue
        o = observed.get(k, 0)
        sm = sim_mean.get(k, 0.0)
        table[k] = {"observed": float(o), "nullB_expected": round(sm, 2),
                    "excess": round(o / sm, 2) if sm > 0 else None,
                    "observed_share": round(o / max(obs_total, 1), 4)}
    return {
        "covariates": [c for c in feats if c in work.columns] + ["is_first", "group_dummies"],
        "n_chains_observable": obs_total,
        "oof_covariate_auc": round((_auc(y, p_oof) or 0.0), 4),
        "marginal_bad_rate": round(float(y.mean()), 4),
        "mean_p_oof": round(float(p_oof.mean()), 4),
        "share_bad_in_runs_ge2_observed": round(float(
            sum(k * v for k, v in observed.items() if k >= 2)
            / max(sum(k * v for k, v in observed.items()), 1)), 4),
        "share_bad_in_runs_ge2_nullB_mean": round(float(np.mean(sim_share_ge2)), 4),
        "share_bad_in_runs_ge2_nullB_p95": round(float(np.percentile(sim_share_ge2, 95)), 4),
        "run_length_table": table,
        "n_sims": n_sims,
    }


def _clustering(d: pd.DataFrame) -> dict[str, Any]:
    """How clustered are the errors?  Feeds the region-level realign premise."""
    bad = (d["both_abs_err_sec"] > TOL_PRIMARY).to_numpy(dtype=float)
    d = d.assign(_bad=bad)
    keys = ["seg_key", "model", "audio_input", "mode", "pipeline", "unit_index"]
    sub = d[keys].sort_values(keys[:-1] + ["unit_index"])
    runs: list[int] = []
    total_bad = total_units = 0
    seg_with_bad = 0
    for _, g in sub.groupby(["model", "audio_input", "mode", "pipeline", "seg_key"], observed=True):
        arr = d.loc[g.index, "_bad"].to_numpy(dtype=float)
        total_bad += int(arr.sum())
        total_units += len(arr)
        if arr.sum() == 0:
            continue
        seg_with_bad += 1
        cur = 0
        for v in arr:
            if v == 1:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
    runs_arr = np.asarray(runs, dtype=float)
    if runs_arr.size == 0:
        return {"available": False}
    # expected run-length distribution under independence (same marginal rate)
    p_bad = total_bad / max(total_units, 1)
    # Under i.i.d. unit errors a bad run continues with probability p_bad and ends
    # with probability 1 - p_bad, so run length is geometric: P(L=k)=p_bad^(k-1)(1-p_bad).
    counts = {int(k): int((runs_arr == k).sum()) for k in sorted(set(runs_arr.tolist())) if k <= 12}
    n_runs = len(runs_arr)
    kmax = max(counts) if counts else 1
    renorm = 1.0 - p_bad ** kmax
    exp = {int(k): round(float(n_runs * (p_bad ** (k - 1)) * (1.0 - p_bad) / max(renorm, 1e-9)), 2)
           for k in counts}
    return {
        "available": True,
        "unit_bad_rate": round(float(p_bad), 4),
        "segments_with_any_bad": seg_with_bad,
        "n_runs": int(len(runs_arr)),
        "mean_run_len": round(float(runs_arr.mean()), 3),
        "max_run_len": int(runs_arr.max()),
        "share_bad_in_runs_ge2": round(float(runs_arr[runs_arr >= 2].sum() / max(runs_arr.sum(), 1)), 4),
        "observed_run_lengths": counts,
        "expected_run_lengths_geometric": {k: v for k, v in exp.items() if v is not None},
        "interpretation": "share_bad_in_runs_ge2 above ~0.5 with observed long runs "
                          "indicating contiguous error regions rather than i.i.d. unit noise",
    }


# ---------------------------------------------------------------------------
# D. configuration-matrix identity audit
# ---------------------------------------------------------------------------

def compute_matrix(df: pd.DataFrame) -> dict[str, Any]:
    """Are the labelled factors actually different inputs?

    ``evaluation_v1`` runs advertise a 3 x 2 x 2 matrix (model x audio x mode).  If
    two cells were fed the *same* audio bytes and the same effective plan, they are
    not two measurements but one measurement recorded twice; any "factor effect"
    computed from them is vacuous.  This audit decides that from provenance
    (``identity.audio.sha256``) and from the prediction vectors themselves.
    """
    d = df.copy()
    d["iv"] = list(zip(d["model"], d["audio_input"], d["mode"], d["pipeline"], d["item"],
                       d["pred_start_sec"], d["pred_end_sec"]))
    out: dict[str, Any] = {"schema": "gtsinger_gt_config_matrix_audit_v1", "per_run": {}}
    for run, rdf in d.groupby("run", observed=True):
        per_item = []
        for item, idf in rdf.groupby("item", observed=True):
            configs = idf.drop_duplicates(["model", "audio_input", "mode"])
            if configs.empty:
                continue
            # audio provenance per label
            audio_by_label = {lab: sorted(set(configs.loc[configs["audio_input"] == lab, "audio_sha256"]))
                              for lab in ("mix", "vocal")}
            distinct_audio = {a for v in audio_by_label.values() for a in v}
            # prediction-vector uniqueness
            vecs: dict[str, set] = {}
            for _, r in idf.iterrows():
                key = f"{r['model']}|{r['audio_input']}|{r['mode']}"
                vecs.setdefault(key, set()).add((int(r["unit_index"]), float(r["pred_start_sec"]),
                                                 float(r["pred_end_sec"])))
            hashes = {k: hashlib.sha256(repr(sorted(v)).encode()).hexdigest()[:12]
                      for k, v in vecs.items()}
            n_units = int(idf["unit_index"].max() + 1) if len(idf) else 0
            per_item.append({
                "item": item,
                "configs": len(hashes),
                "distinct_vectors": len(set(hashes.values())),
                "n_units": n_units,
                "audio_labels": {k: (v[0][:12] if len(v) == 1 else v) for k, v in audio_by_label.items()},
                "distinct_audio_shas": len(distinct_audio),
                "mix_equals_vocal_sha": (len(audio_by_label.get("mix", [])) == 1
                                         and audio_by_label.get("mix") == audio_by_label.get("vocal")),
            })
        n = len(per_item)
        if n == 0:
            continue
        cfg = np.array([r["configs"] for r in per_item], dtype=float)
        dv = np.array([r["distinct_vectors"] for r in per_item], dtype=float)
        same_sha = np.array([r["mix_equals_vocal_sha"] for r in per_item], dtype=float)
        out["per_run"][run] = {
            "items": n,
            "configs_labelled_per_item_mean": round(float(cfg.mean()), 3),
            "distinct_prediction_vectors_per_item_mean": round(float(dv.mean()), 3),
            "redundancy_factor": round(float(cfg.mean() / max(dv.mean(), 1e-9)), 3),
            "audio_sha_distinct_per_item_min": int(min(r["distinct_audio_shas"] for r in per_item)),
            "audio_sha_distinct_per_item_max": int(max(r["distinct_audio_shas"] for r in per_item)),
            "items_where_mix_and_vocal_audio_identical": int(same_sha.sum()),
            "share_items_mix_equals_vocal_audio": round(float(same_sha.mean()), 4),
            "audio_sha_per_label": per_item[0]["audio_labels"],
        }
    # mode effect: compare windowed vs full prediction vectors where both exist
    pair = d.pivot_table(index=["run", "item", "model", "unit_index"], columns="mode",
                         values="pred_start_sec", aggfunc="first").dropna()
    mode_identical = None
    pair_e = d.pivot_table(index=["run", "item", "model", "unit_index"], columns="mode",
                           values="pred_end_sec", aggfunc="first").dropna()
    if not pair.empty:
        eq = (np.abs(pair["full"] - pair["windowed"]) <= 1e-6).to_numpy(dtype=float)
        eqe = (np.abs(pair_e["full"] - pair_e["windowed"]) <= 1e-6).to_numpy(dtype=float)
        # where they differ, is the whole unit identical except the tail?
        mode_identical = {
            "n_pairs": int(len(pair)),
            "share_start_identical": round(float(eq.mean()), 4),
            "share_end_identical": round(float(eqe.mean()), 4),
            "share_either_moving": round(float(1 - (eq * eqe).mean()), 4),
        }
    pair2 = d.pivot_table(index=["run", "item", "model", "unit_index"], columns="audio_input",
                          values="pred_start_sec", aggfunc="first").dropna()
    audio_identical = None
    if not pair2.empty:
        eq = (np.abs(pair2["mix"] - pair2["vocal"]) <= 1e-6).to_numpy(dtype=float)
        audio_identical = {"n_pairs": int(len(pair2)),
                           "share_identical": round(float(eq.mean()), 4)}
    out["mode_vs_full_start_identity"] = mode_identical
    out["mix_vs_vocal_start_identity"] = audio_identical
    return out


# ---------------------------------------------------------------------------
# E. post-processing repair accounting (raw decoder -> official selection)
# ---------------------------------------------------------------------------

def compute_postprocess(df: pd.DataFrame) -> dict[str, Any]:
    """How often does the official post-processor move a boundary, and does the
    move go toward the ground truth?  This is the same question the realign line
    asks about re-alignment passes, answered on a mechanism that is already always
    on and therefore a legitimate reference point."""
    d = df.copy()
    off = d[d["pipeline"] == "official"].copy()
    rawd = d[d["pipeline"] == "raw"].copy()
    out: dict[str, Any] = {"schema": "gtsinger_gt_postprocess_repair_v1",
                           "tolerance_sec": 1e-3}
    # sanity: does the "raw" pipeline really keep raw == selected?
    if len(rawd):
        shift = np.maximum((rawd["pred_start_sec"] - rawd["raw_start_sec"]).abs(),
                           (rawd["pred_end_sec"] - rawd["raw_end_sec"]).abs())
        out["raw_pipeline_selected_equals_raw_share"] = round(float((shift <= 1e-6).mean()), 4)
    if not len(off):
        return out

    for scope_name, scope in (("all_official", off),
                              ("r2_vocal_windowed", off[(off["model"] == "r2") &
                                                        (off["audio_input"] == "vocal") &
                                                        (off["mode"] == "windowed")])):
        if scope.empty:
            continue
        ds = (scope["pred_start_sec"] - scope["raw_start_sec"]).abs().to_numpy(dtype=float)
        de = (scope["pred_end_sec"] - scope["raw_end_sec"]).abs().to_numpy(dtype=float)
        moved = (np.maximum(ds, de) > 1e-3)
        res: dict[str, Any] = {"n_units": int(len(scope)), "share_units_touched": round(float(moved.mean()), 4)}
        sub = scope[moved]
        if len(sub):
            raw_start_err = (sub["raw_start_sec"] - sub["gt_start_sec"]).abs()
            sel_start_err = (sub["pred_start_sec"] - sub["gt_start_sec"]).abs()
            raw_end_err = (sub["raw_end_sec"] - sub["gt_end_sec"]).abs()
            sel_end_err = (sub["pred_end_sec"] - sub["gt_end_sec"]).abs()
            raw_both = np.maximum(raw_start_err, raw_end_err)
            sel_both = np.maximum(sel_start_err, sel_end_err)
            better = (sel_both + 1e-9 < raw_both).to_numpy(dtype=float)
            worse = (raw_both + 1e-9 < sel_both).to_numpy(dtype=float)
            flip_in = ((raw_both > TOL_PRIMARY) & (sel_both <= TOL_PRIMARY)).to_numpy(dtype=float)
            flip_out = ((raw_both <= TOL_PRIMARY) & (sel_both > TOL_PRIMARY)).to_numpy(dtype=float)
            res["touched"] = {
                "n": int(len(sub)),
                "mean_shift_start_sec": round(float((sub["pred_start_sec"] - sub["raw_start_sec"]).abs().mean()), 4),
                "mean_shift_end_sec": round(float((sub["pred_end_sec"] - sub["raw_end_sec"]).abs().mean()), 4),
                "median_shift_end_sec": round(float((sub["pred_end_sec"] - sub["raw_end_sec"]).abs().median()), 4),
                "direction_end": {"moves_earlier": int(((sub["pred_end_sec"] - sub["raw_end_sec"]) < -1e-3).sum()),
                                  "moves_later": int(((sub["pred_end_sec"] - sub["raw_end_sec"]) > 1e-3).sum())},
                "repair_rate_both": round(float(better.mean()), 4),
                "damage_rate_both": round(float(worse.mean()), 4),
                "tie_rate_both": round(float(1 - better.mean() - worse.mean()), 4),
                "mean_abs_err_raw_both": round(float(raw_both.mean()), 4),
                "mean_abs_err_sel_both": round(float(sel_both.mean()), 4),
                "net_err_delta_sec": round(float(sel_both.mean() - raw_both.mean()), 4),
                "hit100_raw": round(float((raw_both <= TOL_PRIMARY).mean()), 4),
                "hit100_sel": round(float((sel_both <= TOL_PRIMARY).mean()), 4),
                "flips_into_tol": int(flip_in.sum()),
                "flips_out_of_tol": int(flip_out.sum()),
                "start_repair_rate": round(float((sel_start_err + 1e-9 < raw_start_err).mean()), 4),
                "start_damage_rate": round(float((raw_start_err + 1e-9 < sel_start_err).mean()), 4),
                "end_repair_rate": round(float((sel_end_err + 1e-9 < raw_end_err).mean()), 4),
                "end_damage_rate": round(float((raw_end_err + 1e-9 < sel_end_err).mean()), 4),
            }
            # does confidence predict which touches are repairs vs damages?
            conf = scope.loc[moved].copy()
            conf["min_margin"] = conf[["raw_margin_start", "raw_margin_end"]].min(axis=1)
            conf["min_top1"] = conf[["raw_top1_start", "raw_top1_end"]].min(axis=1)
            conf["max_ent"] = conf[["raw_entropy_start", "raw_entropy_end"]].max(axis=1)
            auc = {}
            for sig in ("min_margin", "min_top1", "max_ent"):
                a = _auc(np.asarray(better, dtype=float), conf[sig].to_numpy(dtype=float))
                auc[sig] = None if a is None else round(a, 4)
            res["touched"]["auc_low_confidence_indicates_repair"] = auc
        # Mechanism attribution: which rule moved the boundary?  The official
        # post-processor resolves overlaps by pinning a unit's start to the previous
        # unit's end (and its end to the next unit's start), so "share equal to the
        # neighbour's boundary" identifies the rule without reading its source.
        keys = ["item", "model", "audio_input", "mode"]
        o = scope.sort_values(keys + ["unit_index"]).copy()
        gg = o.groupby(keys, observed=True)
        o["_prev_end"] = gg["pred_end_sec"].shift(1)
        o["_next_start"] = gg["pred_start_sec"].shift(-1)
        d_s = (o["pred_start_sec"] - o["raw_start_sec"]).to_numpy(dtype=float)
        d_e = (o["pred_end_sec"] - o["raw_end_sec"]).to_numpy(dtype=float)
        m_s = np.abs(d_s) > 1e-3
        m_e = np.abs(d_e) > 1e-3
        mech: dict[str, Any] = {"n_start_moved": int(m_s.sum()), "n_end_moved": int(m_e.sum())}
        if m_s.any():
            mech["start_moved"] = {
                "direction_later": int((d_s[m_s] > 0).sum()),
                "direction_earlier": int((d_s[m_s] < 0).sum()),
                "mean_shift_sec": round(float(d_s[m_s].mean()), 4),
                "share_pinned_to_prev_end": round(float(
                    (np.abs(o["pred_start_sec"].to_numpy()[m_s]
                            - o["_prev_end"].to_numpy()[m_s]) <= 1e-3).mean()), 4)}
        if m_e.any():
            mech["end_moved"] = {
                "direction_earlier": int((d_e[m_e] < 0).sum()),
                "direction_later": int((d_e[m_e] > 0).sum()),
                "mean_shift_sec": round(float(d_e[m_e].mean()), 4),
                "share_pinned_to_next_start": round(float(
                    (np.abs(o["pred_end_sec"].to_numpy()[m_e]
                            - o["_next_start"].to_numpy()[m_e]) <= 1e-3).mean()), 4)}
        mech["raw_zero_duration_share"] = round(float(
            ((o["raw_end_sec"] - o["raw_start_sec"]) <= 1e-6).mean()), 4)
        mech["final_zero_duration_share"] = round(float(
            ((o["pred_end_sec"] - o["pred_start_sec"]) <= 1e-6).mean()), 4)
        mech["raw_overlap_rate_with_next"] = round(float(
            (gg["raw_end_sec"].shift(-1).notna() &
             (o["raw_end_sec"] > o.groupby(keys, observed=True)["raw_start_sec"].shift(-1))).mean()), 4)
        res["mechanism"] = mech
        out[scope_name] = res
    return out


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run_all(evidence: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_panel(evidence)
    results: dict[str, Any] = {"evidence": str(evidence), "rows_total": int(len(df))}
    panel = panel_only(df)
    results["panel_rows"] = int(len(panel))
    results["panel_items"] = int(panel["item"].nunique())
    results["panel_segments"] = int(panel["seg_key"].nunique())

    effects = compute_effects(panel)
    (out_dir / "EFFECTS.json").write_text(json.dumps(effects, ensure_ascii=False, indent=2), encoding="utf-8")
    signals = compute_signals(panel)
    (out_dir / "SIGNALS.json").write_text(json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8")
    structure = compute_structure(panel)
    (out_dir / "STRUCTURE.json").write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
    matrix = compute_matrix(df)
    (out_dir / "MATRIX_AUDIT.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    post = compute_postprocess(panel)
    (out_dir / "POSTPROCESS.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")

    # ablation runs: window-mechanism ablations were previously "inconclusive";
    # re-test them against real GT on the small set for completeness.
    ab = df[df["run"].isin([r for r in df["run"].unique() if r not in PANEL_RUNS])]
    if not ab.empty:
        seg = _seg_metrics(ab)
        out_dir.joinpath("ABLATION.json").write_text(json.dumps({
            "schema": "gtsinger_gt_window_ablation_v1",
            "note": "short-clip window-mechanism ablation runs re-scored against real GT",
            "per_run": [{"run": r, "segments": int(s["seg_key"].nunique()),
                         "hit100_macro": round(float(s["hit100"].mean()), 4),
                         "hit200_macro": round(float(s["hit200"].mean()), 4),
                         "mae_start": round(float(s["mae_start"].mean()), 4),
                         "mae_end": round(float(s["mae_end"].mean()), 4)}
                        for r, s in seg.groupby("run", observed=True)],
            "mode_levels": [{"mode": m, "hit100_macro": round(float(s["hit100"].mean()), 4),
                             "n": int(len(s))} for m, s in seg.groupby("mode", observed=True)],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    results["artifacts"] = sorted(p.name for p in out_dir.glob("*.json"))
    (out_dir / "ANALYSIS_SUMMARY.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
    return results
