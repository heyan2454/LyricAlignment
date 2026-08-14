"""WP3 — E1 multi-realign dynamics screening (shadow-only).

Scope (07 plan §9 / session README): for a frozen detector region we run the
SAME R-U style intervention repeatedly, each iteration's request being built
from the previous iteration *candidate* as its new baseline.  The observable is
the per-iteration trajectory of the target units — does the realign dynamics
recover, form a fixed point, or oscillate/diverge.

Crucially this is **shadow-only**: the candidate from one iteration is fed
forward as the *isolated research state* for building the next request, but is
NEVER written back into the production detector baseline (region.units stays
frozen).  Each step's ``baseline_rows`` is derived locally, and the request's
``identity_context.baseline_digest`` is recomputed over *that step's* baseline so
cache identity is content-addressed per iteration.

Family identity chaining: every chained step (iteration > 0) carries a
``chain_context`` with ALL of ``parent_request_identity / iteration /
recrop_view_id / split_slot_id`` as required by ``build_request_identity``
fail-closed logic.  iter0 carries no parent link.

Baseline construction:
  - iter0  baseline = frozen detector rows: ``region.units`` projected to
    ``(canonical_unit_id, start_sec, end_sec)`` rows (no model forward).
  - iter>0 baseline = the previous step's *candidate* rows over the same
    canonical ids (targets got new times from the executor, fixed context kept
    baseline times).

Request type / family: ``build_family_request`` (v2).  ``family`` defaults to the
task contract ``"R-U"``; ``context_neighbors`` selects how many units either side
of the target span join the local window; ``audio_margin_sec`` pads the audio
crop around the target span.

If updating a baseline makes the R-U construction invalid (non-monotonic /
out-of-range times), the step is recorded as ``not_constructible`` with a reason
instead of silently no-op'ing forward (07 contract: no silent empty rotation).

Trajectory schema: ``multi_realign_dynamics_v1`` — see ``extract_trajectory``.

Metrics follow 02 E1 §126-146 first_hit_iterations, monotonic-improvement,
improve-then-regress, fixed-point, oscillation/divergence.  Target displacement
and fixed-context displacement are kept SEPARATE (04 §7).
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

from .request_families import build_family_request, build_request_identity


TRAJECTORY_SCHEMA_VERSION = "multi_realign_dynamics_v1"


# --------------------------------------------------------------------------- #
#  baseline digests / row projection
# --------------------------------------------------------------------------- #
def baseline_rows_from_units(units: Sequence[Mapping[str, Any]],
                             canonical_ids: Sequence[int]) -> list[dict]:
    """Project ``units`` (detector/region/step units) into canonical baseline rows."""
    by_id = {int(u.get("canonical_unit_id")): u for u in units}
    rows = []
    for cid in canonical_ids:
        u = by_id.get(int(cid))
        if u is None:
            raise ValueError(f"baseline unit {cid} not present in units")
        rows.append({"canonical_unit_id": int(cid),
                     "start_sec": float(u["start_sec"]), "end_sec": float(u["end_sec"])})
    return rows


def _baseline_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    import hashlib
    ordered = sorted(rows, key=lambda r: int(r["canonical_unit_id"]))
    raw = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                  for r in ordered).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_rows(rows: Sequence[Mapping[str, Any]]) -> str | None:
    """Return a not_constructible reason if chained baseline rows are invalid
    (any end < start / negative times, or a non-monotonic start sequence across
    canonical order).  R-U's construction does not itself validate monotonicity,
    so build_chain guards the re-request here instead of silently rotating."""
    ordered = sorted(rows, key=lambda r: int(r["canonical_unit_id"]))
    prev_end: float | None = None
    for r in ordered:
        s = float(r["start_sec"])
        e = float(r["end_sec"])
        if s < 0.0 or e < 0.0:
            return "non_negative_time_violation"
        if e < s:
            return "negative_duration"
        if prev_end is not None and s < prev_end:
            return "non_monotonic_candidate_timeline"
        prev_end = e
    return None


def rows_to_units(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Turn a step's baseline/candidate rows back into ``units`` records that
    ``build_family_request`` expects ({canonical_unit_id, text, start_sec,
    end_sec}).  Text is carried through only when present on the row; otherwise
    it is filled by the caller from the region (see build_chain)."""
    out = []
    for r in rows:
        text = r.get("text")
        unit = {"canonical_unit_id": int(r["canonical_unit_id"]),
                "start_sec": float(r["start_sec"]), "end_sec": float(r["end_sec"])}
        if text is not None:
            unit["text"] = str(text)
        out.append(unit)
    return out


