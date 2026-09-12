"""What is a re-decode budget actually worth?  Bound it with reachability, not hope.

To ask for GPU time one number matters: how many points of end accuracy can a given review budget buy.
A naive answer ("re-decode the flagged units and they become correct") overstates the value, because
round 19 showed that for 40 % of long-note endings the ground-truth bin is not even among the
decoder's top-2 candidates — a fresh decode of the same window can still miss it.

So two bounds are reported per budget:

* **optimistic bound** — every selected unit is repaired;
* **reachable bound** — only units whose ground-truth start *and* end bins are within one bin of the
  top-1 or top-2 candidate class can be repaired (round 19/21's containment evidence).

Each is evaluated for three selection policies at the same budget: the fused free trigger
(round 27), random selection, and a perfect oracle that knows the errors. The gap between the fused
trigger and the oracle is the headroom left for better triggers; the gap between the two bounds is
the part no re-decode of the same evidence can recover.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

STEP_SEC = 0.08
TOL_SEC = 0.1
BUDGETS = (0.05, 0.10, 0.20)


def reachability(frame: pd.DataFrame, *, end_bin_col: str = "pred_end_bin",
                 second_col: str = "raw_top2cls_end", gt_bin_col: str = "gt_end_bin"
                 ) -> dict[str, Any]:
    """Share of units whose ground truth is within one bin of the top-1 or top-2 candidate."""
    need = (end_bin_col, second_col, gt_bin_col)
    missing = [c for c in need if c not in frame.columns]
    if missing:
        return {"available": False, "missing_columns": missing}
    a = pd.to_numeric(frame[end_bin_col], errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(frame[second_col], errors="coerce").to_numpy(dtype=float)
    g = pd.to_numeric(frame[gt_bin_col], errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(g)
    if not ok.any():
        return {"available": False}
    near = (np.abs(a - g) <= 1) | (np.abs(b - g) <= 1)
    return {"available": True, "units": int(ok.sum()),
            "reachable_share": round(float(near[ok].mean()), 4),
            "unreachable_share": round(float(1.0 - near[ok].mean()), 4)}


def bound_budget_value(d: pd.DataFrame, *, score_col: str, err_col: str = "both_abs_err_sec",
                       fixable_col: str = "fixable", tol_sec: float = TOL_SEC,
                       budgets: tuple[float, ...] = BUDGETS,
                       rng_seed: int = 20260912) -> dict[str, Any]:
    """Δ hit@tol per budget for trigger / random / oracle selection, under both bounds."""
    x = d.dropna(subset=[score_col, err_col]).copy()
    n = len(x)
    if n < 100:
        return {"available": False, "units": n}
    err = x[err_col].to_numpy(dtype=float)
    fixable = x[fixable_col].to_numpy(dtype=bool)
    wrong = err > tol_sec
    base_hit = round(float(1.0 - wrong.mean()), 4)
    score = x[score_col].to_numpy(dtype=float)
    order_trigger = np.argsort(-score)
    # two different ceilings: ranking by error size (the optimistic bound's ceiling) and ranking by
    # "wrong AND recoverable" (the right ceiling once reachability is credited). An earlier draft
    # reported only the first, which made a good trigger look like it "beat the oracle" (capture > 1)
    # exactly on the strata where unreachability dominates.
    order_oracle_err = np.argsort(-err)
    order_oracle_fix = np.lexsort((-err, ~(wrong & fixable)))
    rng = np.random.default_rng(rng_seed)
    out: dict[str, Any] = {"available": True, "units": n, "tolerance_sec": tol_sec,
                           "baseline_hit": base_hit,
                           "wrong_units": int(wrong.sum()),
                           "wrong_but_unreachable": int((wrong & ~fixable).sum()),
                           "budgets": {}}
    for b in budgets:
        k = max(1, int(round(b * n)))
        res: dict[str, Any] = {"budget_units": k, "budget_pct": round(100 * b, 1)}
        for pol, order in (("fused_trigger", order_trigger),
                           ("oracle_by_error", order_oracle_err),
                           ("oracle_by_recoverable", order_oracle_fix),
                           ("random", rng.permutation(n))):
            sel = np.zeros(n, dtype=bool)
            sel[order[:k]] = True
            res[f"{pol}_optimistic_gain_pp"] = round(100.0 * float((sel & wrong).sum() / n), 2)
            res[f"{pol}_reachable_gain_pp"] = round(100.0 * float((sel & wrong & fixable).sum() / n), 2)
            res[f"{pol}_precision_on_wrong"] = round(float((sel & wrong).sum() / max(sel.sum(), 1)), 4)
            res[f"{pol}_reachable_share_of_selection"] = round(
                float((sel & wrong & fixable).sum() / max((sel & wrong).sum(), 1)), 4)
        out["budgets"][f"{int(b * 100)}pct"] = res
    # headroom summary at the largest budget
    big = out["budgets"][f"{int(max(budgets) * 100)}pct"]
    denom = max(big["oracle_by_recoverable_reachable_gain_pp"], 1e-9)
    out["headroom"] = {
        "trigger_capture_of_recoverable_oracle": round(
            big["fused_trigger_reachable_gain_pp"] / denom, 3),
        "trigger_vs_random_reachable_pp": round(
            big["fused_trigger_reachable_gain_pp"] - big["random_reachable_gain_pp"], 2),
        "recoverable_wrong_units": int((wrong & fixable).sum()),
        "unrecoverable_share_of_wrong_units": round(
            float((wrong & ~fixable).sum() / max(wrong.sum(), 1)), 4)}
    return out
