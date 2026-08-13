"""03_gate: paired GT metrics + no-GT gate features + offline analysis.

Pure functions are unit-tested without models/files; ``run_stage`` wires them
to 02_behavior artifacts plus real GT (contract 03_gate).

No-GT feature rows must survive ``assert_no_label_leak``: output keys never
equal the forbidden field names (label/unsafe/safe/...).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from lyricalign.realign_gate import identity
from lyricalign.realign_gate.detector_audit import _coerce_frozen_op
from lyricalign.realign_recovery.candidate_scores import (
    build_frozen_scorer_from_artifacts,
    evidence_rows_from_request,
    score_units,
)
from lyricalign.research_transition_recovery_detector.real_gt import load_real_gt_with_audit
from lyricalign.research_v7.detector_v2_evidence import assert_no_label_leak

NEUTRAL_EPS_MS = 200.0
CHANGED_EPS_MS = 10.0
CATAS_MS = 200.0
DEV_RATIO = 0.67
N_BIG_DELTA = 0.05

GT_PAIR_SCHEMA = "realign_gate_gt_pair_metrics_v1"
NO_GT_SCHEMA = "realign_gate_no_gt_features_v1"
ANALYSIS_SCHEMA = "realign_gate_analysis_v1"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _row_times(row: Mapping[str, Any]) -> tuple[Any, Any]:
    """Top-level or nested ``raw`` times (start_sec, end_sec)."""
    if isinstance(row.get("raw"), Mapping):
        return row["raw"].get("start_sec"), row["raw"].get("end_sec")
    return row.get("start_sec"), row.get("end_sec")


def _unit_err_ms(pred: Mapping[str, Any] | None, gt: Mapping[str, Any]) -> float | None:
    if pred is None:
        return None
    ps = pred.get("start_sec")
    pe = pred.get("end_sec")
    if ps is None or pe is None:
        return None
    start_err = abs(float(ps) - float(gt["start_sec"]))
    end_err = abs(float(pe) - float(gt["end_sec"]))
    return max(start_err, end_err) * 1000.0


def _label_for(delta_ms: float | None, *, covered_to_missing: bool = False) -> str | None:
    if covered_to_missing:
        return "harm"
    if delta_ms is None:
        return None
    if delta_ms <= -NEUTRAL_EPS_MS:
        return "improve"
    if delta_ms >= NEUTRAL_EPS_MS:
        return "harm"
    return "neutral"


def _catastrophic_reason(
    delta_ms: float | None,
    old_err_ms: float | None,
    new_err_ms: float | None,
    covered_to_missing: bool,
) -> str | None:
    """B13 catastrophic_harm reasons:
    paired delta >200ms, covered-to-missing, or absolute-threshold transition
    from <=100/200ms to >500ms/>1s. Highest-severity reason wins.
    """
    if covered_to_missing:
        return "covered_to_missing"
    if new_err_ms is not None and old_err_ms is not None:
        if old_err_ms <= 100.0 and new_err_ms > 1000.0:
            return "correct_to_gt_1s"
        if old_err_ms <= 200.0 and new_err_ms > 1000.0:
            return "correct_to_gt_1s"
        if old_err_ms <= 100.0 and new_err_ms > 500.0:
            return "correct_to_gt_500"
        if old_err_ms <= 200.0 and new_err_ms > 500.0:
            return "correct_to_gt_500"
    if delta_ms is not None and delta_ms > CATAS_MS:
        return "paired_delta_gt_200"
    return None


def pair_gt(
    new_rows: list[dict],
    real_gt: dict,
    *,
    song_id: str | None,
    old_rows: list[dict] | None = None,
    target_cids: list[int] | None = None,
    expected_variants: list[Mapping[str, Any]] | None = None,
) -> list[dict]:
    """Pair candidate rows against real GT by (song_id, canonical_unit_id) only.

    real_gt is nested {song_id: {cid: {...}}} (contract) or flat {cid: {...}} when
    song_id is None. old_rows (optional) supply old shadow/baseline alignments
    keyed by (case_id, canonical_unit_id) (baseline is variant-independent);
    otherwise rows may carry ``old_error_ms``. A candidate row that cannot
    canonical-bind is marked ``extra_prediction=True`` (no time-IoU fallback).
    ``target_cids`` enables explicit ``new_missing`` records for GT targets
    absent from the candidate.
    """
    gt_song: dict = real_gt.get(song_id, {}) if song_id is not None and song_id in real_gt else dict(real_gt)
    gt_units = {int(k): v for k, v in gt_song.items()}

    old_by_key: dict[tuple, dict] = {}
    for r in old_rows or []:
        if r.get("canonical_unit_id") is None:
            continue
        old_by_key[(r.get("case_id"), int(r["canonical_unit_id"]))] = r

    out: list[dict] = []
    covered_by_variant: dict[Any, set[int]] = {}
    for row in new_rows:
        cid = row.get("canonical_unit_id")
        case_id = row.get("case_id")
        variant = row.get("variant")
        record: dict[str, Any] = {
            "schema": GT_PAIR_SCHEMA,
            "song_id": song_id,
            "case_id": case_id,
            "variant": variant,
            "canonical_unit_id": cid,
            "pairing": None,
            "old_start_error_ms": None,
            "old_end_error_ms": None,
            "new_start_error_ms": None,
            "new_end_error_ms": None,
            "old_error_sec": None,
            "new_error_sec": None,
            "old_error_ms": None,
            "new_error_ms": None,
            "old_missing": None,
            "new_missing": None,
            "duplicate_prediction": row.get("duplicate_prediction"),
            "extra_prediction": False,
            "delta_error_ms": None,
            "label": None,
            "catastrophic_harm": False,
            "catastrophic_reason": None,
            "boundaries_100": False,
            "boundaries_200": False,
            "boundaries_500": False,
        }

        gt = None
        if cid is not None and int(cid) in gt_units:
            gt = gt_units[int(cid)]
            covered_by_variant.setdefault(variant, set()).add(int(cid))
            record["pairing"] = "canonical"
        else:
            record["extra_prediction"] = True
        if gt is None:
            out.append(record)
            continue

        old_pred: dict | None = None
        if cid is not None:
            old_pred = old_by_key.get((case_id, int(cid)))
        old_err_ms = row.get("old_error_ms") if isinstance(row.get("old_error_ms"), (int, float)) else None
        new_err_ms = row.get("new_error_ms") if isinstance(row.get("new_error_ms"), (int, float)) else None

        if old_pred is not None:
            old_err_ms = _unit_err_ms(old_pred, gt)
            record["old_start_error_ms"] = (
                abs(float(old_pred["start_sec"]) - float(gt["start_sec"])) * 1000.0
                if old_pred.get("start_sec") is not None else None)
            record["old_end_error_ms"] = (
                abs(float(old_pred["end_sec"]) - float(gt["end_sec"])) * 1000.0
                if old_pred.get("end_sec") is not None else None)
        if new_pred := _new_pred(row):
            new_err_ms = _unit_err_ms(new_pred, gt)
            record["new_start_error_ms"] = abs(float(new_pred["start_sec"]) - float(gt["start_sec"])) * 1000.0
            record["new_end_error_ms"] = abs(float(new_pred["end_sec"]) - float(gt["end_sec"])) * 1000.0

        record["old_error_ms"] = old_err_ms
        record["new_error_ms"] = new_err_ms
        record["old_error_sec"] = old_err_ms / 1000.0 if old_err_ms is not None else None
        record["new_error_sec"] = new_err_ms / 1000.0 if new_err_ms is not None else None
        record["old_missing"] = old_err_ms is None
        record["new_missing"] = new_err_ms is None
        if old_err_ms is not None and new_err_ms is not None:
            record["delta_error_ms"] = round(new_err_ms - old_err_ms, 4)
        covered_to_missing = old_err_ms is not None and new_err_ms is None
        record["label"] = _label_for(record["delta_error_ms"], covered_to_missing=covered_to_missing)
        record["catastrophic_reason"] = _catastrophic_reason(
            record["delta_error_ms"], old_err_ms, new_err_ms, covered_to_missing)
        record["catastrophic_harm"] = record["catastrophic_reason"] is not None
        if new_err_ms is not None:
            record["boundaries_100"] = new_err_ms <= 100.0
            record["boundaries_200"] = new_err_ms <= 200.0
            record["boundaries_500"] = new_err_ms <= 500.0
        out.append(record)

    if target_cids is not None:
        # The candidate manifest, not the rows that happened to decode, is the
        # denominator.  Otherwise a zero-row forward silently disappears and
        # cannot be counted as covered->missing / invalid evidence.
        variants_by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
        for spec in expected_variants or []:
            case_id, variant = spec.get("case_id"), spec.get("variant")
            if variant is not None:
                variants_by_key[(case_id, variant)] = {"case_id": case_id, "variant": variant}
        for row in new_rows:
            case_id, variant = row.get("case_id"), row.get("variant")
            if variant is not None:
                variants_by_key.setdefault((case_id, variant), {"case_id": case_id, "variant": variant})
        variants = list(variants_by_key.values())
        for cid in target_cids:
            cid = int(cid)
            if cid not in gt_units:
                continue
            for spec in variants:
                case_id, variant = spec["case_id"], spec["variant"]
                if cid in covered_by_variant.get(variant, set()):
                    continue
                old_pred = old_by_key.get((case_id, cid))
                old_err_ms = _unit_err_ms(old_pred, gt_units[cid]) if old_pred is not None else None
                record = {
                    "schema": GT_PAIR_SCHEMA,
                    "song_id": song_id,
                    "case_id": case_id,
                    "variant": variant,
                    "canonical_unit_id": cid,
                    "pairing": "canonical",
                    "old_start_error_ms": (
                        abs(float(old_pred["start_sec"]) - float(gt_units[cid]["start_sec"])) * 1000.0
                        if old_pred is not None and old_pred.get("start_sec") is not None else None),
                    "old_end_error_ms": (
                        abs(float(old_pred["end_sec"]) - float(gt_units[cid]["end_sec"])) * 1000.0
                        if old_pred is not None and old_pred.get("end_sec") is not None else None),
                    "new_start_error_ms": None,
                    "new_end_error_ms": None,
                    "old_error_sec": old_err_ms / 1000.0 if old_err_ms is not None else None,
                    "new_error_sec": None,
                    "old_error_ms": old_err_ms,
                    "new_error_ms": None,
                    "old_missing": old_err_ms is None,
                    "new_missing": True,
                    "duplicate_prediction": None,
                    "extra_prediction": False,
                    "delta_error_ms": None,
                    "label": "harm" if old_err_ms is not None else None,
                    "catastrophic_harm": old_err_ms is not None,
                    "catastrophic_reason": "covered_to_missing" if old_err_ms is not None else None,
                    "boundaries_100": False,
                    "boundaries_200": False,
                    "boundaries_500": False,
                }
                out.append(record)
    return out


def _active_target_ids(request: Mapping[str, Any] | None, case: Mapping[str, Any]) -> list[int]:
    """Resolve the request's actual responsibility range, never a legacy window target."""
    request = request or {}
    provenance = request.get("provenance") if isinstance(request.get("provenance"), Mapping) else {}
    raw = (request.get("active_target_unit_ids") or request.get("target_unit_ids")
           or provenance.get("active_target_unit_ids") or provenance.get("target_unit_ids")
           or case.get("active_target_unit_ids") or case.get("target_unit_ids") or [])
    ids: list[int] = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