# --------------------------------------------------------------------------- #
#  chain construction
# --------------------------------------------------------------------------- #
def build_chain(base_region: Mapping[str, Any], target_unit_ids: Sequence[int],
                family: str = "R-U", iterations: Iterable[int] = (1, 2, 3, 5),
                context_neighbors: int = 1, audio_margin_sec: float = 0.5,
                identity_context: Mapping[str, Any] | None = None,
                executor=None) -> list[dict]:
    """Build one iteration step per requested iteration number.

    When ``executor`` is provided, each step is run immediately and the next
    step's baseline is the *actual* previous candidate (the true multi-realign
    dynamics).  Without an executor only the first (iter0) step can be
    constructed; later steps are marked ``not_constructible``
    (``previous_step_not_constructible``) rather than silently empty.

    Returns a list of steps in iteration order, each step::

        {
          "iteration": int,
          "parent_request_identity": str | None,
          "baseline_rows": [ {canonical_unit_id,start_sec,end_sec}, ... ],
          "candidate_rows": [ {canonical_unit_id,start_sec,end_sec}, ... ],
          "request": <v2 request dict or not_constructible stub>,
          "constructible": bool,
          "status": "ok" | "failed" | None,
          "not_constructible_reason": str | None,
        }

    The ``request`` is produced by ``build_family_request`` with the correct
    ``chain_context`` (iter0 has no parent; iter>0 carries
    parent_request_identity/iteration/recrop_view_id/split_slot_id) and with
    ``identity_context.baseline_digest`` recomputed over *this step's* baseline.
    Base identity context is copied from ``identity_context`` (the caller's
    fully frozen per-region context) and the 8 required identity keys are
    verified before a request_identity is expected.
    """
    iterations_t = sorted(int(i) for i in iterations)
    if iterations_t != list(iterations_t):
        iterations_t = [int(i) for i in iterations]
    if not iterations_t:
        raise ValueError("iterations must be non-empty")
    if iterations_t[0] != 0 and 0 not in iterations_t:
        iterations_t = [0] + iterations_t

    song_id = str(base_region.get("song_id") or "")
    region_id = str(base_region.get("region_id") or "")
    audio_path = str(base_region.get("audio_path") or f"{song_id}.wav")
    unit_texts = {int(u.get("canonical_unit_id")): str(u.get("text") or "")
                  for u in (base_region.get("units") or ())}
    targets = [int(x) for x in target_unit_ids]

    # --- iter0 baseline: frozen detector rows (region.units) ---
    frozen_units = base_region.get("units") or ()
    full_ids = [int(u.get("canonical_unit_id")) for u in frozen_units]
    iter0_rows = baseline_rows_from_units(frozen_units, full_ids)

    base_ctx = dict(identity_context or {})

    steps: list[dict] = []
    prev_request: dict | None = None
    prev_candidate_rows: list[dict] | None = None

    def _execute(v2: dict) -> tuple[list[dict], str | None]:
        """Run one step's v2 request through the executor (if provided) and map
        candidate rows back to canonical ids.  Returns ([], reason) when no
        executor is available or the forward fails."""
        if executor is None:
            return [], "no_executor"
        audio = str(v2.get("audio_path") or f"{v2.get('song_id')}.wav")
        # R-U / R-A / R-B are non-sparse; derive active target LOCAL indices so
        # the smoke executor knows which rows to nudge (else candidate==baseline).
        v2_run = dict(v2)
        if v2_run.get("active_slot_indices") is None:
            ids = [int(x) for x in v2.get("canonical_ids") or ()]
            c2l = {int(k): int(v) for k, v in (v2.get("canonical_to_local") or {}).items()}
            if ids and len(c2l) != len(ids):
                c2l = {cid: i for i, cid in enumerate(ids)}
            targets = [int(x) for x in v2.get("target_unit_ids") or ()]
            v2_run["active_slot_indices"] = tuple(c2l[t] for t in targets if t in c2l)
        try:
            req = _to_v7_request(v2_run, audio)
            req.validate()
            attempt = executor(req)
            return _candidate_rows_from_v2(attempt, v2)
        except Exception as exc:  # noqa: BLE001
            return [], f"forward:{exc}"

    for it in iterations_t:
        step: dict[str, Any] = {"iteration": it, "constructible": True,
                                "not_constructible_reason": None,
                                "candidate_rows": [], "status": None, "error": None}
        if it == 0:
            step["parent_request_identity"] = None
            baseline_rows = list(iter0_rows)
        else:
            step["parent_request_identity"] = prev_request.get("request_identity") if prev_request else None
            if prev_candidate_rows is None:
                # Previous step did not run (not_constructible / failed / no executor):
                # the chain stops — never silently rotate on a dead baseline.
                step["constructible"] = False
                step["not_constructible_reason"] = "previous_step_not_constructible"
                step["baseline_rows"] = []
                step["request"] = None
                steps.append(step)
                break
            baseline_rows = list(prev_candidate_rows)
            # Shadow-only re-request guard: if the previous candidate makes the
            # next R-U window invalid (non-monotonic / out of range), record
            # not_constructible instead of silently feeding a broken baseline.
            invalid = validate_rows(baseline_rows)
            if invalid:
                step["constructible"] = False
                step["not_constructible_reason"] = invalid
                step["baseline_rows"] = []
                step["request"] = None
                steps.append(step)
                prev_candidate_rows = None
                prev_request = None
                break
        step["baseline_rows"] = baseline_rows

        # Rebuild the units for THIS step's request from its baseline rows.
        refactored = rows_to_units(baseline_rows)
        for unit in refactored:
            cid = int(unit["canonical_unit_id"])
            unit.setdefault("text", unit_texts.get(cid, ""))
        step_units = refactored

        # Per-step identity context: base + this step's baseline digest + chain.
        ctx = dict(base_ctx)
        ctx["baseline_digest"] = _baseline_digest(baseline_rows)
        chain_ctx = {} if it == 0 else {
            "parent_request_identity": step["parent_request_identity"],
            "iteration": it,
            # recrop/split are NOT used by this single-view, no-split chain; but
            # build_request_identity's fail-closed chained check requires all four
            # to be truthy, so use explicit "none" sentinels (content-addressed).
            "recrop_view_id": "none",
            "split_slot_id": "none",
        }

        request = build_family_request(
            family=family, song_id=song_id, region_id=region_id,
            audio_path=audio_path, units=step_units, target_unit_ids=targets,
            identity_context={**ctx, **chain_ctx},
            audio_margin_sec=audio_margin_sec, context_neighbors=context_neighbors,
        )
        step["request"] = request

        # Verify required identity keys so a chained request is never silently
        # missing request_identity (fail-closed via build_request_identity too).
        if request.get("family") == "R-NULL" or request.get("status") == "not_constructible":
            step["constructible"] = False
            step["not_constructible_reason"] = request.get("reason") or "null_or_not_constructible"
        elif not request.get("request_identity"):
            required = ("audio_sha256", "baseline_digest", "model_identity",
                        "checkpoint_identity", "decoder_identity", "mapping_schema",
                        "code_identity", "text_adapter_identity")
            missing = [k for k in required if not ctx.get(k)]
            step["constructible"] = False
            step["not_constructible_reason"] = ("missing_identity_context:" + ",".join(missing)
                                                if missing else "request_identity_unassignable")
        steps.append(step)

        if step["constructible"]:
            cand_rows, error = _execute(request)
            step["candidate_rows"] = cand_rows
            if error:
                step["status"] = "failed"
                step["error"] = error
                step["constructible"] = False
                step["not_constructible_reason"] = error
                prev_candidate_rows = None
                prev_request = None
                break
            step["status"] = "ok"
            prev_request = request
            prev_candidate_rows = cand_rows
        else:
            prev_candidate_rows = None
            prev_request = None
            break
    return steps


