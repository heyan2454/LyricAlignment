"""Offline cleanup-rule simulation on real songs, judged structurally (no ground truth).

Round 6 established that the shipped cleanup reaches a clean structure by collapsing units to zero
length (11.2% degenerate before -> 17.1% after on 25 real songs).  Before proposing a replacement
rule, the candidate rules can be compared offline on two GT-free axes:

* **structural outcome**: degenerate share, adjacent-overlap share, start regression;
* **destruction proxy**: how much measured interval mass disappears, and how much of the movement is
  imposed on boundaries the decoder was *confident* about (low entropy) while the less confident side
  was left alone -- the second is the one a real system could act on without labels.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

MIN_DUR_SEC = 0.05
PLAUSIBLE_MAX_SEC = 3.0        # a lyric unit longer than this is a decoding defect, not content
EPS = 1e-9


def _as_2d(s: np.ndarray, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(s, dtype=float).copy(), np.asarray(e, dtype=float).copy()


def rule_none(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    return _as_2d(s, e)


def rule_shipped(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """The recorded post-cleanup output (passed in via ctx["target"])."""
    return _as_2d(ctx["target"][0], ctx["target"][1])


def rule_monotone_clamp(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Enforce non-decreasing starts and end>start without collapsing to zero length."""
    S, E = _as_2d(s, e)
    for i in range(len(S)):
        if E[i] <= S[i] + EPS:
            E[i] = S[i] + MIN_DUR_SEC
        if i and S[i] < S[i - 1]:
            shift = S[i - 1] - S[i]
            S[i], E[i] = S[i - 1], E[i] + shift
    return S, E


