"""Structural compliance audit + repair plan for shipped real-song alignments (no ground truth).

Rounds 6 and 7 established, on three different data domains, that the shipped post-processing reaches
a clean-looking timeline by collapsing units (degenerate 11.2% -> 17.1% on 25 real songs) and that one
joint constrained solve fixes structure better than any sequential rule.  This module turns that into an
operational artifact: for every song, how many shipped units are structurally illegal, what the solve
would change, and which specific units a human should look at first.

No ground truth is used or needed: every metric here is a property of the shipped timeline itself
(zero/negative duration, adjacent overlap, start regression, implausible duration), and the "repair" is
the round-7 LP applied per song.  The output is a review list, not an accuracy claim — the project's
realign discipline (shadow-only, no writeback) is untouched.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lyricalign.analysis import joint_cleanup as J

RUNS = Path("/home/hyan/Data/lyricalign/runs")
DEFAULT_BATCH = RUNS / "20260814_ktv_current_silence"
ALIGN_RELPATH = Path("alignments/r2/vocal/windowed/alignment.json")
STAGES = ("selected", "raw")


def _f(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def load_batch(batch: Path = DEFAULT_BATCH, relpath: Path = ALIGN_RELPATH,
               stage: str = "selected") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Per-unit frame for every song in a batch, at the shipped stage (default) or raw."""
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"batch": str(batch), "stage": stage, "songs": 0, "skipped": []}
    if not batch.exists():
        return pd.DataFrame(rows), meta
    for d in sorted(p for p in batch.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        path = d / relpath
        if not path.exists():
            meta["skipped"].append({"song": d.name, "reason": "no_alignment_json"})
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            meta["skipped"].append({"song": d.name, "reason": f"unreadable:{type(exc).__name__}"})
            continue
        chars = doc.get("characters") or []
        s = doc.get("summary") or {}
        ident = doc.get("identity") or {}
        dur = _f(s.get("audio_duration_sec"))
        for i, c in enumerate(chars):
            if stage == "raw":
                st, en = _f(c.get("raw_global_start_sec")), _f(c.get("raw_global_end_sec"))
            else:
                st = _f(c.get("selected_start_sec", c.get("start_sec")))
                en = _f(c.get("selected_end_sec", c.get("end_sec")))
            rows.append({"song": d.name, "unit_index": i,
                         "text": str(c.get("character", "")),
                         "unit_type": str(c.get("unit_type", "")),
                         "language": str(s.get("language") or ""),
                         "start_sec": st, "end_sec": en,
                         "audio_duration_sec": dur,
                         "audio_sha256": str((ident.get("audio") or {}).get("sha256", "")),
                         "request_hash": str(ident.get("request_hash", "")),
                         "schema_version": str(ident.get("schema_version", "")),
                         "ent_start": _f(c.get("raw_start_entropy")),
                         "ent_end": _f(c.get("raw_end_entropy")),
                         "inference_source": str(c.get("inference_source", ""))})
        meta["songs"] += 1
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["start_sec", "end_sec"]).sort_values(["song", "unit_index"])
        df = df.reset_index(drop=True)
    meta["units"] = int(len(df))
    return df, meta


def flag_violations(df: pd.DataFrame, min_dur: float = 1e-6, max_dur: float = J.MAX_DUR_SEC
                    ) -> pd.DataFrame:
    """Mark every structurally illegal unit in the shipped timeline (per song, so no cross-song edges)."""
    out = df.copy()
    dur = out["end_sec"].to_numpy(dtype=float) - out["start_sec"].to_numpy(dtype=float)
    song_arr = out["song"].to_numpy()
    start_arr = out["start_sec"].to_numpy(dtype=float)
    next_same = (song_arr == np.roll(song_arr, -1)) & (np.arange(len(out)) < len(out) - 1)
    prev_same = (song_arr == np.roll(song_arr, 1)) & (np.arange(len(out)) > 0)
    nxt_start = np.roll(start_arr, -1)
    prev_start = np.roll(start_arr, 1)
    out["duration_sec"] = dur
    out["flag_zero_or_negative"] = (dur <= min_dur)
    out["flag_overshoot"] = dur > max_dur
    out["flag_overlaps_next"] = np.where(next_same, (out["end_sec"].to_numpy(dtype=float)
                                                     - nxt_start) > 1e-3, False)
    out["flag_start_regression"] = np.where(prev_same, (start_arr - prev_start) < -1e-6, False)
    out["n_violations"] = (out[["flag_zero_or_negative", "flag_overshoot", "flag_overlaps_next",
                                "flag_start_regression"]].sum(axis=1))
    out["is_illegal"] = out["n_violations"] > 0
    return out