def _ensure_no_gt_target_spine(
    no_gt_rows: list[dict],
    candidates: list[dict],
    requests_by_id: Mapping[Any, Mapping[str, Any]],
    case_by_id: Mapping[Any, Mapping[str, Any]],
) -> list[dict]:
    """Left-join spine for requested targets that produced no evidence row.

    This is constructed solely from the no-GT request/candidate manifests.  It
    records that an expected output is absent, but deliberately has no GT
    outcome fields.  Evaluation joins labels only later by the stable key.
    """
    existing = {
        (row.get("case_id"), row.get("variant"), row.get("canonical_unit_id"))
        for row in no_gt_rows if isinstance(row, Mapping)
    }
    out = list(no_gt_rows)
    for candidate in candidates:
        case_id, variant = candidate.get("case_id"), candidate.get("variant")
        request = requests_by_id.get(candidate.get("request_id")) or {}
        case = case_by_id.get(case_id) or {}
        for cid in _active_target_ids(request, case):
            key = (case_id, variant, cid)
            if key in existing:
                continue
            row = {
                "schema": NO_GT_SCHEMA,
                "request_identity": candidate.get("content_idn") or candidate.get("request_identity"),
                "case_id": case_id,
                "variant": variant,
                "canonical_unit_id": cid,
                "song_id": case.get("song_id"),
                "candidate_output_present": False,
                "feature_source": "expected_target_without_evidence",
                "feature_valid": True,
                "n_big": None,
                "changed_ratio": None,
                "sum_displacement_ms": None,
                "max_displacement_ms": None,
                "unsafe_inside_disp_ms": None,
                "safe_outside_disp_ms": None,
                "safe_context_changed_count": None,
                "p_bad_delta": None,
                "abs_p_bad_delta": None,
                "entropy_delta": None,
                "margin_delta": None,
                "pile_up": None,
                "inversion": None,
                "compression": None,
                "ra_rb_agreement": None,
            }
            assert_no_label_leak(row)
            out.append(row)
            existing.add(key)
    return out


