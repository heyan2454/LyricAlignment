"""Evaluation-only unit outcomes for realign candidates.

This module deliberately accepts GT only as an explicit evaluator argument.
It never constructs requests or no-GT gate features.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

UNIT_OUTCOME_SCHEMA = "unit_realign_outcome_v2"
BUCKETS_MS = (100, 200, 500, 1000)


def _times(row: Mapping[str, Any] | None) -> tuple[float, float] | None:
    if row is None:
        return None
    start = row.get("fixed_global_start_sec", row.get("start_sec"))
    end = row.get("fixed_global_end_sec", row.get("end_sec"))
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
        return None
    return float(start), float(end)


def _index(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[int, Mapping[str, Any]], list[int]]:
    indexed: dict[int, Mapping[str, Any]] = {}
    duplicates: list[int] = []
    for row in rows:
        cid = row.get("canonical_unit_id")
        if not isinstance(cid, int):
            continue
        if cid in indexed:
            duplicates.append(cid)
        else:
            indexed[cid] = row
    return indexed, duplicates


def _errors(pred: Mapping[str, Any] | None, gt: Mapping[str, Any]) -> dict[str, float | None]:
    interval = _times(pred)
    gt_interval = _times(gt)
    if interval is None or gt_interval is None:
        return {"onset_error_ms": None, "offset_error_ms": None, "max_boundary_error_ms": None}
    onset = abs(interval[0] - gt_interval[0]) * 1000.0
    offset = abs(interval[1] - gt_interval[1]) * 1000.0
    return {
        "onset_error_ms": round(onset, 4),
        "offset_error_ms": round(offset, 4),
        "max_boundary_error_ms": round(max(onset, offset), 4),
    }


def _buckets(errors: Mapping[str, float | None], prefix: str) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    for name, value in errors.items():
        metric = name.removesuffix("_ms")
        for threshold in BUCKETS_MS:
            out[f"{prefix}_{metric}_le_{threshold}ms"] = None if value is None else value <= threshold
    return out


def pair_unit_outcomes(
    *,
    baseline_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    gt_by_canonical: Mapping[int, Mapping[str, Any]],
    song_id: str,
    region_id: str,
    request_id: str,
    family: str,
    target_unit_ids: Sequence[int],
    fixed_context_unit_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """Canonical-pair baseline/candidate rows with GT at unit granularity.

    One output row is emitted for each GT target/context unit plus every extra
    candidate prediction.  Missing/extra/duplicate are explicit; target role
    is never inferred from timing.
    """
    baseline, baseline_dups = _index(baseline_rows)
    candidate, candidate_dups = _index(candidate_rows)
    targets = {int(cid) for cid in target_unit_ids}
    # Legacy callers without an explicit local context retain their previous
    # behavior. v2 callers pass it, so outside-window GT rows never enter an
    # efficacy denominator.
    scoped = targets | ({int(x) for x in fixed_context_unit_ids} if fixed_context_unit_ids is not None else set(gt_by_canonical) | set(baseline))
    extras = {cid for cid in candidate if cid not in gt_by_canonical and cid not in baseline}
    ids = sorted(scoped | extras)
    out: list[dict[str, Any]] = []
    for cid in ids:
        gt = gt_by_canonical.get(cid)
        old = baseline.get(cid)
        new = candidate.get(cid)
        old_err = _errors(old, gt) if gt is not None else _errors(None, {})
        new_err = _errors(new, gt) if gt is not None else _errors(None, {})
        old_max, new_max = old_err["max_boundary_error_ms"], new_err["max_boundary_error_ms"]
        delta = None if old_max is None or new_max is None else round(new_max - old_max, 4)
        row = {
            "schema": UNIT_OUTCOME_SCHEMA,
            "song_id": song_id, "region_id": region_id, "request_id": request_id,
            "family": family, "canonical_unit_id": cid,
            "role": "target" if cid in targets else ("extra" if cid in extras else "context"),
            "pairing": "canonical" if gt is not None else "extra_prediction",
            "old_missing": old is None, "new_missing": new is None,
            "extra_prediction": gt is None and new is not None,
            "baseline_duplicate_prediction": cid in baseline_dups,
            "candidate_duplicate_prediction": cid in candidate_dups,
            **{f"old_{k}": v for k, v in old_err.items()},
            **{f"new_{k}": v for k, v in new_err.items()},
            "delta_max_boundary_error_ms": delta,
        }
        row.update(_buckets(old_err, "old"))
        row.update(_buckets(new_err, "new"))
        out.append(row)
    # An output outside the request-local mapping is evidence, not something
    # to silently discard. It deliberately has no canonical-unit primary key.
    for prediction in candidate_rows:
        if isinstance(prediction.get("canonical_unit_id"), int):
            continue
        extra_row = {
            "schema": UNIT_OUTCOME_SCHEMA, "song_id": song_id, "region_id": region_id,
            "request_id": request_id, "family": family, "canonical_unit_id": None,
            "prediction_local_index": prediction.get("prediction_local_index", prediction.get("global_character_index")),
            "role": "extra", "pairing": "invalid_unpairable", "old_missing": True, "new_missing": False,
            "covered_to_missing": False, "missing_to_covered": False, "extra_prediction": True,
            "invalid_unpairable": True, "baseline_duplicate_prediction": False,
            "candidate_duplicate_prediction": False, "old_onset_error_ms": None, "old_offset_error_ms": None,
            "old_max_boundary_error_ms": None, "new_onset_error_ms": None, "new_offset_error_ms": None,
            "new_max_boundary_error_ms": None, "delta_max_boundary_error_ms": None,
        }
        extra_row.update(_buckets({"onset_error_ms": None, "offset_error_ms": None,
                                   "max_boundary_error_ms": None}, "old"))
        extra_row.update(_buckets({"onset_error_ms": None, "offset_error_ms": None,
                                   "max_boundary_error_ms": None}, "new"))
        out.append(extra_row)
    return out


def classify_unit_outcome(row: Mapping[str, Any], *, material_ms: float = 200.0, catastrophic_ms: float = 1000.0) -> str:
    """Classify one evaluator row without averaging away missing coverage.

    ``degraded_finite`` is decided purely on delta: candidate must be a
    material (>= ``material_ms``) regression relative to baseline. A unit whose
    baseline itself is already poor (e.g. old_max > ``catastrophic_ms``) is not
    flagged as degraded unless candidate makes it materially worse; absolute
    catastrophic severity for targets is evaluated separately in
    ``aggregate_region_outcome``. ``catastrophic_ms`` is retained for signature
    compatibility with that caller.
    """
    if row.get("invalid_unpairable"):
        return "invalid"
    if row.get("extra_prediction"):
        return "extra"
    if row.get("old_missing") and not row.get("new_missing"):
        return "missing_to_covered"
    if not row.get("old_missing") and row.get("new_missing"):
        return "covered_to_missing"
    delta = row.get("delta_max_boundary_error_ms")
    if not isinstance(delta, (int, float)):
        return "invalid"
    if delta <= -material_ms:
        return "improved_finite"
    if delta >= material_ms:
        return "degraded_finite"
    return "unchanged_finite"


def aggregate_region_outcome(rows: Sequence[Mapping[str, Any]], *, material_ms: float = 200.0, catastrophic_ms: float = 1000.0) -> dict[str, Any]:
    """Conservative candidate/region label, preserving target and context roles.

    Denominator accounting separates fixed-context from extra rows:
    ``n_fixed_context`` counts rows with role == "context"; ``n_extra`` counts
    rows with role == "extra" (including invalid_unpairable).  ``n_context``
    is retained as an alias for fixed-context only.  Extra rows still take
    part in harm so the frozen beneficial/harmful/mixed/catastrophic
    classification is unchanged.
    """
    relevant = [r for r in rows if r.get("role") in {"target", "context", "extra"}]
    labels = [classify_unit_outcome(r, material_ms=material_ms, catastrophic_ms=catastrophic_ms) for r in relevant]
    target_rows = [r for r in relevant if r.get("role") == "target"]
    target_labels = [classify_unit_outcome(r, material_ms=material_ms, catastrophic_ms=catastrophic_ms) for r in target_rows]
    catastrophic = any(x == "covered_to_missing" for x in target_labels) or any(
        isinstance(r.get("new_max_boundary_error_ms"), (int, float)) and r["new_max_boundary_error_ms"] > catastrophic_ms
        for r in target_rows)
    improved = any(x in {"improved_finite", "missing_to_covered"} for x in labels)
    harmed = any(x in {"degraded_finite", "covered_to_missing", "extra", "invalid"} for x in labels)
    if catastrophic: outcome = "catastrophic_harmful"
    elif improved and harmed: outcome = "mixed"
    elif harmed: outcome = "harmful"
    elif improved: outcome = "beneficial"
    else: outcome = "neutral"
    context_rows = [r for r in relevant if r.get("role") == "context"]
    extra_rows = [r for r in relevant if r.get("role") == "extra"]
    first = relevant[0] if relevant else {}
    return {"schema": "unit_realign_region_outcome_v2", "song_id": first.get("song_id"),
            "region_id": first.get("region_id"), "request_id": first.get("request_id"),
            "request_identity": first.get("request_identity"), "family": first.get("family"),
            "outcome": outcome, "n_target": len(target_rows),
            "n_context": len(context_rows), "n_fixed_context": len(context_rows), "n_extra": len(extra_rows),
            "unit_class_counts": {name: labels.count(name) for name in sorted(set(labels))},
            "material_ms": material_ms, "catastrophic_ms": catastrophic_ms}


def aggregate_candidate_outcome(region_outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate a request only; callers must cluster inference by song."""
    if not region_outcomes:
        return {"schema": "unit_realign_candidate_outcome_v2", "outcome": "invalid", "n_regions": 0,
                "n_fixed_context": 0, "n_extra": 0}
    labels = [str(r.get("outcome")) for r in region_outcomes]
    if "catastrophic_harmful" in labels: outcome = "catastrophic_harmful"
    elif "mixed" in labels or ("beneficial" in labels and "harmful" in labels): outcome = "mixed"
    elif "harmful" in labels: outcome = "harmful"
    elif "beneficial" in labels: outcome = "beneficial"
    else: outcome = "neutral"
    first = region_outcomes[0]
    return {"schema": "unit_realign_candidate_outcome_v2", "song_id": first.get("song_id"),
            "request_identity": first.get("request_identity"), "request_id": first.get("request_id"),
            "family": first.get("family"), "outcome": outcome, "n_regions": len(region_outcomes),
            "n_fixed_context": sum(int(r.get("n_fixed_context") or 0) for r in region_outcomes),
            "n_extra": sum(int(r.get("n_extra") or 0) for r in region_outcomes)}
