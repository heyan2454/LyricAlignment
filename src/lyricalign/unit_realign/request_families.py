"""Versioned, document-global unit-realign request construction.

The identity of an execution request is deliberately different from the
intervention payload used to decide whether a forward is a no-op.  In
particular, changing a family label must never turn an otherwise identical
request into an ``effective_intervention``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


UNIT_REQUEST_SCHEMA = "unit_realign_request_v2"
INTERVENTION_PAYLOAD_SCHEMA = "unit_realign_intervention_payload_v1"


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def intervention_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return exactly the model-input changes relevant to no-op detection."""
    return {
        "schema": INTERVENTION_PAYLOAD_SCHEMA,
        "active_target_unit_ids": [int(x) for x in request.get("active_target_unit_ids", request.get("target_unit_ids", ()))],
        "fixed_context_unit_ids": [int(x) for x in request.get("fixed_context_unit_ids", ())],
        "candidate_audio_range_sec": request.get("candidate_audio_range_sec"),
        "candidate_text_ids": [int(x) for x in request.get("candidate_text_ids", request.get("canonical_ids", ()))],
        "candidate_text_sha256": "sha256:" + hashlib.sha256(
            "\x1f".join(str(x) for x in request.get("text_units", ())).encode("utf-8")).hexdigest(),
        "full_local_ids": [int(x) for x in request.get("canonical_ids", ())],
        "timestamp_slot_indices": request.get("timestamp_slot_indices"),
        "active_slot_indices": request.get("active_slot_indices"),
        "fixed_slot_rows": request.get("fixed_slot_rows"),
        "anchors": request.get("anchors"),
        "decoder_options": request.get("decoder_options", {}),
    }


def build_request_identity(request: Mapping[str, Any]) -> str:
    """Content-address an execution, including every cache-relevant context."""
    required = ("audio_sha256", "baseline_digest", "model_identity", "checkpoint_identity",
                "decoder_identity", "mapping_schema", "code_identity", "text_adapter_identity")
    missing = [key for key in required if not request.get(key)]
    if missing:
        raise ValueError("request identity missing " + ", ".join(missing))
    return _digest({
        "schema": UNIT_REQUEST_SCHEMA,
        "family": request.get("family"), "family_version": request.get("family_version", "v1"),
        "intervention_payload": intervention_payload(request),
        "canonical_ids": request.get("canonical_ids"), "local_to_canonical": request.get("local_to_canonical"),
        "baseline_digest": request.get("baseline_digest"), "audio_sha256": request.get("audio_sha256"),
        "model_identity": request.get("model_identity"), "checkpoint_identity": request.get("checkpoint_identity"),
        "decoder_identity": request.get("decoder_identity"), "decoder_options": request.get("decoder_options", {}),
        "mapping_schema": request.get("mapping_schema"), "code_identity": request.get("code_identity"),
        "text_adapter_identity": request.get("text_adapter_identity"),
        "audio_preprocess_identity": request.get("audio_preprocess_identity"),
        "determinism_identity": request.get("determinism_identity"),
    })


def classify_intervention(request: Mapping[str, Any], baseline_request: Mapping[str, Any]) -> dict[str, Any]:
    """Classify no-ops without considering family/request/schema identifiers."""
    if request.get("family") == "R-NULL":
        return {"effective_intervention": False, "null_intervention": True, "null_reason": request.get("reason", "r_null")}
    candidate_digest = _digest(intervention_payload(request))
    baseline_digest = _digest(intervention_payload(baseline_request))
    same = candidate_digest == baseline_digest
    return {
        "effective_intervention": not same, "null_intervention": same,
        "null_reason": "identical_intervention_payload" if same else None,
        "candidate_intervention_digest": candidate_digest,
        "baseline_intervention_digest": baseline_digest,
    }


def _null(*, family: str, song_id: str, region_id: str, reason: str) -> dict[str, Any]:
    return {"schema": UNIT_REQUEST_SCHEMA, "family": "R-NULL", "requested_family": family,
            "song_id": song_id, "region_id": region_id, "reason": reason,
            "effective_intervention": False, "null_intervention": True, "null_reason": reason}


