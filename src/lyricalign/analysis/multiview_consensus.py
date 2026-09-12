"""Offline simulation of multi-view consensus re-alignment on the MIR-1K natural panel.

The mainline asks whether re-aligning difficult regions (multiple crops/views, then a selection)
recovers accuracy that a single pass cannot reach.  Running new views costs GPU, but the retained
MIR-1K predictions already give five *independent inference configurations* of the same audio and
the same lyrics over human ground truth, which is a legitimate offline proxy for the selection step:
whatever the ensemble selection can buy here is an upper bound on what view-consensus can buy, and
whatever it cannot buy here is not worth paying GPU for.

Strategies are pre-registered here, then evaluated with the frozen tolerances (100/200/250 ms) and
reported with the *re-alignment budget* each one implies (share of units that a real system would
have to send through another forward):

* ``S0_single``          the reference predictor alone (status quo).
* ``S1_median_all``      median start / median end over all ensemble members.
* ``S2_trimmed_mean``    mean after dropping the extreme member on each side (needs >=5).
* ``S3_vote_bucket``     per-boundary mode of a 20 ms bucket (majority vote in time bins).
* ``S4_stability_gate``  keep the reference; replace only units whose spread exceeds a quantile.
* ``S5_gate_recompute``  like S4 but the fallback is the leave-one-out median of the others.
* ``S6_agreement_cluster`` mean of the largest cluster of members agreeing within 40 ms.
* ``S7_oracle_member``   pick the member with the smallest true error (upper bound, not deployable).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

BUCKET_SEC = 0.020
AGREE_SEC = 0.040
TOLS = (0.100, 0.200, 0.250)


def ensemble_frame(df: pd.DataFrame, members: list[str]) -> pd.DataFrame:
    """Wide per-unit frame: one column set per member, plus ground truth."""
    present = [m for m in members if m in set(df["predictor"])]
    if len(present) < 2:
        raise ValueError(f"need >=2 ensemble members, got {present}")
    wide = df[df["predictor"].isin(present)].pivot_table(
        index=["item_id", "character_index"], columns="predictor",
        values=["gt_start_sec", "gt_end_sec", "pred_start_sec", "pred_end_sec",
                "both_err", "hit100", "is_last_char", "is_first_char", "frac_pos",
                "gt_dur_sec", "item_duration_sec"],
        aggfunc="first")
    gt_s = wide["gt_start_sec"][present[0]].to_numpy(dtype=float)
    gt_e = wide["gt_end_sec"][present[0]].to_numpy(dtype=float)
    out = pd.DataFrame({
        "gt_start_sec": gt_s, "gt_end_sec": gt_e,
        "is_last_char": wide["is_last_char"][present[0]].to_numpy(dtype=float),
        "is_first_char": wide["is_first_char"][present[0]].to_numpy(dtype=float),
        "frac_pos": wide["frac_pos"][present[0]].to_numpy(dtype=float),
        "gt_dur_sec": wide["gt_dur_sec"][present[0]].to_numpy(dtype=float),
    }, index=wide.index)
    for m in present:
        out[f"{m}__s"] = wide["pred_start_sec"][m].to_numpy(dtype=float)
        out[f"{m}__e"] = wide["pred_end_sec"][m].to_numpy(dtype=float)
        out[f"{m}__err"] = wide["both_err"][m].to_numpy(dtype=float)
        out[f"{m}__hit"] = wide["hit100"][m].to_numpy(dtype=float)
    out.attrs["members"] = present
    return out


def _median(a: np.ndarray) -> np.ndarray:
    return np.nanmedian(a, axis=1)


def _trimmed_mean(a: np.ndarray) -> np.ndarray:
    if a.shape[1] < 5:
        return np.nanmean(a, axis=1)
    s = np.sort(a, axis=1)
    return np.nanmean(s[:, 1:-1], axis=1)


def _vote_bucket(a: np.ndarray, bucket: float = BUCKET_SEC) -> np.ndarray:
    """Per-row mode of the discretised boundary value (returns the bucket centre)."""
    res = np.full(a.shape[0], np.nan)
    for i, row in enumerate(a):
        v = row[np.isfinite(row)]
        if v.size == 0:
            continue
        b = np.round(v / bucket)
        vals, counts = np.unique(b, return_counts=True)
        best = vals[np.argmax(counts)]
        # tie-break toward the median of the tied buckets, then to the row median
        tied = vals[counts == counts.max()]
        if tied.size > 1:
            best = float(np.median(tied))
        res[i] = best * bucket if np.max(counts) > 1 else float(np.median(v))
    return res


def _agreement_weighted(a: np.ndarray, tol: float = AGREE_SEC) -> np.ndarray:
    """Mean of the largest agreement cluster (support-weighted, outlier-robust).

    The naive support-weighted *mean* is **not** robust: with five members a single gross outlier
    still carries weight 1/10 of a 5 s shift, which is enough to move the boundary by hundreds of
    milliseconds.  Averaging inside the best-supported cluster instead keeps the "how many peers
    agree" idea without letting one wild member drag the result.
    """
    res = np.full(a.shape[0], np.nan)
    for i, row in enumerate(a):
        v = row[np.isfinite(row)]
        if v.size == 0:
            continue
        support = np.array([np.sum(np.abs(v - x) <= tol) for x in v], dtype=float)
        seed = int(np.argmax(support))
        cluster = v[np.abs(v - v[seed]) <= tol]
        res[i] = float(np.mean(cluster)) if cluster.size else float(np.median(v))
    return res


def _profile(err_s: np.ndarray, err_e: np.ndarray, err_both: np.ndarray,
             mask: np.ndarray | None = None) -> dict[str, Any]:
    if mask is None:
        mask = np.ones(len(err_both), dtype=bool)
    s, e, b = err_s[mask], err_e[mask], err_both[mask]
    if s.size == 0:
        return {"n": 0}
    return {"n": int(s.size),
            "hit100": round(float((b <= TOLS[0]).mean()), 4),
            "hit200": round(float((b <= TOLS[1]).mean()), 4),
            "hit250": round(float((b <= TOLS[2]).mean()), 4),
            "mae_start": round(float(s.mean()), 4),
            "mae_end": round(float(e.mean()), 4),
            "median_both": round(float(np.median(b)), 4),
            "p90_both": round(float(np.percentile(b, 90)), 4)}


def simulate(wide: pd.DataFrame, reference: str | None = None,
             gate_quantiles: tuple[float, ...] = (0.5, 0.8, 0.9)) -> dict[str, Any]:
    members: list[str] = wide.attrs["members"]
    ref = reference if reference in members else max(
        members, key=lambda m: float(np.nanmean(wide[f"{m}__hit"])))
    gt_s = wide["gt_start_sec"].to_numpy(dtype=float)
    gt_e = wide["gt_end_sec"].to_numpy(dtype=float)
    S = np.column_stack([wide[f"{m}__s"].to_numpy(dtype=float) for m in members])
    E = np.column_stack([wide[f"{m}__e"].to_numpy(dtype=float) for m in members])
    ref_idx = members.index(ref)
    ref_s, ref_e = S[:, ref_idx].copy(), E[:, ref_idx].copy()
    ref_err = np.maximum(np.abs(ref_s - gt_s), np.abs(ref_e - gt_e))
    spread = np.nanmax(S, axis=1) - np.nanmin(S, axis=1)
    spread = np.maximum(spread, np.nanmax(E, axis=1) - np.nanmin(E, axis=1))

    out: dict[str, Any] = {"schema": "mir1k_multiview_consensus_v1",
                           "reference_predictor": ref, "members": members,
                           "n_units": int(len(wide)),
                           "honesty": "members are five independent inference configurations of the "
                                       "same audio+text, not different audio crops; treat as a proxy "
                                       "upper bound for view-consensus selection"}
    res: dict[str, Any] = {}

    def score(name: str, s: np.ndarray, e: np.ndarray, budget: float | None = None,
              note: str = "", deployable: bool = True) -> None:
        es = np.abs(s - gt_s)
        ee = np.abs(e - gt_e)
        eb = np.maximum(es, ee)
        entry: dict[str, Any] = _profile(es, ee, eb)
        entry["deployable"] = deployable
        if budget is not None:
            entry["realignment_budget"] = round(float(budget), 4)
        if note:
            entry["note"] = note
        # strata: last character, first character, unstable subset
        for label, mask in (("last_char", wide["is_last_char"].to_numpy(dtype=float) == 1),
                            ("first_char", wide["is_first_char"].to_numpy(dtype=float) == 1),
                            ("unstable_top20pct", spread >= np.nanquantile(spread, 0.8)),
                            ("long_note", wide["gt_dur_sec"].to_numpy(dtype=float) >= 1.0)):
            sub = _profile(es, ee, eb, mask)
            entry[f"stratum_{label}"] = {k: v for k, v in sub.items() if k in ("n", "hit100", "mae_end")}
        ref_hit_full = float(np.mean(ref_err <= TOLS[0]))
        entry["delta_hit100_pp_vs_reference"] = (
            round((entry["hit100"] - ref_hit_full) * 100, 3) if entry["n"] else None)
        # paired per-unit win/loss against the reference
        better = int(np.sum(eb < ref_err - 1e-6))
        worse = int(np.sum(eb > ref_err + 1e-6))
        entry["units_better_vs_ref"] = better
        entry["units_worse_vs_ref"] = worse
        res[name] = entry

    score("S0_single_reference", ref_s, ref_e, budget=0.0, note=f"{ref} alone (status quo)")
    score("S1_median_all", _median(S), _median(E), budget=1.0,
          note="recompute everything, keep the median")
    score("S2_trimmed_mean", _trimmed_mean(S), _trimmed_mean(E), budget=1.0,
          note="mean of inner members (drops one extreme per side)")
    score("S3_vote_bucket", _vote_bucket(S), _vote_bucket(E), budget=1.0,
          note=f"per-boundary majority inside {BUCKET_SEC * 1000:.0f}ms bins")
    score("S6_agreement_weighted", _agreement_weighted(S), _agreement_weighted(E), budget=1.0,
          note=f"mean of the largest agreement cluster (radius {AGREE_SEC * 1000:.0f}ms)")
    for q in gate_quantiles:
        thr = float(np.nanquantile(spread, q))
        gate = spread > thr
        mix_s, mix_e = ref_s.copy(), ref_e.copy()
        med_s, med_e = _median(S), _median(E)
        mix_s[gate] = med_s[gate]
        mix_e[gate] = med_e[gate]
        score(f"S4_gate_p{int(q * 100)}_median", mix_s, mix_e, budget=float(gate.mean()),
              note=f"spread>{thr * 1000:.0f}ms ({100 * gate.mean():.0f}% of units) replaced by median")
        loo_S = np.delete(S, ref_idx, axis=1)
        loo_E = np.delete(E, ref_idx, axis=1)
        l_s, l_e = _median(loo_S), _median(loo_E)
        mix_s2, mix_e2 = ref_s.copy(), ref_e.copy()
        mix_s2[gate] = l_s[gate]
        mix_e2[gate] = l_e[gate]
        score(f"S5_gate_p{int(q * 100)}_loo_median", mix_s2, mix_e2, budget=float(gate.mean()),
              note=f"reference kept elsewhere; unstable units use leave-one-out median "
                   f"(threshold {thr * 1000:.0f}ms)")
    errs = np.column_stack([wide[f"{m}__err"].to_numpy(dtype=float) for m in members])
    best_idx = np.nanargmin(errs, axis=1)
    pick_s = np.array([S[i, best_idx[i]] for i in range(len(S))])
    pick_e = np.array([E[i, best_idx[i]] for i in range(len(E))])
    score("S7_oracle_member_pick", pick_s, pick_e, budget=1.0,
          note="upper bound: per unit pick the member with the smallest true error (uses GT)",
          deployable=False)
    out["strategies"] = res

    # marginal value of the *selection* step: how much of the oracle gap does consensus close?
    ref_hit = float(np.mean(ref_err <= 0.1))
    best_deployable = max((v["hit100"] for k, v in res.items()
                           if v.get("deployable") and v["n"] > 0 and not k.startswith("S0")),
                          default=ref_hit)
    oracle = res["S7_oracle_member_pick"]["hit100"]
    out["summary"] = {
        "reference_hit100": round(ref_hit, 4),
        "best_deployable_hit100": round(best_deployable, 4),
        "oracle_hit100": round(oracle, 4),
        "gap_closed_by_consensus_share": (round((best_deployable - ref_hit) / max(oracle - ref_hit, 1e-9), 3)
                                          if oracle > ref_hit else None),
        "budget_for_best": min([v.get("realignment_budget", 1.0) for v in res.values()
                                if v.get("deployable") and v.get("hit100") == best_deployable],
                               default=None),
        "interpretation": "compare only the *marginal* gain against the re-alignment budget; a "
                          "strategy that reaches the oracle only by recomputing everything is not a "
                          "win over simply trusting the single pass",
    }
    return out
