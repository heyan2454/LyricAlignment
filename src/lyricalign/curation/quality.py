"""Explicit A/B/C quality tiers; raw model output is intentionally not an input."""

from __future__ import annotations

from typing import Any

QUALITY_VERSION = "quality_tier_v1"


def assign_quality_tier(record: dict[str, Any]) -> tuple[str, list[str]]:
    audio = record.get("audio", {})
    if audio.get("audio_status") != "ok":
        return "C_invalid", ["audio_metadata_invalid"]
    mapping = record.get("mapping_status")
    if record.get("status") == "accepted" and mapping in {"accepted_exact", "accepted_rule_based"}:
        return "A_high_confidence", []
    reasons = [str(record.get("status_reason") or mapping or "mapping_review_required")]
    return "B_review_or_robustness", reasons


def apply_quality_tier(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    tier, reasons = assign_quality_tier(record)
    result["quality_tier"] = tier
    result["quality_reason_codes"] = reasons
    result["quality_version"] = QUALITY_VERSION
    return result
