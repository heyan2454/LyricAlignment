"""Pure validation for unit-realign v2 requests before GPU dispatch."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .request_families import UNIT_REQUEST_SCHEMA, build_request_identity


FORBIDDEN_REQUEST_KEYS = frozenset({"gt", "ground_truth", "label", "old_error", "new_error", "delta_error", "oracle"})


def _contains_forbidden(value: Any, path: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lower = str(key).lower()
            if any(token in lower for token in FORBIDDEN_REQUEST_KEYS):
                return f"forbidden_request_field:{path}.{key}"
            found = _contains_forbidden(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, (tuple, list)):
        for i, child in enumerate(value):
            found = _contains_forbidden(child, f"{path}[{i}]")
            if found:
                return found
    return None


def validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return a serializable dispatch decision, never raising for bad input."""
    if request.get("schema") != UNIT_REQUEST_SCHEMA:
        return {"status": "invalid", "reason": "schema_mismatch"}
    if request.get("family") == "R-NULL":
        return {"status": "null", "reason": request.get("reason", "r_null")}
    forbidden = _contains_forbidden(request)
    if forbidden:
        return {"status": "invalid", "reason": forbidden}
    ids = request.get("canonical_ids") or []
    local_to_canonical = request.get("local_to_canonical") or []
    c2l = request.get("canonical_to_local") or {}
    if len(ids) != len(set(ids)) or list(local_to_canonical) != list(ids):
        return {"status": "invalid", "reason": "global_local_mapping_not_bijective"}
    if {str(cid): i for i, cid in enumerate(ids)} != {str(k): int(v) for k, v in c2l.items()}:
        return {"status": "invalid", "reason": "canonical_to_local_mismatch"}
    active = {int(x) for x in request.get("active_target_unit_ids", ())}
    fixed = {int(x) for x in request.get("fixed_context_unit_ids", ())}
    if not active or not active <= set(ids) or active & fixed:
        return {"status": "invalid", "reason": "invalid_active_fixed_partition"}
    if request.get("family") == "R-S" and active | fixed != set(ids):
        return {"status": "invalid", "reason": "sparse_partition_incomplete"}
    audio_range = request.get("candidate_audio_range_sec")
    if not isinstance(audio_range, list) or len(audio_range) != 2 or not all(isinstance(x, (int, float)) for x in audio_range) or audio_range[1] <= audio_range[0]:
        return {"status": "invalid", "reason": "invalid_candidate_audio_span"}
    if request.get("family") == "R-B":
        anchors = request.get("anchors") or {}
        if anchors.get("left") is None or anchors.get("right") is None:
            return {"status": "not_constructible", "reason": "missing_bilateral_anchor"}
    try:
        expected = build_request_identity(request)
    except ValueError as exc:
        return {"status": "invalid", "reason": f"identity_context_incomplete:{exc}"}
    if request.get("request_identity") != expected:
        return {"status": "invalid", "reason": "request_identity_mismatch", "expected_request_identity": expected}
    return {"status": "ready", "reason": None, "request_identity": expected}
