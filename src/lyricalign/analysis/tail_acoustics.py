"""Acoustic tail anchoring: can an energy-decay point fix the character-end boundary?

Round 4/5 located the main remaining failure layer for Mandarin: the **last character of an item**,
whose ground-truth duration averages 1.43 s versus 0.43 s in the middle of a phrase — a held note whose
offset has no sharp acoustic edge.  The literature is blunt that singing-note *offsets* have no robust
solution (see the McGill thesis on singing onset/offset annotation and "A New Method for Detecting
Onset and Offset for Singing", ProQuest 2700544904), so this module does not claim a method; it
measures how much of the observed error an explicit energy-decay anchor can recover.

Discipline
----------
* Thresholds/rules are **derived on GTSinger** (human word-level GT, clean studio vocal) and then
  applied **frozen** to MIR-1K, which stays test-only: no MIR-1K number is used to pick anything.
* Zero GPU: audio is read with soundfile and analysed with numpy/scipy on CPU; only feature
  summaries are written, never copies of audio.
* Baselines are always the recorded model output, so a "win" means "better than what we ship".
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import soundfile as sf

FRAME_SEC = 0.025
HOP_SEC = 0.010
SEARCH_BEFORE_FRAC = 0.4      # decay search starts 40 % into the unit, never before it
THETAS = (0.5, 0.35, 0.25, 0.15, 0.08)
LONG_NOTE_SEC = 1.0
TOL_END = (0.05, 0.1, 0.2)


@dataclass
class Envelope:
    t: np.ndarray          # frame times, seconds
    rms: np.ndarray        # per-frame RMS
    zcr: np.ndarray        # zero-crossing rate proxy of high-frequency content

    @property
    def duration_sec(self) -> float:
        return float(self.t[-1]) if self.t.size else 0.0

    def at(self, time_sec: float) -> float:
        if self.t.size == 0:
            return float("nan")
        i = int(np.clip(round((float(time_sec) - float(self.t[0])) / HOP_SEC), 0, self.t.size - 1))
        return float(self.rms[i])


@lru_cache(maxsize=64)
def load_envelope(path: str) -> Envelope:
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = x.mean(axis=1)
    win = max(1, int(round(FRAME_SEC * sr)))
    hop = max(1, int(round(HOP_SEC * sr)))
    n_frames = 1 + max(0, (mono.size - win) // hop)
    idx = np.arange(win)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = mono[idx] if n_frames else np.zeros((0, win), dtype=np.float32)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) if n_frames else np.zeros(0)
    sign = np.sign(frames)
    zcr = np.mean(np.abs(np.diff(sign, axis=1)) > 0, axis=1) if n_frames else np.zeros(0)
    t = (np.arange(n_frames) * hop + win / 2) / float(sr)
    return Envelope(t=t, rms=rms, zcr=zcr)


def decay_anchor(env: Envelope, start_sec: float, end_sec: float, theta: float,
                 search_end_sec: float | None = None) -> float:
    """First frame after the unit's core whose energy falls below ``theta`` x the unit's peak.

    Returns NaN when no such frame exists inside the search window (e.g. the next note starts before
    any decay), which downstream code must treat as "no acoustic evidence", not as "boundary here".
    """
    if env.t.size == 0 or not np.isfinite(start_sec) or not np.isfinite(end_sec) or end_sec <= start_sec:
        return float("nan")
    dur = end_sec - start_sec
    lo = start_sec + SEARCH_BEFORE_FRAC * dur
    hi = search_end_sec if search_end_sec is not None else end_sec + max(0.5, 1.5 * dur)
    lo = max(lo, float(env.t[0]))
    hi = min(hi, env.duration_sec)
    if hi <= lo:
        return float("nan")
    inside = (env.t >= lo) & (env.t <= hi)
    core = (env.t >= start_sec) & (env.t <= end_sec)
    peak = float(np.max(env.rms[core])) if core.any() else float("nan")
    if not np.isfinite(peak) or peak <= 0:
        return float("nan")
    level = theta * peak
    seg_t = env.t[inside]
    seg_e = env.rms[inside]
    below = seg_e < level
    if not below.any():
        return float("nan")
    return float(seg_t[np.argmax(below)])


def next_start_guard(ends: Sequence[float], starts: Sequence[float], idx: int) -> float | None:
    """Do not let an anchor run into the next unit's onset."""
    nxt = [s for i, s in enumerate(starts) if i == idx + 1 and np.isfinite(s)]
    return float(nxt[0]) if nxt else None


