"""Silence-aware context construction for mechanism (R-U/R-S/R-CF) regions.

Root cause fixed here: region builders previously picked context purely by
lyric-id continuity (``global_character_index +/- N``), ignoring time/silence
gaps.  Units separated by a long unvoiced interval (e.g. 30 s) were therefore
bundled into the same region as text context / fixed slots, even though
acoustically they belong to different segments (evidence: 月半 a16 id236@119.8s
vs id237@151.3s; E1 40-region manifest 36 regions with internal gap > 1 s).

This module adds an optional, parameterized silence-gap cutoff.  The default is
aligned with the frozen baseline ``strong_silence_anchor_sec`` (1.5 s) used by
Current/B4 window planning (window_planning.py: "strong" silence >= that
length), so mechanism regions share the same silence-boundary semantics as the
Current/B4 serial baseline.  Pass ``gap_sec=None`` (or 0) to keep the legacy
pure-id behavior.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def split_into_time_clusters(
    units: Sequence[Mapping[str, Any]],
    gap_sec: float | None,
) -> list[list[Mapping[str, Any]]]:
    """Sort units by start_sec and split wherever the gap between consecutive
    units (next.start - prev.end) exceeds ``gap_sec``.

    ``gap_sec`` None/<=0 disables splitting (single cluster).  Each returned
    cluster keeps ascending time order.  Units whose start/end are missing are
    treated as gap=0 neighbours (never split on them).
    """
    if not units:
        return []
    ordered = sorted(
        units,
        key=lambda u: float(u.get("start_sec") or u.get("selected_start_sec") or 0),
    )
    if gap_sec is None or float(gap_sec) <= 0:
        return [ordered]
    clusters: list[list[Mapping[str, Any]]] = [[ordered[0]]]
    for u in ordered[1:]:
        prev = clusters[-1][-1]
        prev_end = float(prev.get("end_sec") or prev.get("selected_end_sec") or prev.get("start_sec") or 0)
        cur_start = float(u.get("start_sec") or u.get("selected_start_sec") or 0)
        gap = cur_start - prev_end
        if gap > float(gap_sec):
            clusters.append([u])
        else:
            clusters[-1].append(u)
    return clusters


def context_units_silence_aware(
    all_chars: Sequence[Mapping[str, Any]],
    anchor_ids: Sequence[int],
    gap_sec: float | None,
    context_neighbors: int = 3,
) -> list[Mapping[str, Any]]:
    """Build the local units for a region around ``anchor_ids``.

    Legacy behavior took ``all_chars`` ids within
    ``[min(anchor_ids)-N, max(anchor_ids)+N]`` (pure id window).  This version
    first applies that id window, then keeps only the time cluster(s) that are
    silence-contiguous with the anchors: any unit whose gap to its neighbour
    exceeds ``gap_sec`` is not carried across the gap.

    Returns units in ascending global_character_index order (as before), with
    only the anchor-connected cluster(s) retained.
    """
    ids = {int(c.get("global_character_index", -1)) for c in all_chars}
    if not anchor_ids or not ids:
        return []
    lo = min(anchor_ids) - context_neighbors
    hi = max(anchor_ids) + context_neighbors
    window = [
        c for c in all_chars
        if lo <= int(c.get("global_character_index", -1)) <= hi
    ]
    if gap_sec is None or float(gap_sec) <= 0:
        return sorted(window, key=lambda c: int(c.get("global_character_index", -1)))
    clusters = split_into_time_clusters(window, gap_sec)
    anchor_set = set(anchor_ids)
    kept: list[Mapping[str, Any]] = []
    for cluster in clusters:
        cluster_ids = {int(c.get("global_character_index", -1)) for c in cluster}
        if cluster_ids & anchor_set:
            kept.extend(cluster)
    return sorted(kept, key=lambda c: int(c.get("global_character_index", -1)))
