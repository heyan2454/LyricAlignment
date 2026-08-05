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

import math
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
    canonical_to_local: Mapping[int, int] | None = None,
    safe_max_sec: float = SAFE_MAX_ERROR_SEC,
    unsafe_min_sec: float = UNSAFE_MIN_ERROR_SEC,
) -> list[LabeledUnit]:
    """Label every canonical unit present in canonical_gt using decoder rows.

    rows: decoder output rows with raw/official view geometry.

    Row -> canonical binding (M3): a row carrying `canonical_unit_id` uses that
    canonical-axis id directly; otherwise the request-local `global_character_index`
    must be inverted through `canonical_to_local` (local index -> canonical id).
    Rows whose local index has no canonical binding (inserted/extra units) do not
    enter canonical_gt matching (that canonical then has no row -> unsafe). A row
    without `canonical_unit_id` and no usable mapping raises: the request-local
    index is never silently treated as a canonical id.

    Target geometry is same-source only (M2): raw rows consume only raw_* keys and
    official rows only official_fixed_* keys; a row whose target keys are missing or
    one-sided is unsafe (missing output), never consuming the other target's keys.
    Non-finite times are unsafe (invalid_time).

    Units in canonical_gt without a matching row are unsafe (missing output);
    ambiguous units are reported as ambiguous before that (independent cohort).
    """
    if target not in ("raw", "official"):
        raise ValueError(f"target must be raw|official, got {target!r}")
    start_key = "raw_global_start_sec" if target == "raw" else "official_fixed_global_start_sec"
    end_key = "raw_global_end_sec" if target == "raw" else "official_fixed_global_end_sec"
    local_to_canonical = (
        {local: c for c, local in canonical_to_local.items()}
        if canonical_to_local is not None else None
    )
    by_unit: dict[int, Mapping] = {}
    for row in rows:
        if "canonical_unit_id" in row:
            cid = int(row["canonical_unit_id"])
        elif local_to_canonical is not None and "global_character_index" in row:
            cid = local_to_canonical.get(int(row["global_character_index"]))
            if cid is None:
                continue  # request-local unit without canonical binding -> not in canonical_gt
        else:
            raise ValueError(
                "decoder row lacks 'canonical_unit_id' key; request-local "
                "'global_character_index' needs canonical_to_local to bind row -> canonical (M3)")
        if cid >= 0:
            by_unit.setdefault(cid, row)
    out: list[LabeledUnit] = []
    for cid, (gts, gte) in sorted(canonical_gt.items()):
        row = by_unit.get(cid)
        if row is None:
            if cid in occurrence_ambiguous_ids:
                out.append(LabeledUnit(request_identity, cid, target,
                                       UnitLabel("ambiguous"), {"reason": "occurrence_ambiguous"}))
            else:
                out.append(LabeledUnit(request_identity, cid, target,
                                       UnitLabel("unsafe"), {"reason": "missing_output_geometry"}))
            continue
        ps_raw = row.get(start_key)
        pe_raw = row.get(end_key)
        used_keys = {"start_key": start_key, "end_key": end_key,
                     "start_present": ps_raw is not None, "end_present": pe_raw is not None}
        if ps_raw is None or pe_raw is None:
            # M2/混坐标：start/end 必须同源；单边几何按 missing geometry 处理，绝不跨 target 回退
            label, audit = label_unit(gt_start_sec=gts, gt_end_sec=gte,
                                      pred_start_sec=None, pred_end_sec=None,
                                      occurrence_ambiguous=cid in occurrence_ambiguous_ids,
                                      safe_max_sec=safe_max_sec, unsafe_min_sec=unsafe_min_sec)
            audit["reason"] = "missing_output_geometry"
            audit["used_keys"] = used_keys
            out.append(LabeledUnit(request_identity, cid, target, label, audit))
            continue
        ps = float(ps_raw)
        pe = float(pe_raw)
        if not (math.isfinite(ps) and math.isfinite(pe)):
            label, audit = label_unit(gt_start_sec=gts, gt_end_sec=gte,
                                      pred_start_sec=ps, pred_end_sec=pe,
                                      pred_valid_time=False,
                                      occurrence_ambiguous=cid in occurrence_ambiguous_ids,
                                      safe_max_sec=safe_max_sec, unsafe_min_sec=unsafe_min_sec)
            audit["reason"] = "invalid_time"
            audit["non_finite_geometry"] = True
            audit["used_keys"] = used_keys
            out.append(LabeledUnit(request_identity, cid, target, label, audit))
            continue
        valid = pe > ps and ps >= 0
        label, audit = label_unit(gt_start_sec=gts, gt_end_sec=gte,
                                  pred_start_sec=ps, pred_end_sec=pe,
                                  pred_valid_time=valid,
                                  occurrence_ambiguous=cid in occurrence_ambiguous_ids,
                                  safe_max_sec=safe_max_sec, unsafe_min_sec=unsafe_min_sec)
        audit["used_keys"] = used_keys
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
