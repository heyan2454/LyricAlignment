"""A monotone repair that cannot create zero-length units — the shadow candidate for the fix.

Round 45 proved the shipped ``fixed_*`` timestamps come from the upstream processor's
``_fix_timestamps``, which replaces an outlier block with a single constant whenever the block touches
either end of the sequence (or its two bounding good values are equal).  That makes whole windows
collapse onto one timestamp, i.e. characters with no position at all.

This module implements the minimal alternative: keep the raw (unrepaired) timestamps as anchors, then
enforce only what a timeline actually requires —

* starts strictly increasing with a minimum spacing (so no two characters share a start),
* every character at least ``min_dur`` long,
* no overlap with the next start, and nothing exceeding ``max_dur`` or the audio duration.

Because the starts are spaced by ``min_dur`` first, the end clamp is always satisfiable, so the result
is legal by construction rather than by luck.  Nothing here is wired into the product path: it exists
to measure how much the upstream collapse costs, on data where a reference is available.
"""

from __future__ import annotations

from typing import Any

import numpy as np

MIN_DUR_SEC = 0.08          # one timestamp grid step: the smallest meaningful duration
MAX_DUR_SEC = 30.0


def _count_illegal(s: np.ndarray, e: np.ndarray) -> int:
    """Units violating zero length, inversion, or non-overlap (index-safe for any length."""
    n = s.size
    if n == 0:
        return 0
    illegal = (e <= s + 1e-9) | (e < s)
    if n > 1:
        illegal = illegal.copy()
        illegal[:-1] |= e[:-1] > s[1:] + 1e-9
    return int(np.sum(illegal))


def repair_monotone_min_duration(starts, ends, *, min_dur: float = MIN_DUR_SEC,
                                 max_dur: float = MAX_DUR_SEC,
                                 duration: float | None = None) -> dict[str, Any]:
    """Return a legal, non-degenerate timeline that stays as close to the raw values as possible."""
    s = np.asarray(starts, dtype=float).copy()
    e = np.asarray(ends, dtype=float).copy()
    n = s.size
    if n == 0:
        return {"starts": s, "ends": e, "moved_starts": 0, "moved_ends": 0}
    finite = np.isfinite(s)
    if not finite.all():
        s[~finite] = np.nanmax(s[finite]) if finite.any() else 0.0
    finite_e = np.isfinite(e)
    if not finite_e.all():
        e[~finite_e] = s[~finite_e] + min_dur
    original_s = s.copy()
    original_e = e.copy()
    # 1) strictly increasing starts with at least min_dur between them
    s = np.maximum.accumulate(s)
    for i in range(1, n):
        if s[i] < s[i - 1] + min_dur:
            s[i] = s[i - 1] + min_dur
    if duration is not None and np.isfinite(duration):
        # if the tail no longer fits, pull the whole tail back rather than letting it run past the audio
        over = s[-1] + min_dur - float(duration)
        if over > 0:
            shift = min(over, max(0.0, s[0] - 0.0))
            s = np.maximum(s - shift, 0.0)
            for i in range(1, n):
                if s[i] < s[i - 1] + min_dur:
                    s[i] = s[i - 1] + min_dur
    # 2) ends: at least min_dur after their own start, never past the next start
    # the last unit has no "next start" constraint -- its only ceiling is the audio duration, so
    # clamping it to start+min_dur would silently shorten a perfectly good final timestamp
    next_start = np.concatenate([s[1:], [np.inf]])
    e = np.minimum(np.maximum(e, s + min_dur), next_start)
    e = np.minimum(e, s + max_dur)
    if duration is not None and np.isfinite(duration):
        e = np.minimum(e, float(duration))
    e = np.maximum(e, s + min_dur)                 # feasible because starts are spaced by min_dur
    overlap = np.zeros(n, dtype=bool)
    if n > 1:
        overlap[:-1] = e[:-1] > s[1:] + 1e-9
    illegal = (e < s) | (e - s <= 1e-9) | overlap
    return {"starts": s, "ends": e,
            "moved_starts": int(np.sum(np.abs(s - original_s) > 1e-9)),
            "moved_ends": int(np.sum(np.abs(e - original_e) > 1e-9)),
            "zero_length_units": int(np.sum(e - s <= 1e-9)),
            "illegal_units": int(illegal.sum()),
            "min_dur_sec": min_dur}