def repair(df: pd.DataFrame, min_dur: float = J.MIN_DUR_SEC, max_dur: float = J.MAX_DUR_SEC,
           use_confidence: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the joint constrained solve per song and report the impact."""
    out = df.copy()
    out["repaired_start_sec"] = np.nan
    out["repaired_end_sec"] = np.nan
    statuses: dict[str, int] = {}
    for song, sub in df.groupby("song", observed=True):
        pos = sub.index.to_numpy()
        ent_s = sub["ent_start"].to_numpy(dtype=float) if use_confidence else None
        ent_e = sub["ent_end"].to_numpy(dtype=float) if use_confidence else None
        S, E, rep = J.solve_block(sub["start_sec"].to_numpy(dtype=float),
                                 sub["end_sec"].to_numpy(dtype=float),
                                 ent_start=ent_s, ent_end=ent_e,
                                 min_dur=min_dur, max_dur=max_dur,
                                 audio_dur=float(np.nanmax(sub["audio_duration_sec"].to_numpy(dtype=float)))
                                 if np.isfinite(sub["audio_duration_sec"].to_numpy(dtype=float)).any() else None)
        out.loc[pos, "repaired_start_sec"] = S
        out.loc[pos, "repaired_end_sec"] = E
        statuses[rep.status] = statuses.get(rep.status, 0) + 1
    out["repair_shift_sec"] = np.maximum((out["repaired_start_sec"] - out["start_sec"]).abs(),
                                        (out["repaired_end_sec"] - out["end_sec"]).abs())
    out["repair_moved"] = out["repair_shift_sec"] > 1e-3
    return out, {"solve_statuses": statuses, "min_dur_sec": min_dur, "max_dur_sec": max_dur,
                 "confidence_weighted": bool(use_confidence)}


def _rate(x: np.ndarray) -> float:
    return round(float(np.mean(x)), 4) if x.size else 0.0


def summarise(df: pd.DataFrame, top_units: int = 25) -> dict[str, Any]:
    """Totals, per-language and per-song breakdowns, plus the units a human should look at first."""
    out: dict[str, Any] = {"schema": "structural_compliance_v1",
                           "units": int(len(df)), "songs": int(df["song"].nunique())}
    def block(sub: pd.DataFrame) -> dict[str, Any]:
        dur = sub["duration_sec"].to_numpy(dtype=float)
        moved = sub["repair_moved"].to_numpy(dtype=bool)
        shift = sub["repair_shift_sec"].to_numpy(dtype=float)
        entry = {
            "units": int(len(sub)),
            "illegal_share": _rate(sub["is_illegal"].to_numpy(dtype=bool)),
            "zero_or_negative_share": _rate(sub["flag_zero_or_negative"].to_numpy(dtype=bool)),
            "overshoot_share": _rate(sub["flag_overshoot"].to_numpy(dtype=bool)),
            "overlap_next_share": _rate(sub["flag_overlaps_next"].to_numpy(dtype=bool)),
            "start_regression_share": _rate(sub["flag_start_regression"].to_numpy(dtype=bool)),
            "max_duration_sec": round(float(np.nanmax(dur)), 2) if dur.size else None,
            "plausible_mass_sec": round(float(np.nansum(np.clip(dur, 0, J.MAX_DUR_SEC))), 1),
            "repaired_units": int(moved.sum()),
            "repaired_share": _rate(moved),
            "median_shift_sec": round(float(np.median(shift[moved])), 4) if moved.any() else None,
            "p90_shift_sec": round(float(np.percentile(shift[moved], 90)), 4) if moved.any() else None,
            "max_shift_sec": round(float(np.nanmax(shift[moved])), 3) if moved.any() else None,
        }
        # stratify: capping a multi-second overshoot moves its end by seconds, which would otherwise
        # dominate the shift distribution and hide how small the real edits are
        plain = moved & ~sub["flag_overshoot"].to_numpy(dtype=bool)
        if plain.any():
            entry["moved_share_excluding_overshoot"] = _rate(plain)
            entry["median_shift_excluding_overshoot_sec"] = round(float(np.median(shift[plain])), 4)
            entry["p90_shift_excluding_overshoot_sec"] = round(float(np.percentile(shift[plain], 90)), 4)
            entry["max_shift_excluding_overshoot_sec"] = round(float(np.nanmax(shift[plain])), 4)
        entry["illegal_units"] = int(sub["is_illegal"].to_numpy(dtype=bool).sum())
        entry["zero_units"] = int(sub["flag_zero_or_negative"].to_numpy(dtype=bool).sum())
        return entry

    out["overall"] = block(df)
    # verify the repair really removes the violations (structural guarantee of the LP)
    after = df.copy()
    after["start_sec"] = after["repaired_start_sec"]
    after["end_sec"] = after["repaired_end_sec"]
    after = after.dropna(subset=["start_sec", "end_sec"]).sort_values(["song", "unit_index"])
    after = flag_violations(after)
    out["post_repair"] = {"units": int(len(after)),
                          "illegal_share": _rate(after["is_illegal"].to_numpy(dtype=bool)),
                          "zero_or_negative_share": _rate(after["flag_zero_or_negative"].to_numpy(dtype=bool)),
                          "overshoot_share": _rate(after["flag_overshoot"].to_numpy(dtype=bool)),
                          "overlap_next_share": _rate(after["flag_overlaps_next"].to_numpy(dtype=bool)),
                          "start_regression_share": _rate(after["flag_start_regression"].to_numpy(dtype=bool))}
    out["by_language"] = {str(k): block(sub) for k, sub in df.groupby("language", observed=True)}
    per_song = []
    for song, sub in df.groupby("song", observed=True):
        b = block(sub)
        per_song.append({"song": str(song), "language": str(sub["language"].iloc[0]),
                         "units": b["units"], "illegal_share": b["illegal_share"],
                         "zero_or_negative_share": b["zero_or_negative_share"],
                         "overlap_next_share": b["overlap_next_share"],
                         "overshoot_share": b["overshoot_share"],
                         "max_duration_sec": b["max_duration_sec"],
                         "repaired_share": b["repaired_share"],
                         "max_shift_sec": b["max_shift_sec"],
                         "audio_sha_recorded": bool(str(sub["audio_sha256"].iloc[0]))})
    out["per_song"] = sorted(per_song, key=lambda r: -r["illegal_share"])
    worst = df[df["is_illegal"]].sort_values(["n_violations", "duration_sec"], ascending=[False, True])
    out["worst_units"] = [{"song": str(r.song), "unit_index": int(r.unit_index), "text": str(r.text),
                           "unit_type": str(r.unit_type),
                           "duration_sec": None if not np.isfinite(r.duration_sec) else round(float(r.duration_sec), 3),
                           "n_violations": int(r.n_violations),
                           "flags": ",".join([n.replace("flag_", "") for n in
                                              ["flag_zero_or_negative", "flag_overshoot",
                                               "flag_overlaps_next", "flag_start_regression"]
                                              if bool(getattr(r, n))]),
                           "repair_shift_sec": None if not np.isfinite(r.repair_shift_sec)
                           else round(float(r.repair_shift_sec), 3)}
                          for r in worst.head(top_units).itertuples()]
    out["unit_type_profile"] = {str(k): {"units": int(len(sub)),
                                         "illegal_share": _rate(sub["is_illegal"].to_numpy(dtype=bool)),
                                         "zero_share": _rate(sub["flag_zero_or_negative"].to_numpy(dtype=bool))}
                                for k, sub in df.groupby("unit_type", observed=True)}
    return out


def export_repair_list(df: pd.DataFrame, path: Path, max_rows: int = 200_000) -> dict[str, Any]:
    """Write the per-unit review list (illegal units only) as a compressed CSV."""
    bad = df[df["is_illegal"]].copy()
    cols = ["song", "language", "unit_index", "text", "unit_type", "start_sec", "end_sec",
            "duration_sec", "flag_zero_or_negative", "flag_overshoot", "flag_overlaps_next",
            "flag_start_regression", "n_violations", "repaired_start_sec", "repaired_end_sec",
            "repair_shift_sec", "ent_start", "ent_end", "inference_source"]
    bad = bad[[c for c in cols if c in bad.columns]].head(max_rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write(bad.to_csv(index=False))
    return {"path": str(path), "rows": int(len(bad)), "bytes": int(path.stat().st_size)}

def compression_damage(batch: Path = DEFAULT_BATCH, relpath: Path = ALIGN_RELPATH) -> dict[str, Any]:
    """How many zero-length units did the post-processing *create*, and did it notice?

    The shipped artifacts carry their own counter (``overlap_compression_collapsed_to_zero_count``).
    Comparing it against the measured number of units that were non-degenerate at the raw stage and
    degenerate after post-processing tests whether the pipeline can see its own damage.
    """
    rows: list[dict[str, Any]] = []
    for d in sorted(pth for pth in batch.iterdir() if pth.is_dir() and not pth.name.startswith(("_", "."))):
        path = d / relpath
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        chars = doc.get("characters") or []
        rs = np.array([_f(c.get("raw_global_start_sec")) for c in chars], dtype=float)
        re = np.array([_f(c.get("raw_global_end_sec")) for c in chars], dtype=float)
        ss = np.array([_f(c.get("selected_start_sec", c.get("start_sec"))) for c in chars], dtype=float)
        se = np.array([_f(c.get("selected_end_sec", c.get("end_sec"))) for c in chars], dtype=float)
        have_raw = np.isfinite(rs) & np.isfinite(re)
        raw_zero = have_raw & ((re - rs) <= 1e-6)
        sel_zero = np.isfinite(ss) & np.isfinite(se) & ((se - ss) <= 1e-6)
        created = have_raw & ~raw_zero & sel_zero
        healed = have_raw & raw_zero & ~sel_zero
        s = doc.get("summary") or {}
        rows.append({"song": d.name, "language": str(s.get("language") or ""), "units": int(len(chars)),
                    "raw_zero_share": round(float(raw_zero.mean()), 4) if len(chars) else None,
                    "shipped_zero_share": round(float(sel_zero.mean()), 4) if len(chars) else None,
                    "created_by_postprocess": int(created.sum()),
                    "healed_by_postprocess": int(healed.sum()),
                    "counter_collapsed_to_zero": s.get("overlap_compression_collapsed_to_zero_count"),
                    "seam_repaired_rate": s.get("seam_repaired_character_rate"),
                    "overlap_compressed_rate": s.get("overlap_compressed_character_rate"),
                    "window_count": s.get("window_count")})
    df = pd.DataFrame(rows)
    out: dict[str, Any] = {"schema": "compression_damage_v1", "songs": int(len(df)),
                           "per_song": rows}
    if len(df):
        total_units = int(df["units"].sum())
        created = int(df["created_by_postprocess"].sum())
        counter = pd.to_numeric(df["counter_collapsed_to_zero"], errors="coerce").fillna(0).sum()
        z_ship = (pd.to_numeric(df["shipped_zero_share"], errors="coerce")
                  * df["units"]).sum()
        z_raw = (pd.to_numeric(df["raw_zero_share"], errors="coerce") * df["units"]).sum()
        out["totals"] = {
            "units": total_units,
            "zero_units_shipped": int(z_ship), "zero_units_raw": int(z_raw),
            "shipped_zero_share": round(float(z_ship / max(total_units, 1)), 4),
            "raw_zero_share": round(float(z_raw / max(total_units, 1)), 4),
            "created_by_postprocess_units": created,
            "created_by_postprocess_share": round(float(created / max(total_units, 1)), 4),
            "healed_by_postprocess_units": int(pd.to_numeric(df["healed_by_postprocess"],
                                                             errors="coerce").fillna(0).sum()),
            "net_change_units": int(z_ship - z_raw),
            "pipeline_counter_total": int(counter),
            "counter_blind_share": round(float(1 - counter / max(created, 1)), 4),
        }
        for col in ("seam_repaired_rate", "overlap_compressed_rate"):
            v = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
            zv = pd.to_numeric(df["shipped_zero_share"], errors="coerce").to_numpy(dtype=float)
            ok = np.isfinite(v) & np.isfinite(zv) & (df["units"].to_numpy() > 20)
            out[f"correlation_zero_share_vs_{col}"] = (
                round(float(np.corrcoef(v[ok], zv[ok])[0, 1]), 4) if ok.sum() > 3 else None)
        out["worst_songs"] = df.sort_values("created_by_postprocess", ascending=False) \
            .head(6).to_dict(orient="records")
    return out

# each stage keeps its own candidate key lists for the two boundaries; conflating them (as an earlier
# version did) silently reported the whole `fixed` stage as missing
STAGE_KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "raw": (("raw_global_start_sec",), ("raw_global_end_sec",)),
    "fixed": (("fixed_global_start_sec", "official_fixed_start_sec"),
              ("fixed_global_end_sec", "official_fixed_end_sec")),
    "selected": (("selected_start_sec",), ("selected_end_sec",)),
    "final": (("start_sec",), ("end_sec",)),
}


def _first_present(char: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        if char.get(k) is not None:
            return _f(char.get(k))
    return None


def _stage_bounds(char: dict[str, Any], stage: str) -> tuple[float | None, float | None]:
    start_keys, end_keys = STAGE_KEYS[stage]
    return _first_present(char, start_keys), _first_present(char, end_keys)


def stage_lineage_attribution(batch: Path = DEFAULT_BATCH,
                              relpath: Path = ALIGN_RELPATH) -> dict[str, Any]:
    """Which pipeline stage creates the degenerate intervals?

    The shipped artifacts record four stages per unit (raw / fixed / selected / final), but only the
    overlap-compression step carries a degenerate-output counter — and its definition is narrow by
    design (it counts collapses *it* caused).  Attributing the zero/negative rate per stage shows
    where the damage actually enters, which no existing summary reports.
    """
    per_song: list[dict[str, Any]] = []
    totals = {st: {"zero": 0, "negative": 0, "known": 0} for st in STAGE_KEYS}
    order = list(STAGE_KEYS)
    for d in sorted(pth for pth in batch.iterdir()
                    if pth.is_dir() and not pth.name.startswith(("_", "."))):
        path = d / relpath
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        chars = doc.get("characters") or []
        if not chars:
            continue
        row: dict[str, Any] = {"song": d.name,
                               "language": str((doc.get("summary") or {}).get("language") or ""),
                               "units": int(len(chars))}
        # "pinned to the owning window's input boundary" is the signature of the remap defect that
        # turns a whole block of units into one identical timestamp; measure it explicitly.
        trace = doc.get("window_trace") or []
        anchors: dict[int, float] = {}
        for i, w in enumerate(trace):
            if isinstance(w, dict) and w.get("input_start_sec") is not None:
                anchors[i] = float(w["input_start_sec"])
        pinned = 0
        if anchors:
            for c in chars:
                fx = _f(c.get("fixed_global_start_sec", c.get("official_fixed_start_sec")))
                if fx is None:
                    continue
                if any(abs(fx - a) <= 1e-6 for a in anchors.values()):
                    pinned += 1
        row["pinned_to_window_input_units"] = int(pinned)
        row["pinned_to_window_input_share"] = round(pinned / len(chars), 4)
        for st in order:
            zero = neg = known = 0
            for c in chars:
                a, b = _stage_bounds(c, st)
                if a is None or b is None:
                    continue
                known += 1
                dur = b - a
                if dur < -1e-6:
                    neg += 1
                elif dur <= 1e-6:
                    zero += 1
            totals[st]["zero"] += zero
            totals[st]["negative"] += neg
            totals[st]["known"] += known
            row[f"{st}_degenerate_share"] = round((zero + neg) / known, 4) if known else None
            row[f"{st}_degenerate_units"] = int(zero + neg)
        for prev, nxt in zip(order, order[1:]):
            a, b = row.get(f"{prev}_degenerate_units"), row.get(f"{nxt}_degenerate_units")
            if a is not None and b is not None:
                # NET change for this song: within a song, units created and units healed cancel,
                # so the unit-level "created" count lives in compression_damage(), not here.
                row[f"net_added_by_{nxt}"] = int(b - a)
        per_song.append(row)
    out: dict[str, Any] = {"schema": "stage_lineage_attribution_v1", "per_song": per_song,
                           "stages": order}
    grand = sum(v["known"] for v in totals.values()) / max(len(totals), 1)
    out["totals"] = {st: {"known_units": v["known"], "zero_units": v["zero"],
                          "negative_units": v["negative"],
                          "degenerate_share": round((v["zero"] + v["negative"]) / v["known"], 4)
                          if v["known"] else None}
                     for st, v in totals.items()}
    deltas = {}
    for prev, nxt in zip(order, order[1:]):
        a = out["totals"][prev]
        b = out["totals"][nxt]
        if a["known_units"] and b["known_units"]:
            deltas[f"{prev}->{nxt}"] = round(
                (b["degenerate_share"] or 0.0) - (a["degenerate_share"] or 0.0), 4)
    out["stage_transitions_degenerate_share_delta"] = deltas
    agg: dict[str, int] = {}
    for r in per_song:
        for k, v in r.items():
            if k.startswith("net_added_by_") and isinstance(v, int):
                agg[k] = agg.get(k, 0) + max(v, 0)
    out["sum_of_positive_net_additions_by_stage"] = agg
    tot_units = sum(int(r["units"]) for r in per_song)
    tot_pinned = sum(int(r.get("pinned_to_window_input_units", 0)) for r in per_song)
    out["pinned_to_window_input"] = {
        "units": int(tot_pinned), "of_units": int(tot_units),
        "share": round(tot_pinned / max(tot_units, 1), 4),
        "songs_affected": int(sum(1 for r in per_song if r.get("pinned_to_window_input_units", 0) > 0)),
        "top_songs": [{"song": r["song"], "language": r["language"],
                       "pinned": int(r.get("pinned_to_window_input_units", 0)),
                       "share": r.get("pinned_to_window_input_share"),
                       "net_added_by_fixed": r.get("net_added_by_fixed")}
                      for r in sorted(per_song, key=lambda x: -int(x.get("pinned_to_window_input_units", 0)))[:5]],
    }
    return out
