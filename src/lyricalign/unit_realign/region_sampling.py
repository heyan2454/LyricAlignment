"""No-GT population enumeration and evaluator-side balanced replenishment."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


def _contiguous(ids: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for cid in sorted(set(ids)):
        if not groups or cid != groups[-1][-1] + 1:
            groups.append([cid])
        else:
            groups[-1].append(cid)
    return groups


def _all_spans(group: list[int], max_units: int) -> list[list[int]]:
    return [group[start:end] for start in range(len(group))
            for end in range(start + 1, min(len(group), start + max_units) + 1)]


def build_region_population(detector_shadow_rows: Sequence[Mapping[str, Any]], *, max_units: int = 8) -> list[dict[str, Any]]:
    """Enumerate every contiguous unsafe subspan of length 1..``max_units``.

    Rows are intentionally no-GT.  ``overlap_interval_sec`` is copied from
    baseline units when available so evaluator-side selection can prevent
    duplicate evidence across overlapping windows.
    """
    if not 1 <= max_units <= 8:
        raise ValueError("max_units must be in [1, 8]")
    out: list[dict[str, Any]] = []
    for shadow in detector_shadow_rows:
        data = shadow.get("detector_shadow") or {}
        units = {int(k): v for k, v in (data.get("units") or {}).items()}
        song_id, window_index = str(shadow.get("song_id")), shadow.get("window_index")
        unsafe_ids = [cid for cid, row in units.items() if str(row.get("state", "")).upper() in {"UNCERTAIN", "REJECT"}]
        accept_ids = [cid for cid, row in units.items() if str(row.get("state", "")).upper() == "ACCEPT"]
        ordinal = 0
        for group in _contiguous(unsafe_ids):
            for ids in _all_spans(group, max_units):
                starts = [units[x].get("start_sec") for x in ids]
                ends = [units[x].get("end_sec") for x in ids]
                timing_ok = all(isinstance(x, (int, float)) for x in starts + ends) and all(
                    float(end) > float(start) >= 0.0 for start, end in zip(starts, ends))
                out.append({
                    "region_id": f"{song_id}:w{window_index}:unsafe:{ordinal}", "song_id": song_id,
                    "language": shadow.get("language"), "window_index": window_index,
                    "seed_kind": "unsafe_region", "target_unit_ids": ids, "detector_state": "UNSAFE",
                    "overlap_interval_sec": [min(starts), max(ends)] if timing_ok else None,
                    "baseline_available": timing_ok,
                    "left_anchor_candidates": [c for c in accept_ids if c < ids[0]],
                    "right_anchor_candidates": [c for c in accept_ids if c > ids[-1]],
                })
                ordinal += 1
        for cid in accept_ids:
            unit = units[cid]
            start, end = unit.get("start_sec"), unit.get("end_sec")
            out.append({
                "region_id": f"{song_id}:w{window_index}:accept:{cid}", "song_id": song_id,
                "language": shadow.get("language"), "window_index": window_index,
                "seed_kind": "accept_control", "target_unit_ids": [cid], "detector_state": "ACCEPT",
                "overlap_interval_sec": [start, end] if isinstance(start, (int, float)) and isinstance(end, (int, float)) else None,
                "baseline_available": (isinstance(start, (int, float)) and isinstance(end, (int, float))
                                       and float(end) > float(start) >= 0.0),
                "left_anchor_candidates": [c for c in accept_ids if c < cid],
                "right_anchor_candidates": [c for c in accept_ids if c > cid],
            })
    return out


def assign_gt_stratum(population: Sequence[Mapping[str, Any]], baseline_gt: Mapping[Any, Mapping[str, Any]], *, catastrophic_region: set[str] | None = None) -> list[dict[str, Any]]:
    """Evaluator-only baseline strata; malformed/missing GT is auditable, never guessed."""
    catastrophic_region = catastrophic_region or set()
    out = []
    for source in population:
        row = dict(source)
        if row.get("baseline_available") is False:
            row.update(stratum_status="ineligible_invalid_baseline_interval", stratum=None, origin="natural")
            out.append(row)
            continue
        errors = []
        for cid in row["target_unit_ids"]:
            # canonical ids are document-global, not corpus-global: prefer a
            # (song_id, canonical_id) lookup and retain int-only support for
            # single-song evaluators.
            gt = baseline_gt.get((str(row["song_id"]), int(cid)), baseline_gt.get(int(cid), {}))
            value = gt.get("max_boundary_error_ms")
            if not isinstance(value, (int, float)):
                errors = []
                row["stratum_status"] = "ineligible_missing_baseline_gt"
                break
            errors.append(float(value))
        if not errors:
            row.setdefault("stratum_status", "ineligible_missing_baseline_gt")
            row["stratum"] = None
        elif row["region_id"] in catastrophic_region or any(x > 1000.0 for x in errors):
            row.update(stratum_status="eligible", stratum="S4" if row["detector_state"] == "ACCEPT" else "S3")
        elif all(x <= 200.0 for x in errors):
            row.update(stratum_status="eligible", stratum="S1" if row["detector_state"] == "ACCEPT" else "S2")
        else:
            row.update(stratum_status="boundary_grey", stratum="BOUNDARY")
        row["origin"] = "natural"
        out.append(row)
    return out


def _overlaps(a: list[float] | None, b: list[float] | None) -> bool:
    return bool(a and b and max(float(a[0]), float(b[0])) < min(float(a[1]), float(b[1])))


def balanced_replenishment(population: Sequence[Mapping[str, Any]], *, target_per_stratum: int,
                           selected_region_ids: set[str] | None = None,
                           prior_selected: Sequence[Mapping[str, Any]] = (),
                           per_song_cap: int = 4, max_per_song_cap: int = 8) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select non-overlapping natural cases fairly, with an explicit exhaustion audit."""
    selected_region_ids = selected_region_ids or set()
    selected: list[dict[str, Any]] = []
    used_ids: set[tuple[str, int]] = set()
    used_intervals: list[tuple[str, list[float]]] = []
    by_stratum: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in population:
        if row.get("stratum") in {"S1", "S2", "S3", "S4"} and row.get("origin", "natural") == "natural":
            by_stratum[str(row["stratum"])].append(row)
    counts: dict[str, int] = defaultdict(int)
    song_counts: dict[str, int] = defaultdict(int)
    # Resume must preserve diversity and non-overlap constraints from previous
    # batches, not merely avoid identical region IDs.
    for row in prior_selected:
        song = str(row.get("song_id"))
        song_counts[song] += 1
        stratum = row.get("stratum")
        if stratum in {"S1", "S2", "S3", "S4"}:
            counts[str(stratum)] += 1
        for cid in row.get("target_unit_ids") or []:
            try:
                used_ids.add((song, int(cid)))
            except (TypeError, ValueError):
                continue
        interval = row.get("overlap_interval_sec")
        if interval:
            used_intervals.append((song, interval))
    reasons: dict[str, int] = defaultdict(int)
    cap = per_song_cap
    while True:
        progressed = False
        for stratum in ("S1", "S2", "S3", "S4"):
            if counts[stratum] >= target_per_stratum:
                continue
            candidates = sorted(by_stratum[stratum], key=lambda r: (song_counts[str(r.get("song_id"))] > 0, str(r.get("song_id")), str(r.get("region_id"))))
            for row in candidates:
                rid, song = str(row["region_id"]), str(row["song_id"])
                targets = {(song, int(cid)) for cid in row["target_unit_ids"]}
                interval = row.get("overlap_interval_sec")
                if rid in selected_region_ids or any(x["region_id"] == rid for x in selected): reasons["already_selected"] += 1; continue
                if song_counts[song] >= cap: reasons["per_song_cap"] += 1; continue
                if targets & used_ids: reasons["target_overlap"] += 1; continue
                if any(prior_song == song and _overlaps(interval, prior) for prior_song, prior in used_intervals): reasons["time_overlap"] += 1; continue
                selected.append(dict(row)); counts[stratum] += 1; song_counts[song] += 1; used_ids |= targets
                if interval: used_intervals.append((song, interval))
                progressed = True
                break
        if all(counts[s] >= target_per_stratum for s in ("S1", "S2", "S3", "S4")):
            break
        if not progressed:
            if cap < max_per_song_cap:
                cap = max_per_song_cap
                continue
            break
    return selected, {"schema": "unit_realign_replenishment_audit_v2", "target_per_stratum": target_per_stratum,
                       "selected_per_stratum": dict(counts), "selected_per_song": dict(song_counts),
                       "per_song_cap_final": cap, "exclusion_reasons": dict(reasons),
                       "status": "complete" if all(counts[s] >= target_per_stratum for s in ("S1", "S2", "S3", "S4")) else "exhausted"}


def adaptive_sample(population: Sequence[Mapping[str, Any]], *, target: int, per_song_cap: int = 4) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Legacy no-GT song-fair screen sampler."""
    by_song: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sorted(population, key=lambda x: (str(x.get("song_id")), str(x.get("region_id")))):
        by_song[str(row.get("song_id"))].append(row)
    selected, taken = [], defaultdict(int)
    while len(selected) < target:
        progressed = False
        for song in sorted(by_song):
            if len(selected) >= target: break
            if taken[song] >= per_song_cap or not by_song[song]: continue
            selected.append(dict(by_song[song].pop(0))); taken[song] += 1; progressed = True
        if not progressed: break
    return selected, {"requested": target, "selected": len(selected), "per_song_cap": per_song_cap,
                      "status": "complete" if len(selected) >= target else "exhausted", "selected_per_song": dict(taken)}
