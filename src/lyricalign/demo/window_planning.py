"""Silence-aware serial window planning for lyric alignment demos."""
from __future__ import annotations

import math
from typing import Any, Sequence


def _intervals_from_mask(mask: Sequence[bool], *, hop_sec: float, duration_sec: float, value: bool) -> list[dict[str, float]]:
    intervals: list[dict[str, float]] = []
    start: int | None = None
    for index, item in enumerate(mask):
        match = bool(item) is value
        if match and start is None:
            start = index
        elif not match and start is not None:
            intervals.append({"start_sec": start * hop_sec, "end_sec": min(duration_sec, index * hop_sec)})
            start = None
    if start is not None:
        intervals.append({"start_sec": start * hop_sec, "end_sec": duration_sec})
    return [row for row in intervals if row["end_sec"] > row["start_sec"] + 1e-9]


def detect_silence_intervals(
    profile: dict[str, Any], *, duration_sec: float, min_silence_sec: float,
    strong_silence_sec: float,
) -> list[dict[str, Any]]:
    """Return sustained-inactivity intervals as reusable stable-boundary evidence."""
    hop = float(profile["hop_sec"])
    raw = _intervals_from_mask(profile["sustained"], hop_sec=hop, duration_sec=duration_sec, value=False)
    result: list[dict[str, Any]] = []
    for ordinal, row in enumerate(raw):
        length = float(row["end_sec"] - row["start_sec"])
        if length + 1e-9 < min_silence_sec:
            continue
        result.append({
            "silence_id": f"silence_{ordinal:04d}",
            "start_sec": float(row["start_sec"]),
            "end_sec": float(row["end_sec"]),
            "duration_sec": length,
            "strength": "strong" if length + 1e-9 >= strong_silence_sec else "normal",
            "source": "vocal_sustained_inactivity",
        })
    return result


