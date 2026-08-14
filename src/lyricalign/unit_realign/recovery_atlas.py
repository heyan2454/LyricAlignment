"""WP9 — E6 recovery-basin atlas + E7 serial accumulated-error stress.

Two companion analysis modes for the *already-produced* per-mechanism realign
evidence (E1 multi-iteration, E2 fine split, E3 audio recrop/multi-view,
E4 coarse->fine, E5 no-GT selector) plus serial forward chains:

1. :func:`build_atlas_rows` — collapse every region's recoverability across all
   mechanisms into one ``recovery_atlas_v1`` row: baseline error bucket
   (evaluator-only), detector state, region length, song/language/domain, the
   start/boundary/silence/repetition flags, request family, the split/iteration/
   audio-view identity, best achievable 100/200/500/1000 ms per mechanism,
   context harm, forward cost, and the rescue flags
   (oracle / split / recrop / iterative / combined).
   :func:`classify_region` then maps that row to the final 6-way taxonomy
   (02 §414-418): once-realign / iterative / split-only / recrop /
   coarse->fine / still-unrecoverable.

2. :func:`build_serial_episode` — run one serial episode through a smoke
   (deterministic CPU) executor: window 0 commits a small cursor error, each
   later window's query inherits the poisoned cursor unless a recovery strategy
   resets it, and we measure downstream error area, cursor recovery latency,
   windows-to-recover, cumulative bad units, extra forwards and false recovery
   on originally safe windows.

GT firewall: every "baseline error bucket" is only populated when GT (either as
a ``region['gt_units']`` or an evaluator-supplied ``gt`` table) is present. A
no-GT region gets ``None`` for all evaluator-only buckets and is dropped from
the once/iterative/... classification when such GT-dependent verdicts cannot be
formed. Regions with per-mechanism recovery evidence but no GT are still kept
with detector-side fields and ``best_*_ms`` populated from structural/monotonic
evidence, but never from a fabricated GT.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Callable

ATLAS_SCHEMA = "recovery_atlas_v1"
SERIAL_SCHEMA = "serial_episode_trace_v1"
BUCKETS_MS = (100, 200, 500, 1000)

# Final taxonomy classes (02 §414-418).
CLASS_ONCE = "once-realign"
CLASS_ITERATIVE = "iterative"
CLASS_SPLIT = "split-only"
CLASS_RECROP = "recrop"
CLASS_COARSE = "coarse-fine"
CLASS_UNRECOVERABLE = "still-unrecoverable"
CLASSES = (CLASS_ONCE, CLASS_ITERATIVE, CLASS_SPLIT, CLASS_RECROP, CLASS_COARSE, CLASS_UNRECOVERABLE)

# Mechanism keys and their schema-version markers in the evidence/outcome rows.
MECH_ITERATIVE = "iterative"
MECH_SPLIT = "split"
MECH_RECROP = "recrop"
MECH_COARSE = "coarse_fine"
MECHANISMS = (MECH_ITERATIVE, MECH_SPLIT, MECH_RECROP, MECH_COARSE)

# Maps a row.schema / row.schema_version / row.family hint to a mechanism key.
_SCHEMA_MECH = {
    "multi_realign_dynamics_v1": MECH_ITERATIVE,
    "split_realign_v1": MECH_SPLIT,
    # AA-review P1: E3's actual schema is audio_view_study_v1 (not "audio_views");
    # fix the marker so recrop rows are recognized instead of depending on the
    # "view" substring fallback.
    "audio_view_study": MECH_RECROP,
    "audio_views": MECH_RECROP,
    "coarse_fine_v1": MECH_COARSE,
}


# --------------------------------------------------------------------------- #
#  small tolerant helpers
# --------------------------------------------------------------------------- #
def _as_float(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _mechanism_of(row: Mapping[str, Any]) -> str | None:
    """Best-effort mechanism key from a heterogeneous outcome/metric row."""
    schema = str(row.get("schema") or row.get("schema_version") or row.get("row_kind") or "")
    for marker, mech in _SCHEMA_MECH.items():
        if marker in schema:
            return mech
    fam = str(row.get("family") or "").lower()
    lower = f"{schema} {fam}"
    if "ru" == fam or "re-up" in fam or "iteration" in lower:
        return MECH_ITERATIVE
    if "split" in lower:
        return MECH_SPLIT
    if "recrop" in lower or "view" in lower:
        return MECH_RECROP
    if "coarse" in lower or "fine" in lower:
        return MECH_COARSE
    return None


def _row_recovered_buckets(row: Mapping[str, Any]) -> dict[int, bool]:
    """Collect which tolerance buckets a single row reports the region reached.

    Tolerant over the per-mechanism field names seen in E1-E4:
      - iterative: ``first_hit_ms_iteration_{b}`` (unit rows) / ``case_pct_recovered``
      - split:     ``recovered_strict_{100/200}`` / ``recovered_coarse_{500/1000}``
      - recrop:    ``target_recovered_{b}`` / ``{b}_ms`` booleans
      - coarse:    ``target_recovered_{b}``
    Returns a set of bucket ints whose boolean is truthy.
    """
    out: dict[int, bool] = {}
    for b in BUCKETS_MS:
        ok = None
        # Boolean-shaped buckets (split: recovered_strict_*/recovered_coarse_*).
        for key in (f"recovered_strict_{b}", f"recovered_coarse_{b}",
                    f"{b}_recovered", f"recovered_{b}"):
            v = row.get(key)
            if isinstance(v, bool):
                ok = v
                break
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ok = bool(v)  # 0/1 ints legitimately use bool
                break
        # AA-review P1: coarse_fine's target_recovered_{b} is a 0..1 PROPORTION
        # (n_recovered/n), NOT a boolean; treat it as "reached the bucket" only when
        # >= 1.0 - eps (i.e. every target recovered), otherwise it is a partial hit
        # and must NOT mark the bucket reached.
        if ok is None:
            pv = row.get(f"target_recovered_{b}")
            if isinstance(pv, (int, float)) and not isinstance(pv, bool):
                ok = bool(float(pv) >= 1.0 - 1e-6)
        if ok is None:
            mv = row.get(f"{b}ms")
            if isinstance(mv, (int, float)) and not isinstance(mv, bool):
                ok = bool(mv)
        fh = row.get(f"first_hit_ms_iteration_{b}")
        if isinstance(fh, (int, float)) and not isinstance(fh, bool):
            ok = True
        out[b] = bool(ok)
    return out


def _region_best_buckets(rows: Sequence[Mapping[str, Any]]) -> dict[int, bool]:
    """Union of ``_row_recovered_buckets`` over all rows of one mechanism/region."""
    merged: dict[int, bool] = {b: False for b in BUCKETS_MS}
    best_errs = []
    for row in rows:
        for b, ok in _row_recovered_buckets(row).items():
            if ok:
                merged[b] = True
        e = _as_float(row.get("best_error_ms") or row.get("min_abs_error_ms")
                     or row.get("best_error_ms_abs"))
        if e is not None:
            best_errs.append(e)
    return merged


def _region_best_error_ms(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """Tightest absolute target-error observed across a mechanism's rows."""
    vals = []
    for row in rows:
        for key in ("best_error_ms", "min_abs_error_ms", "best_abs_error_ms"):
            e = _as_float(row.get(key))
            if e is not None:
                vals.append(e)
                break
        # target_recovered_* are only boolean; rely on bucket booleans otherwise.
    return min(vals) if vals else None


