"""E5 no-GT candidate selection & safety (WP7).

Pure CPU: never runs a forward, never reads GT/evaluator outcomes.  It consumes
already-cached forward evidence (raw/official decoder outputs, per-unit timing,
posterior entropy/margin when present) plus an *optional* no-GT feature matrix
(FrozenScorer `unit_realign_no_gt_features_v1`, whose ``detector_p_bad`` is the
no-GT main proxy ``NO_GT_PROXY``).

Signals accepted here are strictly the ones `unit_gate_features.ALLOWED_FEATURE_KEYS`
and `audio_views` recognise.  No GT delta / GT label / evaluator-only column may
reach the runner or ranker: every feature row passes the GT firewall
(`assert_no_gt_feature_row` from `unit_gate_features`, plus `assert_no_label_leak`
scans opaque mappings/hashes for evaluator namespaces).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .unit_gate_features import (  # reuse the strict allowlist + schema
    ALLOWED_FEATURE_KEYS,
    NO_GT_FEATURE_SCHEMA,
    assert_no_gt_feature_row,
)

# --------------------------------------------------------------------------- #
#  Whitelist & schemas
# --------------------------------------------------------------------------- #
# no-GT primary proxy.  It is `detector_p_bad` carried from the FrozenScorer
# feature matrix (`unit_realign_no_gt_features_v1`), NOT a GT error.
NO_GT_PROXY = "detector_p_bad"

NO_GT_SELECTOR_SCHEMA = "unit_realign_no_gt_selector_v1"
SIGNAL_AUDIT_SCHEMA = "unit_realign_signal_audit_v1"
HELDOUT_EVAL_SCHEMA = "unit_realign_heldout_eval_v1"

# Categorised signal whitelist.  SIGNAL_NAMES is the set of signal keys the
# selector is allowed to read; each must exist in ALLOWED_FEATURE_KEYS (feature
# rows) or be derivable on the raw evidence payload, and must never be a GT
# outcome.  `margin`: higher is more confident, everything else lower is safer.
LOWER_IS_SAFER = frozenset({
    "detector_p_bad", "detector_p_bad_after", "entropy", "mean_boundary_displacement_ms",
    "raw_official_disagreement_ms", "context_displacement_ms", "fixed_point_spread_ms",
})
HIGHER_IS_SAFER = frozenset({"margin", "min_margin", "num_margins_above"})

# Unary decoder/posterior signals read directly off evidence rows.
SIGNAL_NAMES = frozenset({
    "detector_p_bad",           # proxy; from feature matrix rows (detector_p_bad_before/after -> max)
    "margin",                   # posterior start/end margin when present
    "entropy",                  # posterior start/end entropy when present
    "raw_official_disagreement_ms",  # raw vs official decoder boundary distance
    "mean_boundary_displacement_ms", # candidate vs baseline mean displacement
    "context_displacement_ms",  # context-only displacement (targets excluded)
    "detector_state",           # ACCEPT / UNCERTAIN / REJECT tri-state when present
    "candidate_missing",        # structural; reject flag
    "fixed_point_spread_ms",    # stability-only: dispersion of candidate timings across views/iters
    "monotonicity_violation",   # structural
    "slot_violation",           # structural
    "inversion_count",          # structural
    "overlap_sec",              # structural
})

# GT / evaluator-only namespace tokens that must never pass through a payload
# wrapper.  Outcome/evaluator oriented (word-level), so legitimate fields like
# ``attempt.error`` (runtime message) or ``repeat_gt_starts`` (a request
# construction parameter, not an evaluator outcome) are not false-positives.
_FORBIDDEN_TOKENS = ("gt_eval", "verdict", "evaluator", "oracle", "gt_label",
                     "harm", "rescue", "outcome")
# Substring-level aliases that are evaluator-outcome specific (safe to match).
_FORBIDDEN_SUBSTRINGS = ("evaluator", "oracle_", "gt_eval", "rescue")
_ARRAY_KEYS_OK = frozenset({
    "raw_rows", "official_rows", "posterior_rows", "candidate_rows", "baseline_rows",
    "fixed_slot_rows", "attempt_rows",
})


def assert_no_label_leak(payload: Mapping[str, Any]) -> None:
    """Walk the whole payload (evidence or feature row) for evaluator/GT leakage.

    Distinct from `assert_no_gt_feature_row` (which only police feature rows):
    this also rejects evaluator-only wrapper fields (``gt_eval``, ``verdict``,
    ...) and any mapping whose *keys* contain an evaluator name.  It treats the
    given mapping as opaque and never commits to it being a feature row, so it
    is safe to call on raw evidence root objects.
    """
    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                low = str(key).lower()
                if low in _ARRAY_KEYS_OK or key in _ARRAY_KEYS_OK:
                    walk(child, f"{path}.{key}")
                    continue
                if low in _FORBIDDEN_TOKENS or any(t in low for t in _FORBIDDEN_SUBSTRINGS):
                    raise ValueError(f"no-GT leak at {path}.{key} (forbidden evaluator outcome present)")
                walk(child, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for i, child in enumerate(value):
                walk(child, f"{path}[{i}]")
    walk(payload)


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


# --------------------------------------------------------------------------- #
#  Payload -> feature rows (always available: timing + raw/official, optional
#  margin/entropy/p_bad/state).
# --------------------------------------------------------------------------- #
def build_selector_features(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert one cached evidence payload into no-GT selector feature rows.

    Only reads no-GT fields: timing geometry, raw/official rows, posterior
    entropy/margin, and an optional FrozenScorer ``detector_p_bad`` carried from
    the feature matrix.  Every emitted row passes the GT firewall
    (`assert_no_gt_feature_row`) plus the label-leak sweep (`assert_no_label_leak`).

    Note: the raw evidence envelope may legitimately carry evaluator-only fields
    (e.g. ``attempt.gt_eval``) for the *evaluator* consumer.  Those never enter
    this projection, so the firewall is enforced on the emitted no-GT rows below,
    not on the shared raw envelope.
    """
    attempt = payload.get("attempt") or payload
    req = _async_then(attempt.get("request"))
    if not isinstance(req, Mapping):
        req = {}  # evidence without a request block; fall back so timings still extract
    decoder = attempt.get("decoder_outputs") or {}
    raw_rows = decoder.get("raw", {}).get("rows") or []
    off_rows = decoder.get("official", {}).get("rows") or []
    post_rows = (decoder.get("_posterior") or decoder.get("posterior") or {}).get("rows") or []
    fixed_rows = (req.get("fixed_slot_rows") if isinstance(req, Mapping) else None) or []
    request_identity = (req.get("request_identity") if isinstance(req, Mapping) else None)
    song_id = _first_text(req, ("song_id", "item_id"))
    region_id = _first_text(attempt.get("metadata", {}).get("provenance", {}), ("episode_id", "region_id"))
    request_id = attempt.get("metadata", {}).get("request_id") or req.get("request_id") if isinstance(req, Mapping) else None

    by_cid = dict[int, dict[str, Any]]()
    for rows, kind in ((raw_rows, "raw"), (off_rows, "official"), (post_rows, "posterior"),
                       (fixed_rows, "baseline")):
        if not rows:
            continue
        for row in _as_list(rows):
            cid = row.get("canonical_unit_id", row.get("global_character_index"))
            if not isinstance(cid, int):
                continue
            cell = by_cid.setdefault(cid, {})
            cell.setdefault("canonical_unit_id", cid)
            if kind in ("raw", "official", "baseline"):
                s, e = _num(row.get("fixed_global_start_sec") if kind == "baseline"
                            else row.get("fixed_global_start_sec", row.get("start_sec"))), \
                    _num(row.get("fixed_global_end_sec") if kind == "baseline"
                         else row.get("fixed_global_end_sec", row.get("end_sec")))
                if kind == "raw":
                    cell["raw_start"] = s; cell["raw_end"] = e
                elif kind == "official":
                    cell["official_start"] = s; cell["official_end"] = e
                else:
                    cell.setdefault("base_start", s); cell.setdefault("base_end", e)
            if kind == "posterior":
                for bound_key, out_key in (("start_entropy", "entropy"), ("start_margin", "margin")):
                    cell[out_key] = _num(row.get(bound_key)) if cell.get(out_key) is None \
                        else cell[out_key]

    rows: list[dict[str, Any]] = []
    for cid in sorted(by_cid):
        c = by_cid[cid]
        rs, re = c.get("raw_start"), c.get("raw_end")
        os_, oe = c.get("official_start"), c.get("official_end")
        bs, be = c.get("base_start"), c.get("base_end")
        raw_official_disp = None
        if not any(v is None for v in (rs, re, os_, oe)):
            raw_official_disp = round((abs(rs - os_) + abs(re - oe)) * 500.0, 4)  # sec -> ms/2 unit
        mean_disp = None
        if not any(v is None for v in (bs, be, rs, re)):
            mean_disp = round((abs(rs - bs) + abs(re - be)) * 500.0, 4)
        row = {
            "schema": NO_GT_FEATURE_SCHEMA,
            "canonical_unit_id": cid,
            "family": _first_text(req, ("input_variant", "family")) if isinstance(req, Mapping) else None,
            "request_identity": request_identity,
            "song_id": song_id, "region_id": region_id, "request_id": request_id,
            "raw_official_disagreement_ms": raw_official_disp,
            "mean_boundary_displacement_ms": mean_disp,
            "entropy": c.get("entropy"), "margin": c.get("margin"),
            "detector_p_bad": c.get("detector_p_bad"),
        }
        assert_no_gt_feature_row(row)
        assert_no_label_leak(row)
        rows.append(row)
    return rows


