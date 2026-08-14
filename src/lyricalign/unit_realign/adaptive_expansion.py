"""WP8 P6 adaptive expansion.

Pure-CPU orchestration that turns E1--E4 screening results into a decision: pick
the **top K (default 2) effective mechanisms** by strict recovery + safety, then
stratify a ==target_n== independent region population per mechanism plus a
song-held-out **confirmation population** (songs never used by screening or the
main expansion set). Forward expansion is only *book-kept* in the budget ledger;
no GPU forward is performed here.

Key contracts (04 ./4, 07 /9 WP8):

* No full Cartesian product across mechanisms -- only the ranked top K expand.
* No re-use of screening regions or the song-held-out songs for the main set.
* Expansion forward cost is recorded against the BUDGET_PROJECTION ledger, not run.
* Resume is idempotent: identical output root + inputs reproduce the same
  manifest unless the screening input actually changed.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
EXPANSION_SCHEMA_VERSION = "lp_unit_realign_expansion_v1"

# Schema for the pieces we emit (declarative contract, also embedded in outputs).
EXPANSION_SCHEMA: dict[str, Any] = {
    "schema_version": EXPANSION_SCHEMA_VERSION,
    "created_by": "unit_realign.adaptive_expansion",
    "inputs": {
        "screening_results": "list[E1..E6 FINAL_*.json] each with an 'aggregates' array",
        "population": "REGION_POOL.jsonl: no-GT structural regions (see region_sampling)",
        "screening_region_ids": "list[str] region_ids already consumed by screening",
    },
    "outputs": {
        "MECHANISM_RANKING.json": "ranked mechanisms + rationale (recovery/context/catastrophic/fwd)",
        "EXPANSION_MANIFEST.jsonl": ">=target_n expansion regions + confirmation flag per request",
        "RUN_STATE.json": "idempotent resume state keyed by screening digest",
        "FINAL_EXPANSION.json": "counts / budget projection / overage audit (no overwrite)",
    },
    "notes": (
        "No full cartesian product; only ranked top-K mechanisms expand. "
        "Forward is ledger-only here; the real forward runs via WP3/4/6 runners "
        "consuming EXPANSION_MANIFEST.jsonl."
    ),
}


# --------------------------------------------------------------------------- #
# Metric extraction (schema-tolerant across E1..E4 FINAL aggregates)
# --------------------------------------------------------------------------- #
def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _rate(value: Any) -> float | None:
    """Normalize a recovery ratio (0..1). Accepts bool, 0..1 float or 0..100."""
    f = _num(value)
    if f is None:
        return None
    return f / 100.0 if f > 1.0 else f


def region_recovery(row: Mapping[str, Any]) -> dict[str, float | None]:
    """Best-effort strict recovery for one region aggregate row.

    Looks up a priority list of field-name conventions used by WP3/4/6 aggregate
    rows so ranking works regardless of which runner produced the row:
    ``region_strict_100``, ``strict_100``, ``best_strict_100``, ``r100``... and
    the 200 ms variants. ``all_targets_hit`` / ``region_all_hit`` is treated as
    the 200-ms-ish gate when present.
    """
    fields_100 = ("region_strict_100", "strict_100", "best_strict_100", "best_100", "hit_100", "r100",
                  "strict_100_ratio", "region_recovery_100")
    fields_200 = ("region_strict_200", "strict_200", "best_strict_200", "best_200", "hit_200", "r200",
                  "strict_200_ratio", "region_recovery_200")
    strict_100 = strict_200 = None
    for key in fields_100:
        if key in row:
            strict_100 = _rate(row[key])
            break
    for key in fields_200:
        if key in row:
            strict_200 = _rate(row[key])
            break
    all_hit = None
    for key in ("all_targets_hit", "region_all_hit", "all_hit", "region_all_targets_hit"):
        if key in row:
            all_hit = bool(row[key])
            break
    return {"strict_100": strict_100, "strict_200": strict_200,
            "all_targets_hit": all_hit, "recovery_best": strict_200 if strict_200 is not None else (strict_100 if strict_100 is not None else None)}

def region_safety(row: Mapping[str, Any]) -> dict[str, float | None]:
    """Context displacement (lower better) and catastrophic flag."""
    ctx = None
    for key in ("fixed_context_displacement_ms", "fixed_context_displacement",
                "context_displacement_ms", "max_fixed_context_displacement_ms",
                "mean_fixed_context_displacement_ms", "max_context_displacement_ms"):
        if key in row:
            ctx = _num(row[key])
            if ctx is not None:
                break
    catastrophic = None
    for key in ("catastrophic_regression", "catastrophic", "catastrophic_regression_units"):
        if key in row:
            catastrophic = bool(row[key]) if not isinstance(row[key], (list, tuple)) else bool(row[key])
            break
    # danger_flag style: strings mentioning catastrophic
    flags = row.get("danger_flags") or row.get("warnings") or ()
    if isinstance(flags, (list, tuple)) and not catastrophic:
        catastrophic = any("catastrophic" in str(f) for f in flags)
    return {"context_displacement_ms": ctx, "catastrophic": catastrophic}


def mechanism_metrics(aggregates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate per-mechanism metrics from a list of region aggregate rows."""
    rows = [dict(r) for r in aggregates]
    if not rows:
        return {"n_regions": 0, "mean_strict_100": None, "mean_strict_200": None,
                "region_all_hit_ratio": None, "mean_context_displacement_ms": None,
                "catastrophic_ratio": None, "mean_forward_attempts": None,
                "recovery_score": 0.0, "safety_score": 0.0, "composite_score": 0.0}

    r100 = [r["strict_100"] for r in (region_recovery(x) for x in rows) if r["strict_100"] is not None]
    r200 = [r["strict_200"] for r in (region_recovery(x) for x in rows) if r["strict_200"] is not None]
    all_hit = [r["all_targets_hit"] for r in (region_recovery(x) for x in rows)
               if r["all_targets_hit"] is not None]
    safety = [region_safety(x) for x in rows]
    ctx = [s["context_displacement_ms"] for s in safety if s["context_displacement_ms"] is not None]
    catast = [s["catastrophic"] for s in safety if s["catastrophic"] is not None]

    n_fwd = []
    for r in rows:
        f = _num(r.get("forward_attempts", r.get("n_forward", r.get("forward_count"))))
        if f is not None and f >= 0:
            n_fwd.append(f)

    mean_r100 = sum(r100) / len(r100) if r100 else None
    mean_r200 = sum(r200) / len(r200) if r200 else None
    all_hit_ratio = sum(1 for x in all_hit if x) / len(all_hit) if all_hit else None
    mean_ctx = sum(ctx) / len(ctx) if ctx else None
    catastrophic_ratio = sum(1 for x in catast if x) / len(catast) if catast else None
    mean_fwd = sum(n_fwd) / len(n_fwd) if n_fwd else None

    # --- composite scoring (frozen for the round; see _X_wp8_expansion.md) ---
    # recovery = strict 200 mean (gate) with strict 100 upweight; 0 if unknown.
    recovery_score = 0.0
    if mean_r200 is not None:
        recovery_score = mean_r200
        if mean_r100 is not None:
            recovery_score = 0.6 * mean_r200 + 0.4 * mean_r100
    # safety = 1 - normalized context displacement - catastrophic penalty.
    safety_score = 1.0
    if mean_ctx is not None:
        safety_score -= min(1.0, mean_ctx / 1000.0)
    if mean_ctx is None and ctx:  # unlikely; ctx list nonempty means mean not none
        pass
    if catastrophic_ratio is not None:
        safety_score -= 1.5 * catastrophic_ratio
    safety_score = max(0.0, safety_score)
    # fwd: mild penalty, never dominates (fewer forwards is better; guard the sign).
    if mean_fwd is not None:
        fwd_penalty = min(0.10, mean_fwd / 160.0)  # >=16 forwards -> 0.10 off
        fwd_component = -fwd_penalty
    else:
        fwd_penalty = 0.0
        fwd_component = 0.0

    composite = recovery_score * 0.55 + safety_score * 0.35 + fwd_component

    return {
        "n_regions": len(rows),
        "mean_strict_100": round(mean_r100, 4) if mean_r100 is not None else None,
        "mean_strict_200": round(mean_r200, 4) if mean_r200 is not None else None,
        "region_all_hit_ratio": round(all_hit_ratio, 4) if all_hit_ratio is not None else None,
        "mean_context_displacement_ms": round(mean_ctx, 4) if mean_ctx is not None else None,
        "catastrophic_ratio": round(catastrophic_ratio, 4) if catastrophic_ratio is not None else None,
        "mean_forward_attempts": round(mean_fwd, 4) if mean_fwd is not None else None,
        "recovery_score": round(recovery_score, 4),
        "safety_score": round(safety_score, 4),
        "fwd_penalty": round(fwd_penalty if mean_fwd is not None else 0.0, 4),
        "composite_score": round(composite, 4),
    }