def _new_pred(row: Mapping[str, Any]) -> dict | None:
    for key in ("new_alignment", "raw", "official"):
        v = row.get(key)
        if isinstance(v, Mapping) and v.get("start_sec") is not None and v.get("end_sec") is not None:
            return {"start_sec": v["start_sec"], "end_sec": v["end_sec"]}
    if row.get("start_sec") is not None and row.get("end_sec") is not None:
        return {"start_sec": row["start_sec"], "end_sec": row["end_sec"]}
    return None


def _shadow_lookup(old_shadow: Any) -> tuple[dict, dict]:
    """Build (units, intervals) lookups from a baseline shadow.

    units keys: ``(song_id, case_id, canonical_unit_id)`` triples when the
    shadow was built per-song/per-case (B8), else legacy int-cid keys.
    intervals keys: ``(song_id, case_id)`` pairs (B8), else ``None`` for a
    legacy global interval list. Callers must resolve a row via its triple
    first and never fall back to a cid-only lookup across songs.
    """
    units: dict = {}
    intervals: dict = {}
    if isinstance(old_shadow, Mapping):
        if "units" in old_shadow:
            raw_units = old_shadow["units"] or {}
            if isinstance(raw_units, Mapping):
                for k, v in raw_units.items():
                    if isinstance(k, (list, tuple)) and len(k) == 3:
                        units[(str(k[0]), str(k[1]), int(k[2]))] = v
                    elif isinstance(v, Mapping):
                        units[int(k)] = v
            raw_iv = old_shadow.get("unsafe_intervals") or {}
            if isinstance(raw_iv, Mapping):
                for k, ivs in raw_iv.items():
                    if isinstance(k, (list, tuple)) and len(k) == 2:
                        intervals[(str(k[0]), str(k[1]))] = [
                            [float(a), float(b)] for a, b in ivs
                        ]
            elif isinstance(raw_iv, (list, tuple)):
                intervals[None] = [[float(a), float(b)] for a, b in raw_iv]
        elif "canonical_unit_id" in old_shadow:
            units[(None, None, int(old_shadow["canonical_unit_id"]))] = old_shadow
        else:
            units = {int(k): v for k, v in old_shadow.items() if isinstance(v, Mapping)}
    elif isinstance(old_shadow, (list, tuple)):
        for r in old_shadow:
            if isinstance(r, Mapping) and r.get("canonical_unit_id") is not None:
                units[int(r["canonical_unit_id"])] = r
                for iv in r.get("unsafe_intervals") or []:
                    intervals.setdefault(None, []).append([float(iv[0]), float(iv[1])])
    return units, intervals


def _old_unit_for(shadow_units: dict, row: Mapping[str, Any]) -> dict | None:
    """Resolve a baseline unit for ``row``: triple key first, legacy cid only
    when the shadow was not built per-song/per-case (B8). Query keys are
    normalized to (str, str, int) to match ``_shadow_lookup`` construction."""
    cid = row.get("canonical_unit_id")
    if cid is None:
        return None
    triple = (str(row.get("song_id")), str(row.get("case_id")), int(cid))
    if triple in shadow_units:
        return shadow_units[triple]
    return shadow_units.get(int(cid))


def _unsafe_intervals_for(shadow_intervals: dict, row: Mapping[str, Any]) -> list[list[float]]:
    """Resolve per-(song_id, case_id) unsafe intervals, else legacy global list.
    Query keys normalized to (str, str) to match ``_shadow_lookup`` construction."""
    ivs = shadow_intervals.get((str(row.get("song_id")), str(row.get("case_id"))))
    if ivs is None:
        ivs = shadow_intervals.get(None)
    return ivs or []


