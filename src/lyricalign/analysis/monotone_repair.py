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