def repair_stage_frame(frame, *, start_col: str = "start_sec", end_col: str = "end_sec",
                       song_col: str = "song", duration_col: str | None = None,
                       repair=None) -> "Any":
    """Apply the shadow repair per song, preserving row order and the input columns."""
    import pandas as pd

    out = frame.copy()
    new_s = np.full(len(out), np.nan)
    new_e = np.full(len(out), np.nan)
    # the two repair functions report slightly different counters, so aggregate tolerantly
    diag: dict[str, Any] = {"songs": 0, "zero_length_units": 0, "illegal_units": 0,
                            "repaired_units": 0, "blocks": 0, "untouched_units": 0}
    for _, idx in out.groupby(song_col, observed=True).groups.items():
        sub = out.loc[idx]
        dur = None
        if duration_col and duration_col in sub.columns:
            vals = pd.to_numeric(sub[duration_col], errors="coerce").dropna()
            dur = float(vals.iloc[0]) if len(vals) else None
        fn = repair or repair_monotone_min_duration
        res = fn(sub[start_col].to_numpy(dtype=float),
                 sub[end_col].to_numpy(dtype=float), duration=dur)
        new_s[idx.to_numpy()] = res["starts"]
        new_e[idx.to_numpy()] = res["ends"]
        diag["songs"] += 1
        for k in ("zero_length_units", "illegal_units", "repaired_units", "blocks",
                  "untouched_units"):
            diag[k] += int(res.get(k, 0))
    out[start_col] = new_s
    out[end_col] = new_e
    return out, diag


