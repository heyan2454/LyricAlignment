"""Adaptive family screening and expansion bookkeeping (no model dependency)."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


REQUEST_TERMINAL_STATUSES = frozenset({"selected", "not_constructible", "null", "failed", "invalid", "executed", "valid"})


def summarize_case_family_status(request_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Explicit denominators by family and GT stratum; no implicit success."""
    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in request_rows:
        family = str(row.get("family") or row.get("input_variant") or "unknown")
        stratum = str(row.get("stratum") or "unstratified")
        status = str(row.get("status") or ("valid" if row.get("effective_intervention") is True else "null"))
        if status not in REQUEST_TERMINAL_STATUSES:
            status = "invalid"
        counts[(family, stratum)]["selected"] += 1
        counts[(family, stratum)]["selected_status" if status == "selected" else status] += 1
    return {"schema": "unit_realign_family_status_summary_v1", "by_family_stratum": [
        {"family": family, "stratum": stratum, **dict(sorted(values.items()))}
        for (family, stratum), values in sorted(counts.items())
    ]}


def choose_surviving_families(
    request_rows: Sequence[Mapping[str, Any]], feature_rows: Sequence[Mapping[str, Any]],
    *, max_families: int = 4, min_valid: int = 8,
) -> dict[str, Any]:
    """Select production-capable families without GT outcomes.

    Validity is based only on effective interventions, request coverage and
    context preservation.  This is screening policy, never a writeback rule.
    """
    req_by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in request_rows:
        family = str(row.get("family") or row.get("input_variant") or "")
        req_by_family[family].append(row)
    feat_by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in feature_rows:
        feat_by_family[str(row.get("family") or "")].append(row)
    scoreboard = []
    for family, rows in sorted(req_by_family.items()):
        # New P1 records must explicitly reach valid. The narrow fallback is
        # only for historical screening manifests that predate status fields.
        valid = [r for r in rows if r.get("status") == "valid" or
                 ("status" not in r and r.get("effective_intervention") is True)]
        feats = feat_by_family.get(family, [])
        context = [r.get("context_protected") for r in feats if r.get("context_protected") is not None]
        missing = sum(bool(r.get("candidate_missing")) for r in feats)
        preservation = sum(bool(x) for x in context) / len(context) if context else 0.0
        score = len(valid) + preservation - missing * .1
        scoreboard.append({
            "family": family, "n_requests": len(rows), "n_valid": len(valid),
            "n_features": len(feats), "context_protection": preservation,
            "candidate_missing_count": missing, "eligible": len(valid) >= min_valid,
            "screen_score": round(score, 6),
        })
    eligible = [x for x in scoreboard if x["eligible"]]
    eligible.sort(key=lambda x: (-x["screen_score"], x["family"]))
    return {
        "schema": "unit_realign_family_screen_v1",
        "surviving_families": [x["family"] for x in eligible[:max_families]],
        "scoreboard": scoreboard,
        "family_status": summarize_case_family_status(request_rows),
        "status": "ready_for_expansion" if eligible else "no_family_passed_validity",
    }


def expansion_plan(
    population: Sequence[Mapping[str, Any]], *, completed_region_ids: set[str],
    target_regions: int, per_song_cap: int = 8,
) -> dict[str, Any]:
    """Return a refill plan; completed regions are never repeated on resume."""
    counts: dict[str, int] = defaultdict(int)
    selected: list[dict] = []
    for row in sorted(population, key=lambda x: (
            str(x.get("seed_kind")) != "unsafe_region", str(x.get("song_id")), str(x.get("region_id")))):
        rid, song = str(row.get("region_id")), str(row.get("song_id"))
        if rid in completed_region_ids or counts[song] >= per_song_cap:
            continue
        selected.append(dict(row))
        counts[song] += 1
        if len(selected) >= target_regions:
            break
    return {
        "schema": "unit_realign_expansion_plan_v1", "requested": target_regions,
        "selected": len(selected), "regions": selected, "selected_per_song": dict(counts),
        "status": "ready" if len(selected) >= target_regions else "exhausted",
    }