def _not_constructible(*, family: str, song_id: str, region_id: str, reason: str) -> dict[str, Any]:
    return {"schema": UNIT_REQUEST_SCHEMA, "family": family, "requested_family": family,
            "song_id": song_id, "region_id": region_id, "reason": reason,
            "status": "not_constructible", "effective_intervention": False}


def build_family_request(
    *, family: str, song_id: str, region_id: str, audio_path: str,
    units: Sequence[Mapping[str, Any]], target_unit_ids: Sequence[int],
    left_anchor_id: int | None = None, right_anchor_id: int | None = None,
    left_accept_anchor_candidates: Sequence[int] | None = None,
    right_accept_anchor_candidates: Sequence[int] | None = None,
    oracle: bool = False, identity_context: Mapping[str, Any] | None = None,
    audio_margin_sec: float = 0.5,
    context_neighbors: int = 1, ra_context_units: int = 1,
) -> dict[str, Any]:
    """Build a v2 local request; callers add frozen identity context before execution."""
    allowed = {"R-U", "R-U1", "R-U3", "R-A", "R-B", "R-S", "R-O", "R-NULL"}
    if family not in allowed:
        raise ValueError(f"unsupported family {family}")
    by_id = {int(u["canonical_unit_id"]): u for u in units}
    ids = [int(u["canonical_unit_id"]) for u in units]
    targets = [int(x) for x in target_unit_ids]
    if not targets or len(set(targets)) != len(targets) or any(x not in by_id for x in targets):
        return _null(family=family, song_id=song_id, region_id=region_id, reason="target_ids_not_in_local_units")
    if len(targets) == len(ids):
        return _null(family=family, song_id=song_id, region_id=region_id, reason="whole_item_pseudo_local")
    if family in {"R-U", "R-U1", "R-U3"} and (len(targets) > 3 or targets != list(range(min(targets), max(targets) + 1))):
        return _null(family=family, song_id=song_id, region_id=region_id, reason="invalid_unit_target_span")
    if family == "R-B" and (left_anchor_id is None or right_anchor_id is None):
        return _not_constructible(family=family, song_id=song_id, region_id=region_id, reason="missing_bilateral_anchor")
    if family == "R-B" and (left_anchor_id not in by_id or right_anchor_id not in by_id):
        return _not_constructible(family=family, song_id=song_id, region_id=region_id, reason="anchor_not_in_local_context")
    if family == "R-B" and not (left_anchor_id < min(targets) and max(targets) < right_anchor_id):
        return _not_constructible(family=family, song_id=song_id, region_id=region_id, reason="invalid_bilateral_anchor_order")
    if family == "R-B":
        if left_accept_anchor_candidates is None or right_accept_anchor_candidates is None:
            return _not_constructible(family=family, song_id=song_id, region_id=region_id, reason="missing_anchor_candidate_provenance")
        eligible_left = [int(x) for x in left_accept_anchor_candidates if int(x) < min(targets)]
        eligible_right = [int(x) for x in right_accept_anchor_candidates if int(x) > max(targets)]
        if not eligible_left or not eligible_right:
            return _not_constructible(family=family, song_id=song_id, region_id=region_id, reason="missing_bilateral_anchor")
        if left_anchor_id != max(eligible_left) or right_anchor_id != min(eligible_right):
            return _not_constructible(family=family, song_id=song_id, region_id=region_id, reason="non_nearest_bilateral_anchor")

    # Local text context per family contract.  R-U takes the target span plus
    # 0-1 configured neighbor on each side; R-A adds a small fixed context on
    # each side of the unsafe span; R-B is bounded by the nearest left/right
    # ACCEPT anchors; R-S keeps the full local window so the sparse fixed-slot
    # partition stays complete (active | fixed == ids).
    if family in {"R-U", "R-U1", "R-U3", "R-O"}:
        lo = max(0, ids.index(min(targets)) - context_neighbors)
        hi = min(len(ids) - 1, ids.index(max(targets)) + context_neighbors)
        context_ids = ids[lo:hi + 1]
    elif family == "R-A":
        lo = max(0, ids.index(min(targets)) - ra_context_units)
        hi = min(len(ids) - 1, ids.index(max(targets)) + ra_context_units)
        context_ids = ids[lo:hi + 1]
    elif family == "R-B":
        context_ids = ids[ids.index(left_anchor_id):ids.index(right_anchor_id) + 1]
    else:  # R-S keeps the full local window so the sparse partition stays complete
        context_ids = ids
    local = {cid: i for i, cid in enumerate(context_ids)}
    active_local = [local[cid] for cid in targets]
    fixed_ids = [cid for cid in context_ids if cid not in set(targets)]
    fixed = [{"local_index": local[cid], "canonical_unit_id": cid,
              "fixed_global_start_sec": float(by_id[cid]["start_sec"]),
              "fixed_global_end_sec": float(by_id[cid]["end_sec"])} for cid in fixed_ids]
    if family == "R-S":
        for fa, fb in zip(sorted(fixed, key=lambda x: int(x["local_index"])),
                          sorted(fixed, key=lambda x: int(x["local_index"]))[1:]):
            if (float(fb["fixed_global_start_sec"]) < float(fa["fixed_global_start_sec"])
                    or float(fb["fixed_global_end_sec"]) < float(fa["fixed_global_end_sec"])):
                return _not_constructible(family=family, song_id=song_id, region_id=region_id,
                                          reason="non_monotonic_fixed_timeline")
    if family in {"R-U", "R-U1", "R-U3", "R-A", "R-O"}:
        start = max(0.0, min(float(by_id[cid]["start_sec"]) for cid in targets) - audio_margin_sec)
        end = max(float(by_id[cid]["end_sec"]) for cid in targets) + audio_margin_sec
    elif family == "R-B":
        start, end = float(by_id[left_anchor_id]["start_sec"]), float(by_id[right_anchor_id]["end_sec"])
    else:  # R-S: full local span, not the target span
        start = min(float(by_id[cid]["start_sec"]) for cid in context_ids)
        end = max(float(by_id[cid]["end_sec"]) for cid in context_ids)
    sparse = family == "R-S"
    result: dict[str, Any] = {
        "schema": UNIT_REQUEST_SCHEMA, "request_id": f"{song_id}:{region_id}:{family}", "family": family,
        "family_version": "v1", "song_id": song_id, "region_id": region_id, "audio_path": audio_path,
        "index_space": "document_global", "text_units": [str(by_id[c]["text"]) for c in context_ids],
        "canonical_ids": context_ids, "local_to_canonical": context_ids,
        "canonical_to_local": {str(cid): i for cid, i in local.items()}, "mapping_schema": "unit_realign_local_v2",
        "active_target_unit_ids": targets, "target_unit_ids": targets,  # compatibility alias
        "fixed_context_unit_ids": fixed_ids, "outside_unit_ids": [], "writeback_unit_ids": targets,
        "baseline_audio_range_sec": [start, end], "candidate_audio_range_sec": [start, end],
        "baseline_text_ids": context_ids, "candidate_text_ids": context_ids,
        "audio_start_sec": start, "audio_end_sec": end,
        "anchors": ({"left": left_anchor_id, "right": right_anchor_id,
                     "left_candidates": list(left_accept_anchor_candidates or ()),
                     "right_candidates": list(right_accept_anchor_candidates or ())}
                    if family == "R-B" else {"left": left_anchor_id, "right": right_anchor_id}),
        "timestamp_slot_indices": active_local if sparse else None, "active_slot_indices": active_local if sparse else None,
        "fixed_slot_rows": fixed if sparse else None, "slot_constraint_schema": "realign_sparse_fixed_v1" if sparse else None,
        "evaluation_only": bool(oracle or family == "R-O"),
    }
    result["intervention_identity"] = intervention_payload(result)  # legacy diagnostic, not cache identity
    result.update(dict(identity_context or {}))
    # Identity is assigned only when full frozen execution context is present.
    try:
        result["request_identity"] = build_request_identity(result)
    except ValueError:
        result["request_identity"] = None
    return result


def build_r_u(**kwargs: Any) -> dict[str, Any]:
    return build_family_request(family="R-U", **kwargs)


def build_r_a(**kwargs: Any) -> dict[str, Any]:
    return build_family_request(family="R-A", **kwargs)


def build_r_b(**kwargs: Any) -> dict[str, Any]:
    return build_family_request(family="R-B", **kwargs)


def build_r_s(**kwargs: Any) -> dict[str, Any]:
    return build_family_request(family="R-S", **kwargs)
