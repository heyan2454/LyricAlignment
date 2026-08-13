#!/usr/bin/env python3
"""Unit-level realign orchestration: population, screen and resume-aware expansion.

This controller writes only lightweight manifests.  Model forwards remain
owned by scripts/research_v7/run_behavior_suite.py so cache identity and
real-executor provenance have one authoritative implementation.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.controller import choose_surviving_families, expansion_plan
from lyricalign.unit_realign.intervention_check import validate_request
from lyricalign.unit_realign.request_families import UNIT_REQUEST_SCHEMA, build_family_request
from lyricalign.unit_realign.region_sampling import (
    adaptive_sample, assign_gt_stratum, balanced_replenishment, build_region_population,
)
from lyricalign.unit_realign.source_adapter import (
    attach_audio_and_identity, attach_real_units, load_jsonl, make_real_identity_context,
)
from lyricalign.unit_realign.unit_outcome import aggregate_candidate_outcome, aggregate_region_outcome, pair_unit_outcomes


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows))


def _atomic_write(path: Path, payload: str) -> None:
    """A complete manifest is visible, or the prior complete manifest is."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


_IDENTITY_FIELDS = ("completed_identities", "queued_identities", "planned_identities",
                    "failed_identities", "null_identities", "not_constructible_identities")

_STATE_MACHINE_NOTE = ("planned -> queued -> running -> "
                       "executed|failed|invalid|null|not_constructible; "
                       "--resume skips only executed/completed identities; "
                       "queued/planned are re-derived idempotently on each execute "
                       "(FORWARDS.jsonl overwritten, never accumulated); "
                       "completed_identities/completed_region_ids are backfilled by "
                       "evaluate only once real baseline/candidate evidence exists")


def _state(root: Path):
    path = root / "07_runtime" / "RUN_STATE.json"
    if not path.exists():
        return {"schema": "unit_realign_run_state_v2", "state_machine": _STATE_MACHINE_NOTE,
                "completed_region_ids": [], **{key: [] for key in _IDENTITY_FIELDS},
                "updated_at_utc": None}
    state = json.loads(path.read_text(encoding="utf-8"))
    state["schema"] = "unit_realign_run_state_v2"
    state["state_machine"] = _STATE_MACHINE_NOTE
    state.setdefault("completed_region_ids", [])
    for key in _IDENTITY_FIELDS:
        state.setdefault(key, [])
    return state


def _record_identity(state: dict, identity: str, status: str) -> None:
    """Record an identity by dispatch status; ready/valid never mark completed.

    ready/valid land in ``queued_identities`` (current forward plan) and
    ``planned_identities`` (cumulative audit log).  ``completed_identities``
    is backfilled only by evaluate once real evidence has been evaluated.
    """
    bucket = {"null": "null_identities", "not_constructible": "not_constructible_identities",
              "ready": "queued_identities", "valid": "queued_identities"}.get(status, "failed_identities")
    if identity and identity not in state.setdefault(bucket, []):
        state[bucket].append(identity)
    if identity and status in {"ready", "valid"} and identity not in state.setdefault("planned_identities", []):
        state["planned_identities"].append(identity)


_REQUIRED_IDENTITY_KEYS = ("audio_sha256", "baseline_digest", "model_identity", "checkpoint_identity",
                           "decoder_identity", "mapping_schema", "code_identity", "text_adapter_identity")


_P1_A_FAMILIES = ("R-U", "R-A", "R-B", "R-S")


def _region_to_request(region: dict, *, request_config: dict | None = None) -> dict:
    """Build the primary v2 request for a REGION_POOL/P1_SELECTED_REGIONS row.

    ``family`` comes from the region row when the caller has already assigned
    it (per-case family materialization); otherwise defaults to R-U.
    """
    family = str(region.get("family") or "R-U")
    return _build_family_request(region, family=family, request_config=request_config)


def _region_to_requests(region: dict, *, request_config: dict | None = None) -> list[dict]:
    """Materialize all four P1-A families for one case (region).

    One request is produced per family; a family that cannot be constructed
    yields its own not-constructible/null row instead of silently dropping the
    case.  ``stratum`` is threaded through for family x stratum accounting.
    """
    return [_build_family_request(region, family=family, request_config=request_config)
            for family in _P1_A_FAMILIES]


