"""WP5 — E3-B audio recrop / multi-scale view enumeration (shadow-only).

Scope (07 plan §9 + 02 E3 §245-254): instead of a margin x context grid we
pre-register a small set of audio observations (``views``) for the same target
region.  Each view is "the same audio, a different crop" around the target span
/ an R-U proposal.  A view differs from the base request ONLY in its audio
observation and an explicit ``recrop_view_id`` identity dimension — the local
text context (targets + neighbors) is unchanged across the family.

NFC: this module is **no-GT and structurally frozen**.  ``register_audio_views``
is purely geometric (target span + view offsets); ``select_view_no_gt`` must
never read GT/outcome buckets — it returns ``not_selected`` / ``indeterminate``
instead of hard-selecting on GT when no usable no-GT signal is present.

Identity contract (WP1 / C_note §3.3): each view carries a distinct
``recrop_view_id`` and ``view_kind`` inside ``identity_context``.  They are
folded into ``chain_context`` by ``build_family_request`` and content-addressed
by ``build_request_identity``, so two different crops of the same audio can
never reuse a stale forward (candidate_audio_range_sec also differs, but the
explicit recrop dimension makes the intent auditable and fail-closed earlier).
No view here links to a parent candidate, so the chained-request guard in
``build_request_identity`` (which only fires when ``parent_request_identity`` is
present) is not triggered.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .request_families import UNIT_REQUEST_SCHEMA, build_family_request, build_request_identity

# Per-view offset definitions (seconds) in terms of the target span / proposal
# center.  02 E3-B: base = target +/- 0.5s; wider = +/- 1.5s;
# left_enriched = left extend +1.0s, right extend +0.3s;
# recentered = R-U proposal center +/- 0.8s.
AUDIO_VIEW_SCHEMAS: dict[str, dict[str, Any]] = {
    "base": {
        "description": "narrow local crop around the target span (target +/- 0.5s)",
        "left_margin_sec": 0.5,
        "right_margin_sec": 0.5,
        "recenter_proposal": False,
    },
    "wider": {
        "description": "wider local crop around the target span (target +/- 1.5s)",
        "left_margin_sec": 1.5,
        "right_margin_sec": 1.5,
        "recenter_proposal": False,
    },
    "left_enriched": {
        "description": "left-context enriched: left extend +1.0s, right +0.3s",
        "left_margin_sec": 1.0,
        "right_margin_sec": 0.3,
        "recenter_proposal": False,
    },
    "recentered": {
        "description": "recentered around the R-U proposal center (center +/- 0.8s)",
        "left_margin_sec": 0.8,
        "right_margin_sec": 0.8,
        "recenter_proposal": True,
    },
}


def _clip(start: float, end: float, duration_sec: float) -> tuple[float, float]:
    """Clip a [start, end] crop to the audio's [0, duration_sec] domain."""
    start = max(0.0, float(start))
    end = min(duration_sec, float(end))
    if end <= start:
        raise ValueError(f"view crop collapses to empty interval [{start}, {end}] "
                         f"(duration_sec={duration_sec})")
    return start, end


def target_center_sec(region: Mapping[str, Any], target_unit_ids: Sequence[int]) -> float:
    """Center (seconds) of the target-unit span from the region's frozen units."""
    by_id = {int(u.get("canonical_unit_id")): u for u in (region.get("units") or ())}
    targets = [int(x) for x in target_unit_ids]
    if not targets or any(x not in by_id for x in targets):
        raise ValueError("target_unit_ids must be non-empty and present in region.units")
    starts = [float(by_id[c]["start_sec"]) for c in targets]
    ends = [float(by_id[c]["end_sec"]) for c in targets]
    return (min(starts) + max(ends)) / 2.0


def _span_margins(region: Mapping[str, Any], target_unit_ids: Sequence[int]) -> tuple[float, float]:
    by_id = {int(u.get("canonical_unit_id")): u for u in (region.get("units") or ())}
    targets = [int(x) for x in target_unit_ids]
    starts = [float(by_id[c]["start_sec"]) for c in targets]
    ends = [float(by_id[c]["end_sec"]) for c in targets]
    return min(starts), max(ends)