def extract_no_gt_features(evidence_rows: list[dict], old_shadow: Any = None) -> list[dict]:
    """Build NO_GT_FEATURES rows; each row must pass assert_no_label_leak.

    Works on flat fake rows (tests) or nested raw/official evidence (production).
    Aggregates are candidate-level over the (song_id, case_id, variant) group:
    ``changed_ratio``, ``sum|max_displacement_ms``, ``unsafe_inside_disp_ms``,
    ``safe_outside_disp_ms``, ``safe_context_changed_count``, ``pile_up`` and
    ``n_big`` (count(|p_bad_after - p_bad_before| > N_BIG_DELTA)) are computed
    per group and written identically to every row of that group (B7/B12).
    Baseline/shadow units and unsafe intervals resolve per
    (song_id, case_id, canonical_unit_id) (B8); ``ra_rb_agreement`` is looked up
    per (song_id, case_id) from the dict (never pooled across cases).
    """
    shadow_units, shadow_intervals = _shadow_lookup(old_shadow or {})
    out: list[dict] = []
    group_rows: dict[tuple, list[dict]] = defaultdict(list)
    group_recs: dict[tuple, list[dict]] = defaultdict(list)
    grp_changed: dict[tuple, list[bool]] = defaultdict(list)
    grp_disp: dict[tuple, list[tuple[float, str, bool]]] = defaultdict(list)  # (ms, unsafe|safe, changed)
    grp_big: dict[tuple, list[bool | None]] = defaultdict(list)
    ra_rb = _ra_rb_agreement(evidence_rows)

    for row in evidence_rows:
        norm = dict(row)
        if isinstance(row.get("raw"), Mapping):
            raw = row["raw"]
            for k in ("start_sec", "end_sec", "start_entropy", "end_entropy", "start_margin", "end_margin"):
                norm.setdefault(k, raw.get(k))
        rec: dict[str, Any] = {
            "schema": NO_GT_SCHEMA,
            "request_identity": row.get("request_identity"),
            "case_id": row.get("case_id"),
            "variant": row.get("variant"),
            "canonical_unit_id": row.get("canonical_unit_id"),
            "song_id": row.get("song_id"),
            "n_big": None,
            "n_big_uncomputed": None,
            "changed_ratio": None,
            "sum_displacement_ms": None,
            "max_displacement_ms": None,
            "unsafe_inside_disp_ms": None,
            "safe_outside_disp_ms": None,
            "safe_context_changed_count": None,
            "outside_request_changes": None,
            "p_bad_before": None,
            "p_bad_after": None,
            "p_bad_delta": None,
            "abs_p_bad_delta": None,
            "entropy_delta": None,
            "margin_delta": None,
            "pile_up": None,
            "inversion": None,
            "compression": None,
            "text_identity": None,
            "ra_rb_agreement": None,
            "feature_valid": False,
            "leak_reason": None,
        }
        try:
            assert_no_label_leak(rec)
        except ValueError as exc:
            rec["feature_valid"] = False
            rec["leak_reason"] = str(exc)
            out.append(rec)
            continue
        rec["feature_valid"] = True

        gkey = (str(row.get("song_id")), str(row.get("case_id")), str(row.get("variant")))
        group_rows[gkey].append(row)
        group_recs[gkey].append(rec)

        cid = row.get("canonical_unit_id")
        old = _old_unit_for(shadow_units, row)

        new_s = norm.get("start_sec")
        new_e = norm.get("end_sec")
        old_s = norm.get("old_start_sec")
        old_e = norm.get("old_end_sec")
        if old is not None and isinstance(old, Mapping):
            old_s = old_s if old_s is not None else old.get("start_sec")
            old_e = old_e if old_e is not None else old.get("end_sec")

        disp_ms: float | None = None
        changed = False
        if None not in (new_s, new_e, old_s, old_e):
            disp_ms = (abs(float(new_s) - float(old_s)) + abs(float(new_e) - float(old_e))) / 2.0 * 1000.0
            changed = disp_ms > CHANGED_EPS_MS
        grp_changed[gkey].append(changed)

        p_before = norm.get("p_bad_before")
        p_after = norm.get("p_bad_after")
        if p_before is None and old is not None and isinstance(old, Mapping):
            p_before = old.get("p_bad")
        if p_after is None:
            p_after = norm.get("p_bad")
        rec["p_bad_before"] = p_before
        rec["p_bad_after"] = p_after
        if isinstance(p_before, (int, float)) and isinstance(p_after, (int, float)):
            delta = float(p_after) - float(p_before)
            rec["p_bad_delta"] = round(delta, 6)
            rec["abs_p_bad_delta"] = round(abs(delta), 6)
            grp_big[gkey].append(abs(delta) > N_BIG_DELTA)
        else:
            grp_big[gkey].append(None)

        rec["entropy_delta"] = _delta_pair(norm, "start_entropy", "entropy_before", "entropy_after")
        rec["margin_delta"] = _delta_pair(norm, "start_margin", "margin_before", "margin_after")

        center = None
        if new_s is not None and new_e is not None:
            center = (float(new_s) + float(new_e)) / 2.0
        in_unsafe = center is not None and any(
            a <= center <= b for a, b in _unsafe_intervals_for(shadow_intervals, row)
        )
        if disp_ms is not None:
            grp_disp[gkey].append((disp_ms, "unsafe" if in_unsafe else "safe", changed))

        if isinstance(norm.get("in_request"), bool):
            rec["outside_request_changes"] = int(changed and not norm["in_request"])
        if isinstance(norm.get("inversion"), bool):
            rec["inversion"] = int(norm["inversion"])
        elif new_s is not None and new_e is not None:
            rec["inversion"] = int(float(new_s) > float(new_e))

        if new_s is not None and new_e is not None and old_s is not None and old_e is not None:
            nspan = float(new_e) - float(new_s)
            ospan = float(old_e) - float(old_s)
            if ospan > 0 and nspan > 0:
                ratio = min(nspan / ospan, ospan / nspan) if (nspan > 0 and ospan > 0) else 1.0
                rec["compression"] = round(1.0 - ratio, 6) if nspan < ospan else None
        if norm.get("text") is not None and norm.get("old_text") is not None:
            rec["text_identity"] = int(norm["text"] == norm["old_text"])
        elif norm.get("text") is not None:
            rec["text_identity"] = int(norm["text"] == (old.get("text") if isinstance(old, Mapping) else None))
        out.append(rec)

    for gkey, rows in group_rows.items():
        recs = group_recs[gkey]
        changed_flags = grp_changed[gkey]
        n_changed = sum(1 for c in changed_flags if c)
        if n_changed:
            ratio = round(n_changed / max(1, len(changed_flags)), 6)
        else:
            ratio = None
        disps = grp_disp[gkey]
        if disps:
            vals = np.array([d for d, _, _ in disps], dtype=float)
            inside = [d for d, grp, _ in disps if grp == "unsafe"]
            outside = [d for d, grp, _ in disps if grp == "safe"]
            sum_disp = round(float(vals.sum()), 4)
            max_disp = round(float(vals.max()), 4)
            unsafe_inside = round(float(np.mean(inside)), 4) if inside else None
            safe_outside = round(float(np.mean(outside)), 4) if outside else None
            safe_ctx = sum(1 for _, grp, ch in disps if grp == "safe" and ch)
        else:
            sum_disp = None
            max_disp = None
            unsafe_inside = None
            safe_outside = None
            safe_ctx = None
        pile = _pile_up(rows)
        agree = ra_rb.get((gkey[0], gkey[1]))

        n_big = 0
        n_big_uncomputed = 0
        for is_big in grp_big[gkey]:
            if is_big is None:
                n_big_uncomputed += 1
            else:
                n_big += int(is_big)
        has_computed = any(is_big is not None for is_big in grp_big[gkey])

        for rec in recs:
            if rec["changed_ratio"] is None:
                rec["changed_ratio"] = ratio
            rec["sum_displacement_ms"] = sum_disp
            rec["max_displacement_ms"] = max_disp
            rec["unsafe_inside_disp_ms"] = unsafe_inside
            rec["safe_outside_disp_ms"] = safe_outside
            rec["safe_context_changed_count"] = safe_ctx
            if rec["pile_up"] is None:
                rec["pile_up"] = pile
            if rec["ra_rb_agreement"] is None:
                rec["ra_rb_agreement"] = agree
            if has_computed:
                rec["n_big"] = n_big
            if n_big_uncomputed:
                rec["n_big_uncomputed"] = n_big_uncomputed
    return out


