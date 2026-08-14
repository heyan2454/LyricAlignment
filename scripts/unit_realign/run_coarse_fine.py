#!/usr/bin/env python3
"""WP6 — E4 coarse->fine (R-CF) runner over unsafe regions (shadow-only).

Runs the two-stage R-CF composition (07 §9 WP6 / 02 E4 §272-326):

    Stage A  R-U coarse proposal
    Stage B  re-center + sparse/fixed refinement (fail-closed not_constructible)

and emits the ``coarse_fine_v1`` outcomes with all 7 metrics (02 E4 §311-319):
target 100/200/500/1000ms recovery, fixed-context displacement, catastrophic
regression, constructibility/coverage, forward cost, no-GT safety signals, and
Test-Demo structural regressions.

The runner also writes frozen forward evidence so the four-way visualizer can
index the fourth track by family (render_current_4way.py --fourth-family R-CF).
Every evidence payload carries ``mutation_parameters.proposal_method="R-CF"``.

Outputs (under <out-root>):
    01_requests/REQUESTS.jsonl          coarse+fine v2 requests (both stages)
    02_coarse_fine/COARSE_FINE_OUTCOMES.jsonl   coarse_fine_v1 rows
    06_runtime/RUN_STATE.json           resume state by request_identity
    forward/evidence/*.json             R-CF forward evidence for 4-way render
    FINAL_COARSE_FINE.json              per-region aggregate + summary

Usage:
    PYTHONPATH=src python scripts/unit_realign/run_coarse_fine.py \
        --regions <REGION_POOL.jsonl> --out-root <run> --family R-CF \
        [--limit N] [--resume] [--smoke | --real --model-dir <dir> --checkpoint-path <ckpt>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign import coarse_fine as cf  # noqa: E402
from lyricalign.unit_realign.coarse_fine import (  # noqa: E402
    COARSE_FINE_SCHEMA, FOURTH_FAMILY, evaluate_coarse_fine,
    run_coarse_fine,
)


_STATE_SCHEMA = "unit_realign_coarse_fine_run_state_v1"
_STATE_PATH = Path("06_runtime") / "RUN_STATE.json"
_QUESTS_PATH = Path("01_requests") / "REQUESTS.jsonl"
_OUTCOME_PATH = Path("02_coarse_fine") / "COARSE_FINE_OUTCOMES.jsonl"
_FINAL_PATH = Path("FINAL_COARSE_FINE.json")
_EVIDENCE_PATH = Path("forward") / "evidence"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _write_jsonl(path: Path, rows) -> None:
    _atomic_write(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                for r in rows))


def _write_json(path: Path, value) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _load_state(root: Path) -> dict:
    path = root / _STATE_PATH
    if not path.exists():
        return {"schema": _STATE_SCHEMA, "completed_identities": [],
                "queued_identities": [], "planned_identities": [],
                "failed_identities": [], "not_constructible_identities": [],
                "updated_at_utc": None}
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("schema", _STATE_SCHEMA)
    for key in ("completed_identities", "queued_identities", "planned_identities",
                "failed_identities", "not_constructible_identities"):
        state.setdefault(key, [])
    return state


def _save_state(root: Path, state: dict) -> None:
    import datetime
    state["updated_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_json(root / _STATE_PATH, state)


def _record(state: dict, identity: str | None, status: str, *, nc: bool = False) -> None:
    bucket = "not_constructible_identities" if nc else "completed_identities"
    if status == "failed":
        bucket = "failed_identities"
    if identity:
        lst = state.setdefault(bucket, [])
        if identity not in lst:
            lst.append(identity)
        planned = state.setdefault("planned_identities", [])
        if identity not in planned:
            planned.append(identity)


def _candidate_to_decoder_rows(candidate_rows: Sequence[Mapping[str, Any]],
                               request: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Map R-CF candidate rows (canonical_unit_id -> span) back to decoder rows
    with window-local ``global_character_index`` so the four-way renderer
    (visualization.rows_from_decoder) can project them on the family track."""
    local_to_canonical = [int(x) for x in (request.get("local_to_canonical")
                                           or request.get("canonical_ids") or ())]
    lci = {cid: i for i, cid in enumerate(local_to_canonical)}
    rows = []
    for r in candidate_rows:
        cid = int(r["canonical_unit_id"])
        if cid not in lci:
            continue
        start = float(r["start_sec"])
        end = float(r["end_sec"])
        rows.append({
            "global_character_index": lci[cid],
            "raw_global_start_sec": start, "raw_global_end_sec": end,
            "official_fixed_global_start_sec": start, "official_fixed_global_end_sec": end,
            "start_sec": start, "end_sec": end,
            "decoder_kind": "official",
        })
    rows.sort(key=lambda r: r["global_character_index"])
    return rows


