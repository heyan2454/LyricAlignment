"""E4 — R-U coarse proposal -> re-crop -> bounded sparse/fixed refinement (07 §9 WP6).

The fourth unit-realign family is a *composition* of two stages:

  Stage A (coarse):      an R-U forward over the unsafe target span produces a
                         "coarse proposal" (its candidate positions).  Nothing is
                         written back to the production baseline (shadow-only).
  Stage B (fine/refine): the audio crop is *re-centered* on the coarse proposal,
                         the trusted fixed context is retained as fixed slots, and
                         only the target (+ an optional narrow neighborhood) is
                         left active under a sparse/fixed refinement.  If the
                         proposal would collide with / invalidate the fixed context
                         geometry, the stage fails closed (``not_constructible``).

The whole composition is delivered under a single family label
``FOURTH_FAMILY = "R-CF"``.  Every evidence payload produced here carries that
family (via ``mutation_parameters.proposal_method``), so
``render_current_4way.py --fourth-family R-CF`` can index the fourth track by
family (07 §9 / 02 E4 §272-326).

Both stages are chained in identity space exactly as ``build_request_identity``
demands: stage A is the root (``parent_request_identity=None``,
``iteration=0``, ``recrop_view_id="base"``) and stage B carries
``parent_request_identity`` = stage-A identity, ``iteration=1`` and a distinct
re-center ``recrop_view_id``, plus ``split_slot_id="R-CF"`` on both.  Because
``build_request_identity`` content-addresses the whole ``chain_context``, the two
stages can never collide on ``request_identity`` (WP1 / 07 §5).

GT firewall: there is no GT path in this module or anything it calls.  All
recovery references are shadow baseline (frozen detector) positions; the
no-GT safety-signals metric is reported as a schema-consistent placeholder with
no hidden/TT-probe posterior signal.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .multi_iteration import _baseline_digest, baseline_rows_from_units, validate_rows
from .request_families import build_family_request, build_request_identity
from .split_variants import (
    COARSE_1000_MS,
    COARSE_500_MS,
    CONTEXT_EPS_MS,
    STRICT_100_MS,
    STRICT_200_MS,
    _unit_rows,
)

FOURTH_FAMILY = "R-CF"
COARSE_FINE_SCHEMA = "coarse_fine_v1"

# recrop: how wide (in units) the re-centered local crop window is kept on each
# side of the proposal target span.  stage-B active neighborhood default = target
# only (context fully fixed).
STAGE_A_CONTEXT_NEIGHBORS = 1
STAGE_B_CONTEXT_NEIGHBORS = 2
STAGE_B_ACTIVE_NEIGHBORS = 0  # 0 => only targets active in the sparse refinement

# no-GT safety / structural regression tolerance (ms).
CATASTROPHIC_MS = 500.0


# --------------------------------------------------------------------------- #
#  identity context helpers
# --------------------------------------------------------------------------- #
def _default_identity(region: Mapping[str, Any], *, smoke: bool) -> dict[str, Any]:
    """Fill the eight frozen identity keys the request identity relies on, using
    region-provided values when present and smoke_dummy otherwise."""
    ctx: dict[str, Any] = {}
    if smoke:
        ctx.setdefault("audio_sha256", "smoke_dummy_audio")
        ctx.setdefault("model_identity", "qwen-fa-smoke")
        ctx.setdefault("checkpoint_identity", "smoke")
        ctx.setdefault("decoder_identity", "official")
        ctx.setdefault("mapping_schema", "unit_realign_local_v2")
        ctx.setdefault("code_identity", "coarse_fine-smoke")
        ctx.setdefault("text_adapter_identity", "c3-smoke")
    else:
        ctx.setdefault("audio_sha256", region.get("audio_sha256"))
        ctx.setdefault("mapping_schema", "unit_realign_local_v2")
        ctx.setdefault("code_identity", "coarse_fine")
        ctx.setdefault("text_adapter_identity", "c3")
    # baseline digest over the frozen region units (shadow recovery reference).
    region_rows = baseline_rows_from_units(
        _unit_rows(region), [int(u["canonical_unit_id"]) for u in _unit_rows(region)])
    ctx.setdefault("baseline_digest", _baseline_digest(region_rows))
    return ctx


def _rekey_request(request: dict[str, Any], *, family: str,
                   chain_context: Mapping[str, Any]) -> dict[str, Any]:
    """Re-label a geometrically-built request onto a family and chained identity
    context, then recompute ``request_identity`` through the content-addressed
    builder.  ``chain_context`` carries the split/iteration/recrop/parent dims so
    the two coarse/fine stages never collide on identity."""
    out = dict(request)
    out["family"] = family
    out["requested_family"] = family
    out["request_id"] = f"{out.get('song_id')}:{out.get('region_id')}:{family}"
    chain = dict(chain_context)
    out["chain_context"] = chain
    out.update({k: v for k, v in chain.items() if v is not None})
    try:
        out["request_identity"] = build_request_identity(out)
    except ValueError:
        out["request_identity"] = None
    return out


# --------------------------------------------------------------------------- #
#  stage A — coarse R-U proposal (root, iteration 0)
# --------------------------------------------------------------------------- #
def _identity_ctx_for(coarse_identity: str | None, *, split_slot_id: str,
                      iteration: int, recrop_view_id: str) -> dict[str, Any]:
    ctx = {"split_slot_id": split_slot_id, "iteration": iteration,
           "recrop_view_id": recrop_view_id, "parent_request_identity": coarse_identity}
    return ctx


def build_coarse_stage(region: Mapping[str, Any], target_unit_ids: Sequence[int],
                       *, identity_context: Mapping[str, Any] | None = None,
                       context_neighbors: int = STAGE_A_CONTEXT_NEIGHBORS,
                       audio_margin_sec: float = 0.5) -> dict[str, Any]:
    """Stage A: build the coarse R-U proposal request (geometrically R-U, labelled
    R-CF for the composition identity).  Returns the v2 request dict."""
    song_id = str(region.get("song_id") or "")
    region_id = str(region.get("region_id") or "")
    audio_path = str(region.get("audio_path") or f"{song_id}.wav")
    targets = [int(x) for x in target_unit_ids]
    base = dict(identity_context or {})
    chain = dict(base)
    chain.update(_identity_ctx_for(None, split_slot_id="R-CF", iteration=0,
                                   recrop_view_id="base"))
    req = build_family_request(
        family="R-U", song_id=song_id, region_id=region_id, audio_path=audio_path,
        units=_unit_rows(region), target_unit_ids=targets,
        identity_context={**base, **chain}, audio_margin_sec=audio_margin_sec,
        context_neighbors=context_neighbors,
    )
    if req.get("family") == "R-NULL":
        return req  # no constructible coarse target
    return _rekey_request(req, family=FOURTH_FAMILY, chain_context=chain)


# --------------------------------------------------------------------------- #
#  stage B — re-center + sparse/fixed refinement (iteration 1)
# --------------------------------------------------------------------------- #
def _recrop_context_ids(region: Mapping[str, Any], target_unit_ids: Sequence[int],
                        proposal_rows: Sequence[Mapping[str, Any]],
                        neighbors: int) -> tuple[list[int], Sequence[Mapping[str, Any]]]:
    """Choose the re-centered local crop unit set around the coarse proposal
    center, clipped to the region.  Returns (recrop canonical ids, recrop units)."""
    ids = [int(u["canonical_unit_id"]) for u in _unit_rows(region)]
    idx_of = {cid: i for i, cid in enumerate(ids)}
    units = _unit_rows(region)
    targets = [int(x) for x in target_unit_ids]
    # center on the mean of the proposal target spans.
    proposal_by_id = {int(r["canonical_unit_id"]): r for r in (proposal_rows or ())}
    centers = [float(proposal_by_id[t]["start_sec"]) for t in targets if t in proposal_by_id]
    if not centers:
        return ids, units  # fall back to full region re-crop
    center = sum(centers) / len(centers)
    # distance (in units) of every region unit from the proposal center.
    dist = [(i, abs(float(u["start_sec"]) - center)) for i, u in enumerate(units)]
    dist.sort(key=lambda kv: (kv[1], kv[0]))
    # always keep the targets, then nearest neighbors until (neighbors per side)
    # is reached.
    keep = {idx_of[t] for t in targets if t in idx_of}
    needed = max(0, neighbors * 2)
    for i, _ in dist:
        if len(keep) >= needed:
            break
        keep.add(i)
    keep_indices = sorted(keep)
    recrop_ids = [ids[i] for i in keep_indices]
    return recrop_ids, [units[i] for i in keep_indices]


def build_refinement_stage(region: Mapping[str, Any], target_unit_ids: Sequence[int],
                           *, coarse_identity: str, proposal_rows: Sequence[Mapping[str, Any]],
                           identity_context: Mapping[str, Any] | None = None,
                           context_neighbors: int = STAGE_B_CONTEXT_NEIGHBORS,
                           active_neighbors: int = STAGE_B_ACTIVE_NEIGHBORS,
                           audio_margin_sec: float = 0.5) -> dict[str, Any]:
    """Stage B: build the sparse/fixed refinement request on a re-centered crop
    centered at the coarse proposal.  Returns the v2 request dict (or an
    R-NULL not_constructible stub when the proposal/fixed geometry is illegal).
    """
    song_id = str(region.get("song_id") or "")
    region_id = str(region.get("region_id") or "")
    audio_path = str(region.get("audio_path") or f"{song_id}.wav")
    targets = [int(x) for x in target_unit_ids]

    recrop_ids, recrop_units = _recrop_context_ids(
        region, targets, proposal_rows, neighbors=context_neighbors)

    local = {cid: i for i, cid in enumerate(recrop_ids)}
    active_local = [local[cid] for cid in targets]
    extra_active: list[int] = []
    # "necessary neighborhood" may be left active when configured.
    if active_neighbors > 0:
        all_idx = list(range(len(recrop_ids)))
        for t in targets:
            i = local[t]
            for off in range(1, active_neighbors + 1):
                for cand in (i - off, i + off):
                    if 0 <= cand < len(all_idx) and recrop_ids[cand] not in targets:
                        extra_active.append(cand)
        extra_active = sorted(set(extra_active))
    active_all = sorted(set(active_local) | set(extra_active))
    fixed_local = [i for i in range(len(recrop_ids)) if i not in set(active_all)]

    fixed_rows = [{"local_index": i, "canonical_unit_id": recrop_ids[i],
                   "fixed_global_start_sec": float(recrop_units[local[recrop_ids[i]]]["start_sec"]),
                   "fixed_global_end_sec": float(recrop_units[local[recrop_ids[i]]]["end_sec"])}
                  for i in fixed_local]

    # fail closed: fixed context must be a valid monotonic, non-overlapping set.
    fixed_ordered = sorted(fixed_rows, key=lambda r: r["local_index"])
    for a, b in zip(fixed_ordered, fixed_ordered[1:]):
        if (float(b["fixed_global_start_sec"]) < float(a["fixed_global_start_sec"])
                or float(b["fixed_global_end_sec"]) < float(a["fixed_global_end_sec"])):
            return _null_nc(song_id=song_id, region_id=region_id,
                            reason="non_monotonic_fixed_timeline")
    start = min(float(recrop_units[i]["start_sec"]) for i in active_local)
    end = max(float(recrop_units[i]["end_sec"]) for i in active_local)

    base = dict(identity_context or {})
    chain = dict(base)
    chain.update(_identity_ctx_for(coarse_identity, split_slot_id="R-CF",
                                   iteration=1, recrop_view_id="recenter_proposal"))

    result: dict[str, Any] = {
        "schema": "unit_realign_request_v2", "request_id": f"{song_id}:{region_id}:{FOURTH_FAMILY}",
        "family": FOURTH_FAMILY, "family_version": "v1",
        "song_id": song_id, "region_id": region_id, "audio_path": audio_path,
        "index_space": "document_global",
        "text_units": [str(u.get("text") or "") for u in recrop_units],
        "canonical_ids": recrop_ids, "local_to_canonical": recrop_ids,
        "canonical_to_local": {str(cid): i for cid, i in local.items()},
        "mapping_schema": "unit_realign_local_v2",
        "active_target_unit_ids": targets, "target_unit_ids": targets,
        "fixed_context_unit_ids": [recrop_ids[i] for i in fixed_local],
        "outside_unit_ids": [], "writeback_unit_ids": targets,
        "baseline_audio_range_sec": [start, end], "candidate_audio_range_sec": [start, end],
        "baseline_text_ids": recrop_ids, "candidate_text_ids": recrop_ids,
        "audio_start_sec": start, "audio_end_sec": end,
        "anchors": {"left": None, "right": None},
        "timestamp_slot_indices": active_all,
        "active_slot_indices": active_all,
        "fixed_slot_rows": fixed_rows,
        "slot_constraint_schema": "realign_sparse_fixed_v1",
        "recrop_context_ids": recrop_ids,
        "evaluation_only": False,
    }
    result["chain_context"] = dict(chain)
    result.update({k: v for k, v in chain.items() if v is not None})
    try:
        result["request_identity"] = build_request_identity(result)
    except ValueError:
        # chained refinement missing parent chain keys -> fail closed.
        return _null_nc(song_id=song_id, region_id=region_id,
                        reason="missing_chain_identity")
    return result


def _null_nc(*, song_id: str, region_id: str, reason: str) -> dict[str, Any]:
    return {"schema": "unit_realign_request_v2", "family": FOURTH_FAMILY,
            "requested_family": FOURTH_FAMILY, "song_id": song_id, "region_id": region_id,
            "reason": reason, "status": "not_constructible",
            "effective_intervention": False, "request_identity": None}


# --------------------------------------------------------------------------- #
#  smoke executor (deterministic CPU, geometry-valid)
# --------------------------------------------------------------------------- #
def make_coarse_fine_smoke_executor(nudge_target_sec: float = 0.0,
                                    nudge_context_sec: float = 0.0):
    """Deterministic CPU executor for the R-CF composition that keeps the merged
    timeline geometrically valid.

    Fixed (context) rows are placed exactly at their ``fixed_global_start_sec``;
    active (target) rows are packed into the gap between the surrounding fixed
    context (or the recrop window edge) so a clean synthetic region never trivially
    collides.  ``nudge_target_sec`` optionally shifts target rows to exercise
    recovery metrics without breaking validity.
    """
    from lyricalign.research_v7.attempt import AlignmentAttempt

    def _layout_positions(req, active: set[int], fixed_pos: dict[int, tuple[float, float]]):
        # per local index -> (start, end); targets evenly packed across each gap.
        positions: dict[int, tuple[float, float]] = dict(fixed_pos)
        fixed_idx = sorted(fixed_pos)
        # split active set into contiguous runs to pack each run inside one gap.
        act = sorted(active)
        runs: list[list[int]] = []
        for i in act:
            if runs and i == runs[-1][-1] + 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        for run in runs:
            lo_run = min(run)
            hi_run = max(run)
            before = [j for j in fixed_idx if j < lo_run]
            after = [j for j in fixed_idx if j > hi_run]
            lo = fixed_pos[max(before)][1] if before else 0.0
            hi = fixed_pos[min(after)][0] if after else None
            span = (hi - lo) if hi is not None else (len(run) * 0.5)
            if span < len(run) * 0.45:
                span = len(run) * 0.5  # avoid degenerate zero-width packing
            for k, i in enumerate(run):
                start = lo + span * (k + 0.5) / len(run) - 0.2
                start = max(start, lo)
                positions[i] = (start, start + 0.4)
        return positions

    def ex(req):
        n = len(req.text_units)
        offset = req.audio_start_sec
        active = set(req.active_slot_indices or ())
        fixed_pos: dict[int, tuple[float, float]] = {}
        for fr in (req.fixed_slot_rows or ()):
            lidx = int(fr.get("local_index"))
            fixed_pos[lidx] = (float(fr["fixed_global_start_sec"]),
                               float(fr["fixed_global_end_sec"]))
        positions = _layout_positions(req, active, fixed_pos)
        rows = []
        for i in range(n):
            start, end = positions.get(i, (offset + i * 0.5, offset + i * 0.5 + 0.4))
            if i in active and nudge_target_sec:
                start += nudge_target_sec
                end += nudge_target_sec
            if i not in active and nudge_context_sec:
                start += nudge_context_sec
                end += nudge_context_sec
            rows.append({
                "global_character_index": i,
                "raw_global_start_sec": start, "raw_global_end_sec": end,
                "fixed_global_start_sec": start, "fixed_global_end_sec": end,
                "start_sec": start, "end_sec": end,
                "decoder_kind": "official",
            })
        return AlignmentAttempt(
            request=req, attempt_id=f"CF-{req.item_id}-{req.mutation_type}",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            cursor_after=max((r["end_sec"] for r in rows), default=offset),
            committed=True, status="ok",
        )

    return ex


# --------------------------------------------------------------------------- #
#  constructibility / fail-closed geometry guard
# --------------------------------------------------------------------------- #
def constructible(proposal_rows: Sequence[Mapping[str, Any]],
                  region: Mapping[str, Any]) -> str | None:
    """Return None if the coarse proposal plus the frozen fixed context form a
    legal timeline; otherwise a fail-closed not_constructible reason string.

    The proposal target rows and all region context rows are merged and validated
    for monotonicity / non-negative duration (``validate_rows``).  If the proposal
    collides with or flips the fixed context, the refinement is not constructible.
    """
    by_id = {int(r["canonical_unit_id"]): r for r in (proposal_rows or ())}
    if not by_id:
        return "empty_coarse_proposal"
    # region = full unit set; proposal overwrites the target rows.
    merged: list[dict[str, Any]] = []
    for u in _unit_rows(region):
        cid = int(u["canonical_unit_id"])
        cand = by_id.get(cid)
        merged.append({"canonical_unit_id": cid,
                       "start_sec": float(cand["start_sec"]) if cand is not None else float(u["start_sec"]),
                       "end_sec": float(cand["end_sec"]) if cand is not None else float(u["end_sec"])})
    return validate_rows(merged)


# --------------------------------------------------------------------------- #
#  run_coarse_fine
# --------------------------------------------------------------------------- #
def _execute(v2: dict, executor, audio_path: str):
    if executor is None:
        return [], "no_executor"
    from .multi_iteration import _candidate_rows_from_v2, _to_v7_request
    if v2.get("family") == "R-NULL" or v2.get("status") == "not_constructible":
        return [], v2.get("reason") or "null_or_not_constructible"
    try:
        req = _to_v7_request(v2, audio_path)
        req.validate()
        attempt = executor(req)
        return _candidate_rows_from_v2(attempt, v2)
    except Exception as exc:  # noqa: BLE001
        return [], f"forward:{exc}"


def run_coarse_fine(region: Mapping[str, Any], target_unit_ids: Sequence[int],
                    family: str = FOURTH_FAMILY, identity_context: Mapping[str, Any] | None = None,
                    executor=None,
                    context_neighbors: int = STAGE_B_CONTEXT_NEIGHBORS,
                    active_neighbors: int = STAGE_B_ACTIVE_NEIGHBORS,
                    audio_margin_sec: float = 0.5,
                    smoke: bool = False) -> list[dict[str, Any]]:
    """Run the two-stage R-CF composition over a region's unsafe target span.

    Returns a list of two ``step`` dicts (stage A then stage B) with keys::

        stage, iteration, constructible, not_constructible_reason,
        baseline_rows, candidate_rows, request (v2 dict), request_identity,
        parent_request_identity, recrop_view_id, split_slot_id, status, error

    Stage B is skipped (its step marked not_constructible) when Stage A did not
    produce a proposal, the forward failed, or the proposal invalidated the fixed
    context geometry (fail-closed).
    """
    song_id = str(region.get("song_id") or "")
    region_id = str(region.get("region_id") or "")
    audio_path = str(region.get("audio_path") or f"{song_id}.wav")
    targets = [int(x) for x in target_unit_ids]
    base = _default_identity(region, smoke=smoke)
    base.update(dict(identity_context or {}))

    full_ids = [int(u["canonical_unit_id"]) for u in _unit_rows(region)]
    iter0_rows = baseline_rows_from_units(_unit_rows(region), full_ids)

    steps: list[dict[str, Any]] = []

    # ---- Stage A: coarse R-U proposal ----
    a_req = build_coarse_stage(region, targets, identity_context=base,
                               context_neighbors=STAGE_A_CONTEXT_NEIGHBORS,
                               audio_margin_sec=audio_margin_sec)
    a_id = a_req.get("request_identity")
    a_step: dict[str, Any] = {
        "stage": "A", "iteration": 0, "constructible": True, "not_constructible_reason": None,
        "baseline_rows": list(iter0_rows), "candidate_rows": [], "request": a_req,
        "request_identity": a_id, "parent_request_identity": None,
        "recrop_view_id": "base", "split_slot_id": "R-CF",
        "status": None, "error": None,
    }
    if a_req.get("family") == "R-NULL" or a_req.get("status") == "not_constructible":
        a_step["constructible"] = False
        a_step["not_constructible_reason"] = a_req.get("reason") or "null_or_not_constructible"
    elif not a_id:
        a_step["constructible"] = False
        a_step["not_constructible_reason"] = "coarse_identity_unassignable"
    steps.append(a_step)
    if a_step["constructible"]:
        a_rows, a_err = _execute(a_req, executor, audio_path)
        a_step["candidate_rows"] = a_rows
        if a_err:
            a_step["status"] = "failed"
            a_step["error"] = a_err
            a_step["constructible"] = False
            a_step["not_constructible_reason"] = a_err
        else:
            a_step["status"] = "ok"

    # ---- Stage B: re-center + sparse refinement ----
    b_step: dict[str, Any] = {
        "stage": "B", "iteration": 1, "constructible": True, "not_constructible_reason": None,
        "baseline_rows": [], "candidate_rows": [], "request": None,
        "request_identity": None, "parent_request_identity": a_id,
        "recrop_view_id": "recenter_proposal", "split_slot_id": "R-CF",
        "status": None, "error": None,
    }
    if not a_step.get("constructible") or a_step.get("status") != "ok":
        b_step["constructible"] = False
        b_step["not_constructible_reason"] = (a_step["not_constructible_reason"]
                                              or "previous_stage_not_run")
        steps.append(b_step)
        return steps

    proposal = a_step["candidate_rows"]
    geo = constructible(proposal, region)
    if geo:
        b_step["constructible"] = False
        b_step["not_constructible_reason"] = f"proposal_invalidates_fixed_context:{geo}"
        steps.append(b_step)
        return steps
    b_req = build_refinement_stage(region, targets, coarse_identity=a_id, proposal_rows=proposal,
                                   identity_context=base, context_neighbors=context_neighbors,
                                   active_neighbors=active_neighbors,
                                   audio_margin_sec=audio_margin_sec)
    b_id = b_req.get("request_identity")
    b_step["request"] = b_req
    b_step["request_identity"] = b_id
    if b_req.get("status") == "not_constructible":
        b_step["constructible"] = False
        b_step["not_constructible_reason"] = b_req.get("reason") or "refinement_not_constructible"
        steps.append(b_step)
        return steps
    if not b_id:
        b_step["constructible"] = False
        b_step["not_constructible_reason"] = "refinement_identity_unassignable"
        steps.append(b_step)
        return steps
    b_rows, b_err = _execute(b_req, executor, audio_path)
    b_step["candidate_rows"] = b_rows
    if b_err:
        b_step["status"] = "failed"
        b_step["error"] = b_err
        b_step["constructible"] = False
        b_step["not_constructible_reason"] = b_err
        steps.append(b_step)
        return steps
    b_step["status"] = "ok"
    steps.append(b_step)
    return steps


# --------------------------------------------------------------------------- #
#  evaluation — coarse_fine_v1 (02 E4 §311-319)
# --------------------------------------------------------------------------- #
def _final_rows(steps: Sequence[Mapping[str, Any]]) -> tuple[list[dict] | None, dict | None]:
    """Return (merged final candidate rows, winning stage) across steps.

    U-review P1-1: if Stage A produced a valid coarse proposal but Stage B was
    not_constructible (fail-closed stop), the coarse recovery is still real and
    must not be discarded. We fall back to Stage A's candidate rows in that case
    so coverage/target_recovered_* reflect the coarse recovery rather than a
    spurious 0.
    """
    b_step = next((s for s in steps if s.get("stage") == "B"), None)
    a_step = next((s for s in steps if s.get("stage") == "A"), None)
    if b_step is not None and b_step.get("status") == "ok":
        return b_step.get("candidate_rows"), b_step
    # Stage B absent, or present-but-not-constructible, while Stage A succeeded:
    # use the coarse proposal as the final result.
    if a_step is not None and a_step.get("status") == "ok":
        return a_step.get("candidate_rows"), a_step
    return None, None


def evaluate_coarse_fine(steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Produce ``coarse_fine_v1`` rows (per-region aggregate + per-unit target
    rows) covering the full 7-metric contract (02 E4 §311-319).

    Metrics:
        target_100/200/500/1000ms recovery (shadow baseline reference),
        fixed_context_displacement, catastrophic_regression,
        constructibility/coverage, forward_cost, no_gt_safety_signals,
        test_demo_structural_regressions.
    """
    rows: list[dict[str, Any]] = []
    stages = sorted(steps, key=lambda s: (s.get("iteration", 0), s.get("stage", "")))
    region = None
    # steps carry request -> song/region.
    for st in steps:
        rq = st.get("request") or {}
        region = {"song_id": rq.get("song_id") or "?",
                  "region_id": rq.get("region_id") or "?"}
        break
    song_id = (region or {}).get("song_id", "?")
    region_id = (region or {}).get("region_id", "?")

    a_step = next((s for s in stages if s.get("stage") == "A"), None)
    b_step = next((s for s in stages if s.get("stage") == "B"), None)
    final_rows, win = _final_rows(steps)
    a_id = (a_step or {}).get("request_identity")
    b_id = (b_step or {}).get("request_identity")

    # target recovery vs frozen detector baseline: we don't have the region units
    # here unless a request carries context; requests have canonical unit ids.
    # Recover the frozen reference from the stage-A baseline rows' canonical span.
    baseline_by_id: dict[int, tuple[float, float]] = {}
    target_ids: set[int] = set()
    for st in stages:
        rq = st.get("request") or {}
        target_ids |= set(int(x) for x in rq.get("target_unit_ids") or ())
        for r in st.get("baseline_rows") or ():
            cid = int(r["canonical_unit_id"])
            baseline_by_id.setdefault(cid, (float(r["start_sec"]), float(r["end_sec"])))
    final_by_id = {int(r["canonical_unit_id"]): r for r in (final_rows or ())}

    # ---- per-unit target recovery rows ----
    n_ok = n_100 = n_200 = n_500 = n_1000 = 0
    per_unit: list[dict[str, Any]] = []
    for cid in sorted(target_ids):
        ref = baseline_by_id.get(cid)
        cand = final_by_id.get(cid)
        ok = ref is not None and cand is not None
        err_ms = None
        if ok:
            err_ms = (float(cand["start_sec"]) - ref[0]) * 1000.0
        abs_err = abs(float(err_ms)) if ok else None
        row = {
            "schema": COARSE_FINE_SCHEMA, "row_kind": "unit",
            "song_id": song_id, "region_id": region_id,
            "canonical_unit_id": cid,
            "error_ms": round(err_ms, 4) if ok else None,
            "target_recovered_100": bool(ok and abs_err <= STRICT_100_MS),
            "target_recovered_200": bool(ok and abs_err <= STRICT_200_MS),
            "target_recovered_500": bool(ok and abs_err <= COARSE_500_MS),
            "target_recovered_1000": bool(ok and abs_err <= COARSE_1000_MS),
        }
        per_unit.append(row)
        if ok:
            n_ok += 1
            n_100 += 1 if abs_err <= STRICT_100_MS else 0
            n_200 += 1 if abs_err <= STRICT_200_MS else 0
            n_500 += 1 if abs_err <= COARSE_500_MS else 0
            n_1000 += 1 if abs_err <= COARSE_1000_MS else 0
    rows.extend(per_unit)

    # ---- fixed-context displacement ----
    fixed_context_ids = set()
    for st in stages:
        rq = st.get("request") or {}
        fixed_context_ids |= set(int(x) for x in rq.get("fixed_context_unit_ids") or ())
    fixed_context_ids -= target_ids
    context_displacement: list[float] = []
    catastrophic_regressions: list[int] = []
    for cid in sorted(fixed_context_ids):
        ref = baseline_by_id.get(cid)
        cand = final_by_id.get(cid)
        if ref is None or cand is None:
            continue
        disp = abs((float(cand["start_sec"]) - ref[0]) * 1000.0)
        context_displacement.append(disp)
        if disp > CATASTROPHIC_MS:
            catastrophic_regressions.append(cid)
    # any target regression beyond tolerance also counts as catastrophic.
    for cid in sorted(target_ids):
        ref = baseline_by_id.get(cid)
        cand = final_by_id.get(cid)
        if ref is None or cand is None:
            continue
        if abs((float(cand["start_sec"]) - ref[0]) * 1000.0) > CATASTROPHIC_MS:
            catastrophic_regressions.append(cid)
    context_harm = sum(1 for d in context_displacement if d > CONTEXT_EPS_MS)

    # ---- constructibility / coverage ----
    n_a = sum(1 for s in stages if s.get("stage") == "A")
    n_b = sum(1 for s in stages if s.get("stage") == "B")
    constructible_a = bool((a_step or {}).get("constructible", False))
    constructible_b = bool((b_step or {}).get("constructible", False))
    coverage = (n_ok / len(target_ids)) if target_ids else 0.0

    # ---- forward cost ----
    forward_count = sum(1 for s in stages if s.get("status") == "ok")

    # ---- no-GT safety signals (GT firewall: no GT path; placeholder) ----
    no_gt_safety = {
        "provider": "none",
        "available_signals": [],
        "uncertain_flags": [],
        "danger_flags": [f"catastrophic_regression:{c}" for c in catastrophic_regressions],
        "safe_to_proceed_no_gt": not bool(catastrophic_regressions),
    }

    # ---- test-demo structural regressions (merged final timeline validation) ----
    merged_all: list[dict[str, Any]] = []
    for cid, ref in baseline_by_id.items():
        cand = final_by_id.get(cid)
        merged_all.append({"canonical_unit_id": cid,
                           "start_sec": float(cand["start_sec"]) if cand else ref[0],
                           "end_sec": float(cand["end_sec"]) if cand else ref[1]})
    structural = validate_structural(merged_all)

    aggregate = {
        "schema": COARSE_FINE_SCHEMA, "row_kind": "region",
        "song_id": song_id, "region_id": region_id,
        "family": FOURTH_FAMILY,
        # per-stage request identities (must differ) — G5 identity verification.
        "stage_a_request_identity": a_id,
        "stage_b_request_identity": b_id,
        "stage_a_constructible": constructible_a,
        "stage_b_constructible": constructible_b,
        "not_constructible_reason": (_fail_reason(steps) or None),
        # U-review P1-1: final_stage records whether the reported recovery came from
        # Stage B (refine) or fell back to Stage A (coarse) when B was not_constructible.
        "final_stage": str((win or {}).get("stage")) if win else None,
        "stage_b_not_constructible": bool(b_step is not None and b_step.get("status") != "ok"),
        # target 100/200/500/1000ms recovery rates.
        "n_target_units": len(target_ids),
        "target_recovered_100": round((n_100 / n_ok), 4) if n_ok else 0.0,
        "target_recovered_200": round((n_200 / n_ok), 4) if n_ok else 0.0,
        "target_recovered_500": round((n_500 / n_ok), 4) if n_ok else 0.0,
        "target_recovered_1000": round((n_1000 / n_ok), 4) if n_ok else 0.0,
        # fixed context displacement.
        "fixed_context_displacement_ms": round(max(context_displacement), 4) if context_displacement else None,
        "mean_fixed_context_displacement_ms": round(sum(context_displacement) / len(context_displacement), 4) if context_displacement else None,
        "n_context_units_harmed": context_harm,
        # catastrophic regression.
        "catastrophic_regression": bool(catastrophic_regressions),
        "catastrophic_regression_units": sorted(set(catastrophic_regressions)),
        # constructibility / coverage.
        "constructibility": {"stage_a": constructible_a, "stage_b": constructible_b,
                             "n_stages": len(stages)},
        "coverage": round(coverage, 4),
        # forward cost.
        "forward_cost": forward_count,
        # no-GT safety signals.
        "no_gt_safety_signals": no_gt_safety,
        # Test Demo objective structural regressions.
        "test_demo_structural_regressions": structural,
        "actual_writeback": 0,
    }
    rows.append(aggregate)
    return rows


def _fail_reason(steps: Sequence[Mapping[str, Any]]) -> str | None:
    for s in steps:
        if not s.get("constructible"):
            return s.get("not_constructible_reason")
    return None


def validate_structural(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Test-Demo structural regression validator on a merged (global) timeline."""
    ordered = sorted(rows, key=lambda r: int(r["canonical_unit_id"]))
    neg_dur: list[int] = []
    non_mono: list[tuple[int, int]] = []
    overlap: list[tuple[int, int]] = []
    prev: dict | None = None
    for r in ordered:
        s, e = float(r["start_sec"]), float(r["end_sec"])
        if e < s:
            neg_dur.append(int(r["canonical_unit_id"]))
        if prev is not None:
            ps, pe = float(prev["start_sec"]), float(prev["end_sec"])
            if s < ps:
                non_mono.append((int(prev["canonical_unit_id"]), int(r["canonical_unit_id"])))
            if max(ps, s) < min(pe, e):
                overlap.append((int(prev["canonical_unit_id"]), int(r["canonical_unit_id"])))
        prev = r
    return {
        "ok": not (neg_dur or non_mono or overlap),
        "negative_duration_units": neg_dur,
        "non_monotonic_pairs": non_mono,
        "overlap_pairs": overlap,
    }