# --------------------------------------------------------------------------- #
#  smoke execution
# --------------------------------------------------------------------------- #
def make_smoke_executor():
    """Deterministic CPU executor mirroring run_forward_real's fake for v2
    requests.  Returns one row per text unit; active targets nudged +0.1s while
    context units stay frozen.  Times are offset by request.audio_start_sec (as
    the real executor does) so absolute-time logic is exercised."""
    from lyricalign.research_v7.attempt import AlignmentAttempt

    def ex(req):
        n = len(req.text_units)
        offset = req.audio_start_sec
        active = set(req.active_slot_indices or ())
        rows = []
        for i in range(n):
            delta = 0.10 if i in active else 0.0
            start = offset + i * 0.5 + delta
            end = start + 0.4
            rows.append({
                "global_character_index": i,
                "raw_global_start_sec": start, "raw_global_end_sec": end,
                "fixed_global_start_sec": start, "fixed_global_end_sec": end,
                "start_sec": start, "end_sec": end,
                "decoder_kind": "official",
            })
        return AlignmentAttempt(
            request=req, attempt_id=f"F-{req.item_id}-{req.mutation_type}",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            cursor_after=float(n) * 0.5 + offset, committed=True, status="ok",
        )

    return ex


def _to_v7_request(v2: dict, audio_path: str):
    from lyricalign.research_v7.requests import AlignmentRequest
    text_units = tuple(str(u) for u in v2.get("text_units") or ())
    ids = [int(x) for x in v2.get("canonical_ids") or ()]
    local_to_canonical = [int(x) for x in v2.get("local_to_canonical") or ids]
    a0, a1 = (float(x) for x in (v2.get("candidate_audio_range_sec") or [0.0, 0.0]))
    family = str(v2.get("family") or "R-U")
    c2l = {int(k): int(v) for k, v in (v2.get("canonical_to_local") or {}).items()}
    if ids and len(c2l) != len(ids):
        c2l = {cid: i for i, cid in enumerate(ids)}
    return AlignmentRequest(
        request_id=str(v2.get("request_id") or ""),
        item_id=str(v2.get("region_id") or ""),
        parent_request_id=None,
        audio_source=audio_path,
        audio_start_sec=a0,
        audio_end_sec=a1,
        text_source="unit_realign_v2",
        text_start_index=0,
        text_end_index=len(text_units),
        text_units=text_units,
        timestamp_slot_indices=tuple(int(x) for x in v2["timestamp_slot_indices"]) if v2.get("timestamp_slot_indices") is not None else None,
        workflow_mode="unit_realign_v2",
        mutation_type=family,
        mutation_parameters={"request_identity": v2.get("request_identity")},
        model_id=str(v2.get("model_identity") or "unknown"),
        checkpoint_id=str(v2.get("checkpoint_identity") or "unknown"),
        input_variant=f"unit_realign_{family}",
        active_slot_indices=tuple(int(x) for x in v2["active_slot_indices"]) if v2.get("active_slot_indices") is not None else None,
        fixed_slot_rows=v2.get("fixed_slot_rows") or None,
        slot_constraint_schema=v2.get("slot_constraint_schema"),
        canonical_text_start=min(ids) if ids else None,
        canonical_text_end=(max(ids) + 1) if ids else None,
        canonical_to_local=c2l or None,
        canonical_ids=ids or None,
        metadata={"song_id": str(v2.get("song_id") or ""), "region_id": str(v2.get("region_id") or ""),
                  "family": family, "stratum": v2.get("stratum")},
    )


