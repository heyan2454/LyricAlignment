"""Detector features, labels, spans, and lightweight calibration models.

The detector is intentionally decoder-agnostic: it consumes standardized
alignment candidates plus optional raw logits, cross-input candidates, audio
support, serial history, and GT labels.  It emits continuous risk/safety scores
and proposed spans; binary thresholds are an experiment output, not a hidden
production rule.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import statistics
from typing import Any, Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class DetectorConfig:
    error_tolerance_sec: float = 0.16
    short_duration_sec: float = 0.04
    long_duration_sec: float = 2.0
    overlap_tolerance_sec: float = 0.02
    movement_tolerance_sec: float = 0.16
    cross_input_tolerance_sec: float = 0.24
    low_margin: float = 0.05
    high_entropy: float = 3.0
    rate_window_units: int = 8
    rate_z_threshold: float = 3.0
    risk_threshold: float = 1.0
    safe_threshold: float = 0.25
    merge_gap_units: int = 1
    minimum_span_units: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_FEATURES = (
    "raw_negative_duration",
    "raw_overlap_sec",
    "raw_start_regression_sec",
    "raw_zero_duration",
    "raw_short_duration",
    "raw_long_duration",
    "raw_equal_boundary_left",
    "raw_equal_boundary_right",
    "raw_start_margin_low",
    "raw_end_margin_low",
    "raw_start_entropy_high",
    "raw_end_entropy_high",
    "raw_official_movement_sec",
    "official_zero_duration",
    "official_overlap_sec",
    "cross_input_spread_sec",
    "cross_window_spread_sec",
    "audio_boundary_support_missing",
    "lyrics_in_silence",
    "local_rate_z",
    "serial_cursor_disagreement_units",
)


def _ordered(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))


def _boundary(row: dict[str, Any], kind: str, side: str) -> float | None:
    keys = {
        ("raw", "start"): ("raw_global_start_sec", "raw_start_sec"),
        ("raw", "end"): ("raw_global_end_sec", "raw_end_sec"),
        ("official", "start"): ("official_fixed_global_start_sec", "official_start_sec"),
        ("official", "end"): ("official_fixed_global_end_sec", "official_end_sec"),
        ("selected", "start"): ("start_sec", "fixed_global_start_sec"),
        ("selected", "end"): ("end_sec", "fixed_global_end_sec"),
    }[(kind, side)]
    for key in keys:
        if row.get(key) is not None:
            return float(row[key])
    return None


def candidate_spread(candidates: Sequence[Sequence[dict[str, Any]]]) -> dict[int, float]:
    by_candidate: list[dict[int, dict[str, Any]]] = [
        {int(row["global_character_index"]): row for row in _ordered(rows)} for rows in candidates
    ]
    indices = sorted(set().union(*(mapping.keys() for mapping in by_candidate))) if by_candidate else []
    result: dict[int, float] = {}
    for index in indices:
        starts: list[float] = []
        ends: list[float] = []
        for mapping in by_candidate:
            row = mapping.get(index)
            if row is None:
                continue
            start = _boundary(row, "selected", "start")
            end = _boundary(row, "selected", "end")
            if start is not None and end is not None:
                starts.append(start)
                ends.append(end)
        if len(starts) >= 2:
            result[index] = max(max(starts) - min(starts), max(ends) - min(ends))
    return result


def _local_rate_z(rows: list[dict[str, Any]], window: int) -> list[float]:
    durations = []
    for row in rows:
        start = _boundary(row, "selected", "start")
        end = _boundary(row, "selected", "end")
        durations.append(None if start is None or end is None else max(0.0, end - start))
    finite = [value for value in durations if value is not None and value > 1e-9]
    global_median = statistics.median(finite) if finite else 0.0
    global_mad = statistics.median(abs(value - global_median) for value in finite) if finite else 0.0
    scale = max(1.4826 * global_mad, 1e-3)
    result: list[float] = []
    radius = max(1, int(window) // 2)
    for index, value in enumerate(durations):
        if value is None:
            result.append(0.0)
            continue
        local = [v for v in durations[max(0, index - radius): min(len(rows), index + radius + 1)] if v is not None]
        local_median = statistics.median(local) if local else global_median
        result.append(abs(value - local_median) / scale)
    return result


def extract_features(
    rows: Iterable[dict[str, Any]],
    *,
    config: DetectorConfig = DetectorConfig(),
    input_candidates: Sequence[Sequence[dict[str, Any]]] = (),
    window_candidates: Sequence[Sequence[dict[str, Any]]] = (),
    audio_support_by_index: dict[int, dict[str, float]] | None = None,
    cursor_disagreement_by_index: dict[int, float] | None = None,
) -> list[dict[str, Any]]:
    ordered = _ordered(rows)
    input_spread = candidate_spread(input_candidates)
    window_spread = candidate_spread(window_candidates)
    rate_z = _local_rate_z(ordered, config.rate_window_units)
    result: list[dict[str, Any]] = []
    previous_raw_start: float | None = None
    previous_raw_end: float | None = None
    previous_official_end: float | None = None
    for position, row in enumerate(ordered):
        index = int(row["global_character_index"])
        raw_start = _boundary(row, "raw", "start")
        raw_end = _boundary(row, "raw", "end")
        official_start = _boundary(row, "official", "start")
        official_end = _boundary(row, "official", "end")
        selected_start = _boundary(row, "selected", "start")
        selected_end = _boundary(row, "selected", "end")
        raw_duration = None if raw_start is None or raw_end is None else raw_end - raw_start
        official_duration = None if official_start is None or official_end is None else official_end - official_start
        raw_overlap = 0.0 if raw_start is None or previous_raw_end is None else max(0.0, previous_raw_end - raw_start)
        official_overlap = 0.0 if official_start is None or previous_official_end is None else max(0.0, previous_official_end - official_start)
        start_regression = 0.0 if raw_start is None or previous_raw_start is None else max(0.0, previous_raw_start - raw_start)
        movement = 0.0
        if None not in (raw_start, raw_end, official_start, official_end):
            movement = max(abs(raw_start - official_start), abs(raw_end - official_end))
        left_equal = 0.0
        right_equal = 0.0
        if position > 0 and raw_start is not None:
            previous = _boundary(ordered[position - 1], "raw", "start")
            left_equal = float(previous is not None and abs(raw_start - previous) <= 1e-9)
        if position + 1 < len(ordered) and raw_end is not None:
            following = _boundary(ordered[position + 1], "raw", "end")
            right_equal = float(following is not None and abs(raw_end - following) <= 1e-9)
        support = (audio_support_by_index or {}).get(index, {})
        feature = {
            "global_character_index": index,
            "character": row.get("character"),
            "raw_negative_duration": float(raw_duration is not None and raw_duration < -1e-9),
            "raw_overlap_sec": raw_overlap,
            "raw_start_regression_sec": start_regression,
            "raw_zero_duration": float(raw_duration is not None and abs(raw_duration) <= 1e-9),
            "raw_short_duration": float(raw_duration is not None and 0.0 <= raw_duration < config.short_duration_sec),
            "raw_long_duration": float(raw_duration is not None and raw_duration > config.long_duration_sec),
            "raw_equal_boundary_left": left_equal,
            "raw_equal_boundary_right": right_equal,
            "raw_start_margin": float(row.get("raw_start_margin", 0.0)),
            "raw_end_margin": float(row.get("raw_end_margin", 0.0)),
            "raw_start_margin_low": float(float(row.get("raw_start_margin", 1.0)) < config.low_margin),
            "raw_end_margin_low": float(float(row.get("raw_end_margin", 1.0)) < config.low_margin),
            "raw_start_entropy": float(row.get("raw_start_entropy", 0.0)),
            "raw_end_entropy": float(row.get("raw_end_entropy", 0.0)),
            "raw_start_entropy_high": float(float(row.get("raw_start_entropy", 0.0)) > config.high_entropy),
            "raw_end_entropy_high": float(float(row.get("raw_end_entropy", 0.0)) > config.high_entropy),
            "raw_official_movement_sec": movement,
            "raw_official_large_movement": float(movement > config.movement_tolerance_sec),
            "official_zero_duration": float(official_duration is not None and official_duration <= 1e-9),
            "official_overlap_sec": official_overlap,
            "cross_input_spread_sec": float(input_spread.get(index, 0.0)),
            "cross_window_spread_sec": float(window_spread.get(index, 0.0)),
            "cross_input_unstable": float(input_spread.get(index, 0.0) > config.cross_input_tolerance_sec),
            "cross_window_unstable": float(window_spread.get(index, 0.0) > config.cross_input_tolerance_sec),
            "audio_boundary_support": float(support.get("boundary_support", 1.0)),
            "audio_boundary_support_missing": float(support.get("boundary_support", 1.0) < 0.25),
            "lyrics_in_silence": float(support.get("lyrics_in_silence", 0.0)),
            "local_rate_z": float(rate_z[position]),
            "local_rate_outlier": float(rate_z[position] > config.rate_z_threshold),
            "serial_cursor_disagreement_units": float((cursor_disagreement_by_index or {}).get(index, 0.0)),
            "selected_start_sec": selected_start,
            "selected_end_sec": selected_end,
        }
        result.append(feature)
        previous_raw_start = raw_start if raw_start is not None else previous_raw_start
        previous_raw_end = raw_end if raw_end is not None else previous_raw_end
        previous_official_end = official_end if official_end is not None else previous_official_end
    return result


# The default score is deliberately transparent and uncalibrated.  Experiments
# must report feature vectors and threshold curves rather than treating this as
# a production gate.
def rule_risk_score(feature: dict[str, Any]) -> float:
    structural = (
        2.0 * float(feature.get("raw_negative_duration", 0.0))
        + min(2.0, 4.0 * float(feature.get("raw_overlap_sec", 0.0)))
        + min(1.5, 4.0 * float(feature.get("raw_start_regression_sec", 0.0)))
        + 0.75 * float(feature.get("raw_zero_duration", 0.0))
        + 0.50 * float(feature.get("raw_short_duration", 0.0))
        + 0.50 * float(feature.get("raw_long_duration", 0.0))
    )
    uncertainty = (
        0.35 * float(feature.get("raw_start_margin_low", 0.0))
        + 0.35 * float(feature.get("raw_end_margin_low", 0.0))
        + 0.25 * float(feature.get("raw_start_entropy_high", 0.0))
        + 0.25 * float(feature.get("raw_end_entropy_high", 0.0))
    )
    consistency = (
        min(1.5, 2.0 * float(feature.get("raw_official_movement_sec", 0.0)))
        + min(2.0, 2.0 * float(feature.get("cross_input_spread_sec", 0.0)))
        + min(2.0, 2.0 * float(feature.get("cross_window_spread_sec", 0.0)))
    )
    support = (
        0.75 * float(feature.get("audio_boundary_support_missing", 0.0))
        + 1.0 * float(feature.get("lyrics_in_silence", 0.0))
        + min(1.0, 0.25 * float(feature.get("local_rate_z", 0.0)))
    )
    return structural + uncertainty + consistency + support


def safe_boundary_score(feature: dict[str, Any], *, risk_score: float | None = None) -> float:
    risk = rule_risk_score(feature) if risk_score is None else float(risk_score)
    margin = min(float(feature.get("raw_start_margin", 0.0)), float(feature.get("raw_end_margin", 0.0)))
    support = float(feature.get("audio_boundary_support", 1.0))
    stability = math.exp(-2.0 * (
        float(feature.get("cross_input_spread_sec", 0.0))
        + float(feature.get("cross_window_spread_sec", 0.0))
    ))
    return max(0.0, min(1.0, (1.0 / (1.0 + risk)) * (0.5 + margin) * support * stability))


def _merge_indices(indices: Sequence[int], gap: int, minimum_units: int) -> list[tuple[int, int]]:
    if not indices:
        return []
    ordered = sorted(set(int(value) for value in indices))
    spans: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value <= previous + gap + 1:
            previous = value
            continue
        if previous - start + 1 >= minimum_units:
            spans.append((start, previous))
        start = previous = value
    if previous - start + 1 >= minimum_units:
        spans.append((start, previous))
    return spans


def score_detector_features(
    features: Sequence[dict[str, Any]],
    *,
    config: DetectorConfig = DetectorConfig(),
    risk_model: Any | None = None,
    active_threshold: float | None = None,
    active_safe_threshold: float | None = None,
    active_safe_boundary_score_threshold: float = 0.25,
    detector_name: str | None = None,
) -> dict[str, Any]:
    """Apply one explicit detector score and derive spans from that score.

    ``risk_score`` always denotes the active score consumed by downstream
    experiments.  The transparent rule score is retained separately as
    ``rule_risk_score``; a frozen learned model additionally emits
    ``learned_risk_score``.  This prevents a learned probability threshold from
    being accidentally applied to the rule-score scale.
    """
    active_key = "learned_risk_score" if risk_model is not None else "rule_risk_score"
    threshold = float(
        active_threshold if active_threshold is not None
        else config.risk_threshold
    )
    safe_threshold = float(
        active_safe_threshold if active_safe_threshold is not None
        else config.safe_threshold
    )
    scored: list[dict[str, Any]] = []
    for source in features:
        feature = dict(source)
        rule_score = rule_risk_score(feature)
        feature["rule_risk_score"] = rule_score
        if risk_model is not None:
            feature["learned_risk_score"] = float(risk_model.predict_score(feature))
        active_score = float(feature[active_key])
        feature["risk_score"] = active_score
        feature["active_risk_score_key"] = active_key
        feature["safe_boundary_score"] = safe_boundary_score(feature, risk_score=active_score)
        # A safe boundary is a joint decision: sufficiently low active risk and
        # sufficiently strong boundary evidence.  Persist a decision score so
        # calibration/evaluation uses exactly the same predicate as planning.
        feature["safe_boundary_decision_score"] = (
            float(feature["safe_boundary_score"])
            if active_score <= safe_threshold
            else 0.0
        )
        scored.append(feature)
    risky = [int(row["global_character_index"]) for row in scored if float(row["risk_score"]) >= threshold]
    safe_boundary_score_threshold = float(active_safe_boundary_score_threshold)
    if safe_boundary_score_threshold <= 0.0:
        raise ValueError("safe-boundary evidence threshold must be positive")
    safe = [
        int(row["global_character_index"]) for row in scored
        if (
            float(row["safe_boundary_decision_score"]) > 0.0
            and float(row["safe_boundary_decision_score"]) >= safe_boundary_score_threshold
        )
    ]
    return {
        "schema_version": "alignment_detector_report_v2",
        "config": config.to_dict(),
        "selected_detector": detector_name or (type(risk_model).__name__ if risk_model is not None else "rule"),
        "active_score_key": active_key,
        "active_risk_threshold": threshold,
        "active_safe_threshold": safe_threshold,
        "active_safe_boundary_score_threshold": safe_boundary_score_threshold,
        "feature_count": len(scored),
        "risk_spans": [
            {"character_start": start, "character_end": end}
            for start, end in _merge_indices(risky, config.merge_gap_units, config.minimum_span_units)
        ],
        "safe_boundaries": safe,
        "features": scored,
    }


def inspect_alignment(
    rows: Iterable[dict[str, Any]],
    *,
    config: DetectorConfig = DetectorConfig(),
    input_candidates: Sequence[Sequence[dict[str, Any]]] = (),
    window_candidates: Sequence[Sequence[dict[str, Any]]] = (),
    audio_support_by_index: dict[int, dict[str, float]] | None = None,
    cursor_disagreement_by_index: dict[int, float] | None = None,
    risk_model: Any | None = None,
    active_threshold: float | None = None,
    active_safe_threshold: float | None = None,
    active_safe_boundary_score_threshold: float = 0.25,
    detector_name: str | None = None,
) -> dict[str, Any]:
    features = extract_features(
        rows,
        config=config,
        input_candidates=input_candidates,
        window_candidates=window_candidates,
        audio_support_by_index=audio_support_by_index,
        cursor_disagreement_by_index=cursor_disagreement_by_index,
    )
    return score_detector_features(
        features,
        config=config,
        risk_model=risk_model,
        active_threshold=active_threshold,
        active_safe_threshold=active_safe_threshold,
        active_safe_boundary_score_threshold=active_safe_boundary_score_threshold,
        detector_name=detector_name,
    )


def add_gt_labels(
    features: Sequence[dict[str, Any]],
    gt_rows: Iterable[dict[str, Any]],
    prediction_rows: Iterable[dict[str, Any]],
    *,
    tolerance_sec: float = 0.16,
) -> list[dict[str, Any]]:
    gt = {
        int(row.get("character_index", row.get("global_character_index"))): row
        for row in gt_rows
    }
    pred = {int(row["global_character_index"]): row for row in _ordered(prediction_rows)}
    output: list[dict[str, Any]] = []
    for source in features:
        row = dict(source)
        index = int(row["global_character_index"])
        g = gt.get(index)
        p = pred.get(index)
        if g is None or p is None:
            row.update({"gt_available": False, "gt_error": None, "gt_max_abs_error_sec": None})
        else:
            start = _boundary(p, "selected", "start")
            end = _boundary(p, "selected", "end")
            error = max(abs(float(start) - float(g["start_sec"])), abs(float(end) - float(g["end_sec"])))
            row.update({
                "gt_available": True,
                "gt_error": bool(error > tolerance_sec),
                "gt_max_abs_error_sec": error,
            })
        output.append(row)
    return output


def binary_metrics(rows: Sequence[dict[str, Any]], *, score_key: str, label_key: str, threshold: float) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    for row in rows:
        if row.get(label_key) is None:
            continue
        predicted = float(row.get(score_key, 0.0)) >= threshold
        actual = bool(row[label_key])
        if predicted and actual:
            tp += 1
        elif predicted:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "threshold": threshold,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
    }


def event_metrics(
    rows: Sequence[dict[str, Any]],
    *,
    score_key: str,
    label_key: str,
    threshold: float,
    merge_gap_units: int = 1,
) -> dict[str, Any]:
    """One-to-one overlap PRF for contiguous error/risk events.

    Unit-level PRF can look strong when a detector paints a very wide region.
    Event PRF therefore merges neighbouring positive units and matches each
    predicted event to at most one GT event by maximum index overlap.
    """
    usable = [row for row in rows if row.get(label_key) is not None]
    predicted_indices = [
        int(row["global_character_index"]) for row in usable
        if float(row.get(score_key, 0.0)) >= threshold
    ]
    reference_indices = [
        int(row["global_character_index"]) for row in usable if bool(row[label_key])
    ]
    predicted_spans = _merge_indices(predicted_indices, merge_gap_units, 1)
    reference_spans = _merge_indices(reference_indices, 0, 1)
    pairs: list[tuple[int, int, int]] = []
    for p_index, (p_start, p_end) in enumerate(predicted_spans):
        for r_index, (r_start, r_end) in enumerate(reference_spans):
            overlap = max(0, min(p_end, r_end) - max(p_start, r_start) + 1)
            if overlap:
                pairs.append((overlap, p_index, r_index))
    matched_pred: set[int] = set()
    matched_ref: set[int] = set()
    for _, p_index, r_index in sorted(pairs, reverse=True):
        if p_index in matched_pred or r_index in matched_ref:
            continue
        matched_pred.add(p_index); matched_ref.add(r_index)
    tp = len(matched_pred)
    fp = len(predicted_spans) - tp
    fn = len(reference_spans) - len(matched_ref)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "threshold": float(threshold),
        "predicted_event_count": len(predicted_spans),
        "reference_event_count": len(reference_spans),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "predicted_spans": [{"character_start": a, "character_end": b} for a, b in predicted_spans],
        "reference_spans": [{"character_start": a, "character_end": b} for a, b in reference_spans],
        "merge_gap_units": int(merge_gap_units),
    }


def event_threshold_curve(
    rows: Sequence[dict[str, Any]], *, score_key: str = "risk_score", label_key: str = "gt_error",
    thresholds: Sequence[float] | None = None, merge_gap_units: int = 1,
) -> list[dict[str, Any]]:
    if thresholds is None:
        values = sorted({float(row.get(score_key, 0.0)) for row in rows})
        if len(values) > 100:
            thresholds = [float(np.quantile(values, q)) for q in np.linspace(0.0, 1.0, 101)]
        else:
            thresholds = values
    return [
        event_metrics(
            rows, score_key=score_key, label_key=label_key,
            threshold=float(value), merge_gap_units=merge_gap_units,
        )
        for value in thresholds
    ]


def threshold_curve(
    rows: Sequence[dict[str, Any]], *, score_key: str = "risk_score", label_key: str = "gt_error",
    thresholds: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    if thresholds is None:
        values = sorted({float(row.get(score_key, 0.0)) for row in rows})
        if len(values) > 100:
            thresholds = [float(np.quantile(values, q)) for q in np.linspace(0.0, 1.0, 101)]
        else:
            thresholds = values
    return [binary_metrics(rows, score_key=score_key, label_key=label_key, threshold=float(value)) for value in thresholds]


@dataclass
class LogisticRiskModel:
    feature_names: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float

    @classmethod
    def fit(
        cls,
        rows: Sequence[dict[str, Any]],
        *,
        feature_names: Sequence[str] = DEFAULT_FEATURES,
        label_key: str = "gt_error",
        learning_rate: float = 0.05,
        epochs: int = 1000,
        l2: float = 1e-3,
        class_balance: bool = True,
    ) -> "LogisticRiskModel":
        usable = [row for row in rows if row.get(label_key) is not None]
        if not usable:
            raise ValueError("no labelled detector rows")
        names = tuple(feature_names)
        x = np.asarray([[float(row.get(name, 0.0)) for name in names] for row in usable], dtype=np.float64)
        y = np.asarray([float(bool(row[label_key])) for row in usable], dtype=np.float64)
        mean = x.mean(axis=0)
        scale = x.std(axis=0)
        scale[scale < 1e-8] = 1.0
        z = (x - mean) / scale
        weights = np.zeros(z.shape[1], dtype=np.float64)
        bias = 0.0
        sample_weight = np.ones_like(y)
        if class_balance and 0 < y.sum() < len(y):
            positive = len(y) / (2.0 * y.sum())
            negative = len(y) / (2.0 * (len(y) - y.sum()))
            sample_weight = np.where(y > 0.5, positive, negative)
        for _ in range(max(1, int(epochs))):
            logits = np.clip(z @ weights + bias, -30.0, 30.0)
            probabilities = 1.0 / (1.0 + np.exp(-logits))
            residual = (probabilities - y) * sample_weight
            gradient = z.T @ residual / len(y) + l2 * weights
            bias_gradient = float(residual.mean())
            weights -= learning_rate * gradient
            bias -= learning_rate * bias_gradient
        return cls(names, mean, scale, weights, float(bias))

    def predict_score(self, row: dict[str, Any]) -> float:
        x = np.asarray([float(row.get(name, 0.0)) for name in self.feature_names], dtype=np.float64)
        z = (x - self.mean) / self.scale
        logit = float(np.clip(z @ self.weights + self.bias, -30.0, 30.0))
        return 1.0 / (1.0 + math.exp(-logit))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "logistic_risk_model_v1",
            "feature_names": list(self.feature_names),
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "weights": self.weights.tolist(),
            "bias": self.bias,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LogisticRiskModel":
        return cls(
            tuple(payload["feature_names"]),
            np.asarray(payload["mean"], dtype=np.float64),
            np.asarray(payload["scale"], dtype=np.float64),
            np.asarray(payload["weights"], dtype=np.float64),
            float(payload["bias"]),
        )


@dataclass
class DecisionStump:
    feature: str
    threshold: float
    left_value: float
    right_value: float

    def predict(self, row: dict[str, Any]) -> float:
        return self.left_value if float(row.get(self.feature, 0.0)) <= self.threshold else self.right_value


@dataclass
class StumpBoostRiskModel:
    base_score: float
    learning_rate: float
    stumps: list[DecisionStump]

    @classmethod
    def fit(
        cls,
        rows: Sequence[dict[str, Any]],
        *,
        feature_names: Sequence[str] = DEFAULT_FEATURES,
        label_key: str = "gt_error",
        rounds: int = 50,
        learning_rate: float = 0.1,
        candidate_quantiles: int = 16,
    ) -> "StumpBoostRiskModel":
        usable = [row for row in rows if row.get(label_key) is not None]
        if not usable:
            raise ValueError("no labelled detector rows")
        y = np.asarray([float(bool(row[label_key])) for row in usable], dtype=np.float64)
        prevalence = min(max(float(y.mean()), 1e-5), 1.0 - 1e-5)
        base = math.log(prevalence / (1.0 - prevalence))
        scores = np.full(len(usable), base, dtype=np.float64)
        stumps: list[DecisionStump] = []
        for _ in range(max(1, int(rounds))):
            probabilities = 1.0 / (1.0 + np.exp(-np.clip(scores, -30, 30)))
            residual = y - probabilities
            best: tuple[float, DecisionStump, np.ndarray] | None = None
            for feature in feature_names:
                values = np.asarray([float(row.get(feature, 0.0)) for row in usable], dtype=np.float64)
                thresholds = np.unique(np.quantile(values, np.linspace(0.0, 1.0, candidate_quantiles + 2)[1:-1]))
                for threshold in thresholds:
                    left = values <= threshold
                    if not left.any() or left.all():
                        continue
                    left_value = float(residual[left].mean())
                    right_value = float(residual[~left].mean())
                    prediction = np.where(left, left_value, right_value)
                    loss = float(np.mean((residual - prediction) ** 2))
                    stump = DecisionStump(feature, float(threshold), left_value, right_value)
                    if best is None or loss < best[0]:
                        best = (loss, stump, prediction)
            if best is None:
                break
            _, stump, prediction = best
            stumps.append(stump)
            scores += learning_rate * prediction
        return cls(base, learning_rate, stumps)

    def predict_score(self, row: dict[str, Any]) -> float:
        score = self.base_score + self.learning_rate * sum(stump.predict(row) for stump in self.stumps)
        score = max(-30.0, min(30.0, score))
        return 1.0 / (1.0 + math.exp(-score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "stump_boost_risk_model_v1",
            "base_score": self.base_score,
            "learning_rate": self.learning_rate,
            "stumps": [asdict(stump) for stump in self.stumps],
        }