def register_audio_views(
    region: Mapping[str, Any],
    target_unit_ids: Sequence[int],
    duration_sec: float,
    *,
    view_kinds: Sequence[str] = ("base", "wider", "left_enriched", "recentered"),
    recrop_view_id_prefix: str | None = None,
    proposal_center_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Pre-register the geometric audio views (no forward, no GT).

    Returns a list of ``{recrop_view_id, view_kind, audio_start_sec,
    audio_end_sec}``.  ``recentered`` uses ``proposal_center_sec`` (the R-U
    proposal center) when given, otherwise falls back to the frozen target-span
    center (documented as ``recenter_source`` so the choice is auditable).
    """
    unknown = [k for k in view_kinds if k not in AUDIO_VIEW_SCHEMAS]
    if unknown:
        raise ValueError("unknown view_kind(s): " + ", ".join(unknown))
    if duration_sec <= 0:
        raise ValueError(f"duration_sec must be > 0 (got {duration_sec})")
    song_id = str(region.get("song_id") or "")
    region_id = str(region.get("region_id") or "")
    span_start, span_end = _span_margins(region, target_unit_ids)
    center = proposal_center_sec
    recenter_source = "proposal_center" if proposal_center_sec is not None else "target_span_center"
    prefix = recrop_view_id_prefix or f"{song_id}:{region_id}"

    views: list[dict[str, Any]] = []
    for kind in view_kinds:
        schema = AUDIO_VIEW_SCHEMAS[kind]
        if schema["recenter_proposal"]:
            c = center if center is not None else (span_start + span_end) / 2.0
            raw_start, raw_end = c - schema["left_margin_sec"], c + schema["right_margin_sec"]
        else:
            raw_start, raw_end = (span_start - schema["left_margin_sec"],
                                  span_end + schema["right_margin_sec"])
        start, end = _clip(raw_start, raw_end, duration_sec)
        views.append({
            "recrop_view_id": f"{prefix}:view:{kind}",
            "view_kind": kind,
            "audio_start_sec": start,
            "audio_end_sec": end,
            "recenter_source": recenter_source if schema["recenter_proposal"] else "target_span_margins",
        })
    return views


def _override_audio_range(request: dict[str, Any], start: float, end: float) -> dict[str, Any]:
    """Point a built request's audio observation at ``[start, end]`` and recompute
    identity over the new crop (content-addressed: crop + recrop_view_id)."""
    start, end = float(start), float(end)
    request = dict(request)
    for key in ("audio_start_sec", "audio_end_sec"):
        request[key] = start if key == "audio_start_sec" else end
    for key in ("candidate_audio_range_sec", "baseline_audio_range_sec"):
        request[key] = [start, end]
    request["intervention_identity"] = None  # reset to avoid stale diagnostic digest
    # Recompute identity over the new crop.  recrop_view_id/view_kind are already
    # in chain_context (from identity_context), so the digest is distinct per view.
    try:
        request["request_identity"] = build_request_identity(request)
    except ValueError:
        request["request_identity"] = None
    return request


def build_view_requests(
    region: Mapping[str, Any],
    target_unit_ids: Sequence[int],
    *,
    family: str = "R-U",
    duration_sec: float,
    identity_context: Mapping[str, Any] | None = None,
    view_kinds: Sequence[str] = ("base", "wider", "left_enriched", "recentered"),
    proposal_center_sec: float | None = None,
    **family_kwargs: Any,
) -> list[dict[str, Any]]:
    """Build one v2 request per audio view for the same region.

    Every view is a fresh R-U-style request over the SAME frozen local text
    context (targets + configured neighbors) but a different audio crop.  The
    ``identity_context`` gains ``recrop_view_id`` + ``view_kind`` (entered into
    ``chain_context`` by ``build_family_request``), and the request's audio range
    is overridden to the view's crop — so distinct views have distinct
    ``request_identity`` and can never reuse a stale forward.  The candidate
    across views is "same audio, different crop"; identity must differ and we
    deliberately do NOT reuse the base forward (WP1 P1-2).

    Non-constructible / families that fail to build yield their own
    ``{status: "null"|"not_constructible", reason: ...}`` row instead of being
    silently dropped.
    """
    views = register_audio_views(
        region, target_unit_ids, duration_sec,
        view_kinds=view_kinds, proposal_center_sec=proposal_center_sec,
    )
    song_id = str(region.get("song_id") or "")
    region_id = str(region.get("region_id") or "")
    base_ctx = dict(identity_context or {})
    requests: list[dict[str, Any]] = []
    for view in views:
        kind = view["view_kind"]
        # Per-view identity context: base + view observation identity.
        ctx = dict(base_ctx)
        ctx["recrop_view_id"] = view["recrop_view_id"]
        ctx["view_kind"] = kind
        ctx["audio_view_schema"] = "audio_view_study_v1"
        # Guard: a chained request that links a parent must carry all four family
        # dimensions; audio views are leaf (no parent), so only recrop_view_id is
        # populated and build_request_identity's guard does not require the rest.
        try:
            request = build_family_request(
                family=family, song_id=song_id, region_id=region_id,
                audio_path=str(region.get("audio_path") or f"{song_id}.wav"),
                units=region.get("units") or (), target_unit_ids=target_unit_ids,
                identity_context=ctx, **family_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            requests.append({"schema": UNIT_REQUEST_SCHEMA, "family": family,
                             "requested_family": family, "song_id": song_id,
                             "region_id": region_id, "recrop_view_id": view["recrop_view_id"],
                             "view_kind": kind, "status": "not_constructible",
                             "reason": f"construction_failed:{type(exc).__name__}"})
            continue
        if request.get("family") == "R-NULL" or request.get("status") == "not_constructible":
            request["recrop_view_id"] = view["recrop_view_id"]
            request["view_kind"] = kind
            requests.append(request)
            continue
        # Point the candidate audio at this view's crop and recompute identity.
        request = _override_audio_range(request, view["audio_start_sec"], view["audio_end_sec"])
        request["recrop_view_id"] = view["recrop_view_id"]
        request["view_kind"] = kind
        request["audio_view_schema"] = "audio_view_study_v1"
        requests.append(request)
    return requests


# --------------------------------------------------------------------------- #
#  no-GT view selection
# --------------------------------------------------------------------------- #
_SELECTABLE_NUMERIC_KEYS = (
    "detector_p_bad",        # lower is safer
    "detector_p_bad_after",  # lower is safer
    "margin",                # higher is more confident (top1 - top2)
    "entropy",               # lower is more confident
    "raw_official_disagreement_ms",  # lower = official/raw agree
    "mean_boundary_displacement_ms",  # lower = less motion of targets
)
_LOWER_IS_BETTER = {"detector_p_bad", "detector_p_bad_after", "entropy",
                    "raw_official_disagreement_ms", "mean_boundary_displacement_ms"}
_HIGHER_IS_BETTER = {"margin"}


def _view_signal_means(view_result: Mapping[str, Any]) -> dict[str, float | None]:
    """Aggregate usable no-GT per-unit signals across a view's candidate rows."""
    rows = view_result.get("candidate_rows") or ()
    if not rows:
        return {key: None for key in _SELECTABLE_NUMERIC_KEYS}
    means: dict[str, float | None] = {}
    for key in _SELECTABLE_NUMERIC_KEYS:
        vals = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        means[key] = round(sum(vals) / len(vals), 6) if vals else None
    return means


def _usable_signals(aggregates: Sequence[dict[str, float | None]]) -> list[str]:
    usable: set[str] = set()
    for agg in aggregates:
        for key, value in agg.items():
            if value is not None:
                usable.add(key)
    return sorted(usable)


def select_view_no_gt(views_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Choose the best view WITHOUT GT, using only actually-available no-GT signals.

    Signals considered (E_note §2, unit_gate_features allowed keys):
    ``detector_p_bad(_after)``, ``margin``, ``entropy``,
    ``raw_official_disagreement_ms``, ``mean_boundary_displacement_ms``, plus
    structural flags (``candidate_missing``, ``context_protected``).  GT-failure
    buckets / outcome / oracle are NEVER read.

    Returns ``{schema, selected, selected_view, reason, per_view}``.  ``selected``
    is True only when at least one usable numeric signal exists AND a single view
    strictly wins on the available signals (ties resolve to no decision).  When no
    usable signal is present, or the views are indistinguishable, it returns
    ``selected: False`` with ``status: "indeterminate"/"no_signal"`` rather than
    using GT to hard-select (GT firewall / fail-closed).
    """
    out: list[dict[str, Any]] = []
    aggregates = []
    for view_result in views_results:
        aggs = _view_signal_means(view_result)
        aggregates.append(aggs)
        candidate_rows = view_result.get("candidate_rows") or ()
        out.append({
            "recrop_view_id": view_result.get("recrop_view_id"),
            "view_kind": view_result.get("view_kind"),
            "request_identity": view_result.get("request_identity"),
            "status": view_result.get("status"),
            "candidate_row_count": len(candidate_rows),
            "n_candidate_missing": sum(1 for r in candidate_rows if r.get("candidate_missing")),
            "n_context_protected": sum(1 for r in candidate_rows if r.get("context_protected")),
            "signal_means": aggs,
        })
    usable = _usable_signals(aggregates)
    if not usable:
        return {
            "schema": "audio_view_study_v1",
            "selected": False, "selected_view": None,
            "status": "no_signal",
            "reason": "none_of_detector_p_bad/margin/entropy/raw_official_disagreement/"
                      "mean_boundary_displacement_ms available on candidate rows; "
                      "cannot select without GT (fail-closed)",
            "per_view": out,
        }
    # Score each view by rank on each available signal; strict all-ties => no decision.
    decisive = []
    for key in usable:
        present = [(i, aggregates[i][key]) for i in range(len(aggregates))
                   if aggregates[i][key] is not None]
        if not present:
            continue
        best_idx = min(present, key=lambda iv: iv[1])[0] if key in _LOWER_IS_BETTER \
            else max(present, key=lambda iv: iv[1])[0]
        target = aggregates[best_idx][key]
        n_best = sum(1 for i, _ in present if aggregates[i][key] == target)
        if n_best == 1:
            decisive.append((key, best_idx))
    if not decisive:
        return {
            "schema": "audio_view_study_v1",
            "selected": False, "selected_view": None,
            "status": "indeterminate",
            "reason": "available no-GT signals present but none has a unique best view "
                      "(all tied); refusing to GT-hard-select",
            "usable_signals": usable, "per_view": out,
        }
    # Winner = view that strictly wins on the most decisive signals.  Ties on the
    # count are NOT resolved — report indeterminate rather than pick arbitrarily.
    from collections import Counter
    votes = Counter(idx for _, idx in decisive)
    top_two = votes.most_common(2)
    winner_idx, top_votes = top_two[0]
    if len(top_two) > 1 and top_two[1][1] == top_votes:
        return {
            "schema": "audio_view_study_v1",
            "selected": False, "selected_view": None,
            "status": "indeterminate",
            "reason": "no-GT signals split the winner across views with equal decisive "
                      "votes; refusing to GT-hard-select",
            "usable_signals": usable, "votes": dict(votes), "per_view": out,
        }
    winner_recrop = out[winner_idx].get("recrop_view_id")
    return {
        "schema": "audio_view_study_v1",
        "selected": True, "selected_view": winner_recrop,
        "status": "selected_no_gt",
        "reason": f"unique no-GT winner ({top_votes} decisive signal(s): "
                  f"{[k for k, i in decisive if i == winner_idx]})",
        "usable_signals": usable, "votes": dict(votes), "per_view": out,
    }
