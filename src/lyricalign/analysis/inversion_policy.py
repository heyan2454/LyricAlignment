"""What should the pipeline do with a decoder start/end inversion?  Measured, not assumed.

Round 16 found the shipped behaviour is to clamp ``end := max(end, start)``, which turns an
inversion into a zero-length unit that two shipped counters never report.  Round 17 showed those
zero-length units also depress the reported accuracy (up to +5.4 pp for the base predictor once they
are excluded).  This module prices the candidate policies against ground truth, on the two panels
where a boundary reference exists:

* GTSinger ``pipeline=raw`` (human word-level GT; 76 inverted units) — a bypass path that keeps
  inversions, so the model output can be observed un-clamped;
* M4 long-form (weak signed GT rebuilt from segment labels; 1,562 inverted units).

Policies are applied **per unit**, in isolation, and only to inverted units, so the comparison says
what a policy is worth at the margin rather than what a full re-decode would cost.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

MIN_DUR_SEC = 0.05
TOL_SEC = 0.1


def policy_clamp_zero(s: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Current shipped behaviour: end := max(end, start) -> a zero-length unit at the start value."""
    out = np.maximum(e, s)
    return s, out


def policy_swap(s: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Treat the two slots as unordered: start := min, end := max."""
    return np.minimum(s, e), np.maximum(s, e)


def policy_midpoint(s: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """No usable span: put both boundaries at the mean of the two predictions."""
    mid = 0.5 * (s + e)
    return mid, mid


def policy_min_dur(s: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Smallest legal interval that keeps the min-duration floor: start := min, end := start + floor."""
    start = np.minimum(s, e)
    return start, start + MIN_DUR_SEC


def policy_previous_end_to_floor(s: np.ndarray, e: np.ndarray, *,
                                 prev_e: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Anchor the start at the previous unit's end and give the unit the median plausible span.

    Requires sequence context (``prev_e``); falls back to ``policy_min_dur`` where it is missing.
    """
    start, end = policy_min_dur(s, e)
    if prev_e is None:
        return start, end
    ok = np.isfinite(prev_e)
    start = np.where(ok, prev_e, start)
    end = np.where(ok, start + (MIN_DUR_SEC * 6), end)      # ~0.3 s, near the observed median span
    return np.minimum(start, end), end


POLICIES: dict[str, Callable[..., tuple[np.ndarray, np.ndarray]]] = {
    "P0_shipped_clamp_to_zero": policy_clamp_zero,
    "P1_swap_endpoints": policy_swap,
    "P2_midpoint": policy_midpoint,
    "P3_min_duration_floor": policy_min_dur,
    "P4_floor_from_previous_end": policy_previous_end_to_floor,
}


def evaluate_policies(frame: pd.DataFrame, *, start_col: str = "raw_start_sec",
                      end_col: str = "raw_end_sec", gt_start: str = "gt_start_sec",
                      gt_end: str = "gt_end_sec", seq_col: str | None = None,
                      tol_sec: float = TOL_SEC) -> dict[str, Any]:
    """Score every policy on the inverted units (and, for reference, on all units)."""
    # positional indexing is used below, so a filtered frame must be re-based first
    frame = frame.reset_index(drop=True)
    s = pd.to_numeric(frame[start_col], errors="coerce").to_numpy(dtype=float)
    e = pd.to_numeric(frame[end_col], errors="coerce").to_numpy(dtype=float)
    gs = pd.to_numeric(frame[gt_start], errors="coerce").to_numpy(dtype=float)
    ge = pd.to_numeric(frame[gt_end], errors="coerce").to_numpy(dtype=float)
    have = np.isfinite(s) & np.isfinite(e) & np.isfinite(gs) & np.isfinite(ge)
    inverted = have & ((e - s) < -1e-6)
    prev_e: np.ndarray | None = None
    if seq_col and seq_col in frame.columns:
        prev_e = np.full(len(frame), np.nan)
        ordered = frame.assign(_s=s, _e=e)
        for _k, sub in ordered.groupby(seq_col, observed=True):
            idx = sub.index.to_numpy()
            shifted = np.concatenate([[np.nan], sub["_e"].to_numpy(dtype=float)[:-1]])
            prev_e[idx] = shifted
    out: dict[str, Any] = {"units": int(have.sum()), "inverted_units": int(inverted.sum()),
                           "inverted_share": round(float(inverted.sum() / max(have.sum(), 1)), 5),
                           "tolerance_sec": tol_sec, "policies": {}}
    for name, fn in POLICIES.items():
        try:
            ns, ne = fn(s, e, prev_e=prev_e) if name.startswith("P4") else fn(s, e)
        except TypeError:
            ns, ne = fn(s, e)
        entry: dict[str, Any] = {}
        for tag, mask in (("inverted_units_only", inverted), ("all_units", have)):
            if not mask.any():
                continue
            err = np.maximum(np.abs(ns[mask] - gs[mask]), np.abs(ne[mask] - ge[mask]))
            entry[tag] = {
                "n": int(mask.sum()),
                "hit_at_tol": round(float(np.mean(err <= tol_sec)), 4),
                "mae_start_sec": round(float(np.mean(np.abs(ns[mask] - gs[mask]))), 4),
                "mae_end_sec": round(float(np.mean(np.abs(ne[mask] - ge[mask]))), 4),
                "bias_end_sec": round(float(np.mean(ne[mask] - ge[mask])), 4),
                "zero_length_share": round(float(np.mean(np.abs(ne[mask] - ns[mask]) <= 1e-6)), 4),
                "duration_violation_share": round(float(np.mean((ne[mask] - ns[mask]) < 0)), 4)}
        # the "mark and re-decode" option: no boundary change, just cost and metric effect
        entry["trigger"] = {"flagged_units": int(inverted.sum()),
                            "flag_share": round(float(inverted.sum() / max(have.sum(), 1)), 5)}
        out["policies"][name] = entry
    return out


def decision_summary(res: dict[str, Any]) -> dict[str, Any]:
    """Rank policies by their hit-rate on the inverted units and show what a re-decode marker costs."""
    rows = []
    for name, v in res["policies"].items():
        inv = v.get("inverted_units_only")
        if not inv:
            continue
        rows.append({"policy": name, "hit_at_tol": inv["hit_at_tol"],
                     "mae_end_sec": inv["mae_end_sec"], "bias_end_sec": inv["bias_end_sec"],
                     "zero_length_share": inv["zero_length_share"],
                     "duration_violation_share": inv["duration_violation_share"]})
    if not rows:
        return {"available": False}
    tab = pd.DataFrame(rows).sort_values("hit_at_tol", ascending=False)
    best = tab.iloc[0]
    current = next((r for r in rows if r["policy"].startswith("P0")), None)
    return {"available": True, "ranking": tab.to_dict(orient="records"),
            "best_policy": str(best["policy"]),
            "best_hit_at_tol": float(best["hit_at_tol"]),
            "gain_vs_shipped_pp": (round(100.0 * (float(best["hit_at_tol"]) - float(current["hit_at_tol"])), 2)
                                   if current else None),
            "shipped_zero_length_share_after": (current["zero_length_share"] if current else None),
            "trigger_cost_share": res["policies"][tab.iloc[0]["policy"]]["trigger"]["flag_share"]}


def structural_consequence(shipped: "pd.DataFrame", *, raw_start: str = "raw_s",
                           raw_end: str = "raw_e", start: str = "start_sec",
                           end: str = "end_sec", song_col: str = "song",
                           max_dur_sec: float = 3.0) -> dict[str, Any]:
    """What each policy does to timeline *legality* when no ground truth exists.

    Swapping looks attractive until the inversion magnitudes are inspected: on the real-song batch
    the median inverted gap is seconds and the tail is minutes, so a swapped interval swallows its
    neighbours and trades zero-length units for overlaps and start regressions.  That is the
    quantitative reason the recommendation is "flag for re-decode / solve globally", not "swap".
    """
    import numpy as np

    from lyricalign.analysis import joint_cleanup as J
    from lyricalign.analysis import structural_compliance as SC

    df = shipped.reset_index(drop=True)
    rs = pd.to_numeric(df[raw_start], errors="coerce").to_numpy(dtype=float)
    re = pd.to_numeric(df[raw_end], errors="coerce").to_numpy(dtype=float)
    s0 = pd.to_numeric(df[start], errors="coerce").to_numpy(dtype=float)
    e0 = pd.to_numeric(df[end], errors="coerce").to_numpy(dtype=float)
    inv = np.isfinite(rs) & np.isfinite(re) & ((re - rs) < -1e-6)
    gaps = np.abs(rs[inv] - re[inv])
    out: dict[str, Any] = {"units": int(len(df)), "inverted_units": int(inv.sum()),
                           "inverted_share": round(float(inv.sum() / max(len(df), 1)), 4),
                           "inversion_gap_median_sec": round(float(np.median(gaps)), 2) if gaps.size else None,
                           "inversion_gap_p90_sec": round(float(np.percentile(gaps, 90)), 2) if gaps.size else None,
                           "policies": {}}
    variants = {
        "P0_shipped": (s0, e0),
        "P1_swap": (np.where(inv, np.minimum(rs, re), s0), np.where(inv, np.maximum(rs, re), e0)),
        "P3_min_floor": (np.where(inv, np.minimum(rs, re), s0),
                         np.where(inv, np.minimum(rs, re) + MIN_DUR_SEC, e0)),
    }
    for name, (S, E) in variants.items():
        probe = df.assign(**{start: S, end: E}).dropna(subset=[start, end])
        probe = probe.sort_values([song_col] + [c for c in ("unit_index",) if c in probe.columns])
        flagged = SC.flag_violations(probe, max_dur=max_dur_sec)
        out["policies"][name] = {
            "degenerate_share": round(float(flagged["flag_zero_or_negative"].mean()), 4),
            "overlap_share": round(float(flagged["flag_overlaps_next"].mean()), 4),
            "regression_share": round(float(flagged["flag_start_regression"].mean()), 4),
            "overshoot_share": round(float(flagged["flag_overshoot"].mean()), 4),
            "illegal_share": round(float(flagged["is_illegal"].mean()), 4),
            "flag_share_for_redecode": round(float(inv.mean()), 4),
        }
    # and the global answer: policies first, joint constrained solve last
    S, E = variants["P1_swap"]
    probe = df.assign(**{start: S, end: E}).dropna(subset=[start, end]).reset_index(drop=True)
    fixed: list[float] = []
    fixed_e: list[float] = []
    for _k, sub in probe.groupby([song_col], observed=True):
        idx = sub.index.to_numpy()
        pos = probe.index.get_indexer(idx)
        a, b, _rep = J.solve_block(sub[start].to_numpy(dtype=float), sub[end].to_numpy(dtype=float),
                                   audio_dur=float(np.nanmax(pd.to_numeric(
                                       sub.get("audio_duration_sec"), errors="coerce").to_numpy(dtype=float))
                                       if "audio_duration_sec" in sub else None)
                                   if "audio_duration_sec" in probe else None)
        fixed.append(pd.Series(a, index=pos))
        fixed_e.append(pd.Series(b, index=pos))
    if fixed:
        Sf = pd.concat(fixed).sort_index().to_numpy(dtype=float)
        Ef = pd.concat(fixed_e).sort_index().to_numpy(dtype=float)
        probe2 = probe.assign(**{start: Sf, end: Ef})
        flagged = SC.flag_violations(probe2.dropna(subset=[start, end]))
        out["policies"]["P1_swap_then_joint_solve"] = {
            "degenerate_share": round(float(flagged["flag_zero_or_negative"].mean()), 4),
            "overlap_share": round(float(flagged["flag_overlaps_next"].mean()), 4),
            "regression_share": round(float(flagged["flag_start_regression"].mean()), 4),
            "overshoot_share": round(float(flagged["flag_overshoot"].mean()), 4),
            "illegal_share": round(float(flagged["is_illegal"].mean()), 4),
            "median_shift_vs_shipped_sec": round(float(np.median(np.abs(Sf - s0) + np.abs(Ef - e0)) / 2), 4),
        }
    return out
