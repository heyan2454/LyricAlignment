"""True multi-view selection on GTSinger, scored against human per-word ground truth.

Round 9 measured cross-window consensus on natural long-form data against a *weak, model-derived*
reference, and only 40% of units had more than one attempt.  The round-1 GTSinger panel is the harder
test: every unit carries **12 genuinely different views** — three checkpoints (r0 projector-only, r1,
r2 LoRA) x two audio inputs (mix, separated vocal) x two planning modes (whole clip, 60 s windowed) —
and the reference is human annotation.

Deployable baselines are the individual views (in particular the production-like one: r2 + vocal +
windowed).  Label-free selectors are consensus, agreement support, decoder entropy and combinations.
The oracle (best view per unit, chosen with GT) is reported as an upper bound only.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

VIEWS = ["model", "audio_input", "mode"]
UNIT_KEY = ["pipeline", "item", "unit_index"]
PRODUCTION_VIEW = ("r2", "vocal", "windowed")
TOLS = (0.100, 0.200, 0.250)
SEED = 20260912
N_BOOT = 400


def build_view_frame(df: pd.DataFrame, pipeline: str = "official") -> pd.DataFrame:
    """One row per (unit, view) with the error against human GT, keeping recorded posteriors."""
    d = df[(df["pipeline"] == pipeline)].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec"]).copy()
    d["view"] = d["model"].astype(str) + "|" + d["audio_input"].astype(str) + "|" + d["mode"].astype(str)
    d["view_id"] = pd.factorize(d["view"])[0]
    d["both_err"] = np.maximum((d["pred_start_sec"] - d["gt_start_sec"]).abs(),
                               (d["pred_end_sec"] - d["gt_end_sec"]).abs())
    d["start_err"] = (d["pred_start_sec"] - d["gt_start_sec"]).abs()
    d["end_err"] = (d["pred_end_sec"] - d["gt_end_sec"]).abs()
    return d.sort_values(UNIT_KEY + ["view"]).reset_index(drop=True)


def view_quality(d: pd.DataFrame) -> dict[str, Any]:
    """Per-view accuracy table plus the diversity decomposition (starts and ends separately)."""
    out: dict[str, Any] = {"views": {}, "units": int(d.groupby(UNIT_KEY, observed=True).ngroups)}
    for (model, audio, mode, _v), sub in d.groupby(VIEWS + ["view"], observed=True):
        e = sub["both_err"].to_numpy(dtype=float)
        out["views"][f"{model}|{audio}|{mode}"] = {
            "units": int(e.size),
            "hit100": round(float(np.mean(e <= TOLS[0])), 4),
            "hit250": round(float(np.mean(e <= TOLS[2])), 4),
            "mae_both_sec": round(float(np.mean(e)), 4),
            "is_production_view": (model, audio, mode) == PRODUCTION_VIEW,
        }
    prod = out["views"].get("|".join(PRODUCTION_VIEW), {})
    out["production_view"] = {"name": "|".join(PRODUCTION_VIEW), **prod}
    g = d.groupby(UNIT_KEY, observed=True)
    bb = g.apply(lambda x: float(max(x["pred_start_sec"].max() - x["pred_start_sec"].min(),
                                     x["pred_end_sec"].max() - x["pred_end_sec"].min())),
                 include_groups=False).to_numpy(dtype=float)
    out["cross_view_disagreement"] = {
        "median_sec": round(float(np.median(bb)), 4),
        "p75": round(float(np.percentile(bb, 75)), 4),
        "p90": round(float(np.percentile(bb, 90)), 4),
        "share_gt_100ms": round(float(np.mean(bb > 0.1)), 4),
        "share_gt_250ms": round(float(np.mean(bb > 0.25)), 4),
    }
    # per-factor decomposition: hold the *other* view factors fixed, otherwise joining on the unit key
    # alone produces a cross product (r2-mix vs r0-vocal) and invents spread that does not exist --
    # the same ambiguity that round 9's duplicate-key measurement fell into.
    factors: dict[str, Any] = {}
    for f in VIEWS:
        levels = sorted({str(v) for v in d[f]})
        if len(levels) < 2:
            continue
        others = [x for x in VIEWS if x != f]
        pair_key = UNIT_KEY[1:] + others
        starts, ends = [], []
        for _k, sub in d.groupby(pair_key, observed=True):
            if sub[f].nunique() < 2:
                continue
            starts.append(float(sub["pred_start_sec"].max() - sub["pred_start_sec"].min()))
            ends.append(float(sub["pred_end_sec"].max() - sub["pred_end_sec"].min()))
        if not starts:
            continue
        ss = np.asarray(starts, dtype=float)
        ee = np.asarray(ends, dtype=float)
        factors[f"{f} (other factors held fixed)"] = {
            "levels": levels, "matched_cells": int(ss.size),
            "start_diff_median_sec": round(float(np.median(ss)), 4),
            "start_diff_share_gt_100ms": round(float(np.mean(ss > 0.1)), 4),
            "end_diff_median_sec": round(float(np.median(ee)), 4),
            "end_diff_share_gt_100ms": round(float(np.mean(ee > 0.1)), 4),
        }
    out["factor_decomposition"] = factors
    return out


def _score(err: np.ndarray, groups: np.ndarray, note: str = "") -> dict[str, Any]:
    ok = np.isfinite(err)
    e = err[ok]
    out: dict[str, Any] = {"units": int(e.size),
                           "hit100": round(float(np.mean(e <= TOLS[0])), 4),
                           "hit200": round(float(np.mean(e <= TOLS[1])), 4),
                           "hit250": round(float(np.mean(e <= TOLS[2])), 4),
                           "mae_both_sec": round(float(np.mean(e)), 4),
                           "median_both_sec": round(float(np.median(e)), 4)}
    uniq = np.unique(groups[ok])
    idx = {g: np.flatnonzero(groups[ok] == g) for g in uniq}
    rng = np.random.default_rng(SEED)
    draws_mae = np.empty(N_BOOT)
    draws_hit = np.empty(N_BOOT)
    for i in range(N_BOOT):
        picked = rng.choice(uniq, len(uniq), True)
        sample = e[np.concatenate([idx[g] for g in picked])]
        draws_mae[i] = sample.mean()
        draws_hit[i] = float(np.mean(sample <= TOLS[0]))
    lo, hi = np.percentile(draws_mae, [2.5, 97.5])
    hlo, hhi = np.percentile(draws_hit, [2.5, 97.5])
    out["hit100_ci95_item_boot"] = [round(float(hlo), 4), round(float(hhi), 4)]
    out["mae_ci95_item_boot"] = [round(float(lo), 4), round(float(hi), 4)]
    if note:
        out["note"] = note
    return out


def selection_experiment(d: pd.DataFrame) -> dict[str, Any]:
    """Compare deployable selectors against per-view baselines and the GT oracle."""
    out: dict[str, Any] = {"schema": "gtsinger_multiview_selection_v1", "results": {}}
    g = d.groupby(UNIT_KEY, observed=True)
    items = d["item"].to_numpy()

    def unit_index_of(frame: pd.DataFrame) -> pd.Index:
        return frame.set_index(UNIT_KEY).index

    # consensus boundaries (median over views) — a deployable output, not a view
    cons = g.apply(lambda x: pd.Series({
        "c_s": float(np.median(x["pred_start_sec"])), "c_e": float(np.median(x["pred_end_sec"])),
        "gt_s": float(x["gt_start_sec"].iloc[0]), "gt_e": float(x["gt_end_sec"].iloc[0]),
        "err_mean_view": float(x["both_err"].mean()),
        "err_best_view": float(x["both_err"].min()),
        "err_worst_view": float(x["both_err"].max()),
        "disagreement": float(max(x["pred_start_sec"].max() - x["pred_start_sec"].min(),
                                 x["pred_end_sec"].max() - x["pred_end_sec"].min())),
        "n_views": float(len(x)),
    }), include_groups=False).reset_index()
    cons_err = np.maximum(np.abs(cons["c_s"] - cons["gt_s"]), np.abs(cons["c_e"] - cons["gt_e"]))
    item_of_unit = cons["item"].to_numpy()

    out["per_view_baseline"] = {
        "mean_of_views_hit100": round(float(np.mean(d["both_err"] <= TOLS[0])), 4),
        "mean_of_views_mae": round(float(d["both_err"].mean()), 4),
        "production_view": None,
    }
    prod = d[(d["model"] == PRODUCTION_VIEW[0]) & (d["audio_input"] == PRODUCTION_VIEW[1])
             & (d["mode"] == PRODUCTION_VIEW[2])]
    if len(prod):
        out["per_view_baseline"]["production_view"] = {
            "name": "|".join(PRODUCTION_VIEW), **_score(
                prod["both_err"].to_numpy(dtype=float), prod["item"].to_numpy(dtype=object),
                note="single deployed configuration")}
    out["results"]["R1_consensus_median_boundaries"] = _score(
        cons_err.to_numpy(dtype=float), item_of_unit, note="median boundary across the 12 views")
    out["results"]["R0_mean_of_views"] = _score(
        d["both_err"].to_numpy(dtype=float), items, note="average over views (equals a random view)")

    # selectors that pick one view per unit, using label-free features only
    d = d.copy()
    # distance from the cross-view consensus (leave-one-out is approximated by the full median,
    # which is stable with 12 views and keeps the computation vectorised)
    for col, tag in (("pred_start_sec", "s"), ("pred_end_sec", "e")):
        med_all = g[col].transform("median").to_numpy(dtype=float)
        d[f"dev_{tag}"] = np.abs(d[col].to_numpy(dtype=float) - med_all)
    d["dev_consensus"] = np.maximum(d["dev_s"], d["dev_e"])
    # support: number of other views within 100 ms on both boundaries
    sup = np.zeros(len(d))
    for _k, idx in g.indices.items():
        pos = np.asarray(idx, dtype=int)
        s = d.loc[pos, "pred_start_sec"].to_numpy(dtype=float)
        e = d.loc[pos, "pred_end_sec"].to_numpy(dtype=float)
        for j, p in enumerate(pos):
            o_s = np.delete(s, j)
            o_e = np.delete(e, j)
            if o_s.size == 0:
                continue
            sup[p] = float(np.mean((np.abs(o_s - s[j]) <= 0.1) & (np.abs(o_e - e[j]) <= 0.1)))
    d["support_100ms"] = sup
    ent_cols = [c for c in ("raw_entropy_start", "raw_entropy_end") if c in d]
    if ent_cols:
        d["ent_max_view"] = np.fmax.reduce([pd.to_numeric(d[c], errors="coerce").to_numpy(dtype=float)
                                            for c in ent_cols])
    else:
        d["ent_max_view"] = np.nan

    g = d.groupby(UNIT_KEY, observed=True)      # re-group: features were added after `g` first bound
    sel_specs = {
        "S_pick_max_support": ("support_100ms", "max"),
        "S_pick_min_consensus_distance": ("dev_consensus", "min"),
        "S_pick_min_entropy": ("ent_max_view", "min"),
        "S_pick_production_view_else_consensus": None,
    }
    for name, spec in sel_specs.items():
        if spec is None:
            continue
        col, how = spec
        idx = g[col].idxmax() if how == "max" else g[col].idxmin()
        sub = d.loc[d.index.get_indexer(pd.Index(idx.to_numpy()))]
        out["results"][name] = _score(sub["both_err"].to_numpy(dtype=float),
                                      sub["item"].to_numpy(dtype=object),
                                      note=f"pick the view with {how} {col}")
    # production view where it agrees with consensus, otherwise the best-supported view
    prod_mask = ((d["model"] == PRODUCTION_VIEW[0]) & (d["audio_input"] == PRODUCTION_VIEW[1])
                 & (d["mode"] == PRODUCTION_VIEW[2])).to_numpy()
    prod_rows = d[prod_mask]
    prod_idx = prod_rows.set_index(UNIT_KEY).index
    agree = (prod_rows["dev_consensus"].to_numpy(dtype=float) <= 0.1)
    picked = [prod_rows.iloc[i] for i in np.flatnonzero(agree)]
    fallback_pool = d[~prod_mask].copy()
    if len(fallback_pool):
        fb = fallback_pool.loc[fallback_pool.groupby(UNIT_KEY, observed=True)["support_100ms"].idxmax()]
        picked_frames = pd.concat([pd.DataFrame(picked), fb]) if picked else fb
    else:
        picked_frames = pd.DataFrame(picked)
    if len(picked_frames):
        out["results"]["S_production_when_confident_else_best_support"] = _score(
            picked_frames["both_err"].to_numpy(dtype=float),
            picked_frames["item"].to_numpy(dtype=object),
            note=f"keep production view when its consensus distance <=100ms "
                 f"({100 * float(agree.mean()):.0f}% of units), else re-pick by support")

    # oracle and worst (bounds)
    orc = d.loc[g["both_err"].idxmin()]
    wst = d.loc[g["both_err"].idxmax()]
    out["results"]["U_oracle_best_view"] = _score(orc["both_err"].to_numpy(dtype=float),
                                                  orc["item"].to_numpy(dtype=object),
                                                  note="upper bound, uses GT")
    out["results"]["U_worst_view"] = _score(wst["both_err"].to_numpy(dtype=float),
                                            wst["item"].to_numpy(dtype=object),
                                            note="lower bound, uses GT")
    base = out["per_view_baseline"]["production_view"] or {}
    top = out["results"]["U_oracle_best_view"]["hit100"]
    ref = base.get("hit100", out["per_view_baseline"]["mean_of_views_hit100"])
    gap = max(top - ref, 1e-9)
    out["gap_closed"] = {k: {"hit100": v["hit100"],
                             "delta_pp_vs_production": round((v["hit100"] - ref) * 100, 2),
                             "share_of_oracle_gap": round((v["hit100"] - ref) / gap, 3)}
                         for k, v in out["results"].items() if not k.startswith("U_")}
    out["oracle_gap_pp"] = round((top - ref) * 100, 2)
    d_out = d[UNIT_KEY + ["view", "both_err", "support_100ms", "dev_consensus", "ent_max_view"]]
    return out, d_out, cons

def factor_content_audit(df: pd.DataFrame, pipeline: str = "official") -> dict[str, Any]:
    """Did the recorded view factors actually change the input bytes?

    ``request_hash`` differs across cells (the label/path is part of it), which is not the same as the
    *content* differing.  Comparing ``audio_sha256`` between the levels of each factor, with every
    other factor held fixed, says whether an ablation was real.  A factor whose cells share a content
    hash is a dead configuration: any conclusion drawn from it is void.
    """
    d = df[df["pipeline"] == pipeline]
    if "audio_sha256" not in d:
        return {"available": False, "reason": "no audio_sha256 column"}
    # each factor has a different expectation, so a single "identical content" rule would mislabel it:
    #   audio_input  - should change the bytes -> identical sha means the ablation never happened (bug)
    #   mode         - same file, different plan -> identical bytes is expected; uninformative when the
    #                  clip fits in one window (round-1 finding), which is a property of the data
    #   model        - same file on purpose; the informative axis is the output difference, not the input
    expect = {"audio_input": "input_bytes", "mode": "input_plan", "model": "input_checkpoint"}
    effect = {"audio_input": {}, "mode": {}, "model": {}}
    out: dict[str, Any] = {"available": True, "pipeline": pipeline,
                           "expectation": expect, "factors": {}}
    for f in VIEWS:
        levels = sorted({str(v) for v in d[f]})
        if len(levels) < 2:
            continue
        others = [x for x in VIEWS if x != f]
        pair_key = ["item"] + others + ["model"] if f != "model" else ["item"] + others
        same_cells = diff_cells = 0
        rh_same = rh_diff = 0
        for _k, sub in d.groupby(pair_key, observed=True):
            per_level = {str(lvl): sub[sub[f] == lvl] for lvl in levels}
            shas = {lvl: {str(v) for v in per_level[lvl]["audio_sha256"].dropna()} for lvl in levels
                    if len(per_level[lvl])}
            if len(shas) < 2:
                continue
            vals = list(shas.values())
            if all(v == vals[0] for v in vals):
                same_cells += 1
            else:
                diff_cells += 1
            rhs = [set(per_level[lvl]["request_hash"].dropna().astype(str)) for lvl in shas]
            if all(r == rhs[0] for r in rhs):
                rh_same += 1
            else:
                rh_diff += 1
        total = same_cells + diff_cells
        sha_share = round(same_cells / total, 4) if total else None
        if f == "audio_input":
            verdict = ("DEAD CONFIGURATION: mix and vocal cells were fed the *same bytes* "
                       "(identical audio_sha256) => this ablation never happened"
                       if total and same_cells == total else "input genuinely varies")
        elif f == "mode":
            verdict = ("same file by design; uninformative on clips shorter than one window "
                       "(outputs identical, see factor_decomposition)") if total and same_cells == total \
                else "plan varies"
        else:
            verdict = "same file by design (checkpoint axis); differs in output => informative"
        out["factors"][f] = {
            "levels": levels, "matched_cells": int(total),
            "share_identical_audio_sha": sha_share,
            "share_identical_request_hash": round(rh_same / total, 4) if total else None,
            "verdict": verdict,
        }
    return out