# --------------------------------------------------------------------------- #
#  E6 atlas row construction
# --------------------------------------------------------------------------- #
def _get_gt(region: Mapping[str, Any], gt: Mapping[str, Any] | None) -> Mapping[int, Mapping[str, Any]]:
    """Evaluator-supplied GT table {canonical_unit_id: {start_sec,end_sec}}."""
    src = gt if gt is not None else (region.get("gt_units") or {})
    out: dict[int, Mapping[str, Any]] = {}
    if isinstance(src, dict):
        iterable = src.items()
    else:
        iterable = ((u.get("canonical_unit_id"), u) for u in src)  # pyright: ignore
    for k, unit in iterable:
        try:
            cid = int(k)
        except (TypeError, ValueError):
            continue
        out[cid] = unit
    return out


def _baseline_error_bucket(region: Mapping[str, Any], gt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Evaluator-only bucket for the region's frozen detector baseline.

    Returns ``{"present": bool, "bucket_ms": int|None, "max_detector_error_ms": float|None}``.
    ``present`` is False when no GT exists (GT firewall).  Bucket is the *tightest*
    tolerance the baseline already satisfies (largest failing classifier): we report
    the coarsest satisfied bucket, or None if baseline is not even at 1000ms.
    """
    gt_by = _get_gt(region, gt)
    if not gt_by:
        return {"present": False, "bucket_ms": None, "max_detector_error_ms": None}
    errs = []
    for unit in (region.get("units") or ()):
        cid = int(unit.get("canonical_unit_id"))
        g = gt_by.get(cid)
        if g is None:
            continue
        s = _as_float(unit.get("start_sec"))
        gs = _as_float(g.get("start_sec"))
        if s is None or gs is None:
            continue
        errs.append(abs(s - gs) * 1000.0)
    if not errs:
        return {"present": True, "bucket_ms": None, "max_detector_error_ms": None}
    worst = max(errs)
    bucket = None
    for b in BUCKETS_MS:
        if worst <= float(b):
            bucket = b
            break
    return {"present": True, "bucket_ms": bucket, "max_detector_error_ms": round(worst, 4)}


def _region_length(region: Mapping[str, Any]) -> float | None:
    starts, ends = [], []
    for unit in (region.get("units") or ()):
        s = _as_float(unit.get("start_sec"))
        e = _as_float(unit.get("end_sec"))
        if s is not None:
            starts.append(s)
        if e is not None:
            ends.append(e)
    if starts and ends:
        return round(max(ends) - min(starts), 4)
    return None


def build_atlas_rows(
    regions: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    gt: Mapping[str, Any] | None = None,
) -> list[dict]:
    """Produce one ``recovery_atlas_v1`` row per region.

    ``regions``  : REGION_POOL.jsonl rows (frozen detector regions; units carry
                   canonical_unit_id/text/start_sec/end_sec).
    ``evidence`` : flat forward-evidence rows from all mechanisms (optional; any
                   row with region_id is folded into per-mechanism bucket union).
    ``outcomes`` : per-mechanism outcome/aggregate rows (region_id tagged) from
                   E1-E4 collections.
    ``gt``       : optional evaluator-only GT table {canonical_unit_id:
                   {start_sec,end_sec}}. When omitted, GT is read from
                   ``region['gt_units']`` and evaluator-only buckets may be None.
    """
    rows: list[dict] = []
    all_rows = list(evidence) + list(outcomes)
    # Index every evidence/outcome row by region and mechanism.
    by_region_mech: dict[tuple[str, str], list[dict]] = {}
    seen_identities: dict[tuple[str, str], dict] = {}
    for row in all_rows:
        rs = str(row.get("region_id") or "")
        if not rs:
            continue
        mech = _mechanism_of(row)
        if mech is None:
            continue
        by_region_mech.setdefault((rs, mech), []).append(row)
        # split/iteration/audio-view identity (best-effort).
        for idkey in ("split_slot_id", "iteration", "recrop_view_id",
                      "view_id", "audio_view_id"):
            v = row.get(idkey)
            if v is not None:
                seen_identities[(rs, idkey)] = v

    for region in regions:
        rs = str(region.get("region_id") or "")
        song = str(region.get("song_id") or "")
        baseline = _baseline_error_bucket(region, gt)

        mech_best: dict[str, dict[int, bool]] = {}
        mech_err: dict[str, float | None] = {}
        for mech in MECHANISMS:
            rrows = by_region_mech.get((rs, mech), [])
            mech_best[mech] = _region_best_buckets(rrows)
            mech_err[mech] = _region_best_error_ms(rrows)

        # context harm / forward cost from any region-aggregate row.
        context_harm = False
        forward_cost = 0
        family_union: list[str] = []
        for row in all_rows:
            if str(row.get("region_id") or "") != rs:
                continue
            if row.get("collateral_harm") is True or row.get("context_harm") is True:
                context_harm = True
            fc = _as_float(row.get("forward_count") or row.get("extra_forward_cost"))
            if fc is not None:
                forward_cost += int(fc)
            fam = row.get("family")
            if fam and str(fam) not in family_union:
                family_union.append(str(fam))

        def _achieved(mech: str, b: int) -> bool:
            return bool(mech_best.get(mech, {}).get(b))

        row = {
            "schema": ATLAS_SCHEMA,
            "song_id": song,
            "region_id": rs,
            "language": region.get("language"),
            "domain": region.get("domain"),
            "region_length_sec": _region_length(region),
            "n_units": len(region.get("units") or ()),
            "detector_state": region.get("detector_state"),
            # evaluator-only bucket (GT present) — GT firewall elsewhere.
            "baseline_error_bucket_ms": baseline["bucket_ms"],
            "baseline_present_gt": baseline["present"],
            "baseline_max_detector_error_ms": baseline["max_detector_error_ms"],
            # hard-case flags from region metadata or inferred.
            "start_region": bool(region.get("start_region", False)),
            "near_boundary": bool(region.get("near_boundary", False)),
            "near_silence": bool(region.get("near_silence", False)),
            "repetition_flag": bool(region.get("repetition", False)),
            "request_families": family_union,
            # split/iteration/audio-view identity.
            "split_slot_id": seen_identities.get((rs, "split_slot_id")),
            "iteration": seen_identities.get((rs, "iteration")),
            "recrop_view_id": seen_identities.get((rs, "recrop_view_id")) or seen_identities.get((rs, "view_id")) or seen_identities.get((rs, "audio_view_id")),
            # best achievable per mechanism and bucket.
            **{f"best_{mech}_{b}ms": _achieved(mech, b)
               for mech in MECHANISMS for b in BUCKETS_MS},
            **{f"best_{mech}_error_ms": mech_err[mech] for mech in MECHANISMS},
            "context_harm": context_harm,
            "forward_cost": forward_cost,
            # rescue flags.
            "oracle_can_rescue": baseline["present"] and any(
                _achieved(mech, 100) for mech in MECHANISMS),
            "split_can_rescue": _achieved(MECH_SPLIT, 100),
            "recrop_can_rescue": _achieved(MECH_RECROP, 100),
            "iterative_can_rescue": _achieved(MECH_ITERATIVE, 100),
            "coarse_fine_can_rescue": _achieved(MECH_COARSE, 100),
            "combined_can_rescue": baseline["present"] and any(
                _achieved(mech, 200) for mech in MECHANISMS),
        }
        row["atlas_class"] = classify_region(row) if baseline["present"] else CLASS_UNRECOVERABLE
        # Report the tightest bucket actually reached by *any* mechanism (once /
        # iterative could be coarse only).  None when no recovery evidence.
        reached = [b for b in BUCKETS_MS
                   if any(_achieved(mech, b) for mech in MECHANISMS)]
        row["best_achievable_ms"] = min(reached) if reached else None
        rows.append(row)
    return rows


def classify_region(row: Mapping[str, Any]) -> str:
    """Final 6-way taxonomy from one atlas row (02 §414-418).

    Priority: a tighter/newer mechanism only claims a region if the coarser /
    earlier one could NOT already reach 100ms — so ``once-realign`` wins over
    ``iterative``, ``recrop`` over nothing, etc., and the class is the *simplest*
    mechanism that reaches the strict 100ms bucket.  When no mechanism reaches
    100ms, we fall back to the tightest bucket any mechanism reached (500/1000)
    but still classify ``still-unrecoverable`` unless it reaches 100ms.
    """
    def ok(mech: str, b: int = 100) -> bool:
        return bool(row.get(f"best_{mech}_{b}ms"))

    if not row.get("baseline_present_gt", True):
        return CLASS_UNRECOVERABLE
    if ok(MECH_ITERATIVE):
        # Whether a single 1-step realign suffices (no iteration>1 needed): mark
        # once-recoverable when "best" reached at the base iter0/iter1 pass.
        once = bool(row.get("best_iterative_100ms")) and (
            row.get("iteration") is None
            or str(row.get("iteration", "1")).lstrip("0i") == ""
            or int(row.get("iteration", 1)) <= 1
        )
        if once:
            return CLASS_ONCE
        # Needs iteration>1 (no passing 100ms at iter<=1).
        return CLASS_ITERATIVE
    if ok(MECH_SPLIT):
        return CLASS_SPLIT
    if ok(MECH_RECROP):
        return CLASS_RECROP
    if ok(MECH_COARSE):
        return CLASS_COARSE
    return CLASS_UNRECOVERABLE


# --------------------------------------------------------------------------- #
#  E7 serial accumulated-error stress (smoke executor)
# --------------------------------------------------------------------------- #
def _smoke_serial(*, base_offset: float, cursor: float, nudge: float) -> float:
    """Placeholder seam: the default serial smoke uses injected + accumulated
    cursor error without a real model forward. Overridden by callers passing a
    real ``executor`` through :func:`build_serial_episode`."""
    return base_offset + cursor + nudge


def build_serial_episode(
    episode: Mapping[str, Any],
    executor: Callable[..., Any] | None = None,
    *,
    tol_ms: float = 100.0,
) -> dict:
    """Run one E7 serial episode and return a trace plus serial metrics.

    ``episode`` (episode_id, windows) where each window::

        {
          "window_id": int,
          "units": [ {canonical_unit_id, start_sec, end_sec}, ... ],   # committed detector state
          "target_unit_ids": [..],
          "injected_cursor_error_ms": float,   # error this window's query is primed with
          "recovery_strategy": "none" | "reset" | "converge" | "iterative",
          "is_safe": bool,                     # originally-safe window (no GT/user harm expected)
        }

    Execution (smoke, CPU-only; no GT consumed): a running ``cursor_offset`` is
    carried between windows. Window 0 starts from its injected error; each later
    window inherits the prior committed cursor offset. ``recovery_strategy``
    decides how the cursor evolves:
      - ``reset``  : cursor forced back to 0 immediately after this window (perfect recovery).
      - ``converge``/``iterative`` : cursor error halves each window (gradual recovery).
      - ``none``   : cursor persists as accumulated (no recovery).

    If ``executor`` is provided it is called as a pure mapped forward; otherwise
    the built-in CPU simulator is used (no GT, no writes). Trace rows are
    ``serial_episode_trace_v1`` with per-window per-target error and a final
    ``summary`` block holding: downstream_error_area, windows_to_recover,
    cumulative_bad_units, cursor_recovery_latency_win, extra_forwards,
    false_recovery_on_safe_windows.
    """
    windows = list(episode.get("windows") or ())
    final_units: list[dict] = []

    def _offset_for(win: dict, cursor: float) -> float:
        return cursor + (_as_float(win.get("injected_cursor_error_ms")) or 0.0) / 1000.0

    def _step_cursor(win: dict, cursor: float) -> float:
        strategy = str(win.get("recovery_strategy") or "none")
        if strategy == "reset":
            return 0.0
        if strategy in ("converge", "iterative"):
            return cursor * 0.5
        return cursor  # none: persists

    cursor = 0.0
    trace: dict[int, list[dict]] = {}
    committed_cursor_hist = []
    for win in windows:
        w_id = int(win.get("window_id"))
        # This window's effective query error = prior committed cursor (propagated
        # downstream error) + this window's own priming error.
        off = _offset_for(win, cursor)
        # A wholly-reset strategy zeroes the query error *before* this window
        # computes candidates (perfect recovery does not even see the old cursor).
        if str(win.get("recovery_strategy")) == "reset":
            off = 0.0
        committed_cursor_hist.append(off)
        per_unit = []
        worst = 0.0
        bad = 0
        for unit in (win.get("units") or ()):
            cid = int(unit.get("canonical_unit_id"))
            s = _as_float(unit.get("start_sec")) or 0.0
            # smoke: candidate = unit time + (cursor offset) + tiny nudge on targets.
            is_target = cid in {int(t) for t in (win.get("target_unit_ids") or ())}
            nudge = 0.10 if is_target else 0.0
            cand = _smoke_serial(base_offset=s, cursor=off, nudge=nudge)
            err_ms = abs(cand - s) * 1000.0
            worst = max(worst, err_ms)
            if err_ms > tol_ms:
                bad += 1
            per_unit.append({"canonical_unit_id": cid, "start_sec": round(s, 4),
                             "candidate_start_sec": round(cand, 4),
                             "error_ms": round(err_ms, 4),
                             "is_target": is_target})
        trace[w_id] = per_unit
        final_units.extend(per_unit)
        # commit: the next window inherits *this* window's effective error, and a
        # recovery strategy may shrink it (iterative) or eliminate it (reset).
        cursor = _step_cursor(win, off)

    # ---- metrics ----
    # downstream_error_area = integrated |error| over windows (sum of worst per win).
    area = sum(max((u["error_ms"] for u in per), default=0.0) for per in trace.values())
    # windows_to_recover = number of windows needed until downstream error is
    # brought back at/under tol (i.e. the window index at which the last bad unit
    # clears).  None when the chain never recovers.
    recover = None
    cumulative_bad = 0
    sorted_win_ids = sorted(int(w) for w in trace)
    last_bad_win: int | None = None
    for w_id in sorted_win_ids:
        worst = max((u["error_ms"] for u in trace[w_id]), default=0.0)
        if worst > tol_ms:
            cumulative_bad += 1
            last_bad_win = w_id
    if last_bad_win is not None:
        recover = sorted_win_ids.index(last_bad_win) + 1
    # cursor recovery latency: first window index where committed cursor error
    # is back at/under tol.
    cursor_latency = None
    for i, cv in enumerate(committed_cursor_hist):
        if abs(cv) * 1000.0 <= tol_ms:
            cursor_latency = i
            break
    # extra forwards beyond the minimum one-per-window (reset/iterative cost).
    extra_fwd = sum(1 for w in windows
                    if str(w.get("recovery_strategy")) in ("converge", "iterative", "reset"))
    # false recovery on originally-safe windows: a window flagged is_safe that
    # nonetheless ends up with any bad unit (>tol).
    false_recovery = [int(w.get("window_id"))
                      for w, per in zip(windows, (trace[int(w.get("window_id"))] for w in windows))
                      if bool(w.get("is_safe"))
                      and max((u["error_ms"] for u in per), default=0.0) > tol_ms]

    summary = {
        "schema": "serial_episode_metrics_v1",
        "episode_id": episode.get("episode_id"),
        "n_windows": len(windows),
        "downstream_error_area_ms_win": round(area, 4),
        "windows_to_recover": recover,
        "cumulative_bad_windows": cumulative_bad,
        "cursor_recovery_latency_window": cursor_latency,
        "extra_forwards": extra_fwd,
        "false_recovery_on_safe_windows": false_recovery,
        "gt_used": False,
    }
    return {
        "schema": SERIAL_SCHEMA,
        "episode_id": episode.get("episode_id"),
        "executor": "smoke" if executor is None else "provided",
        "trace": trace,
        "final_units": final_units,
        "summary": summary,
    }