def _containing_silence(value: float, intervals: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    for row in intervals:
        if float(row["start_sec"]) - 1e-9 <= value <= float(row["end_sec"]) + 1e-9:
            return row
    return None


def _snap_internal_boundaries(
    boundaries: list[float], *, intervals: Sequence[dict[str, Any]], search_sec: float,
    minimum_core_sec: float,
) -> tuple[list[float], list[dict[str, Any]]]:
    if len(boundaries) <= 2 or search_sec <= 0:
        return boundaries, []
    selected = [boundaries[0]]
    diagnostics: list[dict[str, Any]] = []
    final_end = boundaries[-1]
    for position, nominal in enumerate(boundaries[1:-1], start=1):
        remaining_boundaries = len(boundaries) - position - 1
        candidates: list[tuple[float, float, dict[str, Any]]] = []
        for interval in intervals:
            midpoint = (float(interval["start_sec"]) + float(interval["end_sec"])) / 2.0
            if abs(midpoint - nominal) > search_sec + 1e-9:
                continue
            if midpoint - selected[-1] < minimum_core_sec - 1e-9:
                continue
            if final_end - midpoint < remaining_boundaries * minimum_core_sec - 1e-9:
                continue
            candidates.append((abs(midpoint - nominal), -float(interval["duration_sec"]), interval))
        if candidates:
            _, _, interval = min(candidates, key=lambda item: (item[0], item[1], item[2]["silence_id"]))
            chosen = (float(interval["start_sec"]) + float(interval["end_sec"])) / 2.0
            source = "silence_snap"
            silence_id = interval["silence_id"]
        else:
            chosen = nominal
            source = "nominal"
            silence_id = None
        selected.append(chosen)
        diagnostics.append({
            "boundary_position": position,
            "nominal_sec": float(nominal),
            "selected_sec": float(chosen),
            "source": source,
            "silence_id": silence_id,
        })
    selected.append(boundaries[-1])
    return selected, diagnostics


def _rebalance_short_tail(boundaries: list[float], *, minimum_tail_sec: float) -> tuple[list[float], dict[str, Any]]:
    """Remove a short tail and share its duration across the two prior windows.

    For [... A, B, C, END], tail=END-C is removed.  Its duration is split
    equally by replacing B with B+tail/2 and removing C, yielding
    [... A, B+tail/2, END].  If the tail has only one preceding window, both
    are merged into one.
    """
    if len(boundaries) <= 2:
        return boundaries, {"action": "none", "reason": "single_window"}
    tail = float(boundaries[-1] - boundaries[-2])
    if tail + 1e-9 >= minimum_tail_sec:
        return boundaries, {"action": "none", "tail_duration_sec": tail}
    window_count = len(boundaries) - 1
    if window_count == 2:
        return [boundaries[0], boundaries[-1]], {
            "action": "merge_tail_with_only_previous_window",
            "tail_duration_sec": tail,
            "result_window_count": 1,
        }
    a, b, c, end = boundaries[-4], boundaries[-3], boundaries[-2], boundaries[-1]
    new_boundary = b + tail / 2.0
    result = boundaries[:-4] + [a, new_boundary, end]
    return result, {
        "action": "distribute_tail_across_two_previous_windows",
        "tail_duration_sec": tail,
        "removed_boundary_sec": c,
        "shifted_boundary_from_sec": b,
        "shifted_boundary_to_sec": new_boundary,
        "added_to_each_previous_window_sec": tail / 2.0,
        "result_window_count": len(result) - 1,
    }


def build_silence_aware_window_plan(
    duration_sec: float,
    profile: dict[str, Any],
    *,
    target_core_sec: float,
    left_context_sec: float,
    right_context_sec: float,
    min_silence_sec: float = 0.8,
    strong_silence_sec: float = 1.5,
    boundary_search_sec: float = 6.0,
    leading_silence_min_sec: float = 2.0,
    tail_min_core_sec: float = 18.0,
    minimum_core_sec: float = 12.0,
) -> dict[str, Any]:
    if duration_sec <= 0 or target_core_sec <= 0:
        raise ValueError("duration_sec and target_core_sec must be positive")
    intervals = detect_silence_intervals(
        profile, duration_sec=duration_sec, min_silence_sec=min_silence_sec,
        strong_silence_sec=strong_silence_sec,
    )
    soft = _soft_plan_in_span(
        0.0, float(duration_sec), intervals,
        target_core_sec=target_core_sec,
        boundary_search_sec=boundary_search_sec,
        leading_silence_min_sec=leading_silence_min_sec,
        tail_min_core_sec=tail_min_core_sec,
        minimum_core_sec=minimum_core_sec,
    )
    active_start = soft["active_start_sec"]
    active_end = soft["active_end_sec"]
    leading = soft["leading_silence_skipped"]
    trailing = soft["trailing_silence_skipped"]
    boundaries = soft["initial_boundaries_sec"]
    snapped = soft["snapped_boundaries_sec"]
    balanced = soft["final_boundaries_sec"]
    snap_diagnostics = soft["boundary_snap_diagnostics"]
    tail_diagnostic = soft["tail_adjustment"]

    windows: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(balanced[:-1], balanced[1:], strict=True)):
        start_anchor = _containing_silence(start, intervals)
        end_anchor = _containing_silence(end, intervals)
        windows.append({
            "window_index": index,
            "core_start_sec": float(start),
            "core_end_sec": float(end),
            "core_duration_sec": float(end - start),
            "input_start_sec": max(0.0, float(start) - left_context_sec),
            "input_end_sec": min(duration_sec, float(end) + right_context_sec),
            "is_final_core": index == len(balanced) - 2,
            "window_plan_policy": "silence_aware_global_v1",
            "core_start_silence_id": None if start_anchor is None else start_anchor["silence_id"],
            "core_end_silence_id": None if end_anchor is None else end_anchor["silence_id"],
        })

    return {
        "schema_version": "silence_aware_window_plan_v1",
        "policy": "target_core_with_silence_snap_and_tail_redistribution",
        "duration_sec": float(duration_sec),
        "target_core_sec": float(target_core_sec),
        "active_span_start_sec": float(active_start),
        "active_span_end_sec": float(active_end),
        "active_span_duration_sec": float(active_end - active_start),
        "leading_silence_skipped": leading,
        "trailing_silence_skipped": trailing,
        "silence_intervals": intervals,
        "initial_boundaries_sec": [float(value) for value in boundaries],
        "snapped_boundaries_sec": [float(value) for value in snapped],
        "final_boundaries_sec": [float(value) for value in balanced],
        "boundary_snap_diagnostics": snap_diagnostics,
        "tail_adjustment": tail_diagnostic,
        "windows": windows,
        "parameters": {
            "min_silence_sec": float(min_silence_sec),
            "strong_silence_sec": float(strong_silence_sec),
            "boundary_search_sec": float(boundary_search_sec),
            "leading_silence_min_sec": float(leading_silence_min_sec),
            "tail_min_core_sec": float(tail_min_core_sec),
            "minimum_core_sec": float(minimum_core_sec),
            "left_context_sec": float(left_context_sec),
            "right_context_sec": float(right_context_sec),
        },
    }


