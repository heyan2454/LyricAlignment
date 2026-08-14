#!/usr/bin/env python3
"""WP4 — E2 fine-grained split screening over an unsafe region (shadow-only).

For each region we split the unsafe/REJECT-UNCERTAIN fragment under one of four
partition mechanisms (one_unit / two_unit / adaptive / anchor_gap) and evaluate
each sub-target as an independent v2 request through the executor (smoke =
deterministic CPU, real = frozen Qwen forward entry).  Direction controls the
evaluation / chaining order:

  L2R         — serial left→right: each sub-target's candidate becomes the next
                sub-target's baseline (true multi-realign chaining).
  R2L         — serial right→left (mirror).
  independent — all sub-targets evaluated from the frozen detector baseline,
                then merged deterministically.

Every sub-request carries ``split_slot_id`` (partition + direction + sub-index)
and ``direction`` in its identity so distinct shards never share an identity
(WP1 / 07 §5).  02 E2 §205-214 metrics are all emitted under schema
``split_realign_v1``.  GT firewall: there is no GT path here or in any call.

Outputs (under <out-root>):
    01_requests/REQUESTS.jsonl       every sub-target's v2 request (or NC stub)
    02_split/SPLIT_OUTCOMES.jsonl    split_realign_v1 rows (unit + region)
    06_runtime/RUN_STATE.json        resume state by request_identity
    FINAL_SPLIT.json                 per-region aggregate + summary

Usage:
  PYTHONPATH=src python scripts/unit_realign/run_split_realign.py \
      --regions <REGION_POOL.jsonl> --out-root <run> \
      --partition one_unit|two_unit|adaptive|anchor_gap \
      --direction L2R|R2L|independent [--family R-U] [--limit N] [--resume] \
      [--smoke | --real --model-dir <dir> --checkpoint-path <ckpt>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.split_variants import (  # noqa: E402
    SPLIT_REALIGN_SCHEMA, build_split_requests, class_target_order,
    evaluate_split, merge_split_results, partition_region,
)
from lyricalign.unit_realign.multi_iteration import make_smoke_executor  # noqa: E402


_STATE_SCHEMA = "unit_realign_split_run_state_v1"
_STATE_PATH = Path("06_runtime") / "RUN_STATE.json"
_QUESTS_PATH = Path("01_requests") / "REQUESTS.jsonl"
_OUTCOME_PATH = Path("02_split") / "SPLIT_OUTCOMES.jsonl"
_FINAL_PATH = Path("FINAL_SPLIT.json")


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


def _execute_request(request: dict, executor, audio_path: str) -> tuple[list[dict], str | None]:
    """Run one v2 request through the executor; map rows back to canonical ids."""
    from lyricalign.unit_realign.multi_iteration import _candidate_rows_from_v2, _to_v7_request
    if request.get("family") == "R-NULL" or request.get("status") == "not_constructible":
        return [], request.get("reason") or "null_or_not_constructible"
    try:
        req = _to_v7_request(request, audio_path)
        req.validate()
        attempt = executor(req)
        return _candidate_rows_from_v2(attempt, request)
    except Exception as exc:  # noqa: BLE001
        return [], f"forward:{exc}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regions", required=True, help="REGION_POOL.jsonl")
    p.add_argument("--out-root", required=True)
    p.add_argument("--partition", required=True,
                   choices=["one_unit", "two_unit", "adaptive", "anchor_gap"],
                   help="partition mechanism (also accepts short names below)")
    p.add_argument("--direction", default="L2R", choices=["L2R", "R2L", "independent"])
    p.add_argument("--family", default="R-U")
    p.add_argument("--context-neighbors", type=int, default=1)
    p.add_argument("--audio-margin-sec", type=float, default=0.5)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--real", action="store_true")
    p.add_argument("--model-dir")
    p.add_argument("--revision", default="main")
    p.add_argument("--checkpoint-path")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    partition = {"1unit": "one_unit", "1-unit": "one_unit",
                 "2unit": "two_unit", "2-unit": "two_unit",
                 "adaptive": "adaptive", "adaptive-detector": "adaptive",
                 "anchorgap": "anchor_gap", "anchor_gap": "anchor_gap"}.get(
        args.partition, args.partition)
    if partition not in ("one_unit", "two_unit", "adaptive", "anchor_gap"):
        p.error(f"unsupported partition {args.partition}")

    if args.smoke == args.real:
        p.error("choose exactly one of --smoke or --real")
    if args.real and (not args.model_dir or not args.checkpoint_path):
        p.error("--real requires --model-dir and --checkpoint-path")

    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "01_requests").mkdir(parents=True, exist_ok=True)
    (root / "02_split").mkdir(parents=True, exist_ok=True)

    regions = _read_jsonl(Path(args.regions))
    if args.limit:
        regions = regions[:args.limit]

    executor = make_smoke_executor() if args.smoke else None
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
    count = {"ok": 0, "not_constructible": 0, "failed": 0, "resume_skipped": 0}

    for region in regions:
        song_id = str(region.get("song_id") or "")
        region_id = str(region.get("region_id") or "")
        audio_path = str(region.get("audio_path") or f"{song_id}.wav")

        subtargets = partition_region(region, partition)
        order = class_target_order(region, subtargets, args.direction)

        base_ctx = dict(region.get("identity_context") or {})
        if args.smoke:
            base_ctx.setdefault("audio_sha256", "smoke_dummy_audio")
            base_ctx.setdefault("model_identity", "qwen-fa-smoke")
            base_ctx.setdefault("checkpoint_identity", "smoke")
            base_ctx.setdefault("decoder_identity", "official")
            base_ctx.setdefault("mapping_schema", "unit_realign_local_v2")
            base_ctx.setdefault("code_identity", "split_realign-smoke")
            base_ctx.setdefault("text_adapter_identity", "c3-smoke")
        elif args.real:
            base_ctx.setdefault("audio_sha256", region.get("audio_sha256"))
            base_ctx.setdefault("mapping_schema", "unit_realign_local_v2")
            base_ctx.setdefault("code_identity", "split_realign")
            base_ctx.setdefault("text_adapter_identity", "c3")

        # build requests for ALL subtargets (identity independent of serial
        # parent wiring, so L2R/R2L/independent share the same shard set).
        requests = build_split_requests(
            region, subtargets, partition=partition, direction=args.direction,
            family=args.family, identity_context=base_ctx,
            audio_margin_sec=args.audio_margin_sec,
            context_neighbors=args.context_neighbors,
        )
        req_by_idx = {int(st["index"]): st for st in subtargets}
        req_objs = {int(st["index"]): r for st, r in zip(subtargets, requests)}

        # Serial chaining (L2R / R2L): run in traversal order; each run's
        # candidate becomes the next sub-target's baseline.  Because requests for
        # the chain already encoded parent_request_identity from the PRIOR index
        # in build_split_requests, we re-run in order and feed prior candidates.
        executed: list[dict] = []
        fresh_region = False
        fresh_ids: set[str] = set()
        prev_candidate: list[dict] | None = None

        for idx in order:
            st = subtargets[idx]
            req = req_objs[int(st["index"])]
            rid = req.get("request_identity")
            # serial chain: refresh baseline units with the previous candidate so
            # iteration>0 truly consumes the actual previous forward.
            run_region = dict(region)
            if prev_candidate is not None and args.direction in {"L2R", "R2L"}:
                run_units = []
                cmap = {int(r["canonical_unit_id"]): r for r in prev_candidate}
                for u in region.get("units") or ():
                    cu = dict(u)
                    cc = cmap.get(int(u["canonical_unit_id"]))
                    if cc:
                        cu.update({"start_sec": cc["start_sec"], "end_sec": cc["end_sec"]})
                    run_units.append(cu)
                run_region["units"] = run_units
                run_region["audio_path"] = audio_path

            if rid and rid in done_ids:
                count["resume_skipped"] += 1
                executed.append({"sub_target_index": int(st["index"]),
                                 "target_unit_ids": st["sub_target_unit_ids"],
                                 "candidate_rows": prev_candidate or [],
                                 "request_identity": rid,
                                 "constructible": req.get("family") != "R-NULL",
                                 "effective_family": (req.get("split_shard") or {})
                                 .get("effective_family", req.get("family"))})
                continue

            # rebuild request for the chained baseline if serial and we have a
            # prior candidate (identity stays the same; payload changes are
            # reflected in intervention payload only, never in identity — WP1).
            use_req = req
            if prev_candidate is not None and args.direction in {"L2R", "R2L"}:
                use_req = build_split_requests(
                    run_region, [{"index": int(st["index"]),
                                  "sub_target_unit_ids": st["sub_target_unit_ids"],
                                  "partition_identity": st.get("partition_identity")}],
                    partition=partition, direction=args.direction, family=args.family,
                    identity_context=base_ctx, audio_margin_sec=args.audio_margin_sec,
                    context_neighbors=args.context_neighbors,
                )[0]
                # retain shard provenance / identity fields from original.
                use_req["request_identity"] = rid or use_req.get("request_identity")

            cand_rows, error = _execute_request(use_req, executor, audio_path)
            rid = use_req.get("request_identity")
            fresh_region = True
            fresh_ids.add(rid if rid else f"{song_id}:{region_id}:idx{st['index']}:noidentity")
            all_requests.append(use_req)
            constructible = use_req.get("family") != "R-NULL" and use_req.get("status") != "not_constructible"
            if error or not constructible:
                _record(state, rid, "failed" if error else "not_constructible",
                        nc=(not error and not constructible))
                count["failed" if error else "not_constructible"] += 1
                executed.append({"sub_target_index": int(st["index"]),
                                 "target_unit_ids": st["sub_target_unit_ids"],
                                 "candidate_rows": [],
                                 "request_identity": rid, "constructible": False,
                                 "effective_family": (use_req.get("split_shard") or {})
                                 .get("effective_family", use_req.get("family"))})
                prev_candidate = None
                continue
            prev_candidate = cand_rows
            _record(state, rid, "ok")
            count["ok"] += 1
            executed.append({"sub_target_index": int(st["index"]),
                             "target_unit_ids": st["sub_target_unit_ids"],
                             "candidate_rows": cand_rows, "request_identity": rid,
                             "constructible": True,
                             "effective_family": (use_req.get("split_shard") or {})
                             .get("effective_family", use_req.get("family"))})

        merge = merge_split_results(executed)
        fwd = sum(1 for ex in executed if ex.get("candidate_rows"))
        new_rows = evaluate_split(region, subtargets, executed, merge,
                                  partition=partition, direction=args.direction,
                                  family_requested=args.family, forward_count=fwd)
        # only persist fresh region rows (resume never duplicates).
        if fresh_region:
            region_rows = [r for r in new_rows if r.get("row_kind") == "region"]
            region_agg.extend(region_rows)
            all_outcomes.extend(r for r in new_rows
                                if r.get("request_identity") in fresh_ids
                                or r.get("row_kind") == "region"
                                or r.get("request_identity") is None)

    _write_jsonl(root / _QUESTS_PATH, all_requests)
    _write_jsonl(root / _OUTCOME_PATH, all_outcomes)

    summary = {
        "schema": SPLIT_REALIGN_SCHEMA,
        "partition": partition, "direction": args.direction, "family": args.family,
        "executor": "real" if args.real else "smoke",
        "n_regions": len(regions),
        **count,
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

    print(json.dumps({"schema": SPLIT_REALIGN_SCHEMA, "count": count,
                      "n_outcome_rows": len(all_outcomes),
                      "request_manifest": str(root / _QUESTS_PATH),
                      "split_outcomes": str(root / _OUTCOME_PATH),
                      "run_state": str(root / _STATE_PATH),
                      "final": str(root / _FINAL_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