def _async_then(v: Any) -> Any:
    """Unwrap a possibly-awaitable-ish wrapper; plain dict passes through."""
    return v.get("__self__") if isinstance(v, Mapping) else v


def _as_list(x: Any) -> list[Any]:
    if isinstance(x, (list, tuple)):
        return list(x)
    if isinstance(x, Mapping):
        return list(x.values())
    return []


def _first_text(m: Mapping[str, Any] | None, keys: Sequence[str]) -> Any:
    if not isinstance(m, Mapping):
        return None
    for k in keys:
        v = m.get(k)
        if v is not None:
            return v
    return None


def align_feature_matrix(feature_rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Re-validate and normalise a cached FrozenScorer no-GT feature matrix.

    Every row must already pass `assert_no_gt_feature_row` (schema
    ``unit_realign_no_gt_features_v1``).  Extracts known signals and reports each
    row's availability so the consumer can audit.  Yields annotated copies.
    """
    out: list[dict[str, Any]] = []
    for row in feature_rows or ():
        assert_no_gt_feature_row(row)
        assert_no_label_leak(row)
        if row.get("schema") not in (NO_GT_FEATURE_SCHEMA, None):
            raise ValueError(f"unexpected feature schema: {row.get('schema')}")
        out.append(dict(row))
    return out


def signal_present(feature_rows: Sequence[Mapping[str, Any]], signal: str) -> int:
    """Return how many rows carry a non-null value for ``signal``."""
    return sum(1 for r in feature_rows if _num(r.get(signal)) is not None)


# --------------------------------------------------------------------------- #
#  Signal audit
# --------------------------------------------------------------------------- #
def audit_available_signals(payloads: Sequence[Mapping[str, Any]],
                            feature_rows: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Offline availability audit: which no-GT signals are actually exportable.

    Walks the cached evidence payloads (timing geometry, raw/official, posterior
    margin/entropy) plus an optional FrozenScorer feature matrix.  Reports
    ``{signal: {n_available, n_missing}}`` over the union of feature-equivalent
    per-unit rows discovered.  ``n_missing`` = rows where the signal is absent.
    Never calls a forward.
    """
    feat_rows = feature_rows if feature_rows is not None else []
    # Build one per-unit row per payload using build_selector_features (cheap).
    unit_rows: list[dict[str, Any]] = []
    for payload in payloads:
        unit_rows.extend(build_selector_features(payload))
    # Merge FrozenScorer rows: prefer the matrix (it carries p_bad proxy).
    if feat_rows:
        unit_rows = list(feat_rows) + unit_rows

    available: dict[str, int] = {}
    for signal in sorted(SIGNAL_NAMES):
        n_avail = signal_present(unit_rows, signal)
        available[signal] = {"n_available": n_avail, "n_missing": max(0, len(unit_rows) - n_avail)}
    return {
        "schema": SIGNAL_AUDIT_SCHEMA,
        "n_unit_rows": len(unit_rows),
        "n_payloads": len(payloads),
        "n_feature_matrix_rows": len(feat_rows),
        "no_gt_proxy": NO_GT_PROXY,
        "proxy_available": signal_present(unit_rows, NO_GT_PROXY) > 0,
        "signals": available,
        "usable_signals": [s for s, v in available.items() if v["n_available"] > 0],
        "missing_signals": [s for s, v in available.items() if v["n_available"] == 0],
    }


# --------------------------------------------------------------------------- #
#  Simple selector / rules
# --------------------------------------------------------------------------- #
_DEFAULT_RULES = {
    "p_bad_threshold": 0.5,          # proxy>threshold => suspect unit (higher safer when p_bad low)
    "raw_official_tight_ms": 30.0,   # raw/official within 30ms => consistent (tight)
    "raw_official_loose_ms": 80.0,   # beyond 80ms => strong disagreement (suspect)
    "context_disp_tight_ms": 5.0,    # context-only displacement <=5ms => displacement likely localised/target
    "context_disp_loose_ms": 20.0,   # context displacement >20ms => unsafe
    "max_overlap_sec": 0.020,        # >20ms unit overlap => inversion/overlap suspect
    "max_spread_ms": 50.0,           # fixed-point spread >50ms => unstable (safety-first rejects)
    "margin_min": 0.2,               # margin <0.2 => low confidence
}


def default_simple_selector() -> dict[str, Any]:
    return {"schema": NO_GT_SELECTOR_SCHEMA, "variant": "simple_rules_v1", "rules": dict(_DEFAULT_RULES)}


def _signal_mean(rows: Sequence[Mapping[str, Any]], signal: str) -> float | None:
    vals = [r[signal] for r in rows if _num(r.get(signal)) is not None]
    if not vals:
        return None
    return round(sum(float(v) for v in vals) / len(vals), 6)


def freeze_simple_selector(features: Sequence[Mapping[str, Any]], split: str) -> dict[str, Any]:
    """Freeze the simple selector/rules on the discovery/validation split.

    No heldout data is touched here.  Rules are either read from
    ``_DEFAULT_RULES`` or, when the split provides enough proxy signal, the
    p_bad/raw-official thresholds are tightened to the observed percentiles on
    this split only.  Returns the frozen rule set plus the calibration stats.
    """
    rows = aligned = align_feature_matrix(features)
    if split not in ("discovery", "validation", "discovery_validation"):
        raise ValueError(f"unknown freeze split: {split!r}; use discovery|validation|discovery_validation")

    stats: dict[str, dict[str, float | None]] = {}
    for sig in ("detector_p_bad", "raw_official_disagreement_ms", "entropy", "margin",
                "context_displacement_ms", "mean_boundary_displacement_ms"):
        vals = sorted(float(r[sig]) for r in rows if _num(r.get(sig)) is not None)
        stats[sig] = {
            "n": len(vals),
            "p50": round(vals[len(vals) // 2], 6) if vals else None,
            "p90": round(vals[min(len(vals) - 1, int(0.9 * len(vals)))], 6) if vals else None,
        }

    rules = dict(_DEFAULT_RULES)
    if _signal_mean(rows, "detector_p_bad") is not None:
        # tighten p_bad threshold to the 85th percentile on the freeze split (proxy-driven).
        p85 = stats["detector_p_bad"]["p90"]
        if p85 is not None:
            rules["p_bad_threshold"] = p85
    return {
        "schema": NO_GT_SELECTOR_SCHEMA,
        "variant": "simple_rules_v1",
        "split": split,
        "frozen_on": split,
        "rules": rules,
        "calibration_stats": stats,
        "n_rows": len(rows),
    }


def _apply_selector(rows: Sequence[Mapping[str, Any]], selector: Mapping[str, Any],
                    require_proxy: bool, safety_first: bool) -> list[dict[str, Any]]:
    """Score each unit row with the frozen rules; return verdicts.

    ``require_proxy``: when True, units lacking the p_bad proxy are treated as
    ``no_proxy`` (cannot commit) unless another strong signal supports them.
    ``safety_first`` chooses a stricter disagreement/context gate.
    """
    rules = selector.get("rules", {})
    p_thr = rules.get("p_bad_threshold", 0.5)
    ro_tight = rules.get("raw_official_tight_ms", 30.0)
    ro_loose = rules.get("raw_official_loose_ms", 80.0)
    ctx_loose = rules.get("context_disp_loose_ms", 20.0)
    mx_overlap = rules.get("max_overlap_sec", 0.020)
    mx_spread = rules.get("max_spread_ms", 50.0)
    margin_min = rules.get("margin_min", 0.2)

    pick_inc = pick_loose = None
    if safety_first:
        pick_loose, pick_inc = ro_loose, ctx_loose
    else:
        pick_loose, pick_inc = ro_tight, max(ctx_loose * 0.6, 5.0)

    out: list[dict[str, Any]] = []
    for row in rows:
        assert_no_gt_feature_row(row)
        mind = _num(row.get("mean_boundary_displacement_ms"))
        ctx = _num(row.get("context_displacement_ms"))
        ro = _num(row.get("raw_official_disagreement_ms"))
        margin = _num(row.get("margin"))
        entropy = _num(row.get("entropy"))
        overlap = _num(row.get("overlap_sec"))
        spread = _num(row.get("fixed_point_spread_ms"))
        p_bad = _num(row.get(NO_GT_PROXY))

        # structural rejects always dominate
        structural_suspect = bool(row.get("slot_violation") or row.get("inversion_count")
                                  or row.get("monotonicity_violation") or (overlap or 0) > mx_overlap)
        reasons: list[str] = []
        if structural_suspect:
            reasons.append("structural(violation/overlap)")
        # disagreement
        if ro is not None and ro > pick_loose:
            reasons.append("raw_official_disagreement")
        # context safety
        if ctx is not None and ctx > pick_inc:
            reasons.append("context_displacement")
        # margin low
        if margin is not None and margin < margin_min:
            reasons.append("low_margin")
        # proxy suspect
        if p_bad is not None and p_bad > p_thr:
            reasons.append("p_bad_high")
        # stability
        if spread is not None and spread > mx_spread:
            reasons.append("fixed_point_unstable")

        status = "safe"
        if reasons:
            status = "suspect" if len(reasons) == 1 else "reject"
        elif require_proxy and p_bad is None:
            status = "unsupported"  # safety-first: refuse to commit without the p_bad proxy
        # numeric score: start at 0, penalise each reason, reward confident margin.
        score = -sum(1.0 for _ in reasons)
        if status == "safe":
            score = 1.0
            if margin is not None:
                score += min(margin, 1.0)
        out.append({
            "canonical_unit_id": row.get("canonical_unit_id"),
            "family": row.get("family"),
            "request_identity": row.get("request_identity"),
            "song_id": row.get("song_id"), "region_id": row.get("region_id"),
            "p_bad": p_bad, "margin": margin, "entropy": entropy,
            "raw_official_disagreement_ms": ro,
            "context_displacement_ms": ctx, "mean_boundary_displacement_ms": mind,
            "fixed_point_spread_ms": spread,
            "status": status, "reasons": reasons,
            "score": round(score, 6),
        })
    return out


def select_candidates(rows: Sequence[Mapping[str, Any]], selector: Mapping[str, Any],
                      *,
                      safety_first: bool = False, require_proxy: bool = False,
                      min_units: int = 1) -> dict[str, Any]:
    """Pick candidate units under the frozen rules.

    ``recovery-first`` (safety_first=False, require_proxy=False) selects any unit
    with a non-empty safe signal set.  ``safety-first`` (safety_first=True,
    require_proxy=True) requires the p_bad proxy (when available) and applies the
    stricter disagreement/context gate.
    """
    verdicts = _apply_selector(rows, selector, require_proxy=require_proxy,
                               safety_first=safety_first)
    safe = [v for v in verdicts if v["status"] == "safe"]
    suspect = [v for v in verdicts if v["status"] == "suspect"]
    rejects = [v for v in verdicts if v["status"] == "reject"]
    unsupported = [v for v in verdicts if v["status"] == "unsupported"]
    selected = safe if len(safe) >= min_units else []
    return {
        "schema": NO_GT_SELECTOR_SCHEMA,
        "mode": "safety_first" if safety_first else "recovery_first",
        "require_proxy": require_proxy,
        "n_rows": len(verdicts),
        "n_selected": len(selected), "n_safe": len(safe),
        "n_suspect": len(suspect), "n_reject": len(rejects),
        "n_unsupported": len(unsupported),
        "selected_unit_ids": [v["canonical_unit_id"] for v in selected],
        "verdicts": verdicts,
    }


# --------------------------------------------------------------------------- #
#  Heldout evaluation (evaluated once only)
# --------------------------------------------------------------------------- #
def evaluate_heldout_once(selector: Mapping[str, Any], heldout_features: Sequence[Mapping[str, Any]],
                          *, require_proxy_recovery: bool = False) -> dict[str, Any]:
    """Evaluate the FROZEN selector on heldout features exactly once.

    Emits two operating points from that single read: ``recovery-first`` and
    ``safety-first``.  No tuning / threshold search happens on heldout.  Returns
    selection coverage per operating point (posterior-safe proportions).
    """
    rows = align_feature_matrix(heldout_features)
    recovery = select_candidates(rows, selector, safety_first=False, require_proxy=require_proxy_recovery)
    safety = select_candidates(rows, selector, safety_first=True, require_proxy=True)
    return {
        "schema": HELDOUT_EVAL_SCHEMA,
        "evaluated_once": True,
        "n_heldout_features": len(rows),
        "operating_points": {
            "recovery_first": _op(rows, recovery),
            "safety_first": _op(rows, safety),
        },
        "frozen_selector": selector,
    }


def disjoint_check(selector: Mapping[str, Any], heldout: Sequence[Mapping[str, Any]]) -> bool:
    """Best-effort disjointness guard: heldout rows must not reuse the freeze split."""
    frozen = str(selector.get("frozen_on") or selector.get("split") or "")
    heldout_splits = {str(r.get("split")) for r in heldout if r.get("split") is not None}
    return frozen in heldout_splits


def _op(rows: Sequence[Mapping[str, Any]], selection: dict[str, Any]) -> dict[str, Any]:
    safe_frac = selection["n_safe"] / selection["n_rows"] if selection["n_rows"] else 0.0
    reject_frac = selection["n_reject"] / selection["n_rows"] if selection["n_rows"] else 0.0
    return {
        "n_selected": selection["n_selected"], "n_safe": selection["n_safe"],
        "n_suspect": selection["n_suspect"], "n_reject": selection["n_reject"],
        "n_unsupported": selection["n_unsupported"],
        "safe_coverage": round(safe_frac, 6),
        "reject_rate": round(reject_frac, 6),
    }
