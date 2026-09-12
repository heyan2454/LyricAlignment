"""Time-local accompaniment leakage in the separated vocal stem, measured at shipped boundaries.

Correction recorded 2026-09-12 (round 23): the real-song batches do **not** feed the aligner a
channel-selected mix — `work/audio/vocals.identity.json` says `qwen_fa_batch_demucs_v1`,
separator `demucs`, model `htdemucs_ft`, `two_stems=vocals`, and the batch also writes
`accompaniment.wav` plus a global `separation_quality.json` (`audio_separation_quality_v1`, with a
pass/fail gate).  So separation *is* used and *is* quality-checked — but only as whole-file
statistics (RMS, correlation, reconstruction residual).  What has never been measured is whether the
separator leaves accompaniment energy in the vocal stem **exactly where a sustained note ends**,
which is the region round 22 implicated in the accompanied-domain late-end bias.

This module measures that, per unit, using the accompaniment stem as the reference signal:

* ``vocal_lead_over_core`` — how much the vocal stem keeps sounding after the unit ends;
* ``leak_track_corr`` — whether that residual tracks the accompaniment stem across units of the same
  song (high correlation ⇒ the residual is leakage; low ⇒ it is the voice's own tail/reverb);
* prevalence of boundaries whose following region is dominated by residual vocal-stem energy.

Everything is reference-free and uses non-test product data (the 33 real accompanied songs); no
ground truth and no new forwards are involved, and audio is only read, never copied.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import soundfile as sf

HOP_SEC = 0.01
WIN_SEC = 0.025
LEAD_SEC = 0.30
RESIDUAL_ACTIVE_RMS = 0.02        # absolute floor, kept only to exclude digital silence
RESIDUAL_RELATIVE_ACTIVE = 0.25   # scale-free: residual >= 25 % of the unit's own core energy


def _envelope(path: str, target_sr: int = 16000) -> tuple[np.ndarray, np.ndarray] | None:
    """Mono RMS envelope at 10 ms hops (resampled with a cheap block mean to keep this CPU-light)."""
    try:
        info = sf.info(path)
    except Exception:
        return None
    sr = info.samplerate
    x, sr2 = sf.read(path, dtype="float32", always_2d=True)
    mono = x.mean(axis=1).astype(np.float64)
    if sr2 != target_sr:
        factor = int(round(sr2 / target_sr))
        if factor * sr2 / sr2 >= 1 and mono.size >= factor:
            n = mono.size // factor
            mono = mono[: n * factor].reshape(n, factor).mean(axis=1)
    win = max(1, int(round(WIN_SEC * target_sr)))
    hop = max(1, int(round(HOP_SEC * target_sr)))
    n_frames = 1 + max(0, (mono.size - win) // hop)
    if n_frames <= 1:
        return None
    idx = np.arange(win)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = mono[idx]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    t = (np.arange(n_frames) * hop + win / 2) / float(target_sr)
    return t, rms


def _rms_in(t: np.ndarray, env: np.ndarray, lo: float, hi: float) -> float:
    m = (t >= lo) & (t <= hi)
    return float(np.sqrt(np.mean(env[m] ** 2))) if m.any() else float("nan")


MIN_GAP_SEC = 0.05


def measure_song(units: pd.DataFrame, stems: dict[str, str], *,
                 lead_sec: float = LEAD_SEC) -> dict[str, Any]:
    """Per-unit residual/leakage features at the shipped end boundary of each unit.

    Two windows are measured on purpose.  The naive ``[end, end+lead]`` window is usually *inside the
    next unit* because lyric units are contiguous, so energy there says nothing about tails or
    leakage; the informative one is the **gap** ``[end, min(end+lead, next_start)]`` restricted to
    gaps long enough to measure (>= MIN_GAP_SEC).  Both are reported so the confound is visible.
    """
    voc = _envelope(stems["vocals"])
    acc = _envelope(stems["accompaniment"])
    if voc is None or acc is None:
        return {"available": False, "reason": "stems unreadable"}
    (vt, venv), (at, aenv) = voc, acc
    arr = units.reset_index(drop=True)
    nxt = arr["start_sec"].shift(-1).to_numpy(dtype=float)
    same_song = np.ones(len(arr), dtype=bool)
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(arr.itertuples()):
        if not np.isfinite(r.start_sec) or not np.isfinite(r.end_sec):
            continue
        v_core = _rms_in(vt, venv, r.start_sec, r.end_sec)
        v_lead = _rms_in(vt, venv, r.end_sec, r.end_sec + lead_sec)
        a_core = _rms_in(at, aenv, r.start_sec, r.end_sec)
        a_lead = _rms_in(at, aenv, r.end_sec, r.end_sec + lead_sec)
        gap_hi = min(float(r.end_sec) + lead_sec, float(nxt[i])) if np.isfinite(nxt[i]) \
            else float(r.end_sec) + lead_sec
        gap = gap_hi - float(r.end_sec)
        v_gap = _rms_in(vt, venv, r.end_sec, gap_hi) if gap >= MIN_GAP_SEC else float("nan")
        a_gap = _rms_in(at, aenv, r.end_sec, gap_hi) if gap >= MIN_GAP_SEC else float("nan")
        rows.append({"unit_index": int(r.unit_index),
                     "gap_sec": round(float(gap), 4), "gap_measurable": bool(gap >= MIN_GAP_SEC),
                     "vocal_gap": v_gap, "accomp_gap": a_gap,
                     "language": str(r.language), "pred_dur_sec": float(r.end_sec - r.start_sec),
                     "vocal_core": v_core, "vocal_lead": v_lead,
                     "accomp_core": a_core, "accomp_lead": a_lead,
                     "vocal_lead_over_core": v_lead / v_core if v_core else float("nan"),
                     "accomp_lead_over_core": a_lead / a_core if a_core else float("nan"),
                     "residual_share_of_lead": v_lead / (v_lead + a_lead)
                     if (v_lead + a_lead) else float("nan"),
                     "vocal_still_active": bool(np.isfinite(v_lead) and v_lead > RESIDUAL_ACTIVE_RMS)})
    if not rows:
        return {"available": False, "reason": "no units"}
    d = pd.DataFrame(rows)
    long_m = d["pred_dur_sec"] >= 1.0
    short_m = d["pred_dur_sec"] < 0.4
    gap_m = d["gap_measurable"].to_numpy(dtype=bool)
    gap_long = gap_m & long_m

    def _corr(mask: np.ndarray, vcol: str = "vocal_lead",
              acol: str = "accomp_lead") -> float | None:
        sub = d[mask]
        v = sub[vcol].to_numpy(dtype=float)
        a = sub[acol].to_numpy(dtype=float)
        ok = np.isfinite(v) & np.isfinite(a)
        if ok.sum() < 20 or np.std(v[ok]) == 0 or np.std(a[ok]) == 0:
            return None
        return round(float(np.corrcoef(v[ok], a[ok])[0, 1]), 4)

    def _blk(mask: np.ndarray) -> dict[str, Any]:
        sub = d[mask]
        if not len(sub):
            return {"units": 0}
        vc = sub["vocal_core"].to_numpy(dtype=float)
        vl = sub["vocal_lead"].to_numpy(dtype=float)
        rel = vl / np.where(vc > 0, vc, np.inf)
        return {"units": int(len(sub)),
                "relative_residual_active_share": round(float(np.mean(rel > RESIDUAL_RELATIVE_ACTIVE)), 4),
                "median_vocal_lead_over_core": round(
                    float(np.nanmedian(sub["vocal_lead_over_core"])), 4),
                "median_accomp_lead_over_core": round(
                    float(np.nanmedian(sub["accomp_lead_over_core"])), 4),
                "residual_active_share": round(float(sub["vocal_still_active"].mean()), 4),
                "median_residual_share_of_lead": round(
                    float(np.nanmedian(sub["residual_share_of_lead"])), 4),
                "corr_vocal_lead_vs_accomp_lead": _corr(mask)}
    def _gap_blk(mask: np.ndarray) -> dict[str, Any]:
        sub = d[mask]
        if not len(sub):
            return {"units": 0}
        v = sub["vocal_gap"].to_numpy(dtype=float)
        a = sub["accomp_gap"].to_numpy(dtype=float)
        core = sub["vocal_core"].to_numpy(dtype=float)
        core = np.where(np.isfinite(core) & (core > 0), core, np.inf)
        okv = np.isfinite(v)
        return {"units": int(len(sub)),
                "median_gap_sec": round(float(np.median(sub["gap_sec"])), 3),
                # scale-free activity: residual energy relative to the unit's own core energy.
                # An absolute RMS floor is unreliable across songs with different loudness.
                "vocal_active_share_in_gap": round(float(np.mean(
                    v[okv] > RESIDUAL_ACTIVE_RMS)), 4) if okv.any() else None,
                "relative_residual_active_share": round(float(np.mean(
                    (v[okv] > RESIDUAL_ACTIVE_RMS) &
                    (v[okv] > RESIDUAL_RELATIVE_ACTIVE * core[okv]))), 4) if okv.any() else None,
                "median_relative_residual": round(float(np.median(v[okv] / core[okv])), 4)
                if okv.any() and np.all(core[okv] > 0) else None,
                "median_vocal_gap_rms": round(float(np.median(v[okv])), 5) if okv.any() else None,
                "median_accomp_gap_rms": round(float(np.median(a[np.isfinite(a)])), 5)
                if np.isfinite(a).any() else None,
                "corr_vocal_gap_vs_accomp_gap": _corr(mask, "vocal_gap", "accomp_gap")}
    return {"available": True, "units": int(len(d)),
            "gaps": {"all_measurable": _gap_blk(gap_m), "long_units": _gap_blk(gap_long)},
            "gap_measurable_share": round(float(gap_m.mean()), 4),
            "all_units": _blk(np.ones(len(d), dtype=bool)),
            "long_units": _blk(long_m.to_numpy()),
            "short_units": _blk(short_m.to_numpy()),
            "corr_vocal_lead_vs_accomp_lead": _corr(np.ones(len(d), dtype=bool))}


def measure_batch(batch: Path, units: pd.DataFrame) -> dict[str, Any]:
    """Run the per-song measurement and pool it, with language and duration strata."""
    per_song: list[dict[str, Any]] = []
    pooled_rows: list[dict[str, Any]] = []
    for song, sub in units.groupby("song", observed=True):
        stem_dir = batch / song / "work" / "audio"
        stems = {"vocals": str(stem_dir / "vocals.wav"),
                 "accompaniment": str(stem_dir / "accompaniment.wav")}
        if not Path(stems["vocals"]).exists() or not Path(stems["accompaniment"]).exists():
            per_song.append({"song": str(song), "available": False, "reason": "stems missing"})
            continue
        qual = {}
        qp = stem_dir / "separation_quality.json"
        if qp.exists():
            try:
                q = json.loads(qp.read_text(encoding="utf-8"))
                qual = {"passed": q.get("passed"),
                        "vocals_vs_accompaniment_correlation":
                            (q.get("vocals_vs_accompaniment") or {}).get("correlation"),
                        "reconstruction_residual_ratio": q.get("reconstruction_residual_ratio")}
            except (OSError, ValueError):
                qual = {"passed": None}
        res = measure_song(sub, stems)
        entry = {"song": str(song), "language": str(sub["language"].iloc[0]),
                 **{k: v for k, v in res.items() if k != "available"},
                 "available": bool(res.get("available")), **qual}
        per_song.append(entry)
        if res.get("available"):
            pooled_rows.append(entry)
    ok = [r for r in per_song if r.get("available")]
    corr_vals = [r["corr_vocal_lead_vs_accomp_lead"] for r in ok
                 if r.get("corr_vocal_lead_vs_accomp_lead") is not None]
    long_corr = [r["long_units"].get("corr_vocal_lead_vs_accomp_lead") for r in ok
                 if isinstance(r.get("long_units"), dict)
                 and r["long_units"].get("corr_vocal_lead_vs_accomp_lead") is not None]
    out: dict[str, Any] = {"schema": "separation_leakage_v1", "batch": str(batch),
                           "songs_measured": len(ok), "songs_skipped": len(per_song) - len(ok),
                           "per_song": per_song,
                           "pooled": {
                               "median_song_corr_vocal_vs_accomp_lead":
                                   round(float(np.median(corr_vals)), 4) if corr_vals else None,
                               "median_song_corr_long_units":
                                   round(float(np.median(long_corr)), 4) if long_corr else None,
                               "median_residual_active_share": round(float(np.median(
                                   [r["all_units"]["residual_active_share"] for r in ok
                                    if r["all_units"].get("units")])), 4) if ok else None,
                               "median_long_residual_active_share": round(float(np.median(
                                   [r["long_units"]["residual_active_share"] for r in ok
                                    if r.get("long_units", {}).get("units")])), 4) if ok else None,
                               "separation_quality_all_passed": bool(
                                   all(bool(r.get("passed", True)) for r in ok)) if ok else None}}
    return out
