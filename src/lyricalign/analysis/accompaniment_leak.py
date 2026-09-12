"""Why does the accompanied domain end long notes *late*?  Test the accompaniment-bleed mechanism.

Round 21 measured a sign flip: on studio a-cappella data the aligner truncates sustained notes early
(end bias median −40 ms), while on real accompanied recordings the same stratum runs late (+32 ms,
74% late).  The obvious mechanism candidate is bleed: the Mandarin inputs in this project are
*channel-selected*, not source-separated (MIR-1K uses the extracted vocal channel of the original
stereo mix), so whatever the separator leaves in the vocal channel can keep the boundary decoder
firing after the lyric ends.

This module measures that, per unit: how much energy is in the accompaniment channel (and in the
vocal channel) at the ground-truth end versus at the predicted end, and specifically in the
over-extension region between them.  Paired within a unit, plus a control stratum of short notes
where no late bias exists.

Discipline: MIR-1K is test-only.  Everything here is a **retrospective mechanism measurement** — no
threshold, view or checkpoint is selected with it, and any shipped trigger based on these features
must be re-derived on non-test data first.  Zero GPU: audio is read with soundfile and reduced to
10 ms envelopes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lyricalign.analysis import tail_acoustics as TA

LEAD_SEC = 0.30           # window examined just after each boundary candidate


def _rms_at(t: np.ndarray, env: np.ndarray, at: float, half_width: float = 0.05) -> float:
    m = (t >= at - half_width) & (t <= at + half_width)
    return float(np.sqrt(np.mean(env[m] ** 2))) if m.any() else float("nan")


def unit_features(t: np.ndarray, vocal: np.ndarray, accomp: np.ndarray, *,
                  gt_end: float, pred_end: float, gt_start: float) -> dict[str, float]:
    """Bleed features at the two candidate boundaries and in the over-extension region."""
    lo, hi = min(gt_end, pred_end), max(gt_end, pred_end)
    accomp_at_gt = _rms_at(t, accomp, gt_end)
    accomp_at_pred = _rms_at(t, accomp, pred_end)
    vocal_at_gt = _rms_at(t, vocal, gt_end)
    vocal_at_pred = _rms_at(t, vocal, pred_end)
    lead = (t >= gt_end) & (t <= gt_end + LEAD_SEC)
    lead_accomp = float(np.sqrt(np.mean(accomp[lead] ** 2))) if lead.any() else float("nan")
    lead_vocal = float(np.sqrt(np.mean(vocal[lead] ** 2))) if lead.any() else float("nan")
    core = (t >= gt_start) & (t <= gt_end)
    core_accomp = float(np.sqrt(np.mean(accomp[core] ** 2))) if core.any() else float("nan")
    denom = lead_accomp + lead_vocal if np.isfinite(lead_accomp) else float("nan")
    return {
        "accomp_rms_at_gt_end": accomp_at_gt,
        "accomp_rms_at_pred_end": accomp_at_pred,
        "vocal_rms_at_gt_end": vocal_at_gt,
        "vocal_rms_at_pred_end": vocal_at_pred,
        "accomp_lead_rms": lead_accomp,
        "vocal_lead_rms": lead_vocal,
        "accomp_core_rms": core_accomp,
        # bleed share right after the lyric ends: the quantity a channel-select input cannot escape
        "accomp_share_in_lead": lead_accomp / denom if denom and np.isfinite(denom) else float("nan"),
        "accomp_ratio_pred_over_gt": (accomp_at_pred / accomp_at_gt)
        if accomp_at_gt and np.isfinite(accomp_at_gt) else float("nan"),
        "overextension_sec": hi - lo,
        "ends_late": float(pred_end > gt_end + 1e-6),
    }


def _paired_stats(diffs: np.ndarray) -> dict[str, Any]:
    d = diffs[np.isfinite(diffs)]
    if d.size == 0:
        return {"n": 0}
    pos = float(np.mean(d > 0))
    # rank-biserial correlation for the paired sign/magnitude pattern
    ranks = pd.Series(np.abs(d)).rank().to_numpy(dtype=float)
    r_pos = ranks[d > 0].sum()
    r_neg = ranks[d < 0].sum()
    n = d.size
    rb = (r_pos - r_neg) / (n * (n + 1) / 2.0)
    return {"n": int(n), "median_diff": round(float(np.median(d)), 5),
            "mean_diff": round(float(np.mean(d)), 5),
            "share_higher_in_pred": round(pos, 4),
            "rank_biserial": round(float(rb), 4),
            "sign_test_p_two_sided": round(float(_binom_two_sided(n, int((d > 0).sum()))), 6)}


def _binom_two_sided(n: int, k: int) -> float:
    """Two-sided exact binomial p-value against p=0.5 (scipy when present, else normal approx).

    An earlier version summed exact tails with ``2.0 ** n`` and overflowed at n ≈ 1000.
    """
    if n <= 0:
        return 1.0
    try:
        from scipy.stats import binomtest
        return float(binomtest(k, n, 0.5).pvalue)
    except Exception:
        from math import erf, sqrt
        z = (abs(k - n / 2.0) - 0.5) / sqrt(n / 4.0) if n > 0 else 0.0
        return max(0.0, min(1.0, 1.0 - erf(z / sqrt(2.0))))


def profile_leak(units: pd.DataFrame, stereo_dir: Path, *, tol_sec: float = 0.1) -> dict[str, Any]:
    """Paired bleed comparison on long notes (the biased stratum) and short notes (control)."""
    cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray] | None] = {}
    rows: list[dict[str, Any]] = []
    for r in units.itertuples():
        path = str(Path(stereo_dir) / f"{r.item_id}.wav")
        if path not in cache:
            cache[path] = TA.load_stereo_envelopes(path)
        env = cache[path]
        if env is None:
            continue
        t, vocal, accomp = env
        f = unit_features(t, vocal, accomp, gt_end=float(r.gt_end_sec),
                          pred_end=float(r.pred_end_sec), gt_start=float(r.gt_start_sec))
        f.update({"item_id": str(r.item_id), "character_index": int(r.character_index),
                  "gt_dur_sec": float(r.gt_dur_sec),
                  "end_err_signed_sec": float(r.pred_end_sec) - float(r.gt_end_sec),
                  "hit100": float(abs(float(r.pred_end_sec) - float(r.gt_end_sec)) <= tol_sec)})
        rows.append(f)
    if not rows:
        return {"available": False, "reason": "no readable stereo audio"}
    d = pd.DataFrame(rows)
    long_m = d["gt_dur_sec"] >= 1.0
    short_m = d["gt_dur_sec"] < 0.4
    out: dict[str, Any] = {"available": True, "units": int(len(d)),
                           "stereo_files_used": int(d["item_id"].nunique()),
                           "lead_window_sec": LEAD_SEC, "tolerance_sec": tol_sec,
                           "strata": {}}
    for name, mask in (("long_note", long_m), ("short_note", short_m), ("all_units",
                                                                        pd.Series(True, index=d.index))):
        sub = d[mask]
        if not len(sub):
            continue
        out["strata"][name] = {
            "units": int(len(sub)),
            "ends_late_share": round(float(sub["ends_late"].mean()), 4),
            "median_end_err_ms": round(float(np.median(sub["end_err_signed_sec"])) * 1000, 1),
            "hit100": round(float(sub["hit100"].mean()), 4),
            "accomp_at_pred_gt_than_at_gt": _paired_stats(
                (sub["accomp_rms_at_pred_end"] - sub["accomp_rms_at_gt_end"]).to_numpy(dtype=float)),
            "vocal_at_pred_gt_than_at_gt": _paired_stats(
                (sub["vocal_rms_at_pred_end"] - sub["vocal_rms_at_gt_end"]).to_numpy(dtype=float)),
            "median_accomp_share_in_lead": round(
                float(np.nanmedian(sub["accomp_share_in_lead"])), 4)
            if sub["accomp_share_in_lead"].notna().any() else None,
            "median_accomp_lead_rms": round(float(np.nanmedian(sub["accomp_lead_rms"])), 5)
            if sub["accomp_lead_rms"].notna().any() else None,
            "median_vocal_lead_rms": round(float(np.nanmedian(sub["vocal_lead_rms"])), 5)
            if sub["vocal_lead_rms"].notna().any() else None,
        }
    # does the size of the late error track the bleed level?  (correlation, long notes)
    ln = d[long_m]
    if len(ln) > 10:
        for col in ("accomp_share_in_lead", "accomp_rms_at_pred_end", "vocal_rms_at_pred_end"):
            v = pd.to_numeric(ln[col], errors="coerce").to_numpy(dtype=float)
            e = ln["end_err_signed_sec"].to_numpy(dtype=float)
            ok = np.isfinite(v) & np.isfinite(e)
            if ok.sum() > 10 and np.std(v[ok]) > 0:
                out["strata"]["long_note"][f"corr_end_err_vs_{col}"] = round(
                    float(np.corrcoef(v[ok], e[ok])[0, 1]), 4)
    # late units vs on-time units: is the lead region accompaniment-dominated?
    late = d["end_err_signed_sec"] > 0.1
    ontime = d["end_err_signed_sec"].abs() <= 0.05
    def _grp(mask): 
        v = pd.to_numeric(d.loc[mask, "accomp_share_in_lead"], errors="coerce").to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        return {"n": int(v.size), "median": round(float(np.median(v)), 4) if v.size else None,
                "p90": round(float(np.percentile(v, 90)), 4) if v.size else None}
    out["accomp_share_in_lead_by_outcome"] = {"late_gt100ms": _grp(late & long_m),
                                              "late_gt100ms_any_dur": _grp(late),
                                              "on_time": _grp(ontime)}
    # discriminative power of the bleed share for "lands late" — reported for the whole panel and for
    # the long-note stratum separately, because the two answer different questions: the first asks
    # whether bleed marks the error, the second whether it ranks errors *within* the stratum
    from lyricalign.realign_gate.gate_features import roc_auc
    share = pd.to_numeric(d["accomp_share_in_lead"], errors="coerce").to_numpy(dtype=float)
    lab = (d["end_err_signed_sec"] > 0.1).to_numpy(dtype=float)
    def _auc(mask):
        ok = mask & np.isfinite(share)
        if ok.sum() < 20 or lab[ok].sum() in (0, ok.sum()):
            return None
        v = roc_auc(lab[ok], share[ok])
        return None if v is None else round(float(v), 4)
    out["auc_bleed_share_predicts_late"] = {
        "all_units": _auc(np.ones(len(d), dtype=bool)),
        "long_note": _auc(long_m.to_numpy() if hasattr(long_m, "to_numpy") else long_m),
        "base_rate_late_all": round(float(lab.mean()), 4)}
    vrp = pd.to_numeric(d["vocal_rms_at_pred_end"], errors="coerce").to_numpy(dtype=float)
    errv = d["end_err_signed_sec"].to_numpy(dtype=float)
    ok = np.isfinite(vrp) & np.isfinite(errv)
    if ok.sum() > 20:
        out["corr_end_err_vs_vocal_rms_at_pred_end_all_units"] = round(
            float(np.corrcoef(errv[ok], vrp[ok])[0, 1]), 4)
    interesting = d[(d["gt_dur_sec"] >= 1.0) | (d["end_err_signed_sec"].abs() > 0.1)]
    out["per_unit"] = interesting.drop(columns=["item_id", "character_index"]).to_dict(orient="records")
    out["per_unit_note"] = ("features for long notes and units landing >100 ms off, "
                           f"{len(interesting)} rows; no audio is copied")
    out["caveat"] = ("retrospective mechanism measurement on test-only data; "
                     "no threshold or model was chosen with it")
    return out
