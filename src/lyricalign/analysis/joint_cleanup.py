"""Joint constrained cleanup: one solve instead of a chain of if-else repairs.

Rationale (2026-09-12, rounds 2/6).  The shipped cleanup reaches a structurally clean result only by
collapsing units (11.2% -> 17.1% degenerate on 25 real songs, 33% of plausible interval mass lost),
round 6 showed that every *sequential* repair either leaves structure broken (tail trimming) or
cascades catastrophically (naive monotone force-ordering: 97.9% of units moved).  The whole question
is therefore a constrained optimisation over the sequence, and it is small enough to solve exactly:

    variables   S_i, E_i              (start/end of every unit, per song/window)
    constraints S_i <= S_{i+1}                          (no start regression)
                E_i >= S_i + min_dur                    (never degenerate)
                E_i <= S_{i+1}                          (no overlap)
                0 <= S_i, E_i <= audio_duration         (stay inside the recording)
                E_i <= S_i + max_dur                    (a unit cannot own more than max_dur)
    objective   min sum_i  ws_i*|S_i - s_i| + we_i*|E_i - e_i|

with `s/e` the *clipped* raw boundaries and weights derived from the decoder's own boundary entropy:
a boundary the model was confident about is expensive to move, an unsure one is cheap.  Weighted L1
with linear constraints is a linear program, solved by HiGHS through ``scipy.optimize.linprog``.

Two things this deliberately does not claim: it is not tuned on ground truth (the weights come from
recorded posteriors only), and structure-only improvement is not accuracy — hence
``evaluate_against_ground_truth`` exists and is reported separately from the structural metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

MIN_DUR_SEC = 0.05
MAX_DUR_SEC = 3.0
CONFIDENCE_ALPHA = 4.0          # how strongly low entropy protects a boundary


@dataclass
class SolveReport:
    n_units: int
    status: str
    moved: float
    cost: float
    fallback: bool = False


def _weights(ent: np.ndarray, alpha: float) -> np.ndarray:
    """Weight per boundary: low entropy (confident) -> high weight, scaled by rank within the block."""
    ent = np.asarray(ent, dtype=float)
    w = np.ones_like(ent, dtype=float)
    ok = np.isfinite(ent)
    if ok.sum() >= 3:
        ranks = np.empty(ent.shape, dtype=float)
        order = np.argsort(np.where(ok, ent, np.inf), kind="mergesort")
        ranks[order] = np.linspace(0.0, 1.0, num=int(ent.size), dtype=float)
        q = np.where(ok, ranks, 0.5)                     # 0 = most confident
        w = np.where(ok, 1.0 + alpha * (1.0 - q), 1.0)
    return w


def solve_block(s: Sequence[float], e: Sequence[float], *, ent_start: Sequence[float] | None = None,
                ent_end: Sequence[float] | None = None, min_dur: float = MIN_DUR_SEC,
                max_dur: float = MAX_DUR_SEC, audio_dur: float | None = None,
                alpha: float = CONFIDENCE_ALPHA, solve_cap: int = 4000,
                overlap_slack_sec: float = 0.0
                ) -> tuple[np.ndarray, np.ndarray, SolveReport]:
    """Exact joint solve for one sequence (song or window); falls back to clipping on failure."""
    s = np.asarray(s, dtype=float)
    e = np.asarray(e, dtype=float)
    n = int(s.size)
    if n == 0:
        return s.copy(), e.copy(), SolveReport(0, "empty", 0.0, 0.0)

    # pre-clip so the LP target is a plausible interval (never preserves a 100 s unit)
    s_t = np.clip(s, 0.0, None)
    e_t = s_t + np.clip(e - s, min_dur, max_dur)
    if audio_dur:
        s_t = np.clip(s_t, 0.0, max(0.0, audio_dur - min_dur))
        e_t = np.clip(e_t, min_dur, audio_dur)

    if n > solve_cap:
        S, E = s_t.copy(), e_t.copy()
        return S, E, SolveReport(n, "too_large_for_exact_solve", 0.0, 0.0, fallback=True)

    es = np.asarray(ent_start, dtype=float) if ent_start is not None else np.zeros(n)
    ee = np.asarray(ent_end, dtype=float) if ent_end is not None else np.zeros(n)
    ws = _weights(es, alpha)
    we = _weights(ee, alpha)

    # variables: S(n), E(n), u(n), v(n)
    N = 4 * n
    # only the deviation variables (u, v) carry cost; putting weight on S/E themselves makes the
    # objective prefer boundaries near zero, which silently collapses the whole sequence
    c = np.concatenate([np.zeros(2 * n), ws, we])
    bounds: list[tuple[float, float]] = []
    hi_s = (audio_dur - min_dur) if audio_dur else None
    for i in range(n):
        bounds.append((0.0, hi_s) if hi_s else (0.0, None))
    for i in range(n):
        bounds.append((0.0, audio_dur if audio_dur else None))
    bounds += [(0.0, None)] * (2 * n)

    rows: list[np.ndarray] = []
    rhs: list[float] = []

    def add(coef: dict[int, float], rhs_val: float) -> None:
        row = np.zeros(N)
        for k, vv in coef.items():
            row[k] = vv
        rows.append(row)
        rhs.append(rhs_val)

    for i in range(n):
        # |S_i - s_i| <= u_i   <=>   S_i - u_i <= s_i  and  -S_i - u_i <= -s_i
        add({i: 1.0, 2 * n + i: -1.0}, s_t[i])
        add({i: -1.0, 2 * n + i: -1.0}, -s_t[i])
        # |E_i - e_i| <= v_i   <=>   E_i - v_i <= e_i  and  -E_i - v_i <= -e_i
        add({n + i: 1.0, 3 * n + i: -1.0}, e_t[i])
        add({n + i: -1.0, 3 * n + i: -1.0}, -e_t[i])
        # E_i >= S_i + min_dur  ->  S_i - E_i <= -min_dur
        add({i: 1.0, n + i: -1.0}, -min_dur)
        # E_i <= S_i + max_dur  ->  E_i - S_i <= max_dur
        add({i: -1.0, n + i: 1.0}, max_dur)
        if i + 1 < n:
            # S_{i+1} >= S_i
            add({i: 1.0, i + 1: -1.0}, 0.0)
            # E_i <= S_{i+1} + slack  (slack > 0 admits genuine overlap, e.g. long-form sustain)
            add({n + i: 1.0, i + 1: -1.0}, float(overlap_slack_sec))
        if audio_dur:
            add({n + i: 1.0}, audio_dur)                  # E_i <= audio_dur

    from scipy.optimize import linprog
    res = linprog(c, A_ub=np.asarray(rows, dtype=float), b_ub=np.asarray(rhs, dtype=float),
                  bounds=bounds, method="highs")
    if not res.success:
        S, E = s_t.copy(), e_t.copy()
        return S, E, SolveReport(n, f"lp_failed:{res.message}", 0.0, 0.0, fallback=True)
    S = np.clip(res.x[:n], 0.0, None)
    E = np.clip(res.x[n:2 * n], S + min_dur, None)
    moved = float(np.mean(np.maximum(np.abs(S - s), np.abs(E - e)) > 1e-3))
    return S, E, SolveReport(n, "ok", moved, float(res.fun))


def solve_frame(df, *, s_col: str, e_col: str, ent_s_col: str | None = None,
                ent_e_col: str | None = None, group_cols: Sequence[str] = ("song",),
                dur_col: str | None = None, min_dur: float = MIN_DUR_SEC,
                max_dur: float = MAX_DUR_SEC, alpha: float = CONFIDENCE_ALPHA,
                overlap_slack_sec: float = 0.0
                ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Apply :func:`solve_block` per group and return aligned (S, E) arrays plus solve stats."""
    import pandas as pd

    S = np.full(len(df), np.nan)
    E = np.full(len(df), np.nan)
    n_fallback = 0
    statuses: dict[str, int] = {}
    for _key, idx in df.groupby(list(group_cols), observed=True).groups.items():
        pos = df.index.get_indexer(pd.Index(idx))
        sub = df.iloc[pos]
        dur = None
        if dur_col and dur_col in sub:
            vals = sub[dur_col].to_numpy(dtype=float)
            dur = float(np.nanmax(vals)) if np.isfinite(vals).any() else None
        s_arr, e_arr, rep = solve_block(
            sub[s_col].to_numpy(dtype=float), sub[e_col].to_numpy(dtype=float),
            ent_start=sub[ent_s_col].to_numpy(dtype=float) if ent_s_col else None,
            ent_end=sub[ent_e_col].to_numpy(dtype=float) if ent_e_col else None,
            min_dur=min_dur, max_dur=max_dur, audio_dur=dur, alpha=alpha,
            overlap_slack_sec=overlap_slack_sec)
        S[pos] = s_arr
        E[pos] = e_arr
        statuses[rep.status] = statuses.get(rep.status, 0) + 1
        n_fallback += int(rep.fallback)
    return S, E, {"groups": len(statuses) and sum(statuses.values()), "statuses": statuses,
                  "fallbacks": n_fallback}


