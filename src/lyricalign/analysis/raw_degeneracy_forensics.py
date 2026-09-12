"""Forensics on raw-stage negative/zero intervals: where they sit, what the decoder believed,
and whether they predict the later fixed-stage collapse.

Round 13 established that shipped real-song timelines contain ~10.8–12.4% degenerate intervals already
at the **raw** stage, of which ~870 are *negative* (end before start), and that the `fixed` stage then
pins blocks onto the owning window's `input_start_sec`.  Two questions decide what to do next:

* Is the raw negativity a systematic artifact (quantisation grid, window edges, unit type), or noise?
* Does it **predict** which units later get pinned/collapsed?  If it does, the decoder's own output
  carries a free trigger signal for the structural repair, and a targeted re-decode can be justified;
  if it does not, the two defects are independent and must be fixed separately.

All inputs are already-on-disk artifacts; no forwards, no ground truth needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RUNS = Path("/home/hyan/Data/lyricalign/runs")
ALIGN_RELPATH = Path("alignments/r2/vocal/windowed/alignment.json")
QUANTISATION_SEC = 0.08      # the decoder boundary grid seen in this project's Qwen-FA outputs


def _f(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def load_all_stages(batch: Path = RUNS / "20260814_ktv_current_silence",
                    relpath: Path = ALIGN_RELPATH) -> pd.DataFrame:
    """One row per (song, unit) with raw / fixed / selected / final boundaries and posteriors."""
    rows: list[dict[str, Any]] = []
    for d in sorted(p for p in batch.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        path = d / relpath
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        s = doc.get("summary") or {}
        trace = doc.get("window_trace") or []
        anchors = {int(w.get("window_index", i)): _f(w.get("input_start_sec"))
                   for i, w in enumerate(trace) if isinstance(w, dict)}
        committed = {int(w.get("window_index", i)):
                     (_f(w.get("committed_character_start")), _f(w.get("committed_character_end")))
                     for i, w in enumerate(trace) if isinstance(w, dict)}
        chars = doc.get("characters") or []
        for i, c in enumerate(chars):
            row = {"song": d.name, "language": str(s.get("language") or ""), "unit_index": i,
                   "text": str(c.get("character", "")), "unit_type": str(c.get("unit_type", "")),
                   "inference_source": str(c.get("inference_source", "")),
                   "audio_duration_sec": _f(s.get("audio_duration_sec")),
                   "n_windows": s.get("window_count"),
                   "owner_window_index": _f(c.get("owner_window_index")),
                   "raw_s": _f(c.get("raw_global_start_sec")), "raw_e": _f(c.get("raw_global_end_sec")),
                   "fixed_s": _f(c.get("fixed_global_start_sec", c.get("official_fixed_global_start_sec"))),
                   "fixed_e": _f(c.get("fixed_global_end_sec", c.get("official_fixed_global_end_sec"))),
                   "sel_s": _f(c.get("selected_start_sec")), "sel_e": _f(c.get("selected_end_sec")),
                   "fin_s": _f(c.get("start_sec")), "fin_e": _f(c.get("end_sec")),
                   "ent_s": _f(c.get("raw_start_entropy")), "ent_e": _f(c.get("raw_end_entropy")),
                   "mar_s": _f(c.get("raw_start_margin")), "mar_e": _f(c.get("raw_end_margin")),
                   "top1_s": _f(c.get("raw_top1_start_probability", c.get("raw_start_top1_probability"))),
                   "top1_e": _f(c.get("raw_end_top1_probability", c.get("raw_top1_end_probability")))}
            wi = row["owner_window_index"]
            row["window_input_anchor_sec"] = anchors.get(int(wi)) if wi is not None else None
            cs, ce = committed.get(int(wi), (None, None)) if wi is not None else (None, None)
            row["units_from_window_start"] = (i - cs) if cs is not None else None
            row["units_from_window_end"] = (ce - 1 - i) if ce is not None else None
            rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["raw_dur"] = df["raw_e"] - df["raw_s"]
    df["raw_negative"] = df["raw_dur"] < -1e-6
    df["raw_zero"] = (df["raw_dur"].abs() <= 1e-6)
    df["raw_degenerate"] = df["raw_negative"] | df["raw_zero"]
    df["fixed_degenerate"] = (df["sel_e"] - df["sel_s"]) <= 1e-6
    df["pinned_to_window_anchor"] = np.where(
        df["window_input_anchor_sec"].notna() & df["fixed_s"].notna(),
        (df["fixed_s"] - df["window_input_anchor_sec"]).abs() <= 1e-6, False)
    df["quantisation_multiple_of_grid"] = np.isfinite(df["raw_dur"]) & (
        (df["raw_dur"].abs() % QUANTISATION_SEC < 1e-6) |
        (QUANTISATION_SEC - df["raw_dur"].abs() % QUANTISATION_SEC < 1e-6))
    return df


def profile(df: pd.DataFrame) -> dict[str, Any]:
    """Distribution of the raw defects and what the decoder believed about them."""
    if df.empty:
        return {"units": 0, "songs": 0, "raw_negative_units": 0, "raw_zero_units": 0,
                "raw_negative_share": None, "by_language": {}, "by_unit_type": {},
                "by_inference_source": {}, "posteriors": {}}   # same key set as the populated path
    neg = df[df["raw_negative"]]
    out: dict[str, Any] = {"units": int(len(df)), "songs": int(df["song"].nunique()),
                           "raw_negative_units": int(len(neg)),
                           "raw_zero_units": int(df["raw_zero"].sum()),
                           # len(), not .size: DataFrame.size counts cells and would report >100%
                           "raw_negative_share": round(float(len(neg) / max(len(df), 1)), 4),
                           "by_language": {}, "by_unit_type": {}, "by_inference_source": {}}
    for label, sub in df.groupby("language", observed=True):
        n = sub[sub["raw_negative"]]
        out["by_language"][str(label)] = {
            "units": int(len(sub)), "negative": int(len(n)),
            "share": round(float(sub["raw_negative"].mean()), 4),
            "median_magnitude_sec": round(float(np.median(n["raw_dur"].abs())), 3) if len(n) else None,
            "worst_sec": round(float(n["raw_dur"].min()), 2) if len(n) else None,
            "pinned_share": round(float(n["pinned_to_window_anchor"].mean()), 4) if len(n) else None,
            "songs_affected": int(n["song"].nunique()),
        }
    for label, sub in df.groupby("unit_type", observed=True):
        out["by_unit_type"][str(label)] = {
            "units": int(len(sub)), "negative_share": round(float(sub["raw_negative"].mean()), 4),
            "zero_share": round(float(sub["raw_zero"].mean()), 4)}
    for label, sub in df.groupby("inference_source", observed=True):
        out["by_inference_source"][str(label)] = {
            "units": int(len(sub)), "negative_share": round(float(sub["raw_negative"].mean()), 4)}

    # magnitude shape: tiny sub-grid slips vs real reversals
    mags = neg["raw_dur"].abs().to_numpy(dtype=float)
    if mags.size:
        out["magnitude"] = {
            "le_grid_share": round(float(np.mean(mags <= QUANTISATION_SEC + 1e-9)), 4),
            "le_0.5s_share": round(float(np.mean(mags <= 0.5)), 4),
            "gt_1s_share": round(float(np.mean(mags > 1.0)), 4),
            "median_sec": round(float(np.median(mags)), 4),
            "p90_sec": round(float(np.percentile(mags, 90)), 3),
            "max_sec": round(float(mags.max()), 2),
            "share_on_0.08s_grid": round(float(df.loc[neg.index, "quantisation_multiple_of_grid"].mean()), 4),
        }
    # where inside the window do they sit?
    head = pd.cut(neg["units_from_window_start"].astype(float), [-0.5, 0.5, 2.5, 5.5, 1e9],
                  labels=["window 1st unit", "2nd-3rd", "4th-6th", "later"]) if len(neg) else None
    if head is not None and head.notna().any():
        tab = neg.assign(hb=head).groupby("hb", observed=True).size()
        base = df.assign(hb=pd.cut(df["units_from_window_start"].astype(float),
                                   [-0.5, 0.5, 2.5, 5.5, 1e9],
                                   labels=["window 1st unit", "2nd-3rd", "4th-6th", "later"]))
        tot = base.groupby("hb", observed=True).size()
        out["negative_by_window_position"] = {
            str(k): {"negatives": int(tab.get(k, 0)), "units": int(tot.get(k, 0)),
                     "share": round(float(tab.get(k, 0) / max(tot.get(k, 0), 1)), 4)}
            for k in ["window 1st unit", "2nd-3rd", "4th-6th", "later"]}
    # what the decoder believed: compare posterior quantities on degenerate vs clean units
    def _stat(sub: pd.DataFrame, col: str) -> dict[str, float] | None:
        v = pd.to_numeric(sub[col], errors="coerce").to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if v.size < 20:
            return None
        return {"n": int(v.size), "median": round(float(np.median(v)), 4),
                "mean": round(float(np.mean(v)), 4)}

    clean = df[~df["raw_degenerate"]]
    out["posteriors"] = {}
    for col in ("ent_s", "ent_e", "mar_s", "mar_e", "top1_s", "top1_e"):
        out["posteriors"][col] = {"raw_negative": _stat(neg, col), "clean": _stat(clean, col)}
    return out


def predicts_collapse(df: pd.DataFrame) -> dict[str, Any]:
    """Is raw degeneracy a leading indicator of the fixed-stage pin/collapse?"""
    if df.empty or "raw_negative" not in df:
        return {"available": False}
    have = df[df["window_input_anchor_sec"].notna() & df["fixed_s"].notna()].copy()
    if have.empty:
        return {"available": False}
    def rate(mask: np.ndarray, col: str) -> dict[str, Any]:
        sub = have[mask]
        return {"units": int(len(sub)),
                "pinned_share": round(float(sub["pinned_to_window_anchor"].mean()), 4),
                "fixed_degenerate_share": round(float(sub["fixed_degenerate"].mean()), 4)}
    out = {
        "available": True, "units": int(len(have)),
        "raw_degenerate": rate(have["raw_degenerate"].to_numpy(dtype=bool), "pinned"),
        "raw_clean": rate((~have["raw_degenerate"]).to_numpy(dtype=bool), "pinned"),
        "raw_negative_only": rate(have["raw_negative"].to_numpy(dtype=bool), "pinned"),
    }
    a = out["raw_degenerate"]
    b = out["raw_clean"]
    out["lift_pinned"] = round(a["pinned_share"] / max(b["pinned_share"], 1e-9), 3)
    out["lift_fixed_degenerate"] = round(a["fixed_degenerate_share"] /
                                         max(b["fixed_degenerate_share"], 1e-9), 3)
    # how much of the collapse is explained by raw degeneracy at all
    collapsed = have[have["fixed_degenerate"]]
    out["collapse_explained_by_raw_degeneracy"] = {
        "collapsed_units": int(len(collapsed)),
        "were_already_raw_degenerate": int(collapsed["raw_degenerate"].sum()),
        "share": round(float(collapsed["raw_degenerate"].mean()), 4),
    }
    # forward test: does raw degeneracy predict collapse *within the same song* beyond base rate?
    per_song = []
    for song, sub in have.groupby("song", observed=True):
        deg = sub[sub["raw_degenerate"]]
        cln = sub[~sub["raw_degenerate"]]
        if len(deg) >= 5 and len(cln) >= 5:
            per_song.append({"song": str(song),
                             "deg_collapse": float(deg["fixed_degenerate"].mean()),
                             "clean_collapse": float(cln["fixed_degenerate"].mean()),
                             "n_deg": int(len(deg))})
    if per_song:
        wins = sum(1 for r in per_song if r["deg_collapse"] > r["clean_collapse"])
        out["per_song_direction"] = {
            "songs_tested": len(per_song), "songs_where_degenerate_worse": wins,
            "share": round(wins / len(per_song), 3)}
    return out


def top_examples(df: pd.DataFrame, k: int = 12) -> list[dict[str, Any]]:
    """Concrete negative-duration examples (largest reversals) for the report."""
    if df.empty or "raw_negative" not in df:
        return []
    neg = df[df["raw_negative"]].copy()
    if neg.empty:
        return []
    neg = neg.sort_values("raw_dur")
    return [{"song": str(r.song), "language": str(r.language), "unit_index": int(r.unit_index),
             "text": str(r.text)[:8], "unit_type": str(r.unit_type),
             "raw": [r.raw_s, r.raw_e], "raw_dur_sec": round(float(r.raw_dur), 3),
             "sel": [r.sel_s, r.sel_e],
             "pinned": bool(r.pinned_to_window_anchor),
             "ent_max": None if not np.isfinite(max(r.ent_s or -1, r.ent_e or -1))
             else round(float(max(r.ent_s or -1, r.ent_e or -1)), 3)}
            for r in neg.head(k).itertuples()]