def apply_rules(rows: pd.DataFrame, envs: dict[str, Envelope], thetas: Sequence[float] = THETAS
                ) -> pd.DataFrame:
    """Add one column per rule giving the candidate character-end estimate."""
    out = rows.copy()
    out["model_end_sec"] = rows["pred_end_sec"].to_numpy(dtype=float)
    out["model_end_err"] = (rows["gt_end_sec"] - rows["pred_end_sec"]).abs()
    for th in thetas:
        est = np.full(len(out), np.nan)
        for i, r in enumerate(out.itertuples()):
            env = envs.get(str(r.audio_path))
            if env is None:
                continue
            guard = None
            if i + 1 < len(out) and out.iloc[i + 1]["item"] == r.item:
                ns = out.iloc[i + 1]["pred_start_sec"]
                guard = float(ns) if np.isfinite(ns) else None
            a = decay_anchor(env, float(r.pred_start_sec), float(r.pred_end_sec), th,
                             search_end_sec=(guard if guard is not None else None))
            est[i] = a
        out[f"anchor_theta{int(th * 100)}"] = est
    # blend rules (no extra tuning knobs): keep the model unless the anchor is close, or average them.
    # use the anchor nearest theta=0.35 among the ones actually computed, so the blends stay defined
    # for any theta subset.
    anchor_cols = [c for c in out.columns if c.startswith("anchor_theta")]
    if not anchor_cols:
        return out
    def _theta_of(col: str) -> float:
        return int(col.replace("anchor_theta", "")) / 100.0
    blend_col = min(anchor_cols, key=lambda c: abs(_theta_of(c) - 0.35))
    a35 = out[blend_col]
    out["blend_close100"] = np.where((a35 - out["model_end_sec"]).abs() <= 0.1, a35, out["model_end_sec"])
    out["blend_mean"] = np.where(np.isfinite(a35), 0.5 * (a35 + out["model_end_sec"]), out["model_end_sec"])
    # structural control: snap the end to the next unit's onset (uses no acoustics at all)
    nxt = out.groupby("item", observed=True)["pred_start_sec"].shift(-1)
    out["control_next_onset"] = np.where(nxt.notna() & (nxt > out["model_end_sec"]),
                                         out["model_end_sec"], nxt.fillna(out["model_end_sec"]))
    return out


def score_ends(df: pd.DataFrame, col: str, mask: np.ndarray | None = None) -> dict[str, Any]:
    err = (df["gt_end_sec"] - df[col]).abs().to_numpy(dtype=float)
    if mask is not None:
        err = err[mask & np.isfinite(err)]
    else:
        err = err[np.isfinite(err)]
    if err.size == 0:
        return {"n": 0}
    out: dict[str, Any] = {"n": int(err.size), "mae_end_sec": round(float(err.mean()), 4),
                           "median_end_sec": round(float(np.median(err)), 4),
                           "p90_end_sec": round(float(np.percentile(err, 90)), 4)}
    for tol in TOL_END:
        out[f"hit{int(tol * 1000)}"] = round(float(np.mean(err <= tol + 1e-9)), 4)
    return out


def evaluate(rows: pd.DataFrame, label: str) -> dict[str, Any]:
    long_note = rows["gt_dur_sec"].to_numpy(dtype=float) >= LONG_NOTE_SEC
    anchors = sorted(c for c in rows.columns if c.startswith("anchor_theta"))
    rules = (["model_end_sec"] + anchors + ["blend_close100", "blend_mean", "control_next_onset"])
    out: dict[str, Any] = {"set": label, "units": int(len(rows)),
                           "long_note_units": int(long_note.sum()),
                           "long_note_share": round(float(long_note.mean()), 4), "rules": {}}
    for col in rules:
        if col not in rows:
            continue
        out["rules"][col] = {"all_units": score_ends(rows, col),
                             "long_notes": score_ends(rows, col, long_note)}
    base = out["rules"]["model_end_sec"]["all_units"]
    out["delta_pp_hit100_vs_model"] = {
        c: round((v["all_units"].get("hit100", float("nan")) - base.get("hit100", float("nan"))) * 100, 2)
        for c, v in out["rules"].items() if v["all_units"].get("n", 0) > 0}
    out["delta_pp_hit100_long_notes_vs_model"] = {
        c: round((v["long_notes"].get("hit100", float("nan"))
                  - out["rules"]["model_end_sec"]["long_notes"].get("hit100", float("nan"))) * 100, 2)
        for c, v in out["rules"].items() if v["long_notes"].get("n", 0) > 0}
    return out

RHOS = (0.9, 0.7, 0.5, 0.3, 0.15)