def rule_end_trim(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Resolve overlaps by trimming the earlier tail, never below MIN_DUR_SEC (round-2 V9)."""
    S, E = _as_2d(s, e)
    for i in range(len(S) - 2, -1, -1):
        if E[i] > S[i + 1] + EPS:
            E[i] = max(S[i + 1], S[i] + MIN_DUR_SEC)
        E[i] = max(E[i], S[i] + MIN_DUR_SEC if E[i] <= S[i] + EPS else E[i])
    return S, E


def rule_confidence_split(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Resolve an overlap by moving the *less confident* side further (no zero collapse)."""
    S, E = _as_2d(s, e)
    ent_e, ent_s = ctx["ent_end"], ctx["ent_start"]
    for i in range(len(S) - 1):
        ov = E[i] - S[i + 1]
        if ov <= EPS:
            continue
        a = float(ent_e[i] if np.isfinite(ent_e[i]) else 1.0)
        b = float(ent_s[i + 1] if np.isfinite(ent_s[i + 1]) else 1.0)
        tot = a + b
        w_a = a / tot if tot > EPS else 0.5            # higher entropy -> moves more
        E[i] = E[i] - ov * w_a
        S[i + 1] = S[i + 1] + ov * (1.0 - w_a)
        if E[i] <= S[i] + EPS:
            E[i] = S[i] + MIN_DUR_SEC
        if S[i + 1] > E[i + 1] - EPS:
            S[i + 1] = max(E[i + 1] - MIN_DUR_SEC, E[i])
    return S, E


def rule_trim_then_monotone(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Constructive candidate: pull overlapping tails back (never below MIN_DUR_SEC), then repair
    residual start regressions by shifting the offending unit forward.

    Order matters: trimming first means the monotone repair rarely has to move anything, so overlaps
    and regressions both go down without manufacturing zero-length units.
    """
    S, E = _as_2d(s, e)
    for i in range(len(S) - 1):
        if S[i + 1] < S[i] + EPS:                 # regression already present in raw
            S[i + 1] = S[i]
            E[i + 1] = max(E[i + 1], S[i + 1] + MIN_DUR_SEC)
        if E[i] > S[i + 1] + EPS:
            E[i] = max(S[i + 1], S[i] + MIN_DUR_SEC)
    for i in range(len(S)):                       # final structural guarantees
        if E[i] <= S[i] + EPS:
            E[i] = S[i] + MIN_DUR_SEC
        if i and S[i] < S[i - 1]:
            shift = S[i - 1] - S[i]
            S[i], E[i] = S[i - 1], E[i] + shift
    return S, E


def rule_clip_only(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Isolate the effect of the neutralisation step (no overlap resolution)."""
    S, E = _as_2d(s, e)
    dur = E - S
    med = float(np.median(dur[dur > EPS])) if np.any(dur > EPS) else MIN_DUR_SEC
    bad = dur <= EPS
    E[bad] = S[bad] + med
    long = (E - S) > PLAUSIBLE_MAX_SEC
    E[long] = S[long] + PLAUSIBLE_MAX_SEC
    return S, E


def rule_clip_then_trim(s: np.ndarray, e: np.ndarray, ctx: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Constructive candidate: neutralise gross raw intervals *first*, then trim overlaps.

    The two naive monotone repairs above (R2/R5) cascade because a single raw interval whose end sits
    seconds before its start poisons every subsequent unit once starts are force-ordered.  Clamping
    each unit to a plausible duration before resolving overlaps avoids the ratchet entirely.
    """
    S, E = _as_2d(s, e)
    dur = E - S
    med = float(np.median(dur[dur > EPS])) if np.any(dur > EPS) else MIN_DUR_SEC
    bad = dur <= EPS                                   # negative or zero raw interval
    E[bad] = S[bad] + med                              # re-anchor to a plausible length
    long = (E - S) > PLAUSIBLE_MAX_SEC
    E[long] = S[long] + PLAUSIBLE_MAX_SEC
    for i in range(len(S) - 2, -1, -1):                 # trim tails (never below MIN_DUR_SEC)
        if E[i] > S[i + 1] + EPS:
            E[i] = max(S[i + 1], S[i] + MIN_DUR_SEC)
    return S, E


RULES: dict[str, Callable] = {
    "R0_none": rule_none,
    "R1_shipped": rule_shipped,
    "R2_monotone_clamp": rule_monotone_clamp,
    "R3_end_trim_min0.05s": rule_end_trim,
    "R4_confidence_split": rule_confidence_split,
    "R5_trim_then_monotone": rule_trim_then_monotone,
    "R6_clip_then_trim": rule_clip_then_trim,
    "R7_clip_only": rule_clip_only,
}


def _structure(S: np.ndarray, E: np.ndarray, song: np.ndarray) -> dict[str, float]:
    dur = E - S
    deg = float(np.mean(dur <= 1e-6))
    neg = float(np.mean(dur < -1e-6))
    ds = np.array([S[i + 1] - S[i] if song[i + 1] == song[i] else np.nan
                   for i in range(len(S) - 1)], dtype=float)
    ov = np.array([E[i] - S[i + 1] if song[i + 1] == song[i] else np.nan
                   for i in range(len(S) - 1)], dtype=float)
    return {"degenerate_share": deg, "negative_share": neg,
            "overlap_share": float(np.nanmean(ov > 1e-3)),
            "start_regression_share": float(np.nanmean(ds < -1e-6)),
            "median_duration_sec": float(np.median(dur)),
            "max_duration_sec": float(np.nanmax(dur)) if dur.size else None,
            # raw mass is dominated by gross outliers (single units claiming >100 s), so the
            # destruction metric uses a capped, plausible mass instead of the raw sum
            "total_duration_sec_uncapped": float(np.nansum(np.maximum(dur, 0))),
            "plausible_mass_sec": float(np.nansum(np.clip(dur, 0, PLAUSIBLE_MAX_SEC))),
            "overshoot_units_share": float(np.mean(dur > PLAUSIBLE_MAX_SEC))}


def simulate(df: pd.DataFrame, view: str = "b4_60s_windowed") -> dict[str, Any]:
    s_col, e_col = f"{view}__rs", f"{view}__re"
    sel_s, sel_e = f"{view}__s", f"{view}__e"
    need = [s_col, e_col, sel_s, sel_e] + [f"{view}__ent_s", f"{view}__ent_e"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        return {"available": False, "reason": "missing columns", "missing": missing}
    d = df.dropna(subset=need).sort_values(["song", "unit_index"]).reset_index(drop=True)
    if d.empty:
        return {"available": False, "reason": "no complete rows"}
    s = d[s_col].to_numpy(dtype=float)
    e = d[e_col].to_numpy(dtype=float)
    song = d["song"].to_numpy()
    ctx = {"target": (d[sel_s].to_numpy(dtype=float), d[sel_e].to_numpy(dtype=float)),
           "ent_start": d[f"{view}__ent_s"].to_numpy(dtype=float),
           "ent_end": d[f"{view}__ent_e"].to_numpy(dtype=float)}
    base = _structure(s, e, song)
    out: dict[str, Any] = {"schema": "real_song_cleanup_simulation_v1", "view": view,
                           "units": int(len(d)), "min_duration_sec": MIN_DUR_SEC,
                           "raw_structure": base, "rules": {}}
    for name, fn in RULES.items():
        S, E = fn(s, e, ctx)
        st = _structure(S, E, song)
        shift = np.maximum(np.abs(S - s), np.abs(E - e))
        moved = shift > 1e-3
        # confidence accounting: how much movement lands on LOW-entropy (confident) boundaries?
        conf_share = None
        if moved.any():
            ent_end = np.where(np.isfinite(ctx["ent_end"]), ctx["ent_end"], np.nanmedian(ctx["ent_end"]))
            ent_start = np.where(np.isfinite(ctx["ent_start"]), ctx["ent_start"], np.nanmedian(ctx["ent_start"]))
            moved_end = np.abs(E - e) > 1e-3
            moved_start = np.abs(S - s) > 1e-3
            # share of moved boundaries that were already confident (entropy below median)
            all_ent = np.concatenate([ent_start, ent_end])
            med = float(np.median(all_ent))
            confident_moved = float(np.nansum((moved_end & (ent_end <= med)) * 1.0)
                                    + np.nansum((moved_start & (ent_start <= med)) * 1.0))
            total_moved = float(np.nansum(moved_end * 1.0) + np.nansum(moved_start * 1.0))
            conf_share = round(confident_moved / total_moved, 4) if total_moved else None
        out["rules"][name] = {
            **{k: round(v, 4) for k, v in st.items()},
            "plausible_mass_lost_share": round(
                1 - st["plausible_mass_sec"] / max(base["plausible_mass_sec"], 1e-9), 4),
            "duration_mass_lost_share_uncapped": round(
                1 - st["total_duration_sec_uncapped"] / max(base["total_duration_sec_uncapped"], 1e-9), 4),
            "share_units_moved": round(float(moved.mean()), 4),
            "median_shift_sec": round(float(np.median(shift[moved])), 4) if moved.any() else None,
            "p90_shift_sec": round(float(np.percentile(shift[moved], 90)), 4) if moved.any() else None,
            "share_moved_boundaries_that_were_confident": conf_share,
        }
    ranked = sorted(out["rules"].items(), key=lambda kv: kv[1]["degenerate_share"])
    out["ranking_by_degenerate_share"] = [k for k, _ in ranked]
    out["note"] = ("no ground truth on this data: these are structural and destruction-proxy "
                   "comparisons only; a rule that yields the fewest degenerate units is a candidate, "
                   "not a verified improvement")
    return out