def _candidate_rows_from_v2(attempt, request_v2: dict) -> tuple[list[dict], str | None]:
    """Map executor rows back to canonical_unit_id using the v2 request's
    local_to_canonical (index-space mapping), mirroring run_forward_real."""
    if getattr(attempt, "status", "") != "ok":
        return [], getattr(attempt, "error", None) or f"status={getattr(attempt, 'status', 'unknown')}"
    local_to_canonical = [int(x) for x in (request_v2.get("local_to_canonical")
                                           or request_v2.get("canonical_ids") or ())]
    rows = (attempt.decoder_outputs or {}).get("official", {}).get("rows") or []
    out = []
    for row in rows:
        gci = row.get("global_character_index")
        if not isinstance(gci, int) or gci < 0 or gci >= len(local_to_canonical):
            continue
        start = row.get("fixed_global_start_sec", row.get("start_sec"))
        end = row.get("fixed_global_end_sec", row.get("end_sec"))
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            continue
        out.append({"canonical_unit_id": int(local_to_canonical[gci]),
                    "start_sec": float(start), "end_sec": float(end)})
    out.sort(key=lambda r: int(r["canonical_unit_id"]))
    return out, None


def run_chain_smoke(base_region: Mapping[str, Any], target_unit_ids: Sequence[int],
                    iterations: Iterable[int] = (1, 2, 3, 5),
                    family: str = "R-U", context_neighbors: int = 1,
                    audio_margin_sec: float = 0.5,
                    identity_context: Mapping[str, Any] | None = None,
                    executor=None) -> dict:
    """Run the full chain through the smoke executor (CPU) and return a dict
    with both step details and the extracted trajectory."""
    ex = executor if executor is not None else make_smoke_executor()
    steps = build_chain(base_region, target_unit_ids, family=family,
                        iterations=iterations, context_neighbors=context_neighbors,
                        audio_margin_sec=audio_margin_sec,
                        identity_context=identity_context, executor=ex)
    results = []
    for step in steps:
        status = step.get("status")
        if status is None:
            status = "not_constructible" if not step["constructible"] else "executed"
        results.append({
            "iteration": step["iteration"],
            "request_identity": (step.get("request") or {}).get("request_identity"),
            "parent_request_identity": step.get("parent_request_identity"),
            "constructible": step["constructible"],
            "not_constructible_reason": step.get("not_constructible_reason"),
            "status": status,
            "error": step.get("error"),
            "baseline_rows": step["baseline_rows"],
            "candidate_rows": step["candidate_rows"],
            "request": step.get("request"),
        })
    return {"schema": "multi_realign_chain_run_v1", "steps": results,
            "trajectory": extract_trajectory(results, region=base_region)}