def structure_metrics(S: np.ndarray, E: np.ndarray, groups: np.ndarray,
                      *, min_dur: float = 1e-6) -> dict[str, float]:
    """Degeneracy / overlap / regression rates that need no ground truth."""
    dur = E - S
    ov, rg = [], []
    order = np.arange(S.size)
    for _g, idx in _group_indices(groups, order):
        s_b, e_b = S[idx], E[idx]
        if s_b.size > 1:
            ov.append(e_b[:-1] - s_b[1:])
            rg.append(np.diff(s_b))
    ov_arr = np.concatenate(ov) if ov else np.array([np.nan])
    rg_arr = np.concatenate(rg) if rg else np.array([np.nan])
    return {
        "units": int(S.size),
        "degenerate_share": round(float(np.mean(dur <= min_dur)), 4),
        "negative_share": round(float(np.mean(dur < -1e-6)), 4),
        "overlap_share": round(float(np.nanmean(ov_arr > 1e-3)), 4),
        "start_regression_share": round(float(np.nanmean(rg_arr < -1e-6)), 4),
        "max_duration_sec": round(float(np.nanmax(dur)), 3),
        "median_duration_sec": round(float(np.nanmedian(dur)), 4),
        "plausible_mass_sec": round(float(np.nansum(np.clip(dur, 0, MAX_DUR_SEC))), 2),
    }