def _delta_pair(norm: Mapping[str, Any], field: str, before_key: str, after_key: str) -> float | None:
    b = norm.get(before_key)
    a = norm.get(after_key)
    if b is None and norm.get(field) is not None:
        b = norm.get(field)
    if b is None or a is None:
        return None
    return round(float(a) - float(b), 6)


def _pile_up(evidence_rows: list[dict]) -> int:
    starts = [s for r in evidence_rows for s, _ in [_row_times(r)] if s is not None]
    counts = {}
    for s in starts:
        key = round(float(s), 3)
        counts[key] = counts.get(key, 0) + 1
    return sum(n - 1 for n in counts.values() if n > 1)


def _ra_rb_agreement(evidence_rows: list[dict]) -> dict[tuple, float | None]:
    """Per-(song_id, case_id) R-A/R-B agreement (B12).

    For each unit covered by >=2 variants of the same (song_id, case_id) case,
    agree if the variant displacement difference <= 50ms. Returns
    {(song_id, case_id): agreement}; a case absent from every row is not in the
    dict (callers fall back to None). Never pooled across cases or songs.
    """
    per_sc: dict[tuple, dict[str, dict[int, float]]] = defaultdict(dict)
    for r in evidence_rows:
        s, e = _row_times(r)
        if s is None or r.get("old_start_sec") is None:
            continue
        disp = (abs(float(s) - float(r["old_start_sec"]))
                + abs(float(e or s) - float(r.get("old_end_sec") or r["old_start_sec"]))) / 2.0 * 1000.0
        key = (str(r.get("song_id")), str(r.get("case_id")))
        per_sc[key].setdefault(str(r.get("variant")), {})[int(r.get("canonical_unit_id"))] = disp
    out: dict[tuple, float | None] = {}
    for sc_key, groups in per_sc.items():
        agrees = 0
        total = 0
        for cid in set().union(*[set(g.keys()) for g in groups.values()]):
            ds = [g[cid] for g in groups.values() if cid in g]
            if len(ds) >= 2:
                total += 1
                if max(ds) - min(ds) <= 50.0:
                    agrees += 1
        out[sc_key] = round(agrees / total, 4) if total else None
    return out


