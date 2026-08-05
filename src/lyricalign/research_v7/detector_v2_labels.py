"""Detector V2 unit correctness labels (raw-target and official-target).

18 §5 GT tri-state labeling on **real traceable unit GT**:
- safe:      onset and offset both <= 100 ms error, valid time, correct occurrence
- unsafe:    either boundary > 250 ms, or missing output, severe inversion/out-of-range,
             wrong repeated section, continuous global misalignment
- grey:      100–250 ms error band (excluded from first-pass training; reported separately)
- ambiguous: GT target occurrence cannot be determined (independent cohort)

Only M4Singer accepted rule-based pinyin-validated character timestamps are used as
training labels. Synthetic-uniform axes never generate correctness labels (21 §1).

Labels are derived strictly from GT; feature extraction must never consume this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

SAFE_MAX_ERROR_SEC = 0.100
UNSAFE_MIN_ERROR_SEC = 0.250


class UnitLabel(str):
    """safe | unsafe | grey | ambiguous"""


def boundary_errors(
    gt_start_sec: float | None, gt_end_sec: float | None,
    pred_start_sec: float | None, pred_end_sec: float | None,
) -> dict:
    """Return per-boundary absolute errors; None for missing geometry."""
    out = {"start_abs_error_sec": None, "end_abs_error_sec": None,
           "missing_geometry": False}
    if pred_start_sec is None or pred_end_sec is None:
        out["missing_geometry"] = True
        return out
    if gt_start_sec is None or gt_end_sec is None:
        out["missing_geometry"] = True
        return out
    out["start_abs_error_sec"] = round(abs(float(pred_start_sec) - float(gt_start_sec)), 6)
    out["end_abs_error_sec"] = round(abs(float(pred_end_sec) - float(gt_end_sec)), 6)
    return out


def label_unit(
    *,
    gt_start_sec: float | None,
    gt_end_sec: float | None,
    pred_start_sec: float | None,
    pred_end_sec: float | None,
    pred_valid_time: bool = True,
    occurrence_ambiguous: bool = False,
    safe_max_sec: float = SAFE_MAX_ERROR_SEC,
    unsafe_min_sec: float = UNSAFE_MIN_ERROR_SEC,
) -> tuple[UnitLabel, dict]:
    """Label one unit; returns (label, audit dict).

    Missing output (no geometry) is unsafe. Severe time inversion or out-of-range
    is unsafe (caller must pass pred_valid_time=False). Ambiguous occurrence is
    always `ambiguous` and never forced into safe/unsafe (18 §5).
    """
    if occurrence_ambiguous:
        return UnitLabel("ambiguous"), {"reason": "occurrence_ambiguous"}
    err = boundary_errors(gt_start_sec, gt_end_sec, pred_start_sec, pred_end_sec)
    if err["missing_geometry"]:
        return UnitLabel("unsafe"), {"reason": "missing_output_geometry", **err}
    if not pred_valid_time:
        return UnitLabel("unsafe"), {"reason": "invalid_time_inversion_or_oob", **err}
    worst = max(err["start_abs_error_sec"], err["end_abs_error_sec"])
    if worst <= safe_max_sec:
        return UnitLabel("safe"), {"reason": "within_safe", "worst_abs_error_sec": worst, **err}
    if worst > unsafe_min_sec:
        return UnitLabel("unsafe"), {"reason": "exceeds_unsafe", "worst_abs_error_sec": worst, **err}
    return UnitLabel("grey"), {"reason": "grey_band", "worst_abs_error_sec": worst, **err}


@dataclass(frozen=True)
class LabeledUnit:
    request_identity: str
    canonical_unit_id: int
    target: str            # raw | official
    label: UnitLabel
    audit: dict


def label_request_units(
    *,
    request_identity: str,
    target: str,
    rows: Sequence[Mapping],
    canonical_gt: Mapping[int, tuple[float, float]],
    occurrence_ambiguous_ids: set[int] = frozenset(),
    safe_max_sec: float = SAFE_MAX_ERROR_SEC,
    unsafe_min_sec: float = UNSAFE_MIN_ERROR_SEC,
) -> list[LabeledUnit]:
    """Label every canonical unit present in canonical_gt using decoder rows.

    rows: decoder output rows with canonical_unit_id + start/end (raw or official
    view). Units in canonical_gt without a matching row are unsafe (missing output).
    """
    if target not in ("raw", "official"):
        raise ValueError(f"target must be raw|official, got {target!r}")
    start_key = "raw_global_start_sec" if target == "raw" else "official_fixed_global_start_sec"
    end_key = "raw_global_end_sec" if target == "raw" else "official_fixed_global_end_sec"
    fallback_start = "raw_global_start_sec" if target == "official" else "official_fixed_global_start_sec"
    fallback_end = "raw_global_end_sec" if target == "official" else "official_fixed_global_end_sec"
    by_unit: dict[int, Mapping] = {}
    for row in rows:
        cid = int(row.get("canonical_unit_id", row.get("global_character_index", -1)))
        if cid >= 0:
            by_unit.setdefault(cid, row)
    out: list[LabeledUnit] = []
    for cid, (gts, gte) in sorted(canonical_gt.items()):
        row = by_unit.get(cid)
        if row is None:
            out.append(LabeledUnit(request_identity, cid, target,
                                   UnitLabel("unsafe"), {"reason": "missing_output_geometry"}))
            continue
        ps = row.get(start_key) if row.get(start_key) is not None else row.get(fallback_start)
        pe = row.get(end_key) if row.get(end_key) is not None else row.get(fallback_end)
        ps = float(ps) if ps is not None else None
        pe = float(pe) if pe is not None else None
        valid = True
        if ps is not None and pe is not None:
            if pe <= ps or ps < 0:
                valid = False
        label, audit = label_unit(gt_start_sec=gts, gt_end_sec=gte,
                                  pred_start_sec=ps, pred_end_sec=pe,
                                  pred_valid_time=valid,
                                  occurrence_ambiguous=cid in occurrence_ambiguous_ids,
                                  safe_max_sec=safe_max_sec, unsafe_min_sec=unsafe_min_sec)
        out.append(LabeledUnit(request_identity, cid, target, label, audit))
    return out


def summarize_labels(labeled: Sequence[LabeledUnit]) -> dict:
    """Pooled label summary with explicit denominators; None when empty."""
    from collections import Counter
    counts = Counter(x.label for x in labeled)
    total = len(labeled)
    return {
        "n_units": total,
        "n_safe": counts["safe"], "n_unsafe": counts["unsafe"],
        "n_grey": counts["grey"], "n_ambiguous": counts["ambiguous"],
        "unsafe_rate": round(counts["unsafe"] / total, 6) if total else None,
        "safe_rate": round(counts["safe"] / total, 6) if total else None,
        "by_target": {
            t: dict(Counter(x.label for x in labeled if x.target == t))
            for t in sorted({x.target for x in labeled})
        },
    }
