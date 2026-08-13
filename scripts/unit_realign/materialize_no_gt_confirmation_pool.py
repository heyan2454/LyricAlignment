#!/usr/bin/env python3
"""Freeze a detector-only confirmation pool without reading GT or errors."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from lyricalign.unit_realign.region_sampling import _overlaps


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _baseline_interval(row):
    """Return [start, end] for a strictly positive-length baseline interval or None."""
    iv = row.get("overlap_interval_sec")
    if not isinstance(iv, (list, tuple)) or len(iv) < 2:
        return None
    try:
        start, end = float(iv[0]), float(iv[1])
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    return [start, end]


def partition_eligible(candidates):
    """Only baseline_available=true rows with a valid (end > start) interval enter the eligible pool."""
    eligible, excluded = [], []
    for row in candidates:
        if row.get("baseline_available") is True and _baseline_interval(row) is not None:
            eligible.append(row)
        else:
            excluded.append(dict(row, exclusion_reason="ineligible_invalid_baseline_interval"))
    return eligible, excluded


def choose(candidates, count, cap, seed, state=None):
    """Song-fair round-robin pick that never reuses a (song, canonical unit id)
    target or a same-song strictly overlapping time interval."""
    state = state if state is not None else {
        "used": defaultdict(int), "used_targets": set(), "used_intervals": []}
    by_song = defaultdict(list)
    for row in candidates:
        by_song[row["song_id"]].append(row)
    rng = random.Random(seed)
    for song in by_song:
        by_song[song].sort(key=lambda x: (x["region_id"], x["target_unit_ids"]))
        rng.shuffle(by_song[song])
    selected, excluded = [], []
    while len(selected) < count:
        progress = False
        for song in sorted(by_song):
            if len(selected) >= count:
                break
            if not by_song[song]:
                continue
            row = by_song[song][0]
            targets = {(song, int(cid)) for cid in row["target_unit_ids"]}
            interval = _baseline_interval(row)
            if state["used"][song] >= cap:
                reason = "per_song_cap"
            elif targets & state["used_targets"]:
                reason = "duplicate_target_unit"
            elif interval is None:
                reason = "ineligible_invalid_baseline_interval"
            elif any(prior_song == song and _overlaps(interval, prior)
                     for prior_song, prior in state["used_intervals"]):
                reason = "time_overlap"
            else:
                reason = None
            if reason is not None:
                excluded.append(dict(row, exclusion_reason=reason))
                by_song[song].pop(0)
                progress = True
                continue
            selected.append(row)
            by_song[song].pop(0)
            state["used"][song] += 1
            state["used_targets"] |= targets
            if interval is not None:
                state["used_intervals"].append((song, interval))
            progress = True
        if not progress:
            break
    for song in sorted(by_song):
        while by_song[song]:
            excluded.append(dict(by_song[song].pop(0), exclusion_reason="not_selected"))
    return selected, excluded, state


def build_case(region, detector_shadow, outside_unit_ids):
    song, index = region["song_id"], int(region["window_index"])
    target_ids = [int(x) for x in region["target_unit_ids"]]
    unit_map = detector_shadow.get("units") or {}
    states = [str(unit_map[str(cid)].get("state", "")).upper() for cid in target_ids]
    state = "ACCEPT" if region["detector_state"] == "ACCEPT" else (
        "REJECT" if "REJECT" in states else "UNCERTAIN")
    window_cids = [int(cid) for cid in unit_map]
    fixed_context = sorted(cid for cid in window_cids if cid not in set(target_ids))
    old_units = [
        {"canonical_unit_id": int(cid), "start_sec": value.get("start_sec"), "end_sec": value.get("end_sec"),
         "p_bad": value.get("p_bad"), "state": value.get("state")}
        for cid, value in unit_map.items()
    ]
    return {
        "case_id": f"{song}:w{index}:confirmation:{region['region_id']}",
        "song_id": song, "window_id": f"{song}:w{index}:full", "window_index": index,
        "active_target_unit_ids": target_ids, "target_unit_ids": target_ids,  # compatibility alias
        "fixed_context_unit_ids": fixed_context,
        "outside_unit_ids": sorted(outside_unit_ids),
        "baseline_audio_range_sec": region.get("overlap_interval_sec"),
        "old_detector_state": state,
        "seed_kind": region["seed_kind"],
        "old_units": old_units,
        "old_units_scope": "whole_window_reference_not_target_or_context",
        "detector_shadow": detector_shadow, "source": "detector_only_confirmation_pool_v1",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", required=True, type=Path)
    parser.add_argument("--shadow", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--unsafe-count", type=int, default=45)
    parser.add_argument("--accept-count", type=int, default=15)
    parser.add_argument("--per-song-cap", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--split-manifest", type=Path,
                        help="optional frozen timeline manifest used only to select a named source split")
    parser.add_argument("--source-split", help="split value required with --split-manifest")
    args = parser.parse_args()
    shadow = {(x["song_id"], int(x["window_index"])): x["detector_shadow"] for x in rows(args.shadow)}
    population = rows(args.regions)
    if args.split_manifest or args.source_split:
        if not args.split_manifest or not args.source_split:
            parser.error("--split-manifest and --source-split must be supplied together")
        allowed = {x["song_id"] for x in rows(args.split_manifest) if x.get("source_split") == args.source_split}
        population = [x for x in population if x["song_id"] in allowed]
    unsafe = [x for x in population if x.get("detector_state") == "UNSAFE"]
    accept = [x for x in population if x.get("detector_state") == "ACCEPT"]
    eligible_unsafe, excluded_ineligible_unsafe = partition_eligible(unsafe)
    eligible_accept, excluded_ineligible_accept = partition_eligible(accept)
    picked_unsafe, excluded_choose_unsafe, state = choose(
        eligible_unsafe, args.unsafe_count, args.per_song_cap, args.seed)
    controls = [x for x in eligible_accept if state["used"][x["song_id"]] < args.per_song_cap]
    picked_accept, excluded_choose_accept, _ = choose(
        controls, args.accept_count, args.per_song_cap, args.seed + 1, state)
    selected = picked_unsafe + picked_accept
    all_excluded = (excluded_ineligible_unsafe + excluded_choose_unsafe
                    + excluded_ineligible_accept + excluded_choose_accept)
    excluded_by_reason = Counter(x["exclusion_reason"] for x in all_excluded)
    song_cids = defaultdict(set)
    for (song, _window), detector in shadow.items():
        song_cids[song] |= {int(cid) for cid in (detector.get("units") or {})}
    cases = []
    for region in selected:
        song, index = region["song_id"], int(region["window_index"])
        detector = shadow[(song, index)]
        window_cids = {int(cid) for cid in (detector.get("units") or {})}
        outside = sorted(song_cids[song] - window_cids)
        cases.append(build_case(region, detector, outside))
    audit = {
        "schema": "unit_realign_no_gt_confirmation_pool_v1", "gt_access": False,
        "requested": {"unsafe": args.unsafe_count, "accept": args.accept_count},
        "available": {"unsafe": len(unsafe), "accept": len(accept)},
        "eligible": {"unsafe": len(eligible_unsafe), "accept": len(eligible_accept), "total": len(eligible_unsafe) + len(eligible_accept)},
        "eligible_total": len(eligible_unsafe) + len(eligible_accept),
        "excluded_total": len(all_excluded),
        "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
        "excluded": all_excluded,
        "selected": {"unsafe": len(picked_unsafe), "accept": len(picked_accept), "total": len(cases)},
        "per_song": {song: sum(x["song_id"] == song for x in cases) for song in sorted({x["song_id"] for x in cases})},
        "status": "complete" if len(picked_unsafe) == args.unsafe_count and len(picked_accept) == args.accept_count else "exhausted",
        "source_split_filter": args.source_split,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cases), encoding="utf-8")
    args.out.with_name("CONFIRMATION_POOL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