def _group_indices(groups: np.ndarray, order: np.ndarray):
    import pandas as pd

    ser = pd.Series(order)
    key = pd.Series(groups)
    for _k, sub in ser.groupby(key.values, observed=True):
        yield _k, sub.to_numpy()


def evaluate_against_ground_truth(S: np.ndarray, E: np.ndarray,
                                  gt_s: np.ndarray, gt_e: np.ndarray,
                                  tolerances: Sequence[float] = (0.1, 0.2, 0.25)
                                  ) -> dict[str, float]:
    es = np.abs(S - gt_s)
    ee = np.abs(E - gt_e)
    both = np.maximum(es, ee)
    out: dict[str, float] = {
        "units": int(both.size),
        "mae_start_sec": round(float(es.mean()), 4),
        "mae_end_sec": round(float(ee.mean()), 4),
        "mae_both_sec": round(float(both.mean()), 4),
        "median_both_sec": round(float(np.median(both)), 4),
        "mean_iou": round(float(_iou(S, E, gt_s, gt_e).mean()), 4),
    }
    for tol in tolerances:
        out[f"hit{int(round(tol * 1000))}"] = round(float(np.mean(both <= tol + 1e-9)), 4)
    return out


def _iou(S: np.ndarray, E: np.ndarray, gs: np.ndarray, ge: np.ndarray) -> np.ndarray:
    inter = np.clip(np.minimum(E, ge) - np.maximum(S, gs), 0, None)
    union = np.maximum(E, ge) - np.minimum(S, gs)
    return np.where(union > 1e-9, inter / np.maximum(union, 1e-9), 0.0)
