"""Pure window, lyric-budget, silence-cap, and serial-state experiment helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Sequence

from .requests import AlignmentRequest


@dataclass(frozen=True)
class SilenceInterval:
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True)
class TimeMappingSegment:
    original_start_sec: float
    original_end_sec: float
    transformed_start_sec: float
    transformed_end_sec: float
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cap_silence_mapping(
    *,
    duration_sec: float,
    silences: Iterable[SilenceInterval],
    cap_sec: float,
    minimum_silence_sec: float = 1.5,
) -> list[TimeMappingSegment]:
    """Map an original clock to a clock where long silences are capped.

    The complete silence remains present; only its duration is shortened.  This
    differs from the historical C0/C1 deletion that retained only 0.2 s on each
    side and directly concatenated active regions.
    """
    if cap_sec <= 0:
        raise ValueError("cap_sec must be positive")
    intervals = sorted(
        (SilenceInterval(max(0.0, value.start_sec), min(duration_sec, value.end_sec)) for value in silences),
        key=lambda value: value.start_sec,
    )
    result: list[TimeMappingSegment] = []
    original_cursor = 0.0
    transformed_cursor = 0.0
    for interval in intervals:
        if interval.end_sec <= interval.start_sec or interval.start_sec < original_cursor:
            continue
        if interval.start_sec > original_cursor:
            length = interval.start_sec - original_cursor
            result.append(TimeMappingSegment(
                original_cursor, interval.start_sec,
                transformed_cursor, transformed_cursor + length, "active_or_short_silence",
            ))
            transformed_cursor += length
        original_length = interval.duration_sec
        transformed_length = min(original_length, cap_sec) if original_length >= minimum_silence_sec else original_length
        result.append(TimeMappingSegment(
            interval.start_sec, interval.end_sec,
            transformed_cursor, transformed_cursor + transformed_length,
            "capped_silence" if transformed_length < original_length else "preserved_silence",
        ))
        transformed_cursor += transformed_length
        original_cursor = interval.end_sec
    if original_cursor < duration_sec:
        length = duration_sec - original_cursor
        result.append(TimeMappingSegment(
            original_cursor, duration_sec,
            transformed_cursor, transformed_cursor + length, "active_or_short_silence",
        ))
    return result


def map_time(value: float, mapping: Sequence[TimeMappingSegment], *, direction: str) -> float:
    if direction not in {"original_to_transformed", "transformed_to_original"}:
        raise ValueError(direction)
    for segment in mapping:
        if direction == "original_to_transformed":
            source_start, source_end = segment.original_start_sec, segment.original_end_sec
            target_start, target_end = segment.transformed_start_sec, segment.transformed_end_sec
        else:
            source_start, source_end = segment.transformed_start_sec, segment.transformed_end_sec
            target_start, target_end = segment.original_start_sec, segment.original_end_sec
        if source_start - 1e-9 <= value <= source_end + 1e-9:
            if source_end <= source_start + 1e-12:
                return target_start
            fraction = min(1.0, max(0.0, (value - source_start) / (source_end - source_start)))
            return target_start + fraction * (target_end - target_start)
    if not mapping:
        return value
    final = mapping[-1]
    if direction == "original_to_transformed":
        return final.transformed_end_sec + max(0.0, value - final.original_end_sec)
    return final.original_end_sec + max(0.0, value - final.transformed_end_sec)


def text_budget_candidates(
    estimate: int,
    *,
    absolute: Sequence[int] = (32, 48, 64),
    deltas: Sequence[int] = (-16, 0, 16),
    minimum: int = 8,
    maximum: int | None = None,
) -> list[int]:
    values = {int(value) for value in absolute}
    values.update(int(estimate + delta) for delta in deltas)
    output = sorted(value for value in values if value >= minimum and (maximum is None or value <= maximum))
    return output or [max(minimum, estimate)]


def split_text_chunks(
    text_start: int,
    text_end: int,
    *,
    chunk_units: int,
    overlap_units: int = 0,
    commit_units: int | None = None,
) -> list[dict[str, int]]:
    if chunk_units <= 0 or overlap_units < 0 or overlap_units >= chunk_units:
        raise ValueError("invalid chunk/overlap")
    commit = commit_units or (chunk_units - overlap_units)
    if commit <= 0 or commit > chunk_units:
        raise ValueError("invalid commit_units")
    result: list[dict[str, int]] = []
    cursor = text_start
    while cursor < text_end:
        input_end = min(text_end, cursor + chunk_units)
        commit_end = min(text_end, cursor + commit)
        result.append({
            "text_start": cursor,
            "text_end": input_end,
            "commit_start": cursor,
            "commit_end": commit_end,
        })
        if commit_end >= text_end:
            break
        cursor = commit_end
    return result


def choose_safe_boundary(
    candidates: Iterable[dict[str, Any]],
    *,
    nominal_sec: float,
    minimum_sec: float,
    maximum_sec: float,
    minimum_score: float = 0.25,
    distance_penalty_per_sec: float = 0.02,
) -> dict[str, Any] | None:
    eligible = []
    for row in candidates:
        time_sec = float(row["time_sec"])
        score = float(row.get("safe_boundary_score", 0.0))
        if minimum_sec <= time_sec <= maximum_sec and score > 0.0 and score >= minimum_score:
            objective = score - distance_penalty_per_sec * abs(time_sec - nominal_sec)
            eligible.append((objective, -abs(time_sec - nominal_sec), row))
    if not eligible:
        return None
    return dict(max(eligible, key=lambda value: (value[0], value[1]))[2])


def dynamic_window_request(
    baseline: AlignmentRequest,
    *,
    safe_boundary: dict[str, Any] | None,
    safe_offset_units: int,
    unit_times: dict[int, tuple[float, float]],
    left_context_sec: float,
    right_context_sec: float,
    duration_sec: float,
) -> AlignmentRequest:
    if safe_boundary is None:
        return baseline.derive(request_role="dynamic_window_fallback")
    boundary_index = int(safe_boundary["global_character_index"])
    shifted_index = max(0, boundary_index - max(0, safe_offset_units))
    if shifted_index not in unit_times:
        return baseline.derive(request_role="dynamic_window_missing_unit_fallback")
    next_start = float(unit_times[shifted_index][0])
    core_end = float(safe_boundary["time_sec"])
    audio_start = max(0.0, next_start - left_context_sec)
    audio_end = min(duration_sec, core_end + right_context_sec)
    text_start = shifted_index
    text_end = max(text_start + 1, baseline.text_end)
    return baseline.derive(
        audio_start_sec=audio_start,
        audio_end_sec=audio_end,
        ownership_start_sec=next_start,
        ownership_end_sec=core_end,
        text_start=text_start,
        text_end=text_end,
        request_role=f"dynamic_safe_minus{safe_offset_units}",
        metadata={"safe_boundary": dict(safe_boundary), "safe_offset_units": safe_offset_units},
    )


def hard_core_soft_context_requests(
    *,
    item_id: str,
    duration_sec: float,
    silences: Sequence[SilenceInterval],
    left_context_sec: float,
    right_lookahead_sec: float,
    text_spans: Sequence[tuple[int, int]],
    cap_sec: float | None = None,
) -> list[AlignmentRequest]:
    """Create active-region ownership windows with right-side acoustic lookahead.

    ``text_spans`` must be generated by GT (diagnostic) or a detector/controller
    (product candidate).  This function never infers lyric boundaries from the
    amount committed in the previous region, avoiding the confound in B5/B6.
    """
    boundaries = [0.0]
    for interval in sorted(silences, key=lambda value: value.start_sec):
        if interval.duration_sec >= 1.5:
            boundaries.extend([interval.start_sec, interval.end_sec])
    boundaries.append(duration_sec)
    active_regions: list[tuple[float, float]] = []
    for start, end in zip(boundaries[::2], boundaries[1::2], strict=False):
        if end > start:
            active_regions.append((start, end))
    if len(text_spans) != len(active_regions):
        raise ValueError(f"text_spans={len(text_spans)} active_regions={len(active_regions)}")
    requests: list[AlignmentRequest] = []
    for region_index, ((start, end), (text_start, text_end)) in enumerate(zip(active_regions, text_spans, strict=True)):
        input_start = max(0.0, start - left_context_sec)
        input_end = min(duration_sec, end + right_lookahead_sec)
        requests.append(AlignmentRequest(
            item_id=item_id,
            audio_start_sec=input_start,
            audio_end_sec=input_end,
            ownership_start_sec=start,
            ownership_end_sec=end,
            text_start=text_start,
            text_end=text_end,
            request_role="hard_core_soft_context",
            metadata={"region_index": region_index, "silence_cap_sec": cap_sec},
        ))
    return requests


@dataclass(frozen=True)
class StateInjection:
    kind: str
    window_index: int
    value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_state_injections() -> list[StateInjection]:
    result: list[StateInjection] = []
    for value in (-8, -4, -2, 2, 4, 8):
        result.append(StateInjection("cursor_units", 1, float(value)))
    for value in (-1.6, -0.8, -0.4, 0.4, 0.8, 1.6):
        result.append(StateInjection("previous_end_sec", 1, value))
    for value in (-5.0, -2.0, 2.0, 5.0):
        result.append(StateInjection("core_boundary_sec", 1, value))
    return result


def build_dynamic_window_plan(
    *,
    duration_sec: float,
    target_core_sec: float,
    left_context_sec: float,
    right_context_sec: float,
    safe_boundaries: Sequence[dict[str, Any]],
    search_before_sec: float = 10.0,
    search_after_sec: float = 10.0,
    minimum_core_sec: float = 12.0,
    minimum_score: float = 0.25,
) -> dict[str, Any]:
    """Build a continuous plan whose internal boundaries are safe candidates.

    Every chosen boundary is both the previous core end and next core start.
    If no acceptable safe candidate exists near a nominal boundary, the nominal
    boundary is retained and marked as a fallback.
    """
    boundaries = [0.0]
    diagnostics: list[dict[str, Any]] = []
    nominal = target_core_sec
    while nominal < duration_sec - minimum_core_sec:
        minimum = max(boundaries[-1] + minimum_core_sec, nominal - search_before_sec)
        maximum = min(duration_sec - minimum_core_sec, nominal + search_after_sec)
        selected = choose_safe_boundary(
            safe_boundaries,
            nominal_sec=nominal,
            minimum_sec=minimum,
            maximum_sec=maximum,
            minimum_score=minimum_score,
        )
        value = nominal if selected is None else float(selected["time_sec"])
        if value <= boundaries[-1] + minimum_core_sec - 1e-9:
            value = min(duration_sec, boundaries[-1] + target_core_sec)
            selected = None
        boundaries.append(value)
        diagnostics.append({
            "nominal_sec": nominal,
            "selected_sec": value,
            "source": "nominal_fallback" if selected is None else "detector_safe_boundary",
            "safe_boundary": selected,
        })
        nominal = value + target_core_sec
    if duration_sec - boundaries[-1] < minimum_core_sec and len(boundaries) > 1:
        boundaries.pop()
        if diagnostics:
            diagnostics.pop()
    boundaries.append(duration_sec)
    windows = []
    for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True)):
        windows.append({
            "window_index": index,
            "core_start_sec": float(start),
            "core_end_sec": float(end),
            "core_duration_sec": float(end - start),
            "input_start_sec": max(0.0, float(start) - left_context_sec),
            "input_end_sec": min(duration_sec, float(end) + right_context_sec),
            "is_final_core": index == len(boundaries) - 2,
            "window_plan_policy": "detector_safe_dynamic_v1",
        })
    return {
        "schema_version": "detector_safe_dynamic_window_plan_v1",
        "policy": "continuous_dynamic_boundary_with_nominal_fallback",
        "duration_sec": duration_sec,
        # ``windowed_alignment`` consumes every externally supplied plan via
        # this field when evaluating end-of-audio ownership.  Dynamic plans
        # are in the original, untrimmed clock, so their active span is the
        # complete item duration.
        "active_span_duration_sec": duration_sec,
        "target_core_sec": target_core_sec,
        "final_boundaries_sec": boundaries,
        "boundary_diagnostics": diagnostics,
        "windows": windows,
    }


def apply_time_mapping_to_audio(
    audio: Any,
    mapping: Sequence[TimeMappingSegment],
    *,
    sample_rate: int = 16000,
) -> Any:
    """Materialize a capped-silence waveform from a piecewise time mapping."""
    import numpy as np

    values = np.asarray(audio)
    pieces = []
    for segment in mapping:
        original_start = max(0, int(round(segment.original_start_sec * sample_rate)))
        original_end = min(len(values), int(round(segment.original_end_sec * sample_rate)))
        target_length = max(0, int(round(
            (segment.transformed_end_sec - segment.transformed_start_sec) * sample_rate
        )))
        source = values[original_start:original_end]
        if target_length == len(source):
            pieces.append(source)
        elif target_length <= 0:
            continue
        elif len(source) <= 1:
            pieces.append(np.zeros(target_length, dtype=values.dtype))
        else:
            # Silence segments are expected to contain little information; a
            # deterministic linear resample preserves edges without creating a
            # hard active-region splice.
            x_old = np.linspace(0.0, 1.0, len(source), endpoint=True)
            x_new = np.linspace(0.0, 1.0, target_length, endpoint=True)
            pieces.append(np.interp(x_new, x_old, source).astype(values.dtype, copy=False))
    return np.concatenate(pieces) if pieces else np.asarray([], dtype=values.dtype)


def build_hard_core_soft_context_plan(
    *,
    duration_sec: float,
    silences: Sequence[SilenceInterval],
    target_core_sec: float,
    left_context_sec: float,
    right_lookahead_sec: float,
    strict_silence_sec: float = 1.5,
    minimum_core_sec: float = 12.0,
) -> dict[str, Any]:
    """Create core windows that stop at long silence but look across it.

    Core ownership excludes long silence.  The final window before a silence has
    an input end extending beyond the silence into the next active region, so
    the current ending and next lyric cursor can still be constrained by future
    content.  Unlike B5/B6 this plan is fed through the normal cursor policy.
    """
    strict = sorted(
        [value for value in silences if value.duration_sec >= strict_silence_sec],
        key=lambda value: value.start_sec,
    )
    active_regions: list[tuple[float, float]] = []
    cursor = 0.0
    for silence in strict:
        if silence.start_sec > cursor + 1e-6:
            active_regions.append((cursor, silence.start_sec))
        cursor = max(cursor, silence.end_sec)
    if cursor < duration_sec - 1e-6:
        active_regions.append((cursor, duration_sec))
    windows: list[dict[str, Any]] = []
    for region_index, (region_start, region_end) in enumerate(active_regions):
        boundaries = [region_start]
        point = region_start + target_core_sec
        while point < region_end - minimum_core_sec:
            boundaries.append(point)
            point += target_core_sec
        boundaries.append(region_end)
        for local_index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True)):
            next_region_start = active_regions[region_index + 1][0] if region_index + 1 < len(active_regions) else None
            is_region_tail = local_index == len(boundaries) - 2
            input_end = min(duration_sec, end + right_lookahead_sec)
            if is_region_tail and next_region_start is not None:
                input_end = min(duration_sec, max(input_end, next_region_start + right_lookahead_sec))
            windows.append({
                "window_index": len(windows),
                "core_start_sec": float(start),
                "core_end_sec": float(end),
                "core_duration_sec": float(end - start),
                "input_start_sec": max(0.0, float(start) - left_context_sec),
                "input_end_sec": input_end,
                "is_final_core": False,
                "window_plan_policy": "hard_core_soft_context_v1",
                "active_region_index": region_index,
                "is_final_region_core": is_region_tail,
                "right_lookahead_crosses_silence": bool(is_region_tail and next_region_start is not None),
            })
    if windows:
        windows[-1]["is_final_core"] = True
    return {
        "schema_version": "hard_core_soft_context_plan_v1",
        "policy": "core_stops_at_long_silence_but_input_looks_into_next_active_region",
        "duration_sec": duration_sec,
        "target_core_sec": target_core_sec,
        "strict_silence_sec": strict_silence_sec,
        "silence_intervals": [asdict(value) for value in strict],
        "active_regions": [{"start_sec": a, "end_sec": b} for a, b in active_regions],
        "windows": windows,
    }


def map_window_plan(
    plan: dict[str, Any],
    mapping: Sequence[TimeMappingSegment],
    *,
    direction: str,
) -> dict[str, Any]:
    result = {key: value for key, value in plan.items() if key != "windows"}
    windows = []
    for source in plan.get("windows", []):
        row = dict(source)
        for key in ("core_start_sec", "core_end_sec", "input_start_sec", "input_end_sec"):
            row[key] = map_time(float(row[key]), mapping, direction=direction)
        row["core_duration_sec"] = row["core_end_sec"] - row["core_start_sec"]
        windows.append(row)
    result["windows"] = windows
    result["mapped_direction"] = direction
    result["mapping"] = [segment.to_dict() for segment in mapping]
    return result
