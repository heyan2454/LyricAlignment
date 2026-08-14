"""No-GT per-unit features for shadow-only realign gating."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

NO_GT_FEATURE_SCHEMA = "unit_realign_no_gt_features_v1"
ALLOWED_FEATURE_KEYS = frozenset({
    "schema", "song_id", "region_id", "request_id", "request_identity", "family", "canonical_unit_id", "role",
    "baseline_present", "candidate_present", "candidate_missing", "mean_boundary_displacement_ms",
    "signed_start_displacement_ms", "signed_end_displacement_ms", "detector_p_bad_before", "detector_p_bad_after",
    "signed_detector_delta", "context_protected", "duration_sec", "decoder_confidence", "state_before", "state_after",
    "monotonicity_violation", "inversion_count", "overlap_sec", "compression_ratio", "slot_violation",
    "safe_context_changed_count", "raw_official_disagreement_ms", "local_consistency",
    # no-GT selector signals (E5/WP7): posterior/scorer/structure, never GT outcomes.
    "margin", "min_margin", "num_margins_above", "entropy", "detector_state", "detector_p_bad",
    "context_displacement_ms", "fixed_point_spread_ms", "split",
})


NESTED_STRUCTURE_KEYS = frozenset({"decoder_confidence"})
_FORBIDDEN_TOKENS = ("gt", "error", "delta", "label", "harm", "oracle")


def assert_no_gt_feature_row(row: Mapping[str, Any]) -> None:
    """Recursive strict allowlist: features cannot smuggle evaluator-derived values in."""
    def walk(value: Any, path: str = "", parent_key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key = str(key)
                if parent_key in NESTED_STRUCTURE_KEYS:
                    if any(token in key.lower() for token in _FORBIDDEN_TOKENS):
                        raise ValueError(f"no-GT feature contains forbidden or unapproved key {path}.{key}")
                elif key not in ALLOWED_FEATURE_KEYS:
                    raise ValueError(f"no-GT feature contains forbidden or unapproved key {path}.{key}")
                walk(child, f"{path}.{key}", key)
        elif isinstance(value, (list, tuple)):
            for i, child in enumerate(value):
                walk(child, f"{path}[{i}]", parent_key)
    walk(row)


def _time(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def build_unit_features(
    *, baseline_rows: Sequence[Mapping[str, Any]], candidate_rows: Sequence[Mapping[str, Any]],
    detector_before: Mapping[int, Mapping[str, Any]] | None = None,
    detector_after: Mapping[int, Mapping[str, Any]] | None = None,
    song_id: str, region_id: str, request_id: str, family: str,
    target_unit_ids: Sequence[int], request_identity: str | None = None,
) -> list[dict[str, Any]]:
    """Emit only alignment/detector/structure signals, never GT outcomes."""
    before = {int(r["canonical_unit_id"]): r for r in baseline_rows
              if isinstance(r.get("canonical_unit_id"), int)}
    after = {int(r["canonical_unit_id"]): r for r in candidate_rows
             if isinstance(r.get("canonical_unit_id"), int)}
    db, da = detector_before or {}, detector_after or {}
    targets = {int(x) for x in target_unit_ids}
    rows: list[dict[str, Any]] = []
    for cid in sorted(set(before) | set(after) | targets):
        old, new = before.get(cid), after.get(cid)
        os, oe = (_time(old or {}, "fixed_global_start_sec"), _time(old or {}, "fixed_global_end_sec"))
        ns, ne = (_time(new or {}, "fixed_global_start_sec"), _time(new or {}, "fixed_global_end_sec"))
        displacement = None
        if None not in (os, oe, ns, ne):
            displacement = round((abs(ns - os) + abs(ne - oe)) * 500.0, 4)
        pb = _time(db.get(cid, {}), "p_bad")
        pa = _time(da.get(cid, {}), "p_bad")
        row = {
            "schema": NO_GT_FEATURE_SCHEMA,
            "song_id": song_id, "region_id": region_id, "request_id": request_id, "family": family,
            "request_identity": request_identity,
            "canonical_unit_id": cid, "role": "target" if cid in targets else "context",
            "baseline_present": old is not None, "candidate_present": new is not None,
            "mean_boundary_displacement_ms": displacement,
            "candidate_missing": new is None,
            "detector_p_bad_before": pb, "detector_p_bad_after": pa,
            # W-review P1-1: expose a bare detector_p_bad (max of before/after) so the
            # no-GT selector's primary proxy has a real producer on the extracted
            # feature matrix (SIGNAL_NAMES intent), instead of being None on real data.
            "detector_p_bad": None if pb is None and pa is None else round(max(pb or 0.0, pa or 0.0), 6),
            "signed_detector_delta": None if pb is None or pa is None else round(pa - pb, 6),
            "context_protected": None if cid in targets or displacement is None else displacement <= 10.0,
            "duration_sec": None if ns is None or ne is None else round(ne - ns, 6),
        }
        assert_no_gt_feature_row(row)
        rows.append(row)
    return rows