def _active_regions_from_strict_silence(
    duration_sec: float,
    intervals: Sequence[dict[str, Any]],
    *,
    strict_silence_sec: float,
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    """Return active regions separated by silences that are strict boundaries."""
    strict = [
        dict(row) for row in intervals
        if float(row["duration_sec"]) + 1e-9 >= strict_silence_sec
    ]
    strict.sort(key=lambda row: float(row["start_sec"]))
    regions: list[dict[str, float]] = []
    cursor = 0.0
    for silence in strict:
        start = max(cursor, float(silence["start_sec"]))
        end = min(duration_sec, float(silence["end_sec"]))
        if start > cursor + 1e-6:
            regions.append({"start_sec": cursor, "end_sec": start})
        cursor = max(cursor, end)
    if cursor < duration_sec - 1e-6:
        regions.append({"start_sec": cursor, "end_sec": float(duration_sec)})
    return regions, strict


def _soft_plan_in_span(
    span_start: float,
    span_end: float,
    intervals: Sequence[dict[str, Any]],
    *,
    target_core_sec: float,
    boundary_search_sec: float,
    leading_silence_min_sec: float,
    tail_min_core_sec: float,
    minimum_core_sec: float,
) -> dict[str, Any]:
    """Run the silence-aware soft windowing logic on an arbitrary time span.

    This is the shared core of ``build_silence_aware_window_plan`` (whole-song
    span) and ``build_strict_silence_boundary_window_plan`` (one active region
    per call).  ``intervals`` must already be restricted to the span; all
    returned times are absolute.  The caller owns leading/trailing semantics
    identical to the whole-song planner: a silence anchored at the span start
    (>= leading_silence_min_sec) trims the active span, and likewise at the end.
    """
    active_start = float(span_start)
    active_end = float(span_end)
    leading = next((row for row in intervals if float(row["start_sec"]) <= float(span_start) + 1e-9), None)
    if leading is not None and float(leading["duration_sec"]) + 1e-9 >= leading_silence_min_sec:
        active_start = float(leading["end_sec"])
    trailing = next((row for row in reversed(intervals) if float(row["end_sec"]) >= float(span_end) - 1e-9), None)
    if trailing is not None and float(trailing["duration_sec"]) + 1e-9 >= leading_silence_min_sec:
        active_end = float(trailing["start_sec"])
    if active_end <= active_start + 1e-6:
        active_start, active_end = float(span_start), float(span_end)
        leading = trailing = None

    boundaries = [active_start]
    cursor = active_start + target_core_sec
    while cursor < active_end - 1e-9:
        boundaries.append(cursor)
        cursor += target_core_sec
    boundaries.append(active_end)
    snapped, snap_diagnostics = _snap_internal_boundaries(
        boundaries, intervals=intervals, search_sec=boundary_search_sec,
        minimum_core_sec=minimum_core_sec,
    )
    balanced, tail_diagnostic = _rebalance_short_tail(snapped, minimum_tail_sec=tail_min_core_sec)

    return {
        "active_start_sec": float(active_start),
        "active_end_sec": float(active_end),
        "leading_silence_skipped": leading,
        "trailing_silence_skipped": trailing,
        "initial_boundaries_sec": [float(value) for value in boundaries],
        "snapped_boundaries_sec": [float(value) for value in snapped],
        "final_boundaries_sec": [float(value) for value in balanced],
        "boundary_snap_diagnostics": snap_diagnostics,
        "tail_adjustment": tail_diagnostic,
    }


def _subdivide_region(
    start_sec: float,
    end_sec: float,
    *,
    target_core_sec: float,
    minimum_core_sec: float,
    tail_min_core_sec: float,
) -> list[float]:
    boundaries = [float(start_sec)]
    cursor = float(start_sec) + float(target_core_sec)
    while cursor < end_sec - 1e-9:
        boundaries.append(cursor)
        cursor += float(target_core_sec)
    boundaries.append(float(end_sec))
    if len(boundaries) > 2:
        boundaries, _ = _rebalance_short_tail(boundaries, minimum_tail_sec=tail_min_core_sec)
    # Avoid creating a tiny first/only core after strict-silence trimming.
    if len(boundaries) > 2 and boundaries[1] - boundaries[0] < minimum_core_sec:
        boundaries.pop(1)
    return boundaries


def build_strict_silence_boundary_window_plan(
    duration_sec: float,
    profile: dict[str, Any],
    *,
    target_core_sec: float,
    left_context_sec: float,
    right_context_sec: float,
    min_silence_sec: float = 0.8,
    strong_silence_sec: float = 1.5,
    strict_silence_sec: float | None = None,
    boundary_search_sec: float = 6.0,
    leading_silence_min_sec: float = 2.0,
    tail_min_core_sec: float = 18.0,
    minimum_core_sec: float = 12.0,
) -> dict[str, Any]:
    """Build windows whose model inputs never cross a strong-silence boundary.

    Unlike the ordinary silence-aware planner, this planner treats sufficiently
    long silence (>= ``strict_silence_sec``) as a hard acoustic boundary: the
    timeline is split into active regions separated by those silences, and the
    *same soft logic as the whole-song planner* (target-core cursor, silence
    snap inside the region, short-tail redistribution, leading/trailing trim)
    runs **independently inside each active region**.  Small island regions
    never participate in another region's split — each region yields its own
    windows.  The silent gap remains on the global timeline, but neither
    neighboring model input contains its body: input intervals are clipped to
    their region, so no input/transcript crop crosses a strict silence.
    """
    if duration_sec <= 0 or target_core_sec <= 0:
        raise ValueError("duration_sec and target_core_sec must be positive")
    strict_threshold = float(strict_silence_sec or strong_silence_sec)
    intervals = detect_silence_intervals(
        profile,
        duration_sec=duration_sec,
        min_silence_sec=min_silence_sec,
        strong_silence_sec=strong_silence_sec,
    )
    regions, strict = _active_regions_from_strict_silence(
        duration_sec, intervals, strict_silence_sec=strict_threshold,
    )
    windows: list[dict[str, Any]] = []
    region_diagnostics: list[dict[str, Any]] = []
    for region_index, region in enumerate(regions):
        region_start = float(region["start_sec"])
        region_end = float(region["end_sec"])
        if region_end <= region_start + 1e-6:
            continue
        # restrict the silence evidence to this active region; a strict
        # silence is a hard boundary so no interval straddles the region edges
        local = [
            dict(row) for row in intervals
            if float(row["end_sec"]) > region_start + 1e-9
            and float(row["start_sec"]) < region_end - 1e-9
        ]
        for row in local:
            row["start_sec"] = max(float(row["start_sec"]), region_start)
            row["end_sec"] = min(float(row["end_sec"]), region_end)
            row["duration_sec"] = float(row["end_sec"]) - float(row["start_sec"])
        soft = _soft_plan_in_span(
            region_start, region_end, local,
            target_core_sec=target_core_sec,
            boundary_search_sec=boundary_search_sec,
            leading_silence_min_sec=leading_silence_min_sec,
            tail_min_core_sec=tail_min_core_sec,
            minimum_core_sec=minimum_core_sec,
        )
        balanced = soft["final_boundaries_sec"]
        region_diagnostics.append({
            "region_index": region_index,
            "start_sec": region_start,
            "end_sec": region_end,
            "boundaries_sec": balanced,
            "soft_plan": soft,
        })
        for local_index, (core_start, core_end) in enumerate(zip(balanced[:-1], balanced[1:], strict=True)):
            windows.append({
                "window_index": len(windows),
                "region_index": region_index,
                "region_window_index": local_index,
                "core_start_sec": float(core_start),
                "core_end_sec": float(core_end),
                "core_duration_sec": float(core_end - core_start),
                "input_start_sec": max(region_start, float(core_start) - left_context_sec),
                "input_end_sec": min(region_end, float(core_end) + right_context_sec),
                "is_final_core": False,
                "is_final_region_core": local_index == len(balanced) - 2,
                "strict_boundary_cursor_policy": "per_region_soft_continue_from_committed_cursor",
                "window_plan_policy": "strict_silence_boundary_v1",
                "strict_region_start_sec": region_start,
                "strict_region_end_sec": region_end,
                "context_crosses_strict_silence": False,
            })
    if windows:
        windows[-1]["is_final_core"] = True
    return {
        "schema_version": "strict_silence_boundary_window_plan_v2",
        "policy": "hard_split_at_strong_silence_then_per_region_soft",
        "duration_sec": float(duration_sec),
        "target_core_sec": float(target_core_sec),
        "active_span_start_sec": float(regions[0]["start_sec"]) if regions else 0.0,
        "active_span_end_sec": float(regions[-1]["end_sec"]) if regions else float(duration_sec),
        "active_span_duration_sec": float(sum(float(region["end_sec"])-float(region["start_sec"]) for region in regions)),
        "strict_silence_sec": strict_threshold,
        "silence_intervals": intervals,
        "strict_silence_intervals": strict,
        "active_regions": regions,
        "region_diagnostics": region_diagnostics,
        "windows": windows,
        "parameters": {
            "min_silence_sec": float(min_silence_sec),
            "strong_silence_sec": float(strong_silence_sec),
            "strict_silence_sec": strict_threshold,
            "left_context_sec": float(left_context_sec),
            "right_context_sec": float(right_context_sec),
            "boundary_search_sec": float(boundary_search_sec),
            "leading_silence_min_sec": float(leading_silence_min_sec),
            "tail_min_core_sec": float(tail_min_core_sec),
            "minimum_core_sec": float(minimum_core_sec),
        },
    }


def compress_silence_audio(
    audio: Any,
    profile: dict[str, Any],
    *,
    sample_rate: int = 16000,
    min_silence_sec: float = 0.8,
    strong_silence_sec: float = 1.5,
    remove_silence_sec: float | None = None,
    keep_edge_padding_sec: float = 0.20,
    trim_to_sec: float | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Remove/trim long-silence interiors and return a reversible time mapping.

    This is a diagnostic counterfactual, not the production window policy.  A
    short edge padding is retained on both sides of each removed interval to
    avoid cutting directly into vocal activity.

    ``trim_to_sec`` selects the "compress to N seconds" mode: every silence
    interval at least ``remove_silence_sec`` long keeps exactly
    ``min(duration, trim_to_sec)`` seconds (split symmetrically, interior
    removed) instead of being removed down to the edge padding.  This keeps a
    short silence marker between active regions so that strict-boundary
    semantics survive compression.  When ``trim_to_sec`` is None the legacy
    removal behavior (keep only ``keep_edge_padding_sec`` on each side) is
    unchanged.
    """
    import numpy as np

    samples = np.asarray(audio)
    duration_sec = float(len(samples) / sample_rate)
    threshold = float(remove_silence_sec or strong_silence_sec)
    detected = detect_silence_intervals(
        profile,
        duration_sec=duration_sec,
        min_silence_sec=min_silence_sec,
        strong_silence_sec=strong_silence_sec,
    )
    removed: list[dict[str, float]] = []
    for row in detected:
        if float(row["duration_sec"]) + 1e-9 < threshold:
            continue
        row_start = float(row["start_sec"])
        row_end = float(row["end_sec"])
        if trim_to_sec is not None:
            keep = min(float(row["duration_sec"]), float(trim_to_sec))
            half = keep / 2.0
            start = min(row_end, row_start + half)
            end = max(start, row_end - half)
        else:
            start = min(row_end, row_start + keep_edge_padding_sec)
            end = max(start, row_end - keep_edge_padding_sec)
        if end > start + 1e-6:
            removed.append({"start_sec": start, "end_sec": end, "duration_sec": end - start})
    kept_segments: list[dict[str, float]] = []
    cursor = 0.0
    compressed_cursor = 0.0
    pieces: list[Any] = []
    for interval in removed:
        start = float(interval["start_sec"])
        end = float(interval["end_sec"])
        if start > cursor + 1e-9:
            sample_start = int(round(cursor * sample_rate))
            sample_end = int(round(start * sample_rate))
            piece = samples[sample_start:sample_end]
            pieces.append(piece)
            length = float(len(piece) / sample_rate)
            kept_segments.append({
                "compressed_start_sec": compressed_cursor,
                "compressed_end_sec": compressed_cursor + length,
                "original_start_sec": cursor,
                "original_end_sec": start,
            })
            compressed_cursor += length
        cursor = max(cursor, end)
    if cursor < duration_sec - 1e-9:
        sample_start = int(round(cursor * sample_rate))
        piece = samples[sample_start:]
        pieces.append(piece)
        length = float(len(piece) / sample_rate)
        kept_segments.append({
            "compressed_start_sec": compressed_cursor,
            "compressed_end_sec": compressed_cursor + length,
            "original_start_sec": cursor,
            "original_end_sec": duration_sec,
        })
        compressed_cursor += length
    compressed = np.concatenate(pieces) if pieces else samples[:0].copy()
    return compressed, {
        "schema_version": "silence_compression_mapping_v1",
        "original_duration_sec": duration_sec,
        "compressed_duration_sec": float(len(compressed) / sample_rate),
        "removed_duration_sec": duration_sec - float(len(compressed) / sample_rate),
        "removed_intervals": removed,
        "kept_segments": kept_segments,
        "parameters": {
            "remove_silence_sec": threshold,
            "keep_edge_padding_sec": float(keep_edge_padding_sec),
            "sample_rate": int(sample_rate),
        },
    }



def map_original_time_to_compressed(
    value: float, mapping: dict[str, Any], *, boundary_side: str = "right",
) -> float:
    """Map an original-song timestamp onto the silence-compressed clock.

    Removed silence interiors collapse to a single splice coordinate.  The
    boundary-side argument is retained for symmetry with the inverse mapping;
    both sides normally share the same compressed coordinate at a splice.
    """
    if boundary_side not in {"left", "right"}:
        raise ValueError(f"unsupported boundary_side: {boundary_side}")
    segments = sorted(
        list(mapping.get("kept_segments", [])),
        key=lambda row: float(row["original_start_sec"]),
    )
    if not segments:
        return float(value)
    value = float(value)
    tolerance = 1e-9
    candidates = [
        segment for segment in segments
        if float(segment["original_start_sec"]) - tolerance
        <= value
        <= float(segment["original_end_sec"]) + tolerance
    ]
    if candidates:
        segment = candidates[0] if boundary_side == "left" else candidates[-1]
        original_start = float(segment["original_start_sec"])
        compressed_start = float(segment["compressed_start_sec"])
        compressed_end = float(segment["compressed_end_sec"])
        mapped = compressed_start + max(0.0, value - original_start)
        return min(compressed_end, mapped)
    if value < float(segments[0]["original_start_sec"]):
        return float(segments[0]["compressed_start_sec"])
    if value > float(segments[-1]["original_end_sec"]):
        return float(segments[-1]["compressed_end_sec"])

    previous = max(
        (segment for segment in segments if float(segment["original_end_sec"]) < value),
        key=lambda row: float(row["original_end_sec"]),
        default=None,
    )
    following = min(
        (segment for segment in segments if float(segment["original_start_sec"]) > value),
        key=lambda row: float(row["original_start_sec"]),
        default=None,
    )
    if boundary_side == "left" and previous is not None:
        return float(previous["compressed_end_sec"])
    if following is not None:
        return float(following["compressed_start_sec"])
    if previous is not None:
        return float(previous["compressed_end_sec"])
    return float(value)


def project_silence_aware_plan_to_compressed_timeline(
    original_plan: dict[str, Any], mapping: dict[str, Any],
) -> dict[str, Any]:
    """Project a silence-snapped original plan onto silence-removed audio.

    Core boundaries are chosen on the original clock first, using the same
    silence-snap and tail rules as B2/B4.  Their projected compressed positions
    become splice boundaries, so a compressed core does not straddle a selected
    silence.  Input intervals remain contiguous on the compressed clock and
    therefore contain no removed-silence samples.
    """
    compressed_duration = float(mapping.get("compressed_duration_sec", 0.0))
    windows: list[dict[str, Any]] = []
    for source in original_plan.get("windows", []):
        original_core_start = float(source["core_start_sec"])
        original_core_end = float(source["core_end_sec"])
        original_input_start = float(source["input_start_sec"])
        original_input_end = float(source["input_end_sec"])
        core_start = map_original_time_to_compressed(
            original_core_start, mapping, boundary_side="right",
        )
        core_end = map_original_time_to_compressed(
            original_core_end, mapping, boundary_side="left",
        )
        input_start = map_original_time_to_compressed(
            original_input_start, mapping, boundary_side="right",
        )
        input_end = map_original_time_to_compressed(
            original_input_end, mapping, boundary_side="left",
        )
        if core_end <= core_start + 1e-9:
            continue
        windows.append({
            **source,
            "window_index": len(windows),
            "core_start_sec": max(0.0, core_start),
            "core_end_sec": min(compressed_duration, core_end),
            "core_duration_sec": max(0.0, core_end - core_start),
            "input_start_sec": max(0.0, min(input_start, core_start)),
            "input_end_sec": min(compressed_duration, max(input_end, core_end)),
            "original_core_start_sec": original_core_start,
            "original_core_end_sec": original_core_end,
            "original_input_start_sec": original_input_start,
            "original_input_end_sec": original_input_end,
            "window_plan_policy": "silence_compressed_with_original_snap_v2",
            "input_excludes_removed_silence": True,
            "compressed_boundary_from_original_silence_snap": True,
        })
    if windows:
        for window in windows:
            window["is_final_core"] = False
        windows[-1]["is_final_core"] = True
    return {
        "schema_version": "silence_compressed_window_plan_v2",
        "policy": "original_silence_snap_then_project_to_compressed_audio",
        "duration_sec": compressed_duration,
        "target_core_sec": original_plan.get("target_core_sec"),
        "active_span_start_sec": (
            float(windows[0]["core_start_sec"]) if windows else 0.0
        ),
        "active_span_end_sec": (
            float(windows[-1]["core_end_sec"]) if windows else compressed_duration
        ),
        "active_span_duration_sec": (
            float(windows[-1]["core_end_sec"] - windows[0]["core_start_sec"])
            if windows else compressed_duration
        ),
        "windows": windows,
        "original_window_plan": original_plan,
        "silence_compression_mapping": mapping,
        "parameters": {
            "input_excludes_removed_silence": True,
            "boundary_policy": "original_silence_snap",
        },
    }

def map_compressed_time_to_original(
    value: float, mapping: dict[str, Any], *, boundary_side: str = "right",
) -> float:
    """Map a compressed timestamp to the original clock.

    A silence-removal splice has two valid original times at the same compressed
    coordinate: the previous kept segment's end and the next segment's start.
    Interval starts therefore use a right-continuous mapping, while interval
    ends use a left-continuous mapping.
    """
    if boundary_side not in {"left", "right"}:
        raise ValueError(f"unsupported boundary_side: {boundary_side}")
    segments = sorted(
        list(mapping.get("kept_segments", [])),
        key=lambda row: float(row["compressed_start_sec"]),
    )
    if not segments:
        return float(value)
    value = float(value)
    tolerance = 1e-9
    candidates = [
        segment for segment in segments
        if float(segment["compressed_start_sec"]) - tolerance
        <= value
        <= float(segment["compressed_end_sec"]) + tolerance
    ]
    if candidates:
        segment = candidates[0] if boundary_side == "left" else candidates[-1]
        left = float(segment["compressed_start_sec"])
        original_start = float(segment["original_start_sec"])
        original_end = float(segment["original_end_sec"])
        mapped = original_start + max(0.0, value - left)
        return min(original_end, mapped)
    if value < float(segments[0]["compressed_start_sec"]):
        return float(segments[0]["original_start_sec"])
    return float(segments[-1]["original_end_sec"])
