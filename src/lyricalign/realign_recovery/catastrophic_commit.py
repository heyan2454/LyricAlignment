"""E3 catastrophic-commit discovery over frozen baseline artifacts (WP C2).

Pure CPU, no GT, no model, no disk-write side effects: consumes a
``baseline.jsonl`` path or an in-memory list of rows and emits, per song, the
first catastrophic window commit plus 1/2/3/5-window continuation flags derived
only from the recorded ``detector_shadow`` values (the E3 shadow-only run).
"""
from __future__ import annotations

import json
import os
from typing import Callable

CONTINUATION_LENGTHS = (1, 2, 3, 5)


def _as_dict(obj):
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


def _load_jsonl(source) -> list[dict]:
    if isinstance(source, (list, tuple)):
        return [_as_dict(item) for item in source]
    path = str(source)
    if not os.path.exists(path):
        return []
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def default_is_catastrophic(shadow) -> bool:
    """True when the shadow carries a non-empty unsafe region.

    Covers both shapes: ``{"unsafe_intervals": [[start, end], ...]}`` (new
    spec) and ``{"bad_window": [start, end]}`` (legacy fixtures). A missing,
    non-dict, or empty shadow is never catastrophic.
    """
    if not isinstance(shadow, dict):
        return False
    intervals = shadow.get("unsafe_intervals")
    if isinstance(intervals, (list, tuple)) and len(intervals) > 0:
        return True
    bad_window = shadow.get("bad_window")
    if isinstance(bad_window, (list, tuple)) and len(bad_window) > 0:
        return True
    return False


def discover_catastrophic_commits(
    baseline_artifacts,
    *,
    window_index_key="window_index",
    song_key="song_id",
    shadow_key="detector_shadow",
    is_catastrophic: Callable[[dict], bool] | None = None,
) -> list[dict]:
    """Discover per-song first catastrophic commit and continuations.

    Rows are grouped by ``song_key`` and sorted by ``window_index_key``
    ascending. The first catastrophic commit is the ``window_index`` of the
    earliest catastrophic window (``None`` if there is none). For each k in
    {1, 2, 3, 5}: ``continuation[k]`` is True when the k windows immediately
    following the first commit are all catastrophic, False when at least k
    windows follow but not all are catastrophic, and None when fewer than k
    windows follow (not enough evidence to judge).

    ``is_catastrophic`` receives the shadow dict; the default is
    ``default_is_catastrophic``.
    """
    predicate = is_catastrophic if is_catastrophic is not None else default_is_catastrophic
    rows = _load_jsonl(baseline_artifacts)

    per_song: dict[str, list[dict]] = {}
    for row in rows:
        song = row.get(song_key, "song")
        per_song.setdefault(song, []).append(row)

    results: list[dict] = []
    for song, song_rows in per_song.items():
        ordered = sorted(song_rows, key=lambda r: int(r.get(window_index_key, 0)))
        flags = [bool(predicate(r.get(shadow_key))) for r in ordered]
        indices = [int(r.get(window_index_key, 0)) for r in ordered]

        first_pos = next((i for i, f in enumerate(flags) if f), None)
        catastrophic_window_indices = [indices[i] for i, f in enumerate(flags) if f]

        continuation: dict[str, bool | None] = {}
        for k in CONTINUATION_LENGTHS:
            if first_pos is None:
                continuation[str(k)] = None
                continue
            following = flags[first_pos + 1 :]
            if len(following) >= k:
                continuation[str(k)] = bool(all(following[:k]))
            else:
                continuation[str(k)] = None

        results.append(
            {
                song_key: song,
                "first_catastrophic_window_index": (
                    indices[first_pos] if first_pos is not None else None
                ),
                "catastrophic_window_indices": catastrophic_window_indices,
                "continuation": continuation,
                "n_windows": len(ordered),
            }
        )

    results.sort(key=lambda r: str(r[song_key]))
    return results
