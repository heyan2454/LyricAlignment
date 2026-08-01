"""Pure timestamp decoders used by the alignment research suite.

All decoders consume rows emitted by ``align_qwen_fa_serial_demo.infer_slice``.
Rows retain raw/official evidence and, when available, top-K timestamp classes
and probabilities.  The functions never call the acoustic model, making decoder
comparisons fair and cheap after one Qwen forward pass.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Sequence

_EPS = 1e-12


@dataclass(frozen=True)
class DecoderConfig:
    name: str = "official"
    timestamp_step_sec: float = 0.08
    top_k: int = 6
    beam_size: int = 96
    hard_monotonic: bool = True
    overlap_tolerance_sec: float = 0.0
    zero_duration_penalty: float = 0.35
    overlap_penalty_per_sec: float = 8.0
    duration_change_penalty: float = 0.10
    duration_prior_sec: float | None = None
    duration_prior_weight: float = 0.0
    isotonic_margin_floor: float = 0.02
    local_spans: tuple[tuple[int, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ordered(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))


def _project(rows: Iterable[dict[str, Any]], prefix: str, *, method: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in _ordered(rows):
        row = dict(source)
        start = row.get(f"{prefix}_global_start_sec", row.get(f"{prefix}_start_sec"))
        end = row.get(f"{prefix}_global_end_sec", row.get(f"{prefix}_end_sec"))
        if start is None or end is None:
            raise KeyError(f"row {row.get('global_character_index')} lacks {prefix} boundaries")
        row["start_sec"] = float(start)
        row["end_sec"] = float(end)
        row["research_decoder"] = method
        result.append(row)
    return result


def _global_audio_offset_sec(row: dict[str, Any]) -> float:
    """Recover the slice-to-global time offset from already cached fields.

    Top-K timestamp classes are local to the model input slice.  We deliberately
    do not add another persisted field: the offset is recovered from a matching
    local/global boundary pair that is already emitted by ``infer_slice``.
    """
    pairs = (
        # Canonical fields emitted by infer_slice.
        ("raw_global_start_sec", "raw_local_start_sec"),
        ("raw_global_end_sec", "raw_local_end_sec"),
        ("official_fixed_global_start_sec", "official_fixed_local_start_sec"),
        ("official_fixed_global_end_sec", "official_fixed_local_end_sec"),
        ("fixed_global_start_sec", "fixed_local_start_sec"),
        ("fixed_global_end_sec", "fixed_local_end_sec"),
        # Backward-compatible aliases found in earlier research caches/tests.
        ("raw_global_start_sec", "raw_start_sec"),
        ("raw_global_end_sec", "raw_end_sec"),
        ("official_fixed_global_start_sec", "official_fixed_start_sec"),
        ("official_fixed_global_end_sec", "official_fixed_end_sec"),
        ("fixed_global_start_sec", "fixed_start_sec"),
        ("fixed_global_end_sec", "fixed_end_sec"),
    )
    offsets: list[float] = []
    for global_key, local_key in pairs:
        if row.get(global_key) is None or row.get(local_key) is None:
            continue
        offsets.append(float(row[global_key]) - float(row[local_key]))
    if not offsets:
        # Old whole-item caches had zero offset and often omitted local fields.
        # A non-zero global boundary without any local counterpart is ambiguous
        # and must not silently be treated as a local timestamp class.
        global_values = [
            float(row[key]) for key in ("raw_global_start_sec", "raw_global_end_sec")
            if row.get(key) is not None
        ]
        if global_values and min(global_values) > 2.0:
            raise KeyError(
                "cannot recover local-to-global timestamp offset from cached row; "
                "expected raw_local_start_sec/raw_local_end_sec or equivalent local fields"
            )
        return 0.0
    # Small numerical differences can arise after JSON serialization.  Median is
    # stable when both start/end pairs are present and one boundary was repaired.
    offsets.sort()
    midpoint = len(offsets) // 2
    return offsets[midpoint] if len(offsets) % 2 else 0.5 * (offsets[midpoint - 1] + offsets[midpoint])


def _topk(row: dict[str, Any], side: str, config: DecoderConfig) -> list[tuple[int, float]]:
    classes = row.get(f"raw_{side}_topk_classes")
    probabilities = row.get(f"raw_{side}_topk_probabilities")
    if classes is not None and probabilities is not None:
        values = [(int(cls), max(float(prob), _EPS)) for cls, prob in zip(classes, probabilities)]
        return values[: max(1, config.top_k)]
    # Backward-compatible fallback for old caches that only saved top-1/top-2.
    offset = _global_audio_offset_sec(row)
    raw_sec = float(row[f"raw_global_{side}_sec"]) - offset
    raw_class = int(round(raw_sec / config.timestamp_step_sec))
    top1 = float(row.get(f"raw_{side}_top1_probability", 1.0))
    top2_class = row.get(f"raw_{side}_top2_class")
    values = [(raw_class, max(top1, _EPS))]
    if top2_class is not None:
        margin = max(0.0, float(row.get(f"raw_{side}_margin", 0.0)))
        top2_prob = max(_EPS, top1 - margin)
        values.append((int(top2_class), top2_prob))
    return values


def _pair_candidates(row: dict[str, Any], config: DecoderConfig) -> list[tuple[float, float, float]]:
    """Return legal ``(start_sec, end_sec, log_score)`` candidates."""
    starts = _topk(row, "start", config)
    ends = _topk(row, "end", config)
    global_offset = _global_audio_offset_sec(row)
    candidates: list[tuple[float, float, float]] = []
    for start_class, start_prob in starts:
        for end_class, end_prob in ends:
            start = global_offset + start_class * config.timestamp_step_sec
            end = global_offset + end_class * config.timestamp_step_sec
            if end < start - 1e-9:
                continue
            duration = max(0.0, end - start)
            score = math.log(start_prob) + math.log(end_prob)
            if duration <= 1e-9:
                score -= config.zero_duration_penalty
            if config.duration_prior_sec is not None and config.duration_prior_weight > 0:
                score -= config.duration_prior_weight * abs(duration - config.duration_prior_sec)
            candidates.append((start, end, score))
    if not candidates:
        # Always return a legal fallback even when old top-K caches contain no
        # legal pair.  This does not hide the failure: metadata records fallback.
        start = float(row["raw_global_start_sec"])
        end = max(start, float(row["raw_global_end_sec"]))
        candidates = [(start, end, -1e9)]
    candidates.sort(key=lambda value: value[2], reverse=True)
    return candidates[: max(config.beam_size, config.top_k)]


def joint_start_end_rows(rows: Iterable[dict[str, Any]], config: DecoderConfig) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in _ordered(rows):
        candidate = _pair_candidates(source, config)[0]
        row = dict(source)
        row["start_sec"], row["end_sec"] = candidate[0], candidate[1]
        row["research_decoder"] = "joint_start_end"
        row["research_decoder_path_score"] = candidate[2]
        result.append(row)
    return result


def topk_sequence_rows(rows: Iterable[dict[str, Any]], config: DecoderConfig) -> list[dict[str, Any]]:
    ordered = _ordered(rows)
    if not ordered:
        return []
    # beam state: score, previous_end, previous_duration, path
    beam: list[tuple[float, float, float | None, list[tuple[float, float, float]]]] = [
        (0.0, -math.inf, None, [])
    ]
    for row in ordered:
        expanded: list[tuple[float, float, float | None, list[tuple[float, float, float]]]] = []
        for score, previous_end, previous_duration, path in beam:
            for start, end, local_score in _pair_candidates(row, config):
                overlap = max(0.0, previous_end - start - config.overlap_tolerance_sec)
                if config.hard_monotonic and overlap > 1e-9:
                    continue
                candidate_score = score + local_score - config.overlap_penalty_per_sec * overlap
                duration = max(0.0, end - start)
                if previous_duration is not None and config.duration_change_penalty > 0:
                    candidate_score -= config.duration_change_penalty * abs(duration - previous_duration)
                expanded.append((candidate_score, end, duration, path + [(start, end, local_score)]))
        if not expanded and config.hard_monotonic:
            # A soft fallback keeps the experiment running and records that the
            # hard constraint had no feasible top-K path.
            relaxed = DecoderConfig(**{**config.to_dict(), "hard_monotonic": False})
            return topk_sequence_rows(ordered, relaxed)
        expanded.sort(key=lambda state: state[0], reverse=True)
        beam = expanded[: max(1, config.beam_size)]
    best_score, _, _, best_path = beam[0]
    result: list[dict[str, Any]] = []
    for source, (start, end, local_score) in zip(ordered, best_path, strict=True):
        row = dict(source)
        row["start_sec"] = start
        row["end_sec"] = end
        row["research_decoder"] = "topk_sequence"
        row["research_decoder_local_score"] = local_score
        row["research_decoder_path_score"] = best_score
        row["research_decoder_hard_monotonic"] = config.hard_monotonic
        result.append(row)
    return result


def _weighted_pava(values: Sequence[float], weights: Sequence[float]) -> list[float]:
    """Weighted isotonic regression using the pool-adjacent-violators algorithm."""
    if len(values) != len(weights):
        raise ValueError("values/weights length mismatch")
    blocks: list[list[float]] = []  # [sum_w, sum_wx, begin, end]
    for index, (value, weight) in enumerate(zip(values, weights, strict=True)):
        w = max(float(weight), _EPS)
        blocks.append([w, w * float(value), float(index), float(index)])
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            if left[1] / left[0] <= right[1] / right[0] + 1e-12:
                break
            blocks[-2:] = [[left[0] + right[0], left[1] + right[1], left[2], right[3]]]
    output = [0.0] * len(values)
    for sum_w, sum_wx, begin, end in blocks:
        mean = sum_wx / sum_w
        for index in range(int(begin), int(end) + 1):
            output[index] = mean
    return output


def weighted_isotonic_rows(rows: Iterable[dict[str, Any]], config: DecoderConfig) -> list[dict[str, Any]]:
    ordered = _ordered(rows)
    if not ordered:
        return []
    values: list[float] = []
    weights: list[float] = []
    for row in ordered:
        values.extend([float(row["raw_global_start_sec"]), float(row["raw_global_end_sec"])])
        start_weight = max(config.isotonic_margin_floor, float(row.get("raw_start_margin", 0.0)))
        end_weight = max(config.isotonic_margin_floor, float(row.get("raw_end_margin", 0.0)))
        weights.extend([start_weight, end_weight])
    projected = _weighted_pava(values, weights)
    result: list[dict[str, Any]] = []
    for index, source in enumerate(ordered):
        row = dict(source)
        row["start_sec"] = projected[2 * index]
        row["end_sec"] = max(projected[2 * index], projected[2 * index + 1])
        row["research_decoder"] = "weighted_isotonic"
        row["research_decoder_movement_sec"] = max(
            abs(row["start_sec"] - values[2 * index]),
            abs(row["end_sec"] - values[2 * index + 1]),
        )
        result.append(row)
    return result


def _in_spans(index: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start <= index <= end for start, end in spans)


def local_repair_rows(rows: Iterable[dict[str, Any]], config: DecoderConfig, method: str) -> list[dict[str, Any]]:
    ordered = _ordered(rows)
    if not config.local_spans:
        raise ValueError(f"{method} requires at least one local span")
    repaired = [dict(row) for row in ordered]
    by_index = {int(row["global_character_index"]): position for position, row in enumerate(ordered)}
    for span_start, span_end in config.local_spans:
        positions = [by_index[index] for index in range(span_start, span_end + 1) if index in by_index]
        if not positions:
            continue
        left = min(positions)
        right = max(positions)
        segment = ordered[left : right + 1]
        local_config = DecoderConfig(**{**config.to_dict(), "local_spans": ()})
        if method == "local_weighted_isotonic":
            candidate = weighted_isotonic_rows(segment, local_config)
        elif method == "local_topk_sequence":
            candidate = topk_sequence_rows(segment, local_config)
        else:
            raise ValueError(method)
        lower_bound = repaired[left - 1]["end_sec"] if left > 0 and "end_sec" in repaired[left - 1] else None
        upper_bound = None
        if right + 1 < len(repaired):
            next_row = repaired[right + 1]
            upper_bound = float(next_row.get("raw_global_start_sec", next_row.get("start_sec", math.inf)))
        for offset, row in enumerate(candidate):
            position = left + offset
            start = float(row["start_sec"])
            end = float(row["end_sec"])
            if lower_bound is not None:
                start = max(start, float(lower_bound))
                end = max(end, start)
            if upper_bound is not None and math.isfinite(upper_bound):
                end = min(end, upper_bound)
                start = min(start, end)
            merged = dict(repaired[position])
            merged.update({"start_sec": start, "end_sec": end})
            merged["research_decoder"] = method
            merged["research_decoder_local_span"] = [span_start, span_end]
            repaired[position] = merged
            lower_bound = end
    # Outside spans remain raw by design.
    for row in repaired:
        if "start_sec" not in row:
            row["start_sec"] = float(row["raw_global_start_sec"])
            row["end_sec"] = float(row["raw_global_end_sec"])
            row["research_decoder"] = "raw_preserved_outside_local_span"
    return repaired


def decode_rows(rows: Iterable[dict[str, Any]], config: DecoderConfig) -> list[dict[str, Any]]:
    name = config.name
    if name in {"raw", "raw_argmax"}:
        return _project(rows, "raw", method="raw")
    if name in {"official", "processor_decoded"}:
        return _project(rows, "official_fixed", method="official")
    if name == "joint_start_end":
        return joint_start_end_rows(rows, config)
    if name == "topk_sequence":
        return topk_sequence_rows(rows, config)
    if name == "weighted_isotonic":
        return weighted_isotonic_rows(rows, config)
    if name in {"local_weighted_isotonic", "local_topk_sequence"}:
        return local_repair_rows(rows, config, name)
    raise ValueError(f"unknown decoder: {name}")