def _rankdata(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(1, len(x) + 1)
    xs = x[order]
    rs = ranks[order]
    edges = np.r_[0, np.nonzero(np.diff(xs))[0] + 1, len(x)]
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a > 1:
            rs[a:b] = rs[a:b].mean()
    out = np.empty_like(ranks)
    out[order] = rs
    return out


def spearman(x, y) -> float | None:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 3 or len(x) != len(y):
        return None
    rx = _rankdata(x)
    ry = _rankdata(y)
    den = math.sqrt(float(((rx - rx.mean()) ** 2).sum() * ((ry - ry.mean()) ** 2).sum()))
    if den == 0:
        return 0.0
    return float(((rx - rx.mean()) * (ry - ry.mean())).sum() / den)


def roc_auc(y_true, scores) -> float | None:
    y = np.asarray(y_true, dtype=bool)
    s = np.asarray(scores, dtype=float)
    mask = np.isfinite(s)
    y = y[mask]
    s = s[mask]
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = _rankdata(s)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def auprc(y_true, scores) -> float | None:
    y = np.asarray(y_true, dtype=bool)
    s = np.asarray(scores, dtype=float)
    mask = np.isfinite(s)
    y = y[mask]
    s = s[mask]
    n_pos = int(y.sum())
    if n_pos == 0:
        return None
    order = np.argsort(-s, kind="mergesort")
    ys = y[order]
    tp = 0
    ap = 0.0
    for i, v in enumerate(ys):
        if v:
            tp += 1
            ap += tp / (i + 1)
    return ap / max(n_pos, 1)


def analyze(
    gt_rows: list[dict],
    no_gt_rows: list[dict],
    *,
    split_ratio: float = DEV_RATIO,
    seed: int = 0,
    out_dir: str | Path | None = None,
) -> dict:
    """Song-split dev/holdout analysis; offline three-state suggestion (no writeback)."""
    gt_by_key: dict = {}
    gt_dups: list = []
    for r in gt_rows:
        if r.get("label") is None:
            continue
        key = (r.get("case_id"), r.get("variant"), r.get("canonical_unit_id"))
        if key in gt_by_key:
            gt_dups.append(key)
        gt_by_key[key] = r
    ng_by_key: dict = {}
    ng_dups: list = []
    for r in no_gt_rows:
        if not r.get("feature_valid"):
            continue
        key = (r.get("case_id"), r.get("variant"), r.get("canonical_unit_id"))
        if key in ng_by_key:
            ng_dups.append(key)
        ng_by_key[key] = r
    keys = sorted(set(gt_by_key) & set(ng_by_key))
    merged = []
    for key in keys:
        g = gt_by_key[key]
        n = ng_by_key[key]
        merged.append({
            "song_id": g.get("song_id") or n.get("song_id"),
            "case_id": key[0],
            "variant": key[1],
            "canonical_unit_id": key[2],
            "delta_error_ms": g.get("delta_error_ms"),
            "label": g.get("label"),
            "n_big": n.get("n_big"),
            "unsafe_inside_disp_ms": n.get("unsafe_inside_disp_ms"),
            "changed_ratio": n.get("changed_ratio"),
            "sum_displacement_ms": n.get("sum_displacement_ms"),
            "max_displacement_ms": n.get("max_displacement_ms"),
            "safe_outside_disp_ms": n.get("safe_outside_disp_ms"),
            "safe_context_changed_count": n.get("safe_context_changed_count"),
            "p_bad_delta": n.get("p_bad_delta"),
            "abs_p_bad_delta": n.get("abs_p_bad_delta"),
            "entropy_delta": n.get("entropy_delta"),
            "margin_delta": n.get("margin_delta"),
            "pile_up": n.get("pile_up"), "inversion": n.get("inversion"),
            "compression": n.get("compression"), "ra_rb_agreement": n.get("ra_rb_agreement"),
        })

    # A candidate, not its constituent character rows, is the independent
    # experiment unit.  Candidate harm is conservative (any harmed target);
    # the diagnostic delta is the worst target delta, so safety failures cannot
    # be averaged away by a long otherwise-neutral region.
    candidate_groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in merged:
        candidate_groups[(row["song_id"], row["case_id"], row["variant"])].append(row)
    candidate_merged: list[dict] = []
    for (song_id, case_id, variant), rows in candidate_groups.items():
        deltas = [float(r["delta_error_ms"]) for r in rows if r["delta_error_ms"] is not None]
        labels = {r["label"] for r in rows}
        label = "harm" if "harm" in labels else ("improve" if "improve" in labels else "neutral")
        item = {
            "song_id": song_id, "case_id": case_id, "variant": variant,
            "canonical_unit_id": None, "label": label,
            "delta_error_ms": max(deltas) if deltas else None,
            "n_big": max((r["n_big"] for r in rows if r["n_big"] is not None), default=None),
            "unsafe_inside_disp_ms": max((r["unsafe_inside_disp_ms"] for r in rows
                                           if r["unsafe_inside_disp_ms"] is not None), default=None),
            "changed_ratio": max((r["changed_ratio"] for r in rows
                                  if r["changed_ratio"] is not None), default=None),
            "n_unit_rows": len(rows),
        }
        for field in ("sum_displacement_ms", "max_displacement_ms", "safe_outside_disp_ms",
                      "safe_context_changed_count", "abs_p_bad_delta", "pile_up", "inversion", "compression"):
            vals = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
            item[field] = max(vals) if vals else None
        for field in ("p_bad_delta", "entropy_delta", "margin_delta", "ra_rb_agreement"):
            vals = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
            item[field] = float(np.median(vals)) if vals else None
        candidate_merged.append(item)
    merged = candidate_merged

    song_ids = sorted({m["song_id"] for m in merged if m["song_id"]})
    rng = np.random.default_rng(seed)
    dev_songs: set = set()
    if song_ids:
        rng.shuffle(song_ids)
        n_dev = max(1, int(round(len(song_ids) * split_ratio)))
        dev_songs = set(song_ids[:n_dev])
    dev = [m for m in merged if m["song_id"] in dev_songs]
    holdout = [m for m in merged if m["song_id"] not in dev_songs]

    def metrics(rows: list[dict]) -> dict:
        labels = np.array([1 if r["label"] == "harm" else 0 for r in rows], dtype=int)
        deltas = np.array([r["delta_error_ms"] if r["delta_error_ms"] is not None else np.nan for r in rows], dtype=float)
        nbig = np.array([r["n_big"] if r["n_big"] is not None else np.nan for r in rows], dtype=float)
        metric = {}
        metric["auroc_delta"] = roc_auc(labels, deltas)
        metric["auprc_delta"] = auprc(labels, deltas)
        metric["auroc_nbig"] = roc_auc(labels, nbig)
        metric["auprc_nbig"] = auprc(labels, nbig)
        metric["spearman_delta_nbig"] = spearman(
            [d for d in deltas if np.isfinite(d)],
            [x for d, x in zip(deltas, nbig) if np.isfinite(d) and np.isfinite(x)] or [0],
        ) if any(np.isfinite(deltas)) and any(np.isfinite(nbig)) else None
        metric["harm_rate"] = float(labels.mean()) if len(labels) else None
        metric["n"] = len(rows)
        return metric

    dev_metrics = metrics(dev)
    hold_metrics = metrics(holdout)

    # Single-signal screen. Orientation is selected only on dev songs, then
    # frozen for holdout. It is explicitly exploratory, never a writeback rule.
    screen_fields = ("n_big", "changed_ratio", "sum_displacement_ms", "max_displacement_ms",
                     "unsafe_inside_disp_ms", "safe_outside_disp_ms", "safe_context_changed_count",
                     "abs_p_bad_delta", "entropy_delta", "margin_delta", "pile_up", "inversion",
                     "compression", "ra_rb_agreement")
    feature_screen = []
    for field in screen_fields:
        def score(rows):
            values = []
            labels = []
            for row in rows:
                value = row.get(field)
                if not isinstance(value, (int, float)):
                    continue
                # Agreement is protective: lower agreement is riskier.
                values.append(1.0 - value if field == "ra_rb_agreement" else float(value))
                labels.append(1 if row["label"] == "harm" else 0)
            return labels, values
        d_y, d_x = score(dev)
        h_y, h_x = score(holdout)
        dev_auc = roc_auc(d_y, d_x)
        sign = 1
        if dev_auc is not None and dev_auc < 0.5:
            sign, dev_auc = -1, 1.0 - dev_auc
        hold_auc = roc_auc(h_y, [sign * x for x in h_x])
        feature_screen.append({"feature": field, "direction": "higher_is_harm" if sign == 1 else "lower_is_harm",
                               "n_dev": len(d_x), "dev_auroc": dev_auc,
                               "n_holdout": len(h_x), "holdout_auroc": hold_auc})
    feature_screen.sort(key=lambda r: (-1 if r["holdout_auroc"] is None else -r["holdout_auroc"], r["feature"]))

    sweep = _threshold_sweep(dev)
    combo = _nbig_locality_combo(dev)
    risk_curve = _risk_coverage_curve(dev)
    # GT is outcome-only.  Never use it to select a candidate or recommend a
    # writeback; offline metrics may describe observability, not a policy.
    hold_risk = None
    suggestion = "DIAGNOSTIC_ONLY_NO_WRITEBACK"

    counterexamples = _counterexamples(merged)
    result: dict[str, Any] = {
        "schema": ANALYSIS_SCHEMA,
        "suggestion": suggestion,
        "suggestion_note": _suggestion_note(suggestion, hold_metrics, hold_risk),
        "splits": {
            "dev_ratio": split_ratio,
            "seed": seed,
            "n_dev_songs": len(dev_songs),
            "n_holdout_songs": len(song_ids) - len(dev_songs),
            "n_dev_candidates": len(dev),
            "n_holdout_candidates": len(holdout),
        },
        "metrics": {"dev": dev_metrics, "holdout": hold_metrics},
        "duplicate_keys": {
            "gt_pair_metrics": len(gt_dups),
            "no_gt_features": len(ng_dups),
        },
        "harmful_risk_writeback_holdout": hold_risk,
        "threshold_sweep": sweep,
        "nbig_locality_combo": combo,
        "risk_coverage_curve": risk_curve,
        "feature_screen_candidate_song_holdout": feature_screen,
        "n_counterexamples": len([c for c in counterexamples if c["reason"] == "counterexample"]),
        "n_ambiguous": len([c for c in counterexamples if c["reason"] == "ambiguous"]),
        "result_status": "ok",
    }
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        result["generated_at_utc"] = now_utc()
        (out / "ANALYSIS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with (out / "COUNTEREXAMPLES.jsonl").open("w", encoding="utf-8") as f:
            for c in counterexamples:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        result["outputs"] = {
            "analysis": str(out / "ANALYSIS.json"),
            "counterexamples": str(out / "COUNTEREXAMPLES.jsonl"),
        }
    return result


def _suggestion(auc_hold: float | None, n_hold: int, risk: float | None) -> str:
    del auc_hold, n_hold, risk
    return "DIAGNOSTIC_ONLY_NO_WRITEBACK"


def _suggestion_note(suggestion: str, hold: dict, risk: float | None) -> str:
    if suggestion == "DIAGNOSTIC_ONLY_NO_WRITEBACK":
        return "GT outcomes are evaluation-only; no gate recommendation or writeback is emitted."
    if suggestion == "REJECT_KEEP_ORIGINAL":
        return f"holdout AUROC={hold['auroc_delta']} risk={risk}; gate not reliable, keep original alignment"
    return "insufficient holdout signal or ambiguous; keep original and retry more cases"


def _threshold_sweep(rows: list[dict]) -> list[dict]:
    points = []
    labels = np.array([1 if r["label"] == "harm" else 0 for r in rows], dtype=int)
    nbig = np.array([r["n_big"] if r["n_big"] is not None else -1 for r in rows], dtype=int)
    total_harm = int(labels.sum())
    for thresh in range(0, int(nbig.max()) + 1 if len(nbig) else 1):
        flagged = nbig >= thresh
        if not flagged.any():
            points.append({"threshold": thresh, "precision": None, "recall": 0.0, "n_flagged": 0})
            continue
        tp = int((labels & flagged).sum())
        points.append({
            "threshold": thresh,
            "precision": tp / int(flagged.sum()) if flagged.any() else None,
            "recall": tp / total_harm if total_harm else None,
            "n_flagged": int(flagged.sum()),
        })
    return points


def _nbig_locality_combo(rows: list[dict]) -> list[dict]:
    nbigs = [r["n_big"] for r in rows if r["n_big"] is not None]
    disp = [r["unsafe_inside_disp_ms"] for r in rows if r["unsafe_inside_disp_ms"] is not None]
    med_n = float(np.median(nbigs)) if nbigs else 0.0
    med_d = float(np.median(disp)) if disp else 0.0
    combos = []
    for n_hi in (False, True):
        for d_hi in (False, True):
            cells = [r for r in rows
                     if (r["n_big"] is not None and (r["n_big"] > med_n) == n_hi)
                     and (r["unsafe_inside_disp_ms"] is not None and (r["unsafe_inside_disp_ms"] > med_d) == d_hi)]
            combos.append({
                "n_big_high": n_hi,
                "disp_high": d_hi,
                "n": len(cells),
                "harm_rate": (sum(1 for r in cells if r["label"] == "harm") / len(cells)) if cells else None,
            })
    return combos


def _risk_coverage_curve(rows: list[dict]) -> list[dict]:
    curve = []
    total_harm = sum(1 for r in rows if r["label"] == "harm")
    nbigs = sorted({r["n_big"] for r in rows if r["n_big"] is not None})
    for t in nbigs:
        flagged = [r for r in rows if r["n_big"] is not None and r["n_big"] >= t]
        harm = sum(1 for r in flagged if r["label"] == "harm")
        curve.append({
            "threshold": t,
            "harm_risk": harm / len(flagged) if flagged else None,
            "coverage": harm / total_harm if total_harm else None,
            "n_flagged": len(flagged),
        })
    return curve


def _counterexamples(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        base = {
            "song_id": r.get("song_id"),
            "case_id": r.get("case_id"),
            "canonical_unit_id": r.get("canonical_unit_id"),
            "variant": r.get("variant"),
            "delta_error_ms": r.get("delta_error_ms"),
            "label": r.get("label"),
            "n_big": r.get("n_big"),
        }
        if r.get("label") == "harm" and (r.get("n_big") in (None, 0)):
            out.append({**base, "reason": "counterexample",
                        "why": "gate missed harmful realign (n_big low / absent)"})
        elif r.get("label") == "improve" and r.get("n_big") is not None and r["n_big"] >= 1:
            out.append({**base, "reason": "counterexample",
                        "why": "gate flagged improvement despite high n_big"})
        elif r.get("delta_error_ms") is not None and abs(r["delta_error_ms"]) <= 50.0:
            out.append({**base, "reason": "ambiguous", "why": "delta near neutral"})
    return out


def run_stage(run_root: str | Path, cfg_path: str | Path | None = None) -> dict:
    """Read 02_behavior artifacts + real GT -> write 03_gate outputs. Return summary."""
    run_root = Path(run_root)
    cfg_file = Path(cfg_path) if cfg_path else run_root / "00_meta/CONFIG.json"
    if not cfg_file.exists():
        raise FileNotFoundError(f"CONFIG not found: {cfg_file}")
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    inputs = cfg.get("inputs", {})

    real_gt: dict = {}
    for manifest in inputs.get("cohort_manifests", []):
        rg, _audit = load_real_gt_with_audit(inputs["real_gt_annotations"], manifest)
        for song, units in rg.items():
            real_gt.setdefault(song, {}).update(units)

    scorer = build_frozen_scorer_from_artifacts(
        _coerce_frozen_op(inputs.get("frozen_op") or str(identity.FROZEN_OP_PATH)),
        inputs.get("labels_path") or str(identity.HANDOFF_RUN / "stage3b_cohort_ab_eval/LABELS.jsonl"),
        inputs.get("evidence_dir_for_scorer") or str(identity.HANDOFF_RUN / "stage3b_cohort_ab_eval/evidence_v2"),
        list(inputs.get("items_dirs") or [
            str(identity.HANDOFF_RUN / "stage3b_cohort_a_reagg/rerun_gpu/items"),
            str(identity.HANDOFF_RUN / "stage3b_cohort_b_dev/items"),
        ]),
        target="raw",
    )

    cases = _read_jsonl(run_root / "02_behavior/CASES.jsonl")
    if not cases:
        raise FileNotFoundError(
            "02_behavior/CASES.jsonl missing or empty: 02 stage must complete first "
            "(not_executed_dependency)")
    case_by_id = {c.get("case_id"): c for c in cases}
    cands = _read_jsonl(run_root / "02_behavior/CANDIDATE_INDEX.jsonl")
    candidates_by_case: dict[Any, list[dict]] = defaultdict(list)
    for candidate in cands:
        candidates_by_case[candidate.get("case_id")].append(candidate)

    requests_by_id: dict[str, dict] = {}
    requests_path = run_root / "02_behavior/REQUESTS.jsonl"
    if requests_path.exists():
        requests_by_id = {r.get("request_id"): r for r in _read_jsonl(requests_path)}

    new_rows: list[dict] = []
    evidence_rows: list[dict] = []
    n_candidate_rows = 0
    n_candidate_missing = 0
    n_candidate_unbound = 0
    for line in cands:
        case = case_by_id.get(line.get("case_id")) or {}
        default_song = case.get("song_id")
        request_row = requests_by_id.get(line.get("request_id"))
        ev_path_raw = line.get("evidence_path")
        if request_row is None or not ev_path_raw:
            n_candidate_missing += 1
            continue
        ev_path = Path(ev_path_raw)
        if not ev_path.is_file():
            n_candidate_missing += 1
            continue
        try:
            payload = json.loads(ev_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            n_candidate_missing += 1
            continue
        rows = evidence_rows_from_request(request_row, payload)
        if not rows:
            n_candidate_unbound += 1
            continue
        n_candidate_rows += len(rows)
        scored = score_units(scorer, rows)
        p_bad_by_cid = {
            int(u["canonical_unit_id"]): float(u["p_bad"])
            for u in scored.get("units", [])
            if u.get("canonical_unit_id") is not None
        }
        for row in rows:
            row = dict(row)
            row["case_id"] = line.get("case_id")
            row["variant"] = line.get("variant")
            row["song_id"] = row.get("song_id") or default_song
            if row.get("canonical_unit_id") is not None:
                pb = p_bad_by_cid.get(int(row["canonical_unit_id"]))
                if pb is not None:
                    row["p_bad"] = pb
            evidence_rows.append(row)
            pred = _new_pred(row)
            if pred:
                new_rows.append({
                    "song_id": row.get("song_id") or default_song,
                    "case_id": line.get("case_id"),
                    "variant": line.get("variant"),
                    "canonical_unit_id": row.get("canonical_unit_id"),
                    "start_sec": pred["start_sec"],
                    "end_sec": pred["end_sec"],
                })

    old_rows: list[dict] = []
    shadow_units: dict = {}
    shadow_intervals: dict = {}
    for c in cases:
        sid = c.get("song_id")
        case_id = c.get("case_id")
        for u in c.get("old_units") or []:
            old_rows.append({
                "case_id": case_id,
                "variant": None,
                "canonical_unit_id": u.get("canonical_unit_id"),
                "start_sec": u.get("start_sec"),
                "end_sec": u.get("end_sec"),
            })
            if u.get("canonical_unit_id") is not None:
                shadow_units[(sid, case_id, int(u["canonical_unit_id"]))] = u
        if (sid, case_id) not in shadow_intervals:
            shadow_intervals[(sid, case_id)] = []
        for iv in c.get("detector_shadow", {}).get("unsafe_intervals") or []:
            shadow_intervals[(sid, case_id)].append([float(iv[0]), float(iv[1])])

    gt_rows: list[dict] = []
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in new_rows:
        by_case.setdefault(str(r.get("case_id")), []).append(r)
    for case in cases:
        case_rows = by_case.get(str(case.get("case_id")), [])
        expected = candidates_by_case.get(case.get("case_id"), [])
        request = next((requests_by_id.get(row.get("request_id")) for row in expected
                        if requests_by_id.get(row.get("request_id")) is not None), None)
        gt_rows.extend(pair_gt(
            case_rows, real_gt,
            song_id=case.get("song_id"),
            old_rows=old_rows,
            target_cids=_active_target_ids(request, case),
            expected_variants=expected,
        ))

    no_gt = extract_no_gt_features(
        evidence_rows, {"units": shadow_units, "unsafe_intervals": shadow_intervals})
    no_gt = _ensure_no_gt_target_spine(no_gt, cands, requests_by_id, case_by_id)

    if not cands:
        result_status, status_reason = "blocked", "no_candidates"
    elif n_candidate_missing or n_candidate_unbound:
        result_status, status_reason = "incomplete", "candidate_evidence_incomplete"
    elif not new_rows:
        result_status, status_reason = "blocked", "no_candidate_rows"
    elif not old_rows:
        result_status, status_reason = "incomplete", "missing_old_baseline"
    else:
        result_status, status_reason = "ok", "full_canonical_pairing"

    out = run_root / "03_gate"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "GT_PAIR_METRICS.jsonl").open("w", encoding="utf-8") as f:
        for r in gt_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out / "NO_GT_FEATURES.jsonl").open("w", encoding="utf-8") as f:
        for r in no_gt:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    analysis = analyze(gt_rows, no_gt, out_dir=out)
    analysis_path = out / "ANALYSIS.json"
    if analysis_path.exists():
        with analysis_path.open("r", encoding="utf-8") as fh:
            persisted = json.load(fh)
        persisted["stage_result_status"] = result_status
        persisted["stage_status_reason"] = status_reason
        analysis_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "result_status": result_status,
        "status_reason": status_reason,
        "generated_at_utc": now_utc(),
        "stage": "03_gate",
        "run_root": str(run_root),
        "n_candidates": len(cands),
        "n_candidate_rows": n_candidate_rows,
        "n_candidate_missing": n_candidate_missing,
        "n_candidate_unbound": n_candidate_unbound,
        "n_paired": len(gt_rows),
        "n_no_gt": len(no_gt),
        "n_cases": len(cases),
        "suggestion": analysis["suggestion"],
        "metrics": analysis["metrics"],
        "outputs": {
            "gt_pair_metrics": str(out / "GT_PAIR_METRICS.jsonl"),
            "no_gt_features": str(out / "NO_GT_FEATURES.jsonl"),
            "analysis": str(out / "ANALYSIS.json"),
            "counterexamples": str(out / "COUNTEREXAMPLES.jsonl"),
        },
    }