def rank_mechanisms(screening_results: Mapping[str, Sequence[Mapping[str, Any]]],
                    *, top_k: int = 2) -> list[dict[str, Any]]:
    """Rank mechanisms (E1..E4) by strict recovery + safety.

    ``screening_results`` maps a mechanism id (e.g. ``E1_direct_i5``) to its
    per-region aggregate list from the corresponding FINAL_*.json ``aggregates``.
    Returns a ranked list (best first) of dicts, each with rationale.
    """
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    scored: list[dict[str, Any]] = []
    for mech, aggregates in screening_results.items():
        agg = mechanism_metrics(aggregates or [])
        scored.append({
            "mechanism_id": str(mech),
            **agg,
            "rationale": _rationale(mech, agg),
        })
    # Require at least one usable recovery observation, else it cannot expand.
    eligible = [s for s in scored if s["n_regions"] > 0 and s["recovery_score"] > 0.0]
    scored_sorted = sorted(eligible, key=lambda s: s["composite_score"], reverse=True)
    return scored_sorted[:top_k]


def _rationale(mech: str, agg: Mapping[str, Any]) -> str:
    parts = [f"n_regions={agg['n_regions']}"]
    if agg["mean_strict_200"] is not None:
        parts.append(f"strict200={agg['mean_strict_200']:.3f}")
    if agg["mean_strict_100"] is not None:
        parts.append(f"strict100={agg['mean_strict_100']:.3f}")
    if agg["mean_context_displacement_ms"] is not None:
        parts.append(f"ctx_disp={agg['mean_context_displacement_ms']}ms")
    if agg["catastrophic_ratio"] is not None:
        parts.append(f"catastrophic={agg['catastrophic_ratio']:.3f}")
    if agg["mean_forward_attempts"] is not None:
        parts.append(f"fwd/region={agg['mean_forward_attempts']}")
    parts.append(f"composite={agg['composite_score']:.3f}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Region selection (stratified, non-overlapping main + song-held-out confirmation)
# --------------------------------------------------------------------------- #
def _overlaps(a: list[float] | None, b: list[float] | None) -> bool:
    return bool(a and b and max(float(a[0]), float(b[0])) < min(float(a[1]), float(b[1])))


def select_regions_for_expansion(
    population: Sequence[Mapping[str, Any]],
    mechanism_subset: Sequence[str],
    *,
    target_n: int = 200,
    per_song_cap: int = 6,
    screening_region_ids: Sequence[str] = (),
    confirmation_target: int = 40,
    confirmation_per_song_cap: int | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Stratified, song-fair expansion region selection.

    ``confirmation`` is **song-held-out**: a reserved set of songs is set aside up
    front and never enters the main expansion pool, so main-song and
    confirmation-song sets are strictly disjoint (and never contain screening-only
    regions). Main selection never reuses screening region ids. Returns a dict
    with ``main`` (>= ``target_n`` overall), ``confirmation`` and an audit.
    """
    import random as _random

    rng = _random.Random(seed)
    screening_ids = {str(x) for x in screening_region_ids}
    c_cap = confirmation_per_song_cap or max(1, per_song_cap)

    # Partition population by song, excluding screening regions.
    by_song: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in population:
        row = dict(raw)
        if str(row.get("region_id")) in screening_ids:
            continue
        by_song[str(row.get("song_id"))].append(row)

    all_songs = sorted(by_song.keys())
    rng.shuffle(all_songs)

    # Reserve the minimum number of songs that can hold the confirmation target.
    n_reserve = 0
    accumulated = 0
    for song in all_songs:
        accumulated += min(c_cap, len(by_song[song]))
        n_reserve += 1
        if accumulated >= confirmation_target:
            break
    reserve_songs = set(all_songs[:n_reserve]) if n_reserve else set()
    main_song_order = [s for s in all_songs if s not in reserve_songs]

    # --- main selection across non-reserved songs -------------------------- #
    main: list[dict[str, Any]] = []
    taken: Counter = Counter()
    used_intervals: list[tuple[str, list[float]]] = []
    pending_song: dict[str, list[dict[str, Any]]] = {}
    for song in main_song_order:
        rows = list(by_song[song])
        rng.shuffle(rows)
        pending_song[song] = rows
    main_pool = sorted(pending_song, key=lambda s: rng.random())
    for _ in range(target_n):
        progressed = False
        for song in main_pool:
            if len(main) >= target_n:
                break
            if taken[song] >= per_song_cap or not pending_song[song]:
                continue
            row = pending_song[song].pop(0)
            interval = row.get("overlap_interval_sec")
            if any(_overlaps(interval, prior) for prior_song, prior in used_intervals if prior_song == song):
                continue
            main.append(row)
            taken[song] += 1
            if interval:
                used_intervals.append((song, interval))
            progressed = True
            break
        if not progressed:
            break

    main_songs = set(taken.keys())

    # --- confirmation: only from the reserved held-out songs ----------------- #
    confirmation: list[dict[str, Any]] = []
    c_taken: Counter = Counter()
    conf_pool = dict((s, list(by_song[s])) for s in reserve_songs)
    for song in conf_pool:
        rng.shuffle(conf_pool[song])
    conf_order = sorted(conf_pool, key=lambda s: rng.random())
    for _ in range(confirmation_target):
        progressed = False
        for song in conf_order:
            if len(confirmation) >= confirmation_target:
                break
            if c_taken[song] >= c_cap or not conf_pool[song]:
                continue
            confirmation.append(conf_pool[song].pop(0))
            c_taken[song] += 1
            progressed = True
            break
        if not progressed:
            break

    confirmation_songs = set(c_taken.keys())

    mechanism_subset = [str(m) for m in mechanism_subset]
    main_rows = [dict(r, mechanism=mechanism_subset, confirmation=False) for r in main]
    conf_rows = [dict(r, mechanism=mechanism_subset, confirmation=True) for r in confirmation]

    audit = {
        "schema": EXPANSION_SCHEMA_VERSION,
        "target_n": target_n, "selected_main": len(main_rows),
        "confirmation_target": confirmation_target, "selected_confirmation": len(conf_rows),
        "per_song_cap": per_song_cap, "confirmation_per_song_cap": c_cap,
        "n_songs_total": len(all_songs),
        "n_songs_reserved_confirmation": len(reserve_songs),
        "n_songs_used_main": len(main_songs),
        "n_songs_used_confirmation": len(confirmation_songs),
        "n_screening_regions_excluded": len(screening_ids),
        "song_sets_disjoint": bool(main_songs.isdisjoint(confirmation_songs)),
        "main_status": "complete" if len(main_rows) >= target_n else "exhausted",
        "confirmation_status": "complete" if len(conf_rows) >= confirmation_target else "exhausted",
    }
    return {
        "main": main_rows,
        "confirmation": conf_rows,
        "audit": audit,
        "mechanism_subset": mechanism_subset,
    }


# --------------------------------------------------------------------------- #
# Manifest building + budget ledger
# --------------------------------------------------------------------------- #
def build_confirmation_manifest(regions: Sequence[Mapping[str, Any]],
                                mechanism: str, *,
                                out: Any = None) -> list[dict[str, Any]]:
    """Emit REQUESTS.jsonl rows for real forward expansion.

    Each request carries the structural region payload plus the mechanism/family
    so the WP3/4/6 runner can dispatch the top-K mechanism. Matching
    ``build_family_request`` identity conventions: family + region + song are the
    identity-bearing fields tracked by the ledger.
    """
    mech = str(mechanism)
    family = MECHANISM_FAMILY.get(mech, family_for_mechanism(mech))
    requests: list[dict[str, Any]] = []
    for row in regions:
        req = {
            "schema": "lp_unit_realign_expansion_request_v1",
            "kind": "expansion",
            "mechanism_id": mech,
            "family": family,
            "expansion_set": "confirmation" if row.get("confirmation") else "main",
            "region_id": str(row.get("region_id")),
            "song_id": str(row.get("song_id")),
            "window_index": row.get("window_index"),
            "language": row.get("language"),
            "target_unit_ids": list(row.get("target_unit_ids") or []),
            "baseline_available": bool(row.get("baseline_available", True)),
            **{k: v for k, v in row.items() if k not in
               {"region_id", "song_id", "window_index", "language", "target_unit_ids",
                "baseline_available", "mechanism", "confirmation"}},
        }
        # compact request_identity digest for ledger de-dup / resume
        req["request_identity"] = _request_identity(req)
        requests.append(req)
    if out is not None:
        _write_jsonl(out, requests)
    return requests


# Default family: derive from mechanism id prefix erring on R-U (the generic
# coarse<-fine / refine family used by WP3/4/6). E2 split uses R-U1/R-U3 etc.
MECHANISM_FAMILY: dict[str, str] = {
    "E1_direct": "R-U", "E1_recrop": "R-U", "E1_perturb": "R-U",
    "E2_one_unit": "R-U1", "E2_two_unit": "R-U2", "E2_adaptive": "R-U",
    "E2_anchor_gap": "R-B", "E4_coarse_fine": "R-U",
}


def family_for_mechanism(mech: str) -> str:
    norm = mech.lower()
    if "anchor" in norm:
        return "R-B"
    if "one_unit" in norm or "split" in norm and "two" in norm:
        return "R-U1" if "one" in norm else "R-U"
    return "R-U"


def _request_identity(req: Mapping[str, Any]) -> str:
    import hashlib
    canonical = json.dumps({
        "mechanism_id": req.get("mechanism_id"),
        "family": req.get("family"),
        "region_id": req.get("region_id"),
        "song_id": req.get("song_id"),
        "target_unit_ids": sorted(map(int, req.get("target_unit_ids") or [])),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


# --------------------------------------------------------------------------- #
# Persistence helpers
# --------------------------------------------------------------------------- #
def _write_json(path: Any, obj: Any) -> None:
    import os
    p = os.fspath(path)
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _write_jsonl(path: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    import os
    p = os.fspath(path)
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