def repair_targeted_blocks(starts, ends, *, min_dur: float = MIN_DUR_SEC,
                           max_dur: float = MAX_DUR_SEC, duration: float | None = None,
                           collapsed_run: int = 2) -> dict[str, Any]:
    """Repair *only* the collapsed / inverted stretches and leave every other timestamp untouched.

    Measured lesson (round 46): re-spacing the whole timeline removes zero-length units but also
    perturbs units that were already correct, which costs accuracy.  A collapsed block, on the other
    hand, has no usable internal timing at all, so redistributing it between its two healthy
    neighbours cannot destroy information that existed.

    A unit is treated as member of a bad block when its end does not exceed its start, or when
    ``collapsed_run`` consecutive units share the same start timestamp (the signature the upstream
    repair leaves behind).  Each block is then laid out evenly inside the span set by its neighbours,
    borrowing room from the right only when the span cannot fit ``min_dur`` per unit.
    """
    s_in = np.asarray(starts, dtype=float).copy()
    e_in = np.asarray(ends, dtype=float).copy()
    n = s_in.size
    if n == 0:
        return {"starts": s_in, "ends": e_in, "blocks": 0, "repaired_units": 0,
                "untouched_units": 0, "zero_length_units": 0}
    bad = ~(e_in > s_in + 1e-9)
    if collapsed_run >= 2:
        run = np.ones(n, dtype=int)
        for i in range(1, n):
            run[i] = run[i - 1] + 1 if abs(s_in[i] - s_in[i - 1]) <= 1e-9 else 1
        # mark every member of a run of >= collapsed_run identical starts
        for i in range(n):
            if run[i] >= collapsed_run:
                bad[i - run[i] + 1: i + 1] = True
    s, e = s_in.copy(), e_in.copy()
    blocks = repaired = 0
    i = 0
    while i < n:
        if not bad[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and bad[j + 1]:
            j += 1
        blocks += 1
        k = j - i + 1
        # the block must start after the previous unit's *end* as well as its start+min_dur, else
        # redistributing it would create an overlap with a unit we promised not to touch
        left = (max(s_in[i - 1] + min_dur, e_in[i - 1]) if i > 0
                else (0.0 if s_in[i] <= 1e-9 else s_in[i]))
        right = s_in[j + 1] if j + 1 < n else (float(duration) if (duration is not None
                                                                  and np.isfinite(duration))
                                               else s_in[j] + min_dur * k)
        span = right - left
        step = span / k if k else min_dur
        if step < min_dur:                      # not enough room: borrow from the right up to duration
            needed = min_dur * k
            if duration is not None and np.isfinite(duration):
                right = min(float(duration), left + needed)
            else:
                right = left + needed
            step = (right - left) / k
        for pos in range(k):
            s[i + pos] = left + step * pos
            e[i + pos] = min(left + step * (pos + 1), s[i + pos] + max_dur)
        e[i + k - 1] = max(e[i + k - 1], s[i + k - 1] + min_dur)
        repaired += k
        i = j + 1
    return {"starts": s, "ends": e, "blocks": blocks, "repaired_units": int(repaired),
            "untouched_units": int(n - repaired),
            "zero_length_units": int(np.sum(e - s <= 1e-9)),
            "illegal_units": int(_count_illegal(s, e)),
            "moved_units": int(np.sum((np.abs(s - s_in) > 1e-9) | (np.abs(e - e_in) > 1e-9)))}


def resolve_overlaps_locally(starts, ends, *, min_dur: float = MIN_DUR_SEC,
                            max_dur: float = MAX_DUR_SEC,
                            duration: float | None = None) -> dict[str, Any]:
    """Fix overlaps and start regressions by moving only the units that are actually broken.

    Round 47 measured the cost of the blanket route: running the joint solver over the whole timeline
    leaves the structure spotless (0.01 % illegal) but moves units that were already correct and drops
    hit@200 by 4.3 pp.  Overlaps and regressions, however, are *local* defects: a later unit starting
    before its predecessor ends.  Pushing that later start forward (cascading only through the
    following unit when it in turn collides) repairs the defect while leaving every other timestamp
    exactly where the data put it.  Ends are only trimmed when they would cross the next start.
    """
    s_in = np.asarray(starts, dtype=float).copy()
    e_in = np.asarray(ends, dtype=float).copy()
    n = s_in.size
    if n == 0:
        return {"starts": s_in, "ends": e_in, "moved_units": 0, "zero_length_units": 0,
                "illegal_units": 0, "shifts": 0}
    s, e = s_in.copy(), e_in.copy()
    shifted = 0
    for i in range(1, n):
        floor = s[i - 1] + min_dur                 # never share a start, never regress
        if s[i] < floor:
            s[i] = floor
            shifted += 1
        # trivially impossible durations get the minimum instead of zero
        if not (e[i] > s[i] + 1e-9):
            e[i] = s[i] + min_dur
    # trim ends that overrun the following start (only the violating end moves)
    if n > 1:
        over = e[:-1] > s[1:] + 1e-9
        e[:-1] = np.where(over, s[1:], e[:-1])
    e = np.minimum(e, s + max_dur)
    if duration is not None and np.isfinite(duration):
        e = np.minimum(e, float(duration))
    e = np.maximum(e, s + min_dur)
    moved = int(np.sum((np.abs(s - s_in) > 1e-9) | (np.abs(e - e_in) > 1e-9)))
    return {"starts": s, "ends": e, "moved_units": moved, "shifts": shifted,
            "zero_length_units": int(np.sum(e - s <= 1e-9)),
            "illegal_units": _count_illegal(s, e)}


def repair_all_targeted(starts, ends, *, min_dur: float = MIN_DUR_SEC,
                        max_dur: float = MAX_DUR_SEC, duration: float | None = None,
                        collapsed_run: int = 2):
    """Collapsed-block repair followed by local overlap resolution — the recommended chain."""
    res = repair_targeted_blocks(starts, ends, min_dur=min_dur, max_dur=max_dur,
                                 duration=duration, collapsed_run=collapsed_run)
    fixed = resolve_overlaps_locally(res["starts"], res["ends"], min_dur=min_dur, max_dur=max_dur,
                                     duration=duration)
    return {**res, "starts": fixed["starts"], "ends": fixed["ends"],
            "overlap_moved_units": fixed["moved_units"], "shifts": fixed["shifts"],
            "zero_length_units": fixed["zero_length_units"], "illegal_units": fixed["illegal_units"]}


#: policies for the fixed-timestamp stage, in the order they were measured (rounds 45-47)
FIXED_POLICIES = ("upstream_repaired", "raw_with_targeted_repair", "upstream_with_block_repair")

#: only these have a measured accuracy comparison against human ground truth (round 46);
#: ``upstream_with_block_repair`` is offered for experiment only and is explicitly unmeasured
MEASURED_POLICIES = ("upstream_repaired", "raw_with_targeted_repair")


def apply_fixed_timestamp_policy(raw_starts, raw_ends, official_starts, official_ends, *,
                                 policy: str = "upstream_repaired",
                                 min_dur: float = MIN_DUR_SEC,
                                 duration: float | None = None) -> dict[str, Any]:
    """Choose the fixed-stage timestamps under an explicit, recordable policy.

    * ``upstream_repaired`` (default, current product behaviour): return the upstream processor's
      values unchanged.  This is the branch that collapses whole spans onto one timestamp when its
      outlier block touches either end of the sequence (rounds 45).
    * ``raw_with_targeted_repair`` (recommended, measured): start from our own argmax timestamps and
      redistribute only the collapsed / inverted stretches, leaving every other unit exactly where the
      data put it.  Measured on GTSinger against human ground truth: zero-length 4.44 % -> 0 % and
      hit@100/200/250 ms +1.02/+1.09/+1.01 pp versus the shipped values.
    * ``upstream_with_block_repair`` (experiment only, **unmeasured**): keep the upstream values but
      redistribute their collapsed blocks, so the accuracy of the resulting timestamps is not known.
    """
    if policy not in FIXED_POLICIES:
        raise ValueError(f"unknown fixed-timestamp policy: {policy!r}; expected one of {FIXED_POLICIES}")
    o_s = np.asarray(official_starts, dtype=float)
    o_e = np.asarray(official_ends, dtype=float)
    if policy == "upstream_repaired":
        return {"starts": o_s.copy(), "ends": o_e.copy(), "policy": policy,
                "measured": policy in MEASURED_POLICIES, "changed_units": 0}
    r_s = np.asarray(raw_starts, dtype=float)
    r_e = np.asarray(raw_ends, dtype=float)
    if policy == "raw_with_targeted_repair":
        res = repair_targeted_blocks(r_s, r_e, min_dur=min_dur, duration=duration)
    else:
        res = repair_targeted_blocks(o_s, o_e, min_dur=min_dur, duration=duration)
    changed = int(np.sum((np.abs(res["starts"] - o_s) > 1e-9) | (np.abs(res["ends"] - o_e) > 1e-9)))
    return {"starts": res["starts"], "ends": res["ends"], "policy": policy,
            "measured": policy in MEASURED_POLICIES, "changed_units": changed,
            "zero_length_units": int(np.sum(res["ends"] - res["starts"] <= 1e-9)),
            "blocks_repaired": int(res.get("blocks", 0)),
            "repaired_units": int(res.get("repaired_units", 0))}


def apply_fixed_timestamp_policy_rows(rows: list[dict], *, policy: str = "upstream_repaired",
                                      segment_sec: float = 0.08,
                                      offset_sec: float = 0.0) -> tuple[list[dict], dict[str, Any]]:
    """Row-level wrapper for :func:`apply_fixed_timestamp_policy`, for the batch writer.

    Reads ``raw_local_*`` / ``official_fixed_local_*`` from the writer's row dicts, applies the chosen
    policy once for the whole window (the upstream repair also works per window), and writes the
    result into ``fixed_local_*`` and ``fixed_global_*``.  The caller is expected to pass the policy
    through unchanged from its CLI flag so the default path stays bit-identical.
    """
    if not rows:
        return rows, {"policy": policy, "units": 0, "changed_units": 0}
    raw_s = np.array([float(r.get("raw_local_start_sec", np.nan)) for r in rows], dtype=float)
    raw_e = np.array([float(r.get("raw_local_end_sec", np.nan)) for r in rows], dtype=float)
    off_s = np.array([float(r.get("official_fixed_local_start_sec",
                                 r.get("fixed_local_start_sec", np.nan))) for r in rows], dtype=float)
    off_e = np.array([float(r.get("official_fixed_local_end_sec",
                                 r.get("fixed_local_end_sec", np.nan))) for r in rows], dtype=float)
    duration = float(np.nanmax(np.concatenate([raw_e, off_e]))) + max(segment_sec, 0.08)
    res = apply_fixed_timestamp_policy(raw_s, raw_e, off_s, off_e, policy=policy,
                                       duration=duration if np.isfinite(duration) else None)
    out: list[dict] = []
    for i, row in enumerate(rows):
        new = dict(row)
        new["fixed_local_start_sec"] = float(res["starts"][i])
        new["fixed_local_end_sec"] = float(res["ends"][i])
        new["fixed_global_start_sec"] = float(res["starts"][i]) + float(offset_sec)
        new["fixed_global_end_sec"] = float(res["ends"][i]) + float(offset_sec)
        new["fixed_timestamp_policy"] = policy
        out.append(new)
    diag = {k: v for k, v in res.items() if k not in ("starts", "ends")}
    diag["units"] = len(rows)
    return out, diag