def _write_evidence(root: Path, request: Mapping[str, Any],
                    candidate_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Write one forward-evidence JSON for the 4-way visualizer.  The payload
    matches visualization_controller's reader contract and carries
    ``proposal_method=R-CF`` so --fourth-family R-CF indexes it."""
    evidence_dir = root / _EVIDENCE_PATH
    evidence_dir.mkdir(parents=True, exist_ok=True)
    decoder_rows = _candidate_to_decoder_rows(candidate_rows, request)
    payload = {
        "schema": "unit_realign_forward_evidence_v1",
        "family": FOURTH_FAMILY,
        "proposal_method": FOURTH_FAMILY,
        "attempt": {
            "status": "ok",
            "request": {
                "request_id": request.get("request_id"),
                "canonical_ids": [int(x) for x in (request.get("canonical_ids") or ())],
                "text_units": [str(x) for x in (request.get("text_units") or ())],
                "mutation_parameters": {"proposal_method": FOURTH_FAMILY,
                                        "stage": request.get("stage", "refinement")},
            },
            "decoder_outputs": {"official": {"rows": decoder_rows},
                                "raw": {"rows": decoder_rows}},
        },
    }
    rid = str(request.get("request_id") or f"cf-{time.time()}")
    path = evidence_dir / f"{rid}.json"
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"path": str(path), "request_id": rid}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regions", required=True, help="REGION_POOL.jsonl")
    p.add_argument("--out-root", required=True)
    p.add_argument("--family", default=FOURTH_FAMILY, choices=[FOURTH_FAMILY])
    p.add_argument("--context-neighbors", type=int, default=cf.STAGE_B_CONTEXT_NEIGHBORS)
    p.add_argument("--active-neighbors", type=int, default=cf.STAGE_B_ACTIVE_NEIGHBORS)
    p.add_argument("--audio-margin-sec", type=float, default=0.5)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--real", action="store_true")
    p.add_argument("--model-dir")
    p.add_argument("--revision", default="main")
    p.add_argument("--checkpoint-path")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    if args.smoke == args.real:
        p.error("choose exactly one of --smoke or --real")
    if args.real and (not args.model_dir or not args.checkpoint_path):
        p.error("--real requires --model-dir and --checkpoint-path")

    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "01_requests").mkdir(parents=True, exist_ok=True)
    (root / "02_coarse_fine").mkdir(parents=True, exist_ok=True)

    regions = _read_jsonl(Path(args.regions))
    if args.limit:
        regions = regions[:args.limit]

    executor = cf.make_coarse_fine_smoke_executor() if args.smoke else None
    if args.real:
        from lyricalign.research_v7.real_executor import RealAligner, make_real_executor
        executor = make_real_executor(RealAligner(args.model_dir, args.revision,
                                                  args.checkpoint_path))

    state = _load_state(root)
    pre_requests = _read_jsonl(root / _QUESTS_PATH)
    pre_outcomes = _read_jsonl(root / _OUTCOME_PATH)
    if args.resume:
        done_ids = set(state["completed_identities"])
        all_requests = list(pre_requests)
        all_outcomes = list(pre_outcomes)
    else:
        done_ids = set()
        all_requests = []
        all_outcomes = []
    region_agg: list[dict] = []
    count = {"ok_stage_b": 0, "ok_stage_a_only": 0, "not_constructible": 0,
             "failed": 0, "resume_skipped": 0}

    for region in regions:
        song_id = str(region.get("song_id") or "")
        region_id = str(region.get("region_id") or "")
        targets = [int(x) for x in (region.get("target_unit_ids") or ())]
        base_ctx = dict(region.get("identity_context") or {})

        steps = run_coarse_fine(
            region, targets, family=args.family, identity_context=base_ctx,
            executor=executor, context_neighbors=args.context_neighbors,
            active_neighbors=args.active_neighbors,
            audio_margin_sec=args.audio_margin_sec, smoke=args.smoke,
        )

        b_step = next((s for s in steps if s.get("stage") == "B"), None)
        a_step = next((s for s in steps if s.get("stage") == "A"), None)
        ids = [s.get("request_identity") for s in steps if s.get("request_identity")]
        # Non-constructible regions may carry no request identity at all; key resume
        # on the region marker so they are never duplicated by --resume.
        region_marker = ids[0] if ids else f"{song_id}:{region_id}:R-CF:no_identity"

        fresh_region = region_marker not in done_ids
        if not fresh_region:
            count["resume_skipped"] += 1

        if fresh_region:
            # persist all stage requests to the manifest.
            for s in steps:
                rq = s.get("request")
                if rq:
                    rq.setdefault("stage", s["stage"])
                    all_requests.append(rq)
            # outcome rows.
            new_rows = evaluate_coarse_fine(steps)
            for r in new_rows:
                if r.get("row_kind") == "region":
                    region_agg.append(r)
                all_outcomes.append(r)
            # evidence + state bookkeeping for the final winning stage.
            win = b_step if (b_step and b_step.get("status") == "ok") else (
                a_step if a_step and a_step.get("status") == "ok" else None)
            if win and win.get("request"):
                _write_evidence(root, win["request"], win.get("candidate_rows") or [])
            for s in steps:
                if s.get("status") == "ok":
                    _record(state, s.get("request_identity"), "ok")
                    count["ok_stage_b" if s.get("stage") == "B" else "ok_stage_a_only"] += 1
                elif s.get("constructible") is False:
                    _record(state, s.get("request_identity"), "not_constructible",
                            nc=not s.get("error"))
                    count["not_constructible"] += 1
                elif s.get("error"):
                    _record(state, s.get("request_identity"), "failed")
                    count["failed"] += 1
            # A region with no request identity (every stage not_constructible /
            # R-NULL) still needs a durable resume marker so --resume never dupes it.
            if not ids:
                _record(state, region_marker, "ok")

    _write_jsonl(root / _QUESTS_PATH, all_requests)
    _write_jsonl(root / _OUTCOME_PATH, all_outcomes)

    summary = {
        "schema": COARSE_FINE_SCHEMA,
        "family": args.family,
        "executor": "real" if args.real else "smoke",
        "n_regions": len(regions),
        **count,
        "step_budget_note": "WP6 E4 coarse->fine pilot (CPU smoke / GPU formal)",
        "aggregates": region_agg,
    }
    if not region_agg and args.resume and (root / _FINAL_PATH).exists():
        try:
            prior = json.loads((root / _FINAL_PATH).read_text(encoding="utf-8"))
            summary["aggregates"] = prior.get("aggregates") or region_agg
        except Exception:  # noqa: BLE001
            pass
    _write_json(root / _FINAL_PATH, summary)
    _save_state(root, state)

    print(json.dumps({"schema": COARSE_FINE_SCHEMA, "family": args.family,
                      "count": count, "n_outcome_rows": len(all_outcomes),
                      "request_manifest": str(root / _QUESTS_PATH),
                      "outcomes": str(root / _OUTCOME_PATH),
                      "run_state": str(root / _STATE_PATH),
                      "evidence_dir": str(root / _EVIDENCE_PATH),
                      "final": str(root / _FINAL_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
