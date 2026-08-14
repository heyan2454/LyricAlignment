"""E2 — fine-grained split screening over an unsafe region (shadow-only).

Implements the four partition mechanisms (07 plan §9 WP4 / 02 E2 §168-222):

  1. one_unit       every unsafe unit its own 1-unit sub-target
  2. two_unit       every contiguous pair of unsafe units a 2-unit sub-target
  3. adaptive       contiguous detector-unsafe span split on *safe* gaps / state
                    transitions (boundaries recorded as ``adaptive_boundary``)
  4. anchor_gap     split on stable ACCEPT anchors and/or long-silence / large
                    time gaps (boundaries recorded as ``anchor_boundary`` /
                    ``gap_boundary``)

Every sub-target is a contiguous canonical-id segment (a ``split_slot``).  Each
sub-request is built by ``build_family_request`` and its request identity MUST
carry ``split_slot_id`` (bound to partition + sub-target index) and the
``direction`` so that different shards of the same region never collide on
identity (WP1 P1-2 / 07 §5).  The whole module is GT-firewalled: no GT path
exists here or in anything it calls; all recovery references are shadow baseline
(frozen detector) positions.

Direction semantics (``classify_direction`` / runner):
  L2R / R2L  — serial chain: sub-targets are processed in increasing (L2R) or
               decreasing (R2L) canonical order and each sub-target's candidate
               becomes the next sub-target's baseline (true multi-realign chaining).
  independent — every sub-target is evaluated from the frozen detector baseline
               (no chaining); results are then deterministically merged.

Output rows use schema ``split_realign_v1`` (02 E2 §205-214), providing all
eight metric families plus extra_forward_cost.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .multi_iteration import _baseline_digest, baseline_rows_from_units
from .request_families import build_family_request

SPLIT_REALIGN_SCHEMA = "split_realign_v1"

# safe-gap threshold (seconds) for adaptive / anchor-gap partition: a gap between
# two consecutive unsafe units larger than this is treated as a "safe boundary"
# (long silence) and split there.
SAFE_GAP_SEC = 0.30
# time gap that marks an anchor-gap boundary even without an ACCEPT anchor.
LONG_GAP_SEC = 0.90

# metric evaluation tolerance (ms) thresholds, single source of truth.
STRICT_100_MS = 100.0
STRICT_200_MS = 200.0
COARSE_500_MS = 500.0
COARSE_1000_MS = 1000.0
# context unit is considered "preserved" if displaced no more than this (ms).
CONTEXT_EPS_MS = 1.0

PARTITION_SCHEMAS = ("one_unit", "two_unit", "adaptive", "anchor_gap")


# --------------------------------------------------------------------------- #
#  partition primitives
# --------------------------------------------------------------------------- #
def _unit_rows(region: Mapping[str, Any]) -> list[dict]:
    """Sorted list of region units (by canonical id)."""
    units = list(region.get("units") or ())
    units.sort(key=lambda u: int(u.get("canonical_unit_id")))
    return units


def unit_state(u: Mapping[str, Any]) -> str:
    return str(u.get("state") or "").upper()


def _contiguous_groups(region: Mapping[str, Any], *, include: set[str]) -> list[list[int]]:
    """Return contiguous runs of canonical ids whose unit state is in ``include``."""
    groups: list[list[int]] = []
    cur: list[int] = []
    for u in _unit_rows(region):
        cid = int(u["canonical_unit_id"])
        if unit_state(u) in include:
            cur.append(cid)
        else:
            if cur:
                groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def unsafe_groups(region: Mapping[str, Any]) -> list[list[int]]:
    """Contiguous runs of REJECT/UNCERTAIN units (the difficulty fragments)."""
    return _contiguous_groups(region, include={"REJECT", "UNCERTAIN"})


def _ids_to_segments(cids: Sequence[int], size: int) -> list[list[int]]:
    out = []
    for i in range(0, max(0, len(cids) - size + 1), size):
        out.append(list(cids[i:i + size]))
    if not out and cids:
        out.append(list(cids))
    return out


def _gap_sec(region: Mapping[str, Any], a: int, b: int) -> float | None:
    """Gap between the end of unit ``a`` and start of unit ``b`` (None if either missing)."""
    by_id = {int(u["canonical_unit_id"]): u for u in _unit_rows(region)}
    ua, ub = by_id.get(a), by_id.get(b)
    if not ua or not ub:
        return None
    a_end = ua.get("end_sec")
    b_start = ub.get("start_sec")
    if not isinstance(a_end, (int, float)) or not isinstance(b_start, (int, float)):
        return None
    return max(0.0, float(b_start) - float(a_end))


def _split_on_boundaries(group: list[int], boundary_indices: set[int]) -> list[list[int]]:
    """Split a contiguous canonical-id group so a segment break is placed between
    ``group[i]`` and ``group[i+1]`` for each i in ``boundary_indices``."""
    if not group:
        return []
    segments: list[list[int]] = []
    start = 0
    for i in range(len(group) - 1):
        if i + 1 in boundary_indices:  # boundary after group[i]
            segments.append(list(group[start:i + 1]))
            start = i + 1
    segments.append(list(group[start:]))
    return segments


def partition_region(region: Mapping[str, Any], partition: str) -> list[dict]:
    """Return sub-targets for a region under one partition mechanism.

    Returns a list of ``{"index": int, "sub_target_unit_ids": [contiguous ints],
    "partition_schema": str, "partition_identity": {...}}``.  Partition identity
    encodes the mechanism + the boundary decisions so two regions that split the
    same way share identity provenance while different boundaries never collide.
    """
    if partition not in PARTITION_SCHEMAS:
        raise ValueError(f"unsupported partition {partition}")
    by_id = {int(u["canonical_unit_id"]): u for u in _unit_rows(region)}
    cids = sorted(by_id)
    groups = unsafe_groups(region)
    flat_targets = [cid for g in groups for cid in g]

    subtargets: list[dict] = []
    boundary_marks: list[str] = []  # provenance of each break, for identity

    def _emit(group: list[int], kind: str, marks: list[str], spec_extra: dict | None = None) -> None:
        for seg in group:
            meta = {"partition_schema": partition, **spec_extra}
            subtargets.append({
                "index": len(subtargets),
                "sub_target_unit_ids": seg,
                "partition_schema": partition,
                "partition_identity": _partition_identity(region, partition, kind, marks),
                "boundary_kind": kind,
                "meta": meta,
            })

    if partition == "one_unit":
        for g in groups:
            marks = ["one_unit"]
            for cid in g:
                subtargets.append({
                    "index": len(subtargets),
                    "sub_target_unit_ids": [cid],
                    "partition_schema": partition,
                    "partition_identity": _partition_identity(region, partition, "one_unit", marks),
                    "boundary_kind": "one_unit",
                    "meta": {"one_unit": True},
                })
    elif partition == "two_unit":
        for g in groups:
            marks = ["two_unit"]
            for pair in _ids_to_segments(g, 2):
                subtargets.append({
                    "index": len(subtargets),
                    "sub_target_unit_ids": pair,
                    "partition_schema": partition,
                    "partition_identity": _partition_identity(region, partition, "two_unit", marks),
                    "boundary_kind": "two_unit",
                    "meta": {"pair_size": 2},
                })
    elif partition == "adaptive":
        for g in groups:
            break_idx: set[int] = set()
            marks = []
            for i in range(len(g) - 1):
                gap = _gap_sec(region, g[i], g[i + 1])
                # split where a safe gap appears between two unsafe units.
                if gap is not None and gap > SAFE_GAP_SEC:
                    break_idx.add(i + 1)
                    marks.append(f"adaptive_boundary@{g[i]}~{g[i + 1]}")
            if not marks:
                marks.append("adaptive_boundary@none")
            for seg in _split_on_boundaries(g, break_idx):
                subtargets.append({
                    "index": len(subtargets),
                    "sub_target_unit_ids": seg,
                    "partition_schema": partition,
                    "partition_identity": _partition_identity(region, partition, "adaptive", marks),
                    "boundary_kind": "adaptive",
                    "meta": {"adaptive_boundary": marks},
                })
    elif partition == "anchor_gap":
        accept_ids = {int(u["canonical_unit_id"]) for u in _unit_rows(region)
                      if unit_state(u) == "ACCEPT"}
        for g in groups:
            break_idx: set[int] = set()
            marks = []
            for i in range(len(g) - 1):
                # anchor-gap boundary if there is a stable ACCEPT anchor strictly
                # between the two units.
                had_anchor = any(a > g[i] and a < g[i + 1] for a in accept_ids)
                gap = _gap_sec(region, g[i], g[i + 1])
                had_gap = gap is not None and gap > LONG_GAP_SEC
                if had_anchor or had_gap:
                    break_idx.add(i + 1)
                    marks.append(f"{'anchor_boundary' if had_anchor else 'gap_boundary'}@{g[i]}~{g[i + 1]}")
            if not marks:
                marks.append("anchor_boundary@none")
            for seg in _split_on_boundaries(g, break_idx):
                subtargets.append({
                    "index": len(subtargets),
                    "sub_target_unit_ids": seg,
                    "partition_schema": partition,
                    "partition_identity": _partition_identity(region, partition, "anchor_gap", marks),
                    "boundary_kind": "anchor_gap",
                    "meta": {"anchor_accept_ids": sorted(accept_ids), "anchor_gap_boundary": marks},
                })
    if not subtargets and flat_targets:
        # No unsafe state annotated (no state → treat the whole region's units as
        # the difficulty fragment so the runner is still constructible/testable).
        subtargets.append({
            "index": 0,
            "sub_target_unit_ids": flat_targets,
            "partition_schema": partition,
            "partition_identity": _partition_identity(region, partition, "fallback_all", []),
            "boundary_kind": "fallback_all",
            "meta": {"fallback_all": True},
        })
    return subtargets


def _partition_identity(region: Mapping[str, Any], partition: str, kind: str,
                        marks: Sequence[str]) -> dict[str, Any]:
    """Deterministic partition identity: region + mechanism + boundary decision."""
    return {
        "partition_schema": partition,
        "region_id": str(region.get("region_id") or ""),
        "song_id": str(region.get("song_id") or ""),
        "target_unit_ids": [int(x) for x in (region.get("target_unit_ids") or ())],
        "boundary_kind": kind,
        "boundary_marks": list(marks),
    }


# --------------------------------------------------------------------------- #
#  request construction
# --------------------------------------------------------------------------- #
def _effective_family(family: str, span_len: int) -> str:
    """R-U caps active targets at 3 contiguous units; subtargets larger than that
    fall back to R-A (context-preserving, no length cap) so the split stays
    constructible.  Caller records the effective family in the outcome."""
    if family in {"R-U", "R-U1", "R-U3"} and span_len > 3:
        return "R-A"
    return family


def build_split_requests(
    region: Mapping[str, Any],
    subtargets: Sequence[Mapping[str, Any]],
    *,
    partition: str,
    direction: str = "L2R",
    family: str = "R-U",
    identity_context: Mapping[str, Any] | None = None,
    audio_margin_sec: float = 0.5,
    context_neighbors: int = 1,
    ra_context_units: int = 1,
) -> list[dict]:
    """Build one v2 request per sub-target.

    Each request embeds ``split_slot_id`` (bound to partition + sub-index) and
    ``direction`` in its ``identity_context`` (hence in ``chain_context`` and the
    content-addressed ``request_identity``), so distinct shards never collide
    (WP1 / 07 §5).  Serial chains (L2R/R2L) additionally carry the previous
    sub-request's ``request_identity`` as ``parent_request_identity`` (with the
    other three fail-closed chain keys); independent leaves parent out.

    Returns the v2 request dict per sub-target (including not_constructible /
    R-NULL guards exactly as ``build_family_request`` dictates).
    """
    base_ctx = dict(identity_context or {})
    song_id = str(region.get("song_id") or "")
    region_id = str(region.get("region_id") or "")
    audio_path = str(region.get("audio_path") or f"{song_id}.wav")

    # All split sub-targets in a region share the frozen detector baseline (the
    # no-GT recovery reference); it also supplies the required `baseline_digest`
    # identity key so each sub-request gets a real, content-addressed identity
    # (identical to build_chain's iter0 contract).
    region_unit_rows = baseline_rows_from_units(_unit_rows(region),
                                                [int(u["canonical_unit_id"])
                                                 for u in _unit_rows(region)])
    base_ctx.setdefault("baseline_digest", _baseline_digest(region_unit_rows))
    base_ctx.setdefault("text_adapter_identity", "c3")

    # _effective family per subtarget span length; keep family stable within a run.
    requests: list[dict] = []
    prev_identity: str | None = None
    for st in subtargets:
        idx = int(st["index"])
        targets = [int(x) for x in st["sub_target_unit_ids"]]
        eff_family = _effective_family(family, len(targets))
        split_slot_id = f"{partition}:{direction}:idx{idx}"
        ctx = dict(base_ctx)
        ctx["split_slot_id"] = split_slot_id
        ctx["direction"] = direction
        ctx["partition"] = partition
        ctx["sub_target_index"] = idx
        chain_ctx = dict(ctx)
        if direction in {"L2R", "R2L"} and prev_identity:
            chain_ctx.update({
                "parent_request_identity": prev_identity,
                "iteration": idx,  # split-step ordinal within the serial chain
                "recrop_view_id": "none",
                "split_slot_id": split_slot_id,
            })
            ctx.update({"parent_request_identity": prev_identity,
                        "iteration": idx, "recrop_view_id": "none"})
        request = build_family_request(
            family=eff_family, song_id=song_id, region_id=region_id,
            audio_path=audio_path, units=_unit_rows(region), target_unit_ids=targets,
            identity_context={**ctx, "chain_context": chain_ctx},
            audio_margin_sec=audio_margin_sec, context_neighbors=context_neighbors,
            ra_context_units=ra_context_units,
        )
        # record shard provenance on the request for resumability / reporting.
        request.setdefault("split_shard", {
            "partition": partition, "direction": direction,
            "sub_target_index": idx, "split_slot_id": split_slot_id,
            "target_unit_ids": targets, "effective_family": eff_family,
            "partition_identity": st.get("partition_identity"),
        })
        requests.append(request)
        if request.get("request_identity"):
            prev_identity = request["request_identity"]
    return requests


def class_target_order(region: Mapping[str, Any], subtargets: Sequence[Mapping[str, Any]],
                       direction: str) -> list[int]:
    """Traversal order of sub-target indices under a direction."""
    all_idx = list(range(len(subtargets)))
    if direction == "L2R":
        return all_idx
    if direction == "R2L":
        return list(reversed(all_idx))
    if direction == "independent":
        # independent: no serial ordering constraint; keep input order but flag
        # it as independent (merging is deterministic on canonical order later).
        return all_idx
    raise ValueError(f"unsupported direction {direction}")


# --------------------------------------------------------------------------- #
#  merge / collision checks
# --------------------------------------------------------------------------- #
def merge_split_results(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge per-sub-target candidate unit positions into one canonical-ordered
    timeline and detect collisions/overlaps/non-monotonicity.

    ``results``: list of ``{"sub_target_index", "target_unit_ids", "candidate_rows"}.
    candidate_rows entries: ``{"canonical_unit_id","start_sec","end_sec"}``.

    Returns ``{"schema": ..., "merge_ok": bool, "collision_units": [...] ,
    "merge_collision": bool, "merge_overlap": bool, "non_monotonic": bool,
    "merged": [unit positions in canonical order]}``.
    """
    merged: dict[int, tuple[float, float]] = {}
    provenance: dict[int, int] = {}
    for res in results:
        for r in res.get("candidate_rows") or ():
            cid = int(r["canonical_unit_id"])
            span = (float(r["start_sec"]), float(r["end_sec"]))
            if cid in merged and merged[cid] != span:
                provenance.setdefault(cid, -1)  # conflict between shards
                continue
            merged[cid] = span
            if cid in provenance and provenance[cid] == -1:
                continue
            provenance[cid] = int(res.get("sub_target_index"))

    ordered = sorted(merged.items(), key=lambda kv: kv[0])
    collision_units: list[int] = [cid for cid, sp in provenance.items() if sp == -1]

    # overlap = two DIFFERENT canonical units interleave (start within other's span).
    overlap: list[tuple[int, int]] = []
    for (a, (as0, as1)), (b, (bs0, bs1)) in zip(ordered, ordered[1:]):
        if max(as0, bs0) < min(as1, bs1):
            overlap.append((a, b))

    # non-monotonic = start time does not strictly increase along canonical order.
    non_mono: list[tuple[int, int]] = []
    for (a, (as0, _)), (b, (bs0, _)) in zip(ordered, ordered[1:]):
        if bs0 < as0:
            non_mono.append((a, b))

    merge_ok = not collision_units and not overlap and not non_mono
    return {
        "schema": "split_merge_v1",
        "merge_ok": merge_ok,
        "merge_collision": bool(collision_units),
        "merge_overlap": bool(overlap),
        "non_monotonic": bool(non_mono),
        "collision_units": collision_units,
        "overlap_pairs": overlap,
        "non_monotonic_pairs": non_mono,
        "n_units_merged": len(merged),
        "merged_units": [{"canonical_unit_id": cid, "start_sec": s, "end_sec": e}
                         for cid, (s, e) in ordered],
    }


