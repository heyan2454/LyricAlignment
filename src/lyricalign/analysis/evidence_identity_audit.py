"""Reusable identity/comparability gate for batches of alignment artifacts.

Three failures in this session had the same shape — two "conditions" that were not actually different,
or a comparison whose rows did not line up:

* GTSinger evaluation_v1's ``mix`` vs ``vocal`` cells shared one audio file (dead factor, round 10);
* ``20260814_ktv_B4`` vs ``20260814_ktv_current_silence`` ran the same window plan (round 5);
* the long-form panel joined label rows to a timeline on a request-local id (rounds 3/7/8).

This module turns those lessons into checks that can be pointed at any pair of batch directories or at
one directory with a varying factor, and returns a verdict instead of a silently meaningless table:

``not_identified``  the cells differ only in labels/paths, not in content or plan -> no comparison
``not_comparable``  rows do not line up (unit counts or per-index text differ)
``identified``      content/plan genuinely differs and the join is sound
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

ALIGN_RELPATH = Path("alignments/r2/vocal/windowed/alignment.json")


def _f(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def collect(root: Path, relpath: Path = ALIGN_RELPATH,
            song_of: Callable[[Path], str] | None = None) -> dict[str, dict[str, Any]]:
    """Gather one record per song from a batch directory: identity, plan, boundaries, structure."""
    out: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        path = d / relpath
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ident = doc.get("identity") or {}
        audio = ident.get("audio") or {}
        win = ident.get("window") or {}
        chars = doc.get("characters") or []
        s = doc.get("summary") or {}
        starts = np.array([_f(c.get("selected_start_sec", c.get("start_sec"))) for c in chars], dtype=float)
        ends = np.array([_f(c.get("selected_end_sec", c.get("end_sec"))) for c in chars], dtype=float)
        dur = ends - starts
        ok = np.isfinite(starts) & np.isfinite(ends)
        key = song_of(d) if song_of else d.name
        out[key] = {
            "path": str(path), "units": int(len(chars)),
            "audio_sha256": str(audio.get("sha256", "")), "audio_path": str(audio.get("path", "")),
            "request_hash": str(ident.get("request_hash", "")),
            "schema_version": str(ident.get("schema_version", "")),
            "decoder_kind": str((ident.get("decoder") or {}).get("kind", ""))
            if isinstance(ident.get("decoder"), dict) else "",
            "window_policy": str(win.get("policy", "")) if isinstance(win, dict) else "",
            "window_core_sec": _f(win.get("core_sec")) if isinstance(win, dict) else None,
            "left_context_sec": _f(win.get("left_context_sec")) if isinstance(win, dict) else None,
            "n_window_flags_recorded": int(sum(1 for _k, v in (win or {}).items() if v is not None)),
            "records_silence_flags": int(any(("silence" in k or "silent" in k)
                                             for k in (win or {}))),
            "audio_duration_sec": _f(s.get("audio_duration_sec")),
            "language": str(s.get("language") or ""),
            "degenerate_share": round(float(np.mean(dur[ok] <= 1e-6)), 4) if ok.any() else None,
            "overlap_share": round(float(np.mean((ends[:-1] - starts[1:])[ok[:-1] & ok[1:]] > 1e-3)), 4)
            if ok.sum() > 1 else None,
            "starts": starts, "ends": ends,
            "text": [str(c.get("character", "")) for c in chars],
        }
    return out


def _diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {k: {"a": a.get(k), "b": b.get(k)} for k in
            ("audio_sha256", "request_hash", "schema_version", "window_policy", "window_core_sec",
             "left_context_sec", "decoder_kind", "units", "audio_duration_sec", "language")
            if a.get(k) != b.get(k)}


def audit_pair(name: str, a: dict[str, dict[str, Any]], b: dict[str, dict[str, Any]],
               tol_sec: float = 1e-3) -> dict[str, Any]:
    """Compare two batches song by song: same input? same plan? same output? rows aligned?"""
    songs = sorted(set(a) & set(b))
    if not songs:
        return {"pair": name, "verdict": "no_overlap", "songs": 0}
    rows: list[dict[str, Any]] = []
    n_same_sha = n_same_req = n_same_plan = n_identical_out = n_text_mismatch = n_len_mismatch = 0
    max_shift = []
    for song in songs:
        x, y = a[song], b[song]
        same_sha = bool(x["audio_sha256"]) and x["audio_sha256"] == y["audio_sha256"]
        same_req = bool(x["request_hash"]) and x["request_hash"] == y["request_hash"]
        same_plan = (x["window_policy"] == y["window_policy"]
                     and x["window_core_sec"] == y["window_core_sec"]
                     and x["left_context_sec"] == y["left_context_sec"])
        len_same = x["units"] == y["units"]
        text_same = len_same and x["text"] == y["text"]
        out_same = False
        shift = None
        if len_same and text_same:
            ds = np.abs(x["starts"] - y["starts"])
            de = np.abs(x["ends"] - y["ends"])
            both = np.maximum(ds, de)
            ok = np.isfinite(both)
            if ok.any():
                shift = float(np.nanmax(both[ok]))
                max_shift.append(shift)
                out_same = bool(shift <= tol_sec)
        n_same_sha += int(same_sha)
        n_same_req += int(same_req)
        n_same_plan += int(same_plan)
        n_identical_out += int(out_same)
        n_text_mismatch += int(len_same and not text_same)
        n_len_mismatch += int(not len_same)
        rows.append({"song": song, "same_audio_sha": int(same_sha), "same_request_hash": int(same_req),
                     "same_window_plan": int(same_plan), "same_unit_count": int(len_same),
                     "same_text": int(text_same), "outputs_identical": int(out_same),
                     "max_boundary_shift_sec": None if shift is None else round(shift, 4),
                     "identity_diff": _diff(x, y)})
    # songs that differ in output while the input content is identical => a real mechanism difference;
    # differences that only occur where the audio bytes changed are input changes, not mechanisms
    diffs_same_audio = sum(1 for r in rows
                           if (not r["outputs_identical"]) and r["same_audio_sha"] and r["same_unit_count"])
    n = len(songs)
    if n_len_mismatch or n_text_mismatch:
        verdict = ("not_comparable",
                   f"{n_len_mismatch} songs differ in unit count, {n_text_mismatch} have the same count "
                   f"but different characters at the same index (index drift)")
    elif n_identical_out == n and n_same_plan == n:
        verdict = ("not_identified",
                   "identical window plan and byte-identical outputs on every song: the two batches are "
                   "the same configuration run twice")
    elif n_identical_out == n and n_same_sha == n:
        verdict = ("not_identified", "same audio content and identical outputs")
    elif diffs_same_audio == 0 and n_same_plan == n and n_identical_out > 0:
        verdict = ("duplicate_configuration",
                   f"{n_identical_out}/{n} songs byte-identical, identical window plan on all songs, and "
                   f"every output difference occurs on a song whose audio content also changed "
                   f"({n - n_same_sha} songs) => the batches are the same configuration re-run, "
                   "not two mechanisms")
    else:
        verdict = ("identified",
                   f"{n - n_identical_out}/{n} songs differ in output "
                   f"(max boundary shift {max(max_shift) if max_shift else 0:.3f}s)")
    return {"pair": name, "songs": n, "verdict": verdict[0], "reason": verdict[1],
            "same_audio_sha_share": round(n_same_sha / n, 4),
            "same_request_hash_share": round(n_same_req / n, 4),
            "same_window_plan_share": round(n_same_plan / n, 4),
            "outputs_identical_share": round(n_identical_out / n, 4),
            "output_differences_on_identical_audio": diffs_same_audio,
            "unit_count_mismatch_songs": n_len_mismatch, "text_mismatch_songs": n_text_mismatch,
            "median_max_shift_sec": round(float(np.median(max_shift)), 4) if max_shift else None,
            "p90_max_shift_sec": round(float(np.percentile(max_shift, 90)), 4) if max_shift else None,
            "per_song": rows}


def audit_identity_hygiene(batches: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """Report batches whose artifacts cannot support a claim: no schema, no sha, no plan flags."""
    out: dict[str, Any] = {}
    for name, coll in batches.items():
        if not coll:
            out[name] = {"present": False}
            continue
        vals = list(coll.values())
        out[name] = {
            "present": True, "songs": len(vals),
            "share_missing_schema_version": round(float(np.mean([not v["schema_version"] for v in vals])), 4),
            "share_missing_audio_sha": round(float(np.mean([not v["audio_sha256"] for v in vals])), 4),
            "share_missing_request_hash": round(float(np.mean([not v["request_hash"] for v in vals])), 4),
            "share_recording_silence_flags": round(float(np.mean([v["records_silence_flags"] for v in vals])), 4),
            "median_window_flags_recorded": float(np.median([v["n_window_flags_recorded"] for v in vals])),
            "degenerate_share": round(float(np.mean([v["degenerate_share"] or 0.0 for v in vals])), 4),
            "overlap_share": round(float(np.mean([v["overlap_share"] or 0.0 for v in vals])), 4),
        }
    return out