# --------------------------------------------------------------------------- #
#  trajectory extraction
# --------------------------------------------------------------------------- #
def _unit_time(rows: Sequence[Mapping[str, Any]], cid: int) -> tuple[float, float] | None:
    for r in rows:
        if int(r.get("canonical_unit_id")) == cid:
            return float(r["start_sec"]), float(r["end_sec"])
    return None


def _initial_target_error_ms(request, cid: int, target_ids: Sequence[int]) -> float:
    """Reserved: per-unit reference error estimate (unused placeholder)."""
    return 0.0


def classify_unit_dynamics(
    signed_errors_ms: Sequence[float], signed_deltas_ms: Sequence[float],
) -> dict[str, Any]:
    """Classify one unit's recovery dynamics from its per-iteration series.

    Pure, testable helper (O-review P0-1).  Uses the SIGNED error series for
    direction-flip (oscillation) detection and the TRUE per-iteration position
    for fixed-point (candidate stops moving), so pure monotonic improvement is
    never misreported as oscillation.

    Returns:
        monotonic_improvement_ratio, improve_then_regress, fixed_point_iteration,
        oscillation_or_divergence
    """
    abs_series = [abs(float(e)) for e in signed_errors_ms]
    signed_series = [float(e) for e in signed_errors_ms]
    deltas = [float(d) for d in signed_deltas_ms]

    mono = 0.0
    if len(abs_series) >= 2:
        mono = sum(1 for a, b in zip(abs_series, abs_series[1:]) if b <= a) / (len(abs_series) - 1)

    improve_then_regress = False
    if len(abs_series) >= 3:
        m = abs_series.index(min(abs_series))
        improve_then_regress = 0 < m < len(abs_series) - 1

    fixed_point = bool(len(deltas) >= 2 and all(abs(d) <= 1.0 for d in deltas[-2:]))

    # oscillation: the SIGNED error direction FLIPS between steps (a + then a -
    # change), never a repeated same direction.  Pure monotonic series (one
    # direction, whether improving or worsening) are therefore not oscillation;
    # divergence (strictly growing in one direction) is reported separately.
    signs = []
    for a, b in zip(signed_series, signed_series[1:]):
        d = b - a
        if abs(d) > 1.0:
            signs.append(1 if d > 0 else -1)
    osc = any(s != p for s, p in zip(signs, signs[1:]))
    div = bool(abs_series and signs and len(set(signs)) == 1 and signs[0] > 0
               and abs_series[-1] > min(abs_series) + 2.0)
    osc_div = osc or div

    return {
        "monotonic_improvement_ratio": round(mono, 4),
        "improve_then_regress": improve_then_regress,
        "fixed_point_iteration": fixed_point,
        "oscillation_or_divergence": osc_div,
    }


