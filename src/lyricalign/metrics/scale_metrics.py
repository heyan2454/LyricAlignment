"""Test-scale interval metrics plus per-song storage, for checkpoint selection after the fact.

Named `scale_metrics` and **not** `test_scale` on purpose: a module whose filename matches pytest's
default `test_*.py` collection pattern is imported as a test module by a bare `pytest` run, and its
`test_scale_metrics(...)` entry point then errors out as a missing-fixture test.

The training loop's own metric (`character_interval_metrics_v3_tolerant`) aggregates
`(onset_err + offset_err) / 2` and reports tolerances of 80/160/240 ms, while the project's test
reporting uses `max(onset_err, offset_err)` at 100/200/250 ms.  Selecting a checkpoint on one scale
and reporting on the other makes the two disagree by construction, so this module recomputes the
**test-scale** numbers and keeps **per-song** values, which is what makes an after-the-fact
sweep able to answer "is this difference real?" (standard error) as well as "which step is best".

It also separates the two failure channels that the existing scalar mixes together: a unit that was
never usable (zero-length / duplicate / missing) and a unit that got a timing answer that is simply
wrong.  Collapsing the first into a ≥1 s penalty makes one number, but hides which of the two moved.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np

DEFAULT_TOLERANCES_SEC = (0.10, 0.20, 0.25)


def _key(row: dict[str, Any]) -> tuple[Any, Any]:
    return (row["item_id"], int(row["character_index"]))


def index_predictions(prediction: Iterable[dict[str, Any]]) -> dict[tuple[Any, Any], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in prediction:
        grouped[_key(row)].append(row)
    return grouped


def _usable(row: dict[str, Any]) -> bool:
    start, end = row.get("start_sec"), row.get("end_sec")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return False
    if isinstance(start, bool) or isinstance(end, bool):
        return False
    if not np.isfinite(float(start)) or not np.isfinite(float(end)):
        return False
    return 0.0 <= float(start) < float(end)


def collapse_runs(prediction: list[dict[str, Any]], *, group_by: str = "song_id",
                  min_run: int = 5) -> dict[str, int]:
    """Longest stretch of consecutive units sharing one start timestamp (the collapse fingerprint)."""

    def _f(row: dict[str, Any], name: str, default: float = float("nan")) -> float:
        value = row.get(name)
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prediction:
        by_group[str(row.get(group_by) or row.get("item_id"))].append(row)
    longest = 0
    blocks = 0
    units = 0
    for rows in by_group.values():
        rows = sorted(rows, key=lambda r: int(r["character_index"]))
        starts = [_f(r, "start_sec") for r in rows]
        ends = [_f(r, "end_sec") for r in rows]
        i = 0
        while i < len(rows):
            if not (np.isfinite(starts[i]) and ends[i] - starts[i] <= 1e-9):
                i += 1
                continue
            j = i
            while (j + 1 < len(rows) and np.isfinite(starts[j + 1])
                   and ends[j + 1] - starts[j + 1] <= 1e-9
                   and abs(starts[j + 1] - starts[i]) <= 1e-9):
                j += 1
            length = j - i + 1
            if length >= min_run:
                blocks += 1
                units += length
                longest = max(longest, length)
            i = j + 1
    return {"collapse_blocks": blocks, "collapse_units": units, "collapse_longest_run": longest}


def test_scale_metrics(reference: list[dict[str, Any]], prediction: list[dict[str, Any]], *,
                       tolerances: tuple[float, ...] = DEFAULT_TOLERANCES_SEC,
                       identity_penalty_sec: float = 1.0) -> dict[str, Any]:
    """Compute test-scale (max boundary error) hit rates and MAE, overall and per song.

    A unit counts as *usable* only when exactly one finite prediction with ``start < end`` exists for
    it; everything else is unusable and fails every tolerance while still carrying an
    ``identity_penalty_sec``-floor error, mirroring the training-loop convention so the two are
    comparable.  `*_valid_only` restricts the denominator to usable units, which is the timing-only
    view of the same forward pass.
    """
    ref = {_key(row): row for row in reference}
    grouped = index_predictions(prediction)
    per_song: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"err": [], "usable": []})
    rows_out: list[dict[str, Any]] = []
    for key, expected in ref.items():
        rows = grouped.get(key, [])
        actual = rows[0] if len(rows) == 1 and _usable(rows[0]) else None
        target = (float(expected["start_sec"]), float(expected["end_sec"]))
        if actual is None:
            err = max(identity_penalty_sec, target[1] - target[0])
            usable = 0.0
        else:
            err = max(abs(float(actual["start_sec"]) - target[0]),
                      abs(float(actual["end_sec"]) - target[1]))
            usable = 1.0
        song = str(expected.get("song_id") or expected["item_id"])
        per_song[song]["err"].append(err)
        per_song[song]["usable"].append(usable)
        rows_out.append({"item_id": expected["item_id"], "song_id": song,
                         "character_index": int(expected["character_index"]),
                         "max_boundary_err_sec": round(err, 6), "usable": bool(usable)})

    count = len(ref)
    all_err = np.array([r["max_boundary_err_sec"] for r in rows_out], dtype=float)
    usable_mask = np.array([r["usable"] for r in rows_out], dtype=bool)
    out: dict[str, Any] = {
        "metric_schema_version": "test_scale_interval_metrics_v1",
        "reference_count": count,
        "usable_rate": round(float(usable_mask.mean()), 4) if count else None,
        "unusable_count": int(count - usable_mask.sum()),
        "mae_all_ms": round(float(np.mean(all_err)) * 1000, 2) if count else None,
        "mae_valid_only_ms": (round(float(np.mean(all_err[usable_mask])) * 1000, 2)
                              if usable_mask.any() else None),
        "per_song": {},
    }
    valid_err = all_err[usable_mask]
    for tol in tolerances:
        tag = f"{int(tol * 1000)}ms"
        out[f"within_{tag}_all"] = round(float((all_err <= tol).mean()), 4) if count else None
        out[f"within_{tag}_valid_only"] = (round(float((valid_err <= tol).mean()), 4)
                                           if valid_err.size else None)
    # A fixed-tolerance hit rate saturates once the bulk of the error distribution sits well inside
    # the tolerance (that is the regime this project is in: MAE ~55-65 ms against a 200 ms window).
    # Percentiles of the per-unit max-boundary error keep the resolution of the continuous error
    # while staying comparable across checkpoints; they are cheap and never replace the rates above.
    if count:
        out["error_percentiles_ms"] = {
            f"p{int(q * 100)}": round(float(np.percentile(valid_err if valid_err.size else all_err, q * 100)) * 1000, 2)
            for q in (0.25, 0.5, 0.75, 0.9, 0.95, 0.99)}
        out["error_percentiles_scope"] = "valid_units" if valid_err.size else "all_units"
    song_within: dict[str, dict[str, Any]] = {}
    for song, values in per_song.items():
        err = np.array(values["err"], dtype=float)
        us = np.array(values["usable"], dtype=bool)
        entry: dict[str, Any] = {"units": int(err.size), "usable_rate": round(float(us.mean()), 4),
                                 "mae_all_ms": round(float(np.mean(err)) * 1000, 2)}
        for tol in tolerances:
            entry[f"within_{int(tol * 1000)}ms"] = round(float((err <= tol).mean()), 4)
        song_within[song] = entry
    out["per_song"] = song_within
    primary_tag = f"within_{int(tolerances[1] * 1000)}ms"
    song_primary = np.array([entry[primary_tag] for entry in song_within.values()], dtype=float)
    if song_primary.size:
        out["primary_tolerance_sec"] = tolerances[1]
        out["macro_song_within_primary"] = round(float(song_primary.mean()), 4)
        out["macro_song_se_primary"] = (
            round(float(song_primary.std(ddof=1) / np.sqrt(song_primary.size)), 4)
            if song_primary.size > 1 else None)
        out["song_count"] = int(song_primary.size)
    out.update(collapse_runs(prediction))
    out["per_unit"] = rows_out
    return out


def select_with_one_se(candidates: list[dict[str, Any]], *, score_key: str,
                       se_key: str | None = None, higher_is_better: bool = True,
                       step_key: str = "step") -> dict[str, Any]:
    """Pick the earliest checkpoint within one standard error of the best score.

    Dense validation makes the raw argmin/argmax a noise picker; the one-standard-error rule keeps
    the reported choice on the plateau's near side, which is also the cheaper and more robust model.
    """
    scored = [c for c in candidates if isinstance(c.get(score_key), (int, float))]
    if not scored:
        return {"selected_step": None, "reason": "no scored candidates"}
    best = max(scored, key=lambda c: c[score_key]) if higher_is_better else \
        min(scored, key=lambda c: c[score_key])
    se = best.get(se_key) if se_key else best.get("macro_song_se_primary")
    if not isinstance(se, (int, float)) or se <= 0:
        chosen = best
        rule = "argmax"
    else:
        threshold = best[score_key] - se if higher_is_better else best[score_key] + se
        near = [c for c in scored if (c[score_key] >= threshold if higher_is_better
                                     else c[score_key] <= threshold)]
        chosen = min(near, key=lambda c: c.get(step_key, 0))
        rule = "one_standard_error_earliest"
    return {"selected_step": chosen.get(step_key), "rule": rule,
            "selected_score": chosen.get(score_key), "best_step": best.get(step_key),
            "best_score": best[score_key], "one_se": (round(float(se), 4)
                                                      if isinstance(se, (int, float)) else None),
            "candidates": len(scored)}