def load_stereo_envelopes(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """(frame times, vocal-channel energy, accompaniment-channel energy) for a 2-channel recording."""
    try:
        x, sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        return None
    if x.shape[1] < 2:
        return None
    win = max(1, int(round(FRAME_SEC * sr)))
    hop = max(1, int(round(HOP_SEC * sr)))
    n = 1 + max(0, (x.shape[0] - win) // hop)
    if n == 0:
        return None
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(x[idx].astype(np.float64) ** 2, axis=1))
    t = (np.arange(n) * hop + win / 2) / float(sr)
    return t, rms[:, 1], rms[:, 0]


def ratio_anchor(t: np.ndarray, ratio: np.ndarray, start_sec: float, end_sec: float,
                 rho: float) -> float:
    """First frame where vocal/accompaniment energy falls below ``rho`` x the unit's peak ratio.

    Unlike the plain RMS decay this fires even when reverb or accompaniment keeps total energy high,
    which is exactly the situation of a sustained final note in a real recording.
    """
    dur = end_sec - start_sec
    if dur <= 0 or t.size == 0:
        return float("nan")
    lo = start_sec + SEARCH_BEFORE_FRAC * dur
    hi = min(end_sec + max(0.5, 1.5 * dur), float(t[-1]))
    core = (t >= start_sec) & (t <= end_sec)
    seg = (t >= lo) & (t <= hi)
    if core.sum() == 0 or seg.sum() == 0:
        return float("nan")
    peak = float(np.max(ratio[core]))
    if not np.isfinite(peak) or peak <= 0:
        return float("nan")
    below = ratio[seg] < rho * peak
    return float(t[seg][np.argmax(below)]) if below.any() else float("nan")


def evaluate_ratio_family(rows: pd.DataFrame, stereo_dir: Path,
                          rhos: Sequence[float] = RHOS) -> dict[str, Any]:
    """Score every rho without selecting one (the data this runs on may be test-only)."""
    items = {str(i): g.reset_index(drop=True) for i, g in rows.groupby("item", observed=True)}
    estimates = {float(r): np.full(len(rows), np.nan) for r in rhos}
    pos = {str(i): np.flatnonzero((rows["item"].astype(str)).to_numpy() == str(i)) for i in items}
    files = 0
    for item, g in items.items():
        path = Path(stereo_dir) / f"{item}.wav"
        loaded = load_stereo_envelopes(str(path))
        if loaded is None:
            continue
        files += 1
        t, ev, ea = loaded
        ratio = ev / (ea + 1e-9)
        for i in range(len(g)):
            r = g.iloc[i]
            for rho in rhos:
                estimates[float(rho)][pos[item][i]] = ratio_anchor(
                    t, ratio, float(r["pred_start_sec"]), float(r["pred_end_sec"]), float(rho))
    gt_end = rows["gt_end_sec"].to_numpy(dtype=float)
    model_err = np.abs(gt_end - rows["pred_end_sec"].to_numpy(dtype=float))
    last = rows["is_last"].to_numpy(dtype=float) == 1.0
    longm = rows["gt_dur_sec"].to_numpy(dtype=float) >= LONG_NOTE_SEC

    def rep(err: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
        ok = mask & np.isfinite(err)
        if not ok.any():
            return {"n": 0}
        return {"n": int(ok.sum()), "hit100": round(float(np.mean(err[ok] <= 0.1)), 4),
                "mae_end_sec": round(float(np.mean(err[ok])), 4)}

    out: dict[str, Any] = {"schema": "ratio_anchor_family_v1", "stereo_files_used": files,
                           "model_baseline": {"all_units": rep(model_err, np.isfinite(model_err)),
                                              "last_char": rep(model_err, last),
                                              "long_notes": rep(model_err, longm)},
                           "rhos": {}}
    for rho, est in estimates.items():
        err = np.abs(gt_end - est)
        cov = np.isfinite(err)
        # fairness: also report the model on exactly the units where this rho produced an anchor
        out["rhos"][str(rho)] = {
            "coverage": round(float(cov.mean()), 4),
            "anchor_all_units": rep(err, cov),
            "anchor_last_char": rep(err, last),
            "anchor_long_notes": rep(err, longm),
            "model_on_covered_all": rep(model_err, cov),
            "model_on_covered_long": rep(model_err, cov & longm),
            "model_on_covered_last": rep(model_err, cov & last),
        }
    out["discipline"] = ("no rho is selected here: this data is test-only, so the whole family is "
                         "reported and any single-rho claim would be tuning on test")
    return out