# --------------------------------------------------------------------------- #
#  split_realign_v1 outcomes (02 E2 §205-214)
# --------------------------------------------------------------------------- #
def ref_position(region: Mapping[str, Any], cid: int) -> float | None:
    """Frozen detector (shadow baseline) reference start for a unit — the no-GT
    recovery reference.  Returns None if the unit is missing from the region."""
    for u in _unit_rows(region):
        if int(u["canonical_unit_id"]) == cid:
            s = u.get("start_sec")
            return float(s) if isinstance(s, (int, float)) else None
    return None


def evaluate_split(
    region: Mapping[str, Any], subtargets: Sequence[Mapping[str, Any]],
    executed: Sequence[Mapping[str, Any]], merge: Mapping[str, Any] | None,
    *,
    partition: str, direction: str, family_requested: str, forward_count: int,
) -> list[dict]:
    """Produce ``split_realign_v1`` rows (per-unit + per-region aggregate) for a
    region's split run.

    ``executed``: one dict per sub-target with keys ``sub_target_index``,
    ``target_unit_ids``, ``candidate_rows``, ``request_identity``,
    ``effective_family``, ``constructible``.

    Recovery is measured against the frozen detector baseline (shadow, no GT):
    err_ms = candidate_start - baseline_start, per canonical unit.
    """
    rows: list[dict] = []
    region_id = str(region.get("region_id") or "?")
    song_id = str(region.get("song_id") or "?")

    unit_rows: dict[int, dict] = {}
    all_targets: list[int] = []
    for ex in executed:
        for cid in ex.get("target_unit_ids") or ():
            all_targets.append(int(cid))
        for r in ex.get("candidate_rows") or ():
            unit_rows[int(r["canonical_unit_id"])] = r

    # context = units in full region that are not active targets.
    region_ids = [int(u["canonical_unit_id"]) for u in _unit_rows(region)]
    target_set = set(all_targets)
    context_ids = [c for c in region_ids if c not in target_set]

    # ---- per-unit recovery rows ----
    per_unit: list[dict] = []
    harm_boundary_units: list[int] = []
    boundary_ids: set[int] = set()
    for st in subtargets:
        sub_targets = [int(x) for x in st["sub_target_unit_ids"]]
        if sub_targets:
            boundary_ids.add(sub_targets[0])
            boundary_ids.add(sub_targets[-1])

    for cid in all_targets:
        ref = ref_position(region, cid)
        cand = unit_rows.get(cid)
        if ref is None or cand is None:
            ok = False
            err_ms = None
        else:
            err_ms = (float(cand["start_sec"]) - ref) * 1000.0
            ok = True
        abs_err = abs(float(err_ms)) if ok else None
        row = {
            "schema": SPLIT_REALIGN_SCHEMA,
            "row_kind": "unit",
            "song_id": song_id, "region_id": region_id,
            "partition": partition, "direction": direction,
            "canonical_unit_id": cid,
            "error_ms": round(err_ms, 4) if ok else None,
            "recovered_strict_100": bool(ok and abs_err <= STRICT_100_MS),
            "recovered_strict_200": bool(ok and abs_err <= STRICT_200_MS),
            "recovered_coarse_500": bool(ok and abs_err <= COARSE_500_MS),
            "recovered_coarse_1000": bool(ok and abs_err <= COARSE_1000_MS),
            "on_split_boundary": bool(cid in boundary_ids),
            "split_boundary_harm": bool(cid in boundary_ids and ok and abs_err > CONTEXT_EPS_MS),
        }
        if cid in boundary_ids and ok and abs_err > CONTEXT_EPS_MS:
            harm_boundary_units.append(cid)
        per_unit.append(row)
    rows.extend(per_unit)

    # ---- context preservation (fixed-context units stay put) ----
    context_harm = 0
    for cid in context_ids:
        ref = ref_position(region, cid)
        cand = unit_rows.get(cid)
        if ref is None or cand is None:
            continue
        disp_ms = abs((float(cand["start_sec"]) - ref) * 1000.0)
        if disp_ms > CONTEXT_EPS_MS:
            context_harm += 1
    context_preserved = (context_harm == 0)

    # ---- region aggregates ----
    ok_units = [r for r in per_unit if r["error_ms"] is not None]
    n_total = len(all_targets)
    n_100 = sum(1 for r in ok_units if r["recovered_strict_100"])
    n_200 = sum(1 for r in ok_units if r["recovered_strict_200"])
    n_500 = sum(1 for r in ok_units if r["recovered_coarse_500"])
    n_1000 = sum(1 for r in ok_units if r["recovered_coarse_1000"])

    recovered_unit_fraction = (n_200 / n_total) if n_total else 0.0
    region_all_hit = bool(n_total and n_200 == n_total)
    region_ge75_hit = bool(n_total and (n_200 / n_total) >= 0.75)
    strict_100_recovery = (n_100 / n_total) if n_total else 0.0
    strict_200_recovery = (n_200 / n_total) if n_total else 0.0
    coarse_500_recovery = (n_500 / n_total) if n_total else 0.0
    coarse_1000_recovery = (n_1000 / n_total) if n_total else 0.0

    effective_families = sorted({str(ex.get("effective_family") or family_requested)
                                 for ex in executed})
    aggregate = {
        "schema": SPLIT_REALIGN_SCHEMA,
        "row_kind": "region",
        "song_id": song_id, "region_id": region_id,
        "partition": partition, "direction": direction,
        "n_target_units": n_total,
        "n_sub_targets": len(subtargets),
        "n_constructible_sub_targets": sum(1 for ex in executed if ex.get("constructible", True)),
        "effective_families": effective_families,
        "strict_100_recovery": round(strict_100_recovery, 4),
        "strict_200_recovery": round(strict_200_recovery, 4),
        "coarse_500_recovery": round(coarse_500_recovery, 4),
        "coarse_1000_recovery": round(coarse_1000_recovery, 4),
        "context_preservation": context_preserved,
        "n_context_units_harmed": context_harm,
        "split_boundary_harm": bool(harm_boundary_units),
        "split_boundary_harm_units": harm_boundary_units,
        "merge_collision": bool(merge and merge["merge_collision"]),
        "merge_overlap": bool(merge and merge["merge_overlap"]),
        "non_monotonic": bool(merge and merge["non_monotonic"]),
        "collision_units": (list(merge["collision_units"]) if merge else []),
        "merge_ok": bool(merge and merge["merge_ok"]),
        "recovered_unit_fraction": round(recovered_unit_fraction, 4),
        "region_all_hit": region_all_hit,
        "region_ge75_hit": region_ge75_hit,
        "extra_forward_cost": max(0, forward_count - 1),
        "forward_count": forward_count,
        "actual_writeback": 0,  # shadow-only, always
    }
    rows.append(aggregate)
    return rows
