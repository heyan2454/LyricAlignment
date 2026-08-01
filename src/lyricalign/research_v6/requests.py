"""Serializable experiment request and corruption contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable


@dataclass(frozen=True)
class AlignmentRequest:
    item_id: str
    audio_start_sec: float
    audio_end_sec: float
    text_start: int
    text_end: int  # exclusive
    ownership_start_sec: float | None = None
    ownership_end_sec: float | None = None
    decoder_names: tuple[str, ...] = ("raw", "official")
    request_role: str = "baseline"
    parent_request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, total_units: int | None = None, duration_sec: float | None = None) -> None:
        if self.audio_start_sec < 0 or self.audio_end_sec <= self.audio_start_sec:
            raise ValueError(f"invalid audio range: {self.audio_start_sec}, {self.audio_end_sec}")
        if self.text_start < 0 or self.text_end <= self.text_start:
            raise ValueError(f"invalid text range: {self.text_start}, {self.text_end}")
        if total_units is not None and self.text_end > total_units:
            raise ValueError(f"text_end {self.text_end} exceeds total_units {total_units}")
        if duration_sec is not None and self.audio_end_sec > duration_sec + 1e-6:
            raise ValueError(f"audio_end {self.audio_end_sec} exceeds duration {duration_sec}")
        if self.ownership_start_sec is not None and self.ownership_end_sec is not None:
            if not (self.audio_start_sec <= self.ownership_start_sec < self.ownership_end_sec <= self.audio_end_sec):
                raise ValueError("ownership range must be inside audio range")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def derive(self, **changes: Any) -> "AlignmentRequest":
        metadata = dict(self.metadata)
        metadata.update(changes.pop("metadata", {}))
        return replace(self, metadata=metadata, **changes)


@dataclass(frozen=True)
class CorruptionSpec:
    name: str
    text_start_delta: int = 0
    text_end_delta: int = 0
    text_length_ratio: float | None = None
    audio_start_delta_sec: float = 0.0
    audio_end_delta_sec: float = 0.0
    duplicate_left_units: int = 0
    replace_units: int = 0
    smooth_time_shift_sec: float = 0.0
    category: str = "input_mismatch"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_corruption(
    request: AlignmentRequest,
    spec: CorruptionSpec,
    *,
    total_units: int,
    duration_sec: float,
) -> AlignmentRequest:
    text_start = request.text_start + spec.text_start_delta
    text_end = request.text_end + spec.text_end_delta
    if spec.text_length_ratio is not None:
        length = max(1, int(round((request.text_end - request.text_start) * spec.text_length_ratio)))
        text_end = text_start + length
    if spec.duplicate_left_units > 0:
        text_start -= spec.duplicate_left_units
    text_start = max(0, min(total_units - 1, text_start))
    text_end = max(text_start + 1, min(total_units, text_end))
    if duration_sec <= 0.0:
        raise ValueError(f"duration_sec must be positive, got {duration_sec}")
    minimum_span = min(0.08, float(duration_sec))
    audio_start = min(
        max(0.0, request.audio_start_sec + spec.audio_start_delta_sec),
        max(0.0, float(duration_sec) - minimum_span),
    )
    audio_end = min(duration_sec, max(0.0, request.audio_end_sec + spec.audio_end_delta_sec))
    if audio_end <= audio_start:
        audio_end = min(duration_sec, audio_start + minimum_span)
    # Audio-boundary corruptions alter the local coordinate frame.  Move the
    # ownership interval by the same boundary perturbation, then clip it into
    # the corrupted audio range so every generated request remains executable
    # (notably for first/last windows at the item boundaries).
    ownership_start = request.ownership_start_sec
    ownership_end = request.ownership_end_sec
    if ownership_start is not None and ownership_end is not None:
        ownership_start += spec.audio_start_delta_sec
        ownership_end += spec.audio_end_delta_sec
        ownership_start = max(audio_start, min(audio_end - 1e-6, ownership_start))
        ownership_end = max(ownership_start + 1e-6, min(audio_end, ownership_end))
    derived = request.derive(
        audio_start_sec=audio_start,
        audio_end_sec=audio_end,
        text_start=text_start,
        text_end=text_end,
        ownership_start_sec=ownership_start,
        ownership_end_sec=ownership_end,
        request_role=f"corruption:{spec.name}",
        parent_request_id=request.metadata.get("request_id"),
        metadata={"corruption": spec.to_dict()},
    )
    derived.validate(total_units=total_units, duration_sec=duration_sec)
    return derived


def default_corruption_specs() -> list[CorruptionSpec]:
    result: list[CorruptionSpec] = []
    for delta in (-8, -4, -2, 2, 4, 8):
        result.append(CorruptionSpec(name=f"text_start_{delta:+d}", text_start_delta=delta, category="text_start"))
        result.append(CorruptionSpec(name=f"text_end_{delta:+d}", text_end_delta=delta, category="text_end"))
    for ratio in (0.50, 0.75, 1.25, 1.50):
        result.append(CorruptionSpec(name=f"text_ratio_{ratio:.2f}", text_length_ratio=ratio, category="text_amount"))
    for delta in (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0):
        result.append(CorruptionSpec(name=f"audio_start_{delta:+.1f}", audio_start_delta_sec=delta, category="audio_start"))
        result.append(CorruptionSpec(name=f"audio_end_{delta:+.1f}", audio_end_delta_sec=delta, category="audio_end"))
    for units in (2, 4, 8):
        result.append(CorruptionSpec(name=f"repeat_left_{units}", duplicate_left_units=units, category="repeated_committed_text"))
        result.append(CorruptionSpec(name=f"replace_text_{units}", replace_units=units, category="wrong_text"))
    for shift in (0.4, 0.8, 1.6):
        result.append(CorruptionSpec(name=f"smooth_shift_{shift:.1f}", smooth_time_shift_sec=shift, category="output_shift"))
    return result


def filter_specs(specs: Iterable[CorruptionSpec], categories: set[str] | None) -> list[CorruptionSpec]:
    return [spec for spec in specs if categories is None or spec.category in categories]
