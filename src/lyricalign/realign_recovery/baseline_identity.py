"""Baseline identity: verifiable identity for the frozen realign-recovery baseline."""
from __future__ import annotations

import hashlib
import json

REQUIRED_IDENTITY_FIELDS = (
    "model_id",
    "model_revision",
    "checkpoint_path",
    "processor_id",
    "request_mode",
    "core_sec",
    "left_context_sec",
    "right_context_sec",
    "silence_aware_window_plan",
    "decoder_view",
    "detector_artifact_sha256",
    "detector_accept_threshold",
    "detector_reject_threshold",
    "real_gt_source",
    "schema_version",
)


def validate_identity(identity: dict) -> list[str]:
    """Return a list of missing or empty-valued required fields.

    A field is reported when it is absent from the dict, or when its value
    is ``None`` or an empty string. Returns an empty list when valid.
    """
    problems: list[str] = []
    for field in REQUIRED_IDENTITY_FIELDS:
        if field not in identity:
            problems.append(field)
        elif identity[field] is None:
            problems.append(field)
        elif isinstance(identity[field], str) and identity[field].strip() == "":
            problems.append(field)
    return problems


def canonical_identity_json(identity: dict) -> str:
    """Serialize an identity to a stable canonical JSON string."""
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def identity_digest(identity: dict) -> str:
    """Return the sha256 hex digest of the canonical identity JSON."""
    return hashlib.sha256(canonical_identity_json(identity).encode("utf-8")).hexdigest()