def _build_family_request(region: dict, *, family: str, request_config: dict | None = None) -> dict:
    """Build one v2 request of ``family`` from a REGION_POOL row."""
    song_id, region_id = str(region.get("song_id") or ""), str(region.get("region_id") or "")
    if not song_id or not region_id:
        return {"schema": UNIT_REQUEST_SCHEMA, "family": family, "requested_family": family,
                "song_id": song_id, "region_id": region_id, "status": "not_constructible",
                "reason": "missing_song_or_region", "stratum": region.get("stratum")}
    units = region.get("units")
    if not units:
        return {"schema": UNIT_REQUEST_SCHEMA, "family": family, "requested_family": family,
                "song_id": song_id, "region_id": region_id, "status": "not_constructible",
                "reason": "missing_region_units", "stratum": region.get("stratum")}
    targets = [int(x) for x in region.get("target_unit_ids") or ()]
    ctx = dict(region.get("identity_context") or {})
    missing = [key for key in _REQUIRED_IDENTITY_KEYS if not ctx.get(key)]
    if missing:
        return {"schema": UNIT_REQUEST_SCHEMA, "family": family, "requested_family": family,
                "song_id": song_id, "region_id": region_id, "status": "not_constructible",
                "reason": "missing_identity_context:" + ",".join(missing), "stratum": region.get("stratum")}
    kwargs = dict(family=family, song_id=song_id, region_id=region_id,
                  audio_path=str(region.get("audio_path") or f"{song_id}.wav"),
                  units=units, target_unit_ids=targets, identity_context=ctx,
                  **({k: request_config[k] for k in ("audio_margin_sec", "context_neighbors", "ra_context_units")
                      if request_config and k in request_config}))
    if family == "R-B":
        left, right = region.get("left_anchor_id"), region.get("right_anchor_id")
        if left is None or right is None:
            lefts = sorted(int(c) for c in (region.get("left_anchor_candidates") or ())
                           if targets and int(c) < min(targets))
            rights = sorted(int(c) for c in (region.get("right_anchor_candidates") or ())
                            if targets and int(c) > max(targets))
            left, right = lefts[-1] if lefts else None, rights[0] if rights else None
        kwargs.update(left_anchor_id=left, right_anchor_id=right,
                      left_accept_anchor_candidates=region.get("left_anchor_candidates"),
                      right_accept_anchor_candidates=region.get("right_anchor_candidates"))
    try:
        request = build_family_request(**kwargs)
    except Exception as exc:
        return {"schema": UNIT_REQUEST_SCHEMA, "family": family, "requested_family": family,
                "song_id": song_id, "region_id": region_id, "status": "not_constructible",
                "reason": f"construction_failed:{type(exc).__name__}", "stratum": region.get("stratum")}
    request["stratum"] = region.get("stratum")
    request["stratum_status"] = region.get("stratum_status")
    return request