def extract_trajectory(steps_results: Sequence[Mapping[str, Any]],
                       region: Mapping[str, Any] | None = None) -> list[dict]:
    """Turn a chain's step results into ``multi_realign_dynamics_v1`` rows.

    Returns a list of per-unit rows (plus per-region aggregate rows flagged by
    ``row_kind == "region"``).  The per-unit rows give, for every constructible
    step: request_identity, iteration, canonical_unit_id, initial_error_ms
    (target start-time error of the step's baseline vs the *very first* frozen
    detector baseline — shadow-baseline drift), error_ms (this step's candidate
    start drift vs the same frozen iter0 time), best_error_ms, and
    delta_to_baseline_ms (candidate vs this step's baseline).
    """
    region_id = (region or {}).get("region_id", "?")
    song_id = (region or {}).get("song_id", "?")

    steps = [s for s in steps_results if s.get("request")]
    if not steps:
        return []
    target_ids = [int(x) for x in (steps[0]["request"].get("target_unit_ids")
                                   or steps[0]["request"].get("active_target_unit_ids") or ())]
    all_ids = [int(x) for x in (steps[0]["request"].get("canonical_ids") or ())]

    iter0_baseline = next((s["baseline_rows"] for s in steps if s["iteration"] == 0),
                          steps[0]["baseline_rows"])
    id0_times = {}
    for r in iter0_baseline:
        cid = int(r["canonical_unit_id"])
        id0_times[cid] = (float(r["start_sec"]), float(r["end_sec"]))

    per_unit: list[dict] = []
    prev_baseline_by_id: dict[int, tuple[float, float]] = {}
    target_prev = {}
    for step in steps:
        it = step["iteration"]
        rid = step.get("request_identity")
        baseline = step["baseline_rows"]
        cand = step["candidate_rows"]
        if not step.get("constructible"):
            continue
        if it == 0:
            prev_baseline_by_id = {cid: (float(r["start_sec"]), float(r["end_sec"]))
                                   for r in baseline}
        for r in cand:
            cid = int(r["canonical_unit_id"])
            if cid not in all_ids:
                continue
            t0 = id0_times.get(cid, (float(r["start_sec"]), float(r["end_sec"])))
            cand_s = float(r["start_sec"])
            blt = prev_baseline_by_id.get(cid)
            baseline_s = blt[0] if blt else cand_s
            err_ms = (cand_s - t0[0]) * 1000.0
            init_err_ms = (baseline_s - t0[0]) * 1000.0
            delta_ms = (cand_s - baseline_s) * 1000.0
            row = {
                "row_kind": "unit",
                "schema_version": TRAJECTORY_SCHEMA_VERSION,
                "song_id": song_id, "region_id": region_id,
                "request_identity": rid, "iteration": it,
                "canonical_unit_id": cid,
                "initial_error_ms": round(init_err_ms, 4),
                "error_ms": round(err_ms, 4),
                "best_error_ms": round(err_ms, 4),  # filled with cross-iteration min below
                "delta_to_baseline_ms": round(delta_ms, 4),
            }
            per_unit.append(row)
        prev_baseline_by_id = {int(r["canonical_unit_id"]): (float(r["start_sec"]), float(r["end_sec"]))
                               for r in cand}

    if not per_unit:
        return []

    # Cross-iteration per-unit best + first-hit + dynamics (P1-1 / N-review):
    # group per unit's error series to compute best_error_ms (true min over
    # iterations) and first_hit_ms_iteration for the 100/200/500/1000ms buckets,
    # plus per-unit monotonic / improve-then-regress / fixed-point / oscillation.
    _unit_errs: dict[int, list[float]] = {}
    for row in per_unit:
        _unit_errs.setdefault(row["canonical_unit_id"], []).append(abs(float(row["error_ms"])))
    for row in per_unit:
        cid = row["canonical_unit_id"]
        series = sorted((r for r in per_unit if r["canonical_unit_id"] == cid),
                        key=lambda r: int(r["iteration"]))
        best = min(float(r["error_ms"]) for r in series)
        row["best_error_ms"] = round(best, 4)
        # first-hit iteration per tolerance bucket: earliest iteration where |err|<=bucket.
        for bucket in (100, 200, 500, 1000):
            hit = next((int(r["iteration"]) for r in series
                        if abs(float(r["error_ms"])) <= float(bucket)), None)
            row[f"first_hit_ms_iteration_{bucket}"] = hit
        # per-unit dynamics over the error series (O/N review P0/P1 fixes) — see
        # classify_unit_dynamics for the signed-vs-abs semantics.
        signed_series = [float(r["error_ms"]) for r in series]
        deltas = [float(r["delta_to_baseline_ms"]) for r in series]
        dyn = classify_unit_dynamics(signed_series, deltas)
        row.update(dyn)

    # ---- per-region aggregate (derived from the enriched per-unit rows) ----
    by_target: dict[int, list[dict]] = {cid: [] for cid in target_ids}
    for row in per_unit:
        if row["canonical_unit_id"] in by_target:
            by_target[row["canonical_unit_id"]].append(row)
    # best absolute error per target unit over the chain (best_error_ms is already
    # the per-unit min); recovered if the unit's best error <= 1ms (~= strict hit).
    target_best = {cid: min(abs(float(r["error_ms"])) for r in rows) for cid, rows in by_target.items() if rows}
    recovered = {cid: (best <= 1.0) for cid, best in target_best.items()}
    all_recovered = bool(target_best) and all(recovered.values())
    pct = 100.0 * sum(1 for cid in target_ids if recovered.get(cid, False)) / max(1, len(target_ids))

    # worst-case error ever observed on a target (for catastrophic detection).
    max_target_err = max((abs(float(r["error_ms"])) for r in per_unit
                          if r["canonical_unit_id"] in target_ids), default=0.0)
    # catastrophic: a target ever regresses well beyond its initial error.
    init_by_target = {}
    for cid, rows in by_target.items():
        if rows:
            init_by_target[cid] = min(abs(float(r["initial_error_ms"])) for r in rows)
    catastrophic_regression = bool(
        target_best and any(
            max_target_err > init_by_target.get(cid, 0.0) + 1000.0 for cid in target_best
        )
    )

    # region-level monotonic ratio / improve-then-regress / fixed-point / oscillation:
    # reuse the per-unit booleans but report them at region granularity too.
    mono_vals = [float(r["monotonic_improvement_ratio"]) for r in per_unit
                 if r["canonical_unit_id"] in target_ids and r.get("monotonic_improvement_ratio") is not None]
    monotonic_ratio = (sum(mono_vals) / len(mono_vals)) if mono_vals else 0.0
    improve_then_regress = any(r["improve_then_regress"] for r in per_unit if r["canonical_unit_id"] in target_ids)
    fixed_point_iteration = any(r["fixed_point_iteration"] for r in per_unit if r["canonical_unit_id"] in target_ids)
    osc_div = any(r["oscillation_or_divergence"] for r in per_unit if r["canonical_unit_id"] in target_ids)

    # displacement: motion of target/fixed-context rows vs frozen iter0.
    target_disp = 0.0
    fixed_disp = 0.0
    last_cand = next((s["candidate_rows"] for s in reversed(steps) if s.get("constructible")), [])
    for r in last_cand:
        cid = int(r["canonical_unit_id"])
        t0 = id0_times.get(cid)
        if t0 is None:
            continue
        d = (float(r["start_sec"]) - t0[0]) * 1000.0
        if cid in target_ids:
            target_disp += abs(d)
        else:
            fixed_disp += abs(d)

    n_ok = sum(1 for s in steps if s.get("status") == "ok")
    # collateral harm: any fixed-context unit displaced beyond a small margin by
    # the recovery chain (02 §139 / 07 §3.2 collateral_harm).
    collateral_harm = fixed_disp > 1.0
    aggregate = {
        "row_kind": "region",
        "schema_version": TRAJECTORY_SCHEMA_VERSION,
        "song_id": song_id, "region_id": region_id,
        "request_identity": None, "iteration": None,
        "canonical_unit_id": None,
        "initial_error_ms": None, "error_ms": None, "best_error_ms": None,
        "delta_to_baseline_ms": None,
        "all_target_recovered": all_recovered,
        "case_pct_recovered": round(pct, 4),
        "monotonic_improvement_ratio": round(monotonic_ratio, 4),
        "monotonic_improvement": monotonic_ratio >= 0.5,
        "improve_then_regress": improve_then_regress,
        "fixed_point_iteration": fixed_point_iteration,
        "oscillation_or_divergence": osc_div,
        "catastrophic_regression": catastrophic_regression,
        "collateral_harm": collateral_harm,
        "target_displacement_ms": round(target_disp, 4),
        "fixed_context_displacement_ms": round(fixed_disp, 4),
        "forward_count": n_ok,
        "wall_time_ms": 0.0,
    }
    return per_unit + [aggregate]