def _missing_evidence_report(not_evaluated: list[dict]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    for row in not_evaluated:
        family = str(row.get("family") or "unknown")
        stratum = str(row.get("stratum") or "unknown")
        counts.setdefault(family, {}).setdefault(stratum, 0)
        counts[family][stratum] += 1
    reasons = {r: sum(1 for x in not_evaluated if x.get("reason") == r)
               for r in sorted({x.get("reason") for x in not_evaluated})}
    return {"schema": "unit_realign_missing_evidence_report_v1",
            "n_not_evaluated": len(not_evaluated),
            "counts_by_family_stratum": counts, "reasons": reasons}


def _family_stratum_accounting(root: Path, status_rows: list[dict], forward_rows: list[dict],
                              candidate_rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Per-(family, stratum) accounting of the case status matrix.

    Matches the frozen contract's case matrix: every case materializes all four
    P1-A families; each family x stratum is counted independently so a formal run
    can be audited against the 25-valid-per-stratum gate.
    """
    accounting: dict[str, dict[str, dict]] = {}
    for row in status_rows:
        family = str(row.get("family") or "unknown")
        stratum = str(row.get("stratum") or "unknown")
        bucket = accounting.setdefault(family, {}).setdefault(stratum, {
            "n_selected": 0, "n_constructible": 0, "n_executed": 0, "n_null": 0,
            "n_not_constructible": 0, "n_failed": 0, "n_invalid": 0, "n_valid": 0})
        bucket["n_selected"] += 1
        status = row.get("status")
        if status == "not_constructible":
            bucket["n_not_constructible"] += 1
        elif status == "null":
            bucket["n_null"] += 1
        elif status == "invalid":
            bucket["n_invalid"] += 1
        elif status in {"ready", "valid"}:
            bucket["n_constructible"] += 1
            if status == "valid":
                bucket["n_valid"] += 1
    for row in forward_rows:
        family = str(row.get("family") or "unknown")
        stratum = str(row.get("stratum") or "unknown")
        bucket = accounting.setdefault(family, {}).setdefault(stratum, {
            "n_selected": 0, "n_constructible": 0, "n_executed": 0, "n_null": 0,
            "n_not_constructible": 0, "n_failed": 0, "n_invalid": 0, "n_valid": 0})
        bucket["n_executed"] += 1
    for row in candidate_rows:
        family = str(row.get("family") or "unknown")
        stratum = str(row.get("stratum") or "unknown")
        bucket = accounting.setdefault(family, {}).setdefault(stratum, {
            "n_selected": 0, "n_constructible": 0, "n_executed": 0, "n_null": 0,
            "n_not_constructible": 0, "n_failed": 0, "n_invalid": 0, "n_valid": 0})
        if row.get("outcome") == "beneficial":
            bucket["n_valid"] = max(bucket["n_valid"], row.get("n_regions", 0))
    return accounting


def _units_by_window(units_rows) -> dict[tuple[str, Any], list[dict]]:
    by: dict[tuple[str, Any], list[dict]] = {}
    for row in units_rows:
        song = str(row.get("song_id") or "")
        index = row.get("window_index")
        if index is None and row.get("window_id"):
            index = int(str(row["window_id"]).rsplit(":", 1)[-1])
        key = (song, index)
        by.setdefault(key, []).append(row)
    return by


def _attach_source_context(population: list[dict], *, inventory: Path, audio_dir: Path | None,
                           shadow: list[dict], text_adapter_identity: str) -> tuple[list[dict], dict]:
    """P0-A: enrich REGION_POOL from the frozen detector inventory.

    Reads BASELINE_UNITS.jsonl / BASELINE_WINDOW_INDEX.jsonl /
    DETECTOR_BASELINE_IDENTITY.json of the detector run, attaches per-window
    units, audio path/sha256 and the 8-key execution identity_context, and
    returns ``(regions, audit)``.
    """
    units = load_jsonl(inventory / "BASELINE_UNITS.jsonl")
    window_index = load_jsonl(inventory / "BASELINE_WINDOW_INDEX.jsonl")
    shadow_by = {(str(row.get("song_id") or ""), row.get("window_index")): row.get("detector_shadow") or {}
                 for row in shadow}
    enriched, units_audit = attach_real_units(
        population, _units_by_window(units), shadow_by_window=shadow_by)
    identity = make_real_identity_context(inventory, text_adapter_identity=text_adapter_identity)
    enriched, audio_audit = attach_audio_and_identity(
        enriched, window_index, identity, audio_dir=audio_dir)
    audit = {"schema": "unit_realign_source_context_attach_v1",
             "n_regions": len(enriched),
             "n_ready": audio_audit["n_ready"],
             "units_audit": units_audit,
             "audio_audit": audio_audit}
    return enriched, audit


def _materialize_requests_from_regions(root: Path, requests_path: Path,
                                       request_config: dict | None = None) -> bool:
    """Materialize 01_requests/REQUESTS.jsonl from P1_SELECTED_REGIONS when absent.

    Emits one request per (case, P1-A family), giving the per-family
    constructible/executed/null/failed/valid accounting the frozen contract
    requires without a Cartesian product.
    """
    pool_path = root / "00_population" / "REGION_POOL.jsonl"
    selected_path = root / "01_requests" / "P1_SELECTED_REGIONS.jsonl"
    if not pool_path.exists() or not selected_path.exists():
        return False
    requests = [request for row in _read_jsonl(selected_path)
                for request in _region_to_requests(row, request_config=request_config)]
    _write_jsonl(requests_path, requests)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("population", "screen", "expand", "p1-pool", "p1-refill",
                                            "execute", "evaluate", "report"))
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--shadow", help="BASELINE_DETECTOR_SHADOW.jsonl; required for population")
    parser.add_argument("--inventory", help="detector 00_inventory/ dir (BASELINE_UNITS + WINDOW_INDEX + identity); "
                        "P0-A source context attach for population/p1-pool")
    parser.add_argument("--audio-dir", help="base dir for relative audio_path in WINDOW_INDEX; "
                        "defaults to the repo runs data root /home/hyan/Data/lyricalign")
    parser.add_argument("--requests", help="request manifest; required for screen/evaluate")
    parser.add_argument("--features", help="no-GT feature manifest; required for screen")
    parser.add_argument("--baseline-gt", help="evaluator-only JSONL: song_id, canonical_unit_id, max_boundary_error_ms")
    parser.add_argument("--evidence-dir", help="per-request baseline/candidate JSONL pairs; required for evaluate")
    parser.add_argument("--stratified-pool", help="evaluator-only STRATIFIED_POOL.jsonl; required for p1-refill")
    parser.add_argument("--target", type=int, default=48)
    parser.add_argument("--target-per-stratum", type=int, default=25)
    parser.add_argument("--per-song-cap", type=int, default=4)
    parser.add_argument("--audio-margin-sec", type=float, default=None,
                        help="R-U/R-A audio margin beyond the target span (seconds); "
                        "defaults to the request_families default")
    parser.add_argument("--context-neighbors", type=int, default=None,
                        help="R-U neighbors on each side of the target span (0-1)")
    parser.add_argument("--ra-context-units", type=int, default=None,
                        help="R-A context units on each side of the unsafe span")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.out_root)
    if args.command in {"population", "p1-pool"}:
        if not args.shadow:
            parser.error("--shadow is required for population")
        shadow_rows = _read_jsonl(Path(args.shadow))
        population = build_region_population(shadow_rows)
        audit = None
        if args.inventory:
            audio_dir = Path(args.audio_dir) if args.audio_dir else Path("/home/hyan/Data/lyricalign")
            population, source_audit = _attach_source_context(
                population, inventory=Path(args.inventory), audio_dir=audio_dir,
                shadow=shadow_rows, text_adapter_identity="pypinyin-zh")
            _write_json(root / "00_population" / "SOURCE_ADAPTER_AUDIT.json", source_audit)
        selected, audit = adaptive_sample(population, target=args.target, per_song_cap=args.per_song_cap)
        _write_jsonl(root / "00_population" / "REGION_POOL.jsonl", population)
        _write_jsonl(root / "00_population" / "SCREEN_SAMPLE.jsonl", selected)
        _write_json(root / "00_population" / "EXHAUSTION_AUDIT.json", audit)
        result = {"status": audit["status"], "n_population": len(population), "n_selected": len(selected)}
        if args.inventory:
            result["n_ready_source_context"] = source_audit["n_ready"]
        if args.command == "p1-pool":
            if not args.baseline_gt:
                parser.error("--baseline-gt is required for p1-pool (evaluator namespace only)")
            gt_rows = _read_jsonl(Path(args.baseline_gt))
            gt = {(str(row["song_id"]), int(row["canonical_unit_id"])): row for row in gt_rows}
            strata = assign_gt_stratum(population, gt)
            _write_jsonl(root / "03_unit_outcomes" / "STRATIFIED_POOL.jsonl", strata)
            result["n_stratified"] = len(strata)
    elif args.command == "screen":
        if not args.requests or not args.features:
            parser.error("--requests and --features are required for screen")
        result = choose_surviving_families(_read_jsonl(Path(args.requests)), _read_jsonl(Path(args.features)))
        _write_json(root / "05_analysis" / "FAMILY_SCREEN.json", result)
    elif args.command == "p1-refill":
        pool_path = Path(args.stratified_pool) if args.stratified_pool else root / "03_unit_outcomes" / "STRATIFIED_POOL.jsonl"
        if not pool_path.exists():
            parser.error("run p1-pool first or provide --stratified-pool")
        state = _state(root)
        selected_path = root / "01_requests" / "P1_SELECTED_REGIONS.jsonl"
        # A fresh invocation must not erase prior selection constraints.  The
        # explicit overwrite operation belongs to a separate audited command.
        prior_selected = _read_jsonl(selected_path) if selected_path.exists() else []
        selected, audit = balanced_replenishment(
            _read_jsonl(pool_path), target_per_stratum=args.target_per_stratum,
            selected_region_ids=set(state.get("completed_region_ids", [])),
            prior_selected=prior_selected,
            per_song_cap=args.per_song_cap, max_per_song_cap=8,
        )
        _write_jsonl(root / "01_requests" / "P1_REFILL_REGIONS.jsonl", selected)
        _write_jsonl(selected_path, [*prior_selected, *selected])
        _write_json(root / "00_population" / "P1_REFILL_AUDIT.json", audit)
        result = {"status": audit["status"], "n_selected": len(selected), "audit": audit}
    elif args.command == "execute":
        requests_path = Path(args.requests) if args.requests else root / "01_requests" / "REQUESTS.jsonl"
        generated = False
        if not requests_path.exists():
            generated = _materialize_requests_from_regions(
                root, requests_path,
                request_config={k: v for k, v in {
                    "audio_margin_sec": args.audio_margin_sec,
                    "context_neighbors": args.context_neighbors,
                    "ra_context_units": args.ra_context_units,
                }.items() if v is not None})
        if not requests_path.exists():
            parser.error("execute requires --requests, 01_requests/REQUESTS.jsonl, or both "
                         "00_population/REGION_POOL.jsonl and 01_requests/P1_SELECTED_REGIONS.jsonl")
        state = _state(root)
        rows = _read_jsonl(requests_path)
        completed = set(state["completed_identities"])
        status_rows, forward_rows, failure_rows, skipped = [], [], [], 0
        planned_at = datetime.now(timezone.utc).isoformat()
        for row in rows:
            identity = row.get("request_identity") or row.get("request_id") or row.get("region_id")
            if args.resume and identity in completed:
                skipped += 1
                continue
            if row.get("status"):
                decision = {"status": row.get("status"), "reason": row.get("reason")}
            else:
                decision = validate_request(row)
            status_rows.append({**decision, "song_id": row.get("song_id"), "region_id": row.get("region_id"),
                                "request_id": row.get("request_id"), "family": row.get("family"),
                                "stratum": row.get("stratum"), "stratum_status": row.get("stratum_status"),
                                "request_identity": identity})
            status = decision.get("status")
            _record_identity(state, identity, status)
            if status in {"ready", "valid"}:
                forward_rows.append({
                    "schema": "unit_realign_forward_v1", "status": "queued",
                    "request_identity": identity, "request_id": row.get("request_id"),
                    "region_id": row.get("region_id"), "song_id": row.get("song_id"),
                    "family": row.get("family"), "stratum": row.get("stratum"),
                    "forwarding": {
                        "executor": "scripts/unit_realign/run_forward_real.py",
                        "evidence_dir": str(root / "02_forwards" / "evidence"),
                        "planned_at_utc": planned_at,
                    },
                })
            else:
                failure_rows.append({
                    "schema": "unit_realign_forward_failure_v1", "status": status,
                    "request_identity": identity, "request_id": row.get("request_id"),
                    "region_id": row.get("region_id"), "song_id": row.get("song_id"),
                    "family": row.get("family"), "reason": decision.get("reason"),
                    "expected_request_identity": decision.get("expected_request_identity"),
                })
        state["updated_at_utc"] = planned_at
        _write_jsonl(root / "01_requests" / "REQUEST_STATUS.jsonl", status_rows)
        _write_jsonl(root / "02_forwards" / "FORWARDS.jsonl", forward_rows)
        _write_jsonl(root / "02_forwards" / "FAILURES.jsonl", failure_rows)
        _write_json(root / "07_runtime" / "RUN_STATE.json", state)
        result = {"status": "ok", "n_requests": len(rows), "skipped_resume": skipped,
                  "requests_materialized": generated, "n_forwards": len(forward_rows),
                  "n_failures": len(failure_rows),
                  "n_queued": len(state["queued_identities"]), "n_planned": len(state["planned_identities"]),
                  "n_completed": len(state["completed_identities"]), "n_failed": len(state["failed_identities"]),
                  "n_null": len(state["null_identities"]), "n_not_constructible": len(state["not_constructible_identities"])}
    elif args.command == "evaluate":
        if not args.requests or not args.baseline_gt or not args.evidence_dir:
            parser.error("--requests, --baseline-gt and --evidence-dir are required for evaluate")
        requests = _read_jsonl(Path(args.requests))
        gt_by_song: dict[str, dict[int, dict]] = {}
        for row in _read_jsonl(Path(args.baseline_gt)):
            gt_by_song.setdefault(str(row["song_id"]), {})[int(row["canonical_unit_id"])] = row
        evidence_dir = Path(args.evidence_dir)
        # R4: evaluate only dispatched requests.  FORWARDS.jsonl is the
        # authoritative dispatched set (ready/valid rows the forward adapter
        # must turn into baseline/candidate evidence); not-constructible and
        # null cases were never forwarded and must not appear as missing
        # evidence.  When FORWARDS is absent (evaluator-only invocation) every
        # request row is considered dispatched.
        requests_by_identity = {str(r.get("request_id") or r.get("request_identity") or ""): r for r in requests}
        forwards_path = root / "02_forwards" / "FORWARDS.jsonl"
        if forwards_path.exists():
            forwarded_ids = {str(f.get("request_id") or f.get("request_identity") or "") for f in _read_jsonl(forwards_path)}
            dispatch = [requests_by_identity[i] for i in forwarded_ids if i in requests_by_identity]
        else:
            dispatch = requests
        outcomes, region_outcomes, not_evaluated = [], [], []
        state = _state(root)
        for request in dispatch:
            rid = str(request.get("request_id") or request.get("request_identity"))
            identity = str(request.get("request_identity") or request.get("request_id") or "")
            baseline_path = evidence_dir / f"{rid}.baseline.jsonl"
            candidate_path = evidence_dir / f"{rid}.candidate.jsonl"
            if not baseline_path.exists() or not candidate_path.exists():
                not_evaluated.append({
                    "schema": "unit_realign_not_evaluated_v1", "request_identity": identity,
                    "song_id": str(request.get("song_id")), "region_id": str(request.get("region_id")),
                    "family": str(request.get("family")), "stratum": request.get("stratum"),
                    "reason": "missing_evidence",
                    "missing": [name for name, p in (("baseline", baseline_path), ("candidate", candidate_path))
                                if not p.exists()],
                })
                continue
            paired = pair_unit_outcomes(
                baseline_rows=_read_jsonl(baseline_path), candidate_rows=_read_jsonl(candidate_path),
                gt_by_canonical=gt_by_song.get(str(request.get("song_id")), {}),
                song_id=str(request.get("song_id")), region_id=str(request.get("region_id")),
                request_id=str(request.get("request_id")), family=str(request.get("family")),
                target_unit_ids=[int(x) for x in request.get("active_target_unit_ids", request.get("target_unit_ids", ()))],
                fixed_context_unit_ids=[int(x) for x in request.get("fixed_context_unit_ids", ())])
            outcomes.extend(paired)
            region_outcomes.append({**aggregate_region_outcome(paired), "request_identity": identity,
                                    "stratum": request.get("stratum"),
                                    "stratum_status": request.get("stratum_status")})
            if identity and identity not in state["completed_identities"]:
                state["completed_identities"].append(identity)
            region_id = str(request.get("region_id") or "")
            if region_id and region_id not in state["completed_region_ids"]:
                state["completed_region_ids"].append(region_id)
        groups: dict[tuple[str, str, str, str], list[dict]] = {}
        for ro in region_outcomes:
            key = (str(ro.get("song_id")), str(ro.get("request_identity") or ro.get("request_id")),
                   str(ro.get("family")), str(ro.get("stratum") or "unknown"))
            groups.setdefault(key, []).append(ro)
        candidate_rows = []
        for key, ro in groups.items():
            candidate = aggregate_candidate_outcome(ro)
            candidate["group_key"] = "::".join(key)
            candidate["stratum"] = key[3]
            candidate_rows.append(candidate)
        global_outcome = aggregate_candidate_outcome(region_outcomes)
        global_outcome["grouping"] = "aggregate over all candidate groups"
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_jsonl(root / "03_unit_outcomes" / "UNIT_OUTCOMES.jsonl", outcomes)
        _write_jsonl(root / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl", region_outcomes)
        _write_jsonl(root / "03_unit_outcomes" / "CANDIDATE_OUTCOMES.jsonl", candidate_rows)
        _write_jsonl(root / "03_unit_outcomes" / "NOT_EVALUATED.jsonl", not_evaluated)
        _write_json(root / "05_analysis" / "CANDIDATE_OUTCOMES.json", global_outcome)
        _write_json(root / "05_analysis" / "MISSING_EVIDENCE_REPORT.json", _missing_evidence_report(not_evaluated))
        _write_json(root / "07_runtime" / "RUN_STATE.json", state)
        result = {"status": "ok", "n_unit_rows": len(outcomes), "n_regions": len(region_outcomes),
                  "n_candidates": len(candidate_rows), "n_not_evaluated": len(not_evaluated)}
    elif args.command == "report":
        state = _state(root)
        region_path = root / "03_unit_outcomes" / "REGION_OUTCOMES.jsonl"
        regions = _read_jsonl(region_path) if region_path.exists() else []
        candidate_path = root / "05_analysis" / "CANDIDATE_OUTCOMES.json"
        candidate = json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.exists() else {}
        candidate_rows_path = root / "03_unit_outcomes" / "CANDIDATE_OUTCOMES.jsonl"
        candidate_rows = _read_jsonl(candidate_rows_path) if candidate_rows_path.exists() else []
        not_evaluated_path = root / "03_unit_outcomes" / "NOT_EVALUATED.jsonl"
        not_evaluated = _read_jsonl(not_evaluated_path) if not_evaluated_path.exists() else []
        status_path = root / "01_requests" / "REQUEST_STATUS.jsonl"
        status_rows = _read_jsonl(status_path) if status_path.exists() else []
        forwards_path = root / "02_forwards" / "FORWARDS.jsonl"
        forward_rows = _read_jsonl(forwards_path) if forwards_path.exists() else []
        accounting = _family_stratum_accounting(root, status_rows, forward_rows, candidate_rows)
        body = [
            "# Unit Realign FINAL_REPORT", "",
            f"- run: `{root}`",
            f"- RUN_STATE: completed={len(state['completed_identities'])}, queued={len(state.get('queued_identities', []))}, "
            f"planned={len(state.get('planned_identities', []))}, failed={len(state['failed_identities'])}, "
            f"null={len(state['null_identities'])}, not_constructible={len(state['not_constructible_identities'])}",
            f"- regions evaluated: {len(regions)}, global candidate outcome: {candidate.get('outcome')} "
            f"(aggregate over all groups)",
            f"- candidates by group: {len(candidate_rows)}, not evaluated: {len(not_evaluated)}", "",
            "## Family x stratum accounting",
            "",
            "| family | stratum | selected | constructible | executed | null | not_constructible | failed | invalid | valid |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for family in sorted(accounting):
            for stratum in sorted(accounting[family]):
                bucket = accounting[family][stratum]
                body.append(f"| {family} | {stratum} | {bucket['n_selected']} | {bucket['n_constructible']} "
                            f"| {bucket['n_executed']} | {bucket['n_null']} | {bucket['n_not_constructible']} "
                            f"| {bucket['n_failed']} | {bucket['n_invalid']} | {bucket['n_valid']} |")
        body.append("")
        for row in candidate_rows:
            body.append(f"  - `{row.get('group_key')}`: n_regions={row.get('n_regions')}, outcome={row.get('outcome')}, "
                        f"n_fixed_context={row.get('n_fixed_context')}, n_extra={row.get('n_extra')}")
        if not_evaluated:
            body.append("")
            body.append("missing evidence:")
            for row in not_evaluated:
                body.append(f"  - {row.get('request_identity')} [{row.get('family')}] {row.get('reason')}")
        report_path = root / "reports" / "FINAL_REPORT.md"
        _atomic_write(report_path, "\n".join(body) + "\n")
        result = {"status": "ok", "report_path": str(report_path), "n_regions": len(regions),
                  "n_candidates": len(candidate_rows), "n_not_evaluated": len(not_evaluated)}
    else:
        population_path = root / "00_population" / "REGION_POOL.jsonl"
        if not population_path.exists():
            parser.error("run population before expand")
        state = _state(root)
        result = expansion_plan(_read_jsonl(population_path),
                                completed_region_ids=set(state.get("completed_region_ids", [])),
                                target_regions=args.target, per_song_cap=args.per_song_cap)
        _write_jsonl(root / "01_requests" / "EXPANSION_REGIONS.jsonl", result["regions"])
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(root / "07_runtime" / "RUN_STATE.json", state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
