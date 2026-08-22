#!/usr/bin/env python3
"""WP3 — run E1 multi-realign dynamics screening over a region pool (shadow-only).

For each region we build a multi-iteration chain (default iterations 1,2,3,5,
iter0 = frozen detector baseline), run each step through the executor
(smoke = deterministic CPU, real = frozen Qwen forward entry), record the
per-unit trajectory and per-region aggregate, and manage resume by
request_identity (content-addressed: same identity is never re-executed).

Outputs (under <out-root>):
   01_requests/REQUESTS.jsonl          every step's v2 request (or NC stub)
   02_trajectory/TRAJECTORY.jsonl      multi_realign_dynamics_v1 rows
   02_trajectory/CHAIN_RUNS.jsonl      raw step-level run records
   06_runtime/RUN_STATE.json           resume state (completed/queued/planned/
                                       failed/not_constructible identities)
   FINAL_TRAJECTORY.json               per-region aggregate + summary

GT firewall: no GT path exists in this script and none of the modules it calls
consume GT; the pipeline is purely structural + executor.  smoke is CPU-only.

Usage:
  PYTHONPATH=src python scripts/unit_realign/run_multi_realign.py \
      --regions <REGION_POOL.jsonl> --out-root <run> [--iterations 1,2,3,5] \
      [--family R-U] [--targets <comma-ids or "auto:firstN">] [--limit N] \
      [--smoke | --real --model-dir <dir> --checkpoint-path <ckpt>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.multi_iteration import (  # noqa: E402
    TRAJECTORY_SCHEMA_VERSION, baseline_rows_from_units, build_chain,
    extract_trajectory, make_smoke_executor, run_chain_smoke,
)


_STATE_SCHEMA = "unit_realign_run_state_v2"
_STATE_PATH = Path("06_runtime") / "RUN_STATE.json"
_QUESTS_PATH = Path("01_requests") / "REQUESTS.jsonl"
_TRAJ_PATH = Path("02_trajectory") / "TRAJECTORY.jsonl"
_RUNS_PATH = Path("02_trajectory") / "CHAIN_RUNS.jsonl"
_FINAL_PATH = Path("FINAL_TRAJECTORY.json")


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    _atomic_write(path, payload)


def _write_json(path: Path, value) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _select_targets(region: dict, spec: str | None) -> list[int]:
    """Resolve --targets spec. 'auto:firstN' picks the first N contiguous units after
    the first unit (index 1..N when pool allows); else a comma list of canonical ids."""
    full_ids = [int(u.get("canonical_unit_id")) for u in (region.get("units") or ())]
    if not full_ids:
        return []
    if not spec:
        # default: middle single target? Use first non-anchor unit. Keep simple: first unit after index 0.
        return [full_ids[1]] if len(full_ids) > 1 else []
    if spec.startswith("auto:"):
        n = int(spec.split(":", 1)[1])
        return full_ids[1:1 + n]
    try:
        return [int(x) for x in spec.split(",") if x.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--targets invalid: {exc}") from exc


def _load_state(root: Path) -> dict:
    path = root / _STATE_PATH
    if not path.exists():
        return {"schema": _STATE_SCHEMA, "completed_identities": [], "queued_identities": [],
                "planned_identities": [], "failed_identities": [], "not_constructible_identities": [],
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


def _record(state: dict, identity: str | None, status: str) -> None:
    bucket = {"not_constructible": "not_constructible_identities",
              "ok": "completed_identities",
              "executed": "completed_identities",
              "failed": "failed_identities"}.get(status, "failed_identities")
    if identity:
        target_bucket = state.setdefault(bucket, [])
        if identity not in target_bucket:
            target_bucket.append(identity)
        planned = state.setdefault("planned_identities", [])
        if identity not in planned:
            planned.append(identity)


def _parse_iterations(spec: str) -> list[int]:
    return [int(x) for x in spec.split(",") if x.strip()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regions", required=True, help="REGION_POOL.jsonl")
    p.add_argument("--out-root", required=True)
    p.add_argument("--targets", default=None,
                   help="comma canonical ids or auto:firstN (default: auto:1 -> first non-anchor)")
    p.add_argument("--iterations", default="1,2,3,5", help="comma iteration numbers")
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

    if args.smoke == args.real:
        p.error("choose exactly one of --smoke or --real")
    if args.real and (not args.model_dir or not args.checkpoint_path):
        p.error("--real requires --model-dir and --checkpoint-path")

    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "01_requests").mkdir(parents=True, exist_ok=True)
    (root / "02_trajectory").mkdir(parents=True, exist_ok=True)

    iterations = _parse_iterations(args.iterations)
    regions = _read_jsonl(Path(args.regions))
    if args.limit:
        regions = regions[: args.limit]

    executor = make_smoke_executor() if args.smoke else None
    if args.real:
        from lyricalign.research_v7.real_executor import RealAligner, make_real_executor
        executor = make_real_executor(RealAligner(args.model_dir, args.revision, args.checkpoint_path))

    state = _load_state(root)
    # Resume merge: preserve already-written requests/trajectories on disk so a
    # --resume rerun never drops completed identities' outputs (only appends new).
    pre_requests = _read_jsonl(root / _QUESTS_PATH)
    pre_traj = _read_jsonl(root / _TRAJ_PATH)
    pre_runs = _read_jsonl(root / _RUNS_PATH)
    if args.resume:
        done_ids = set(state["completed_identities"])
        all_requests = [r for r in pre_requests]
        all_traj_rows = list(pre_traj)
        all_runs = list(pre_runs)
    else:
        done_ids = set()
        all_requests = []
        all_traj_rows = []
        all_runs = []
    region_agg: list[dict] = []
    count = {"ok": 0, "not_constructible": 0, "failed": 0, "resume_skipped": 0}

    for idx, region in enumerate(regions, 1):
        song_id = str(region.get("song_id") or "")
        region_id = str(region.get("region_id") or "")
        if idx == 1 or idx % 10 == 0 or idx == len(regions):
            print(f"[progress] region {idx}/{len(regions)} song={song_id} region={region_id} "
                  f"t0={time.strftime('%H:%M:%S')} ok={count['ok']} nc={count['not_constructible']} "
                  f"failed={count['failed']}", flush=True)
        targets = _select_targets(region, args.targets)
        if not targets:
            count["not_constructible"] += 1
            continue

        identity_context = dict(region.get("identity_context") or {})
        base_ctx = dict(identity_context)
        if args.smoke:
            # smoke: fabricate frozen identity fields so request_identity exists.
            base_ctx.setdefault("audio_sha256", "smoke_dummy_audio")
            base_ctx.setdefault("model_identity", "qwen-fa-smoke")
            base_ctx.setdefault("checkpoint_identity", "smoke")
            base_ctx.setdefault("decoder_identity", "official")
            base_ctx.setdefault("mapping_schema", "unit_realign_local_v2")
            base_ctx.setdefault("code_identity", "multi_iteration-smoke")
            base_ctx.setdefault("text_adapter_identity", "c3-smoke")
            identity_context = base_ctx

        run = run_chain_smoke(
            region, targets, iterations=iterations, family=args.family,
            context_neighbors=args.context_neighbors,
            audio_margin_sec=args.audio_margin_sec,
            identity_context=identity_context,
            executor=executor,
        )
        steps = run["steps"]
        fresh_region = False
        fresh_ids: set[str] = set()
        for s in steps:
            request = s.get("request")
            if request is None:
                # A not_constructible stop-step has no v2 request; still record a stub
                # so REQUESTS / RUN_STATE / summary preserve the stop point (N-review P1-3).
                reason = s.get("not_constructible_reason") or "unknown_not_constructible"
                seed = f"{region.get('song_id','?')}:{region.get('region_id','?')}:iter{s.get('iteration')}:{reason}"
                stub = {
                    "schema": "unit_realign_request_v2",
                    "row_kind": "not_constructible_stub",
                    "schema_version": TRAJECTORY_SCHEMA_VERSION,
                    "song_id": region.get("song_id"), "region_id": region.get("region_id"),
                    "iteration": s.get("iteration"), "family": args.family,
                    "request_identity": seed,
                    "request_id": seed,
                    "not_constructible_reason": reason,
                    "constructible": False,
                    "actual_writeback": 0,
                }
                if seed not in done_ids:
                    fresh_region = True
                    fresh_ids.add(seed)
                    all_requests.append(stub)
                    _record(state, seed, "not_constructible")
                    count["not_constructible"] += 1
                continue
            rid = request.get("request_identity")
            if rid and rid in done_ids:
                count["resume_skipped"] += 1
                continue
            fresh_region = True
            fresh_ids.add(rid)
            all_requests.append(request)
            if s.get("constructible"):
                _record(state, rid, "ok")
                count["ok"] += 1
            else:
                _record(state, rid, "not_constructible")
                count["not_constructible"] += 1

        if fresh_region:
            # Keep only trajectory/runs rows for identities that were newly executed
            # this run, so partial resume never duplicates already-persisted rows
            # (O-review P1-1).
            def _is_fresh_step(st: dict) -> bool:
                rq = st.get("request")
                if rq is not None:
                    rid = rq.get("request_identity")
                    return rid in fresh_ids
                reason = st.get("not_constructible_reason") or "unknown_not_constructible"
                seed = f"{region.get('song_id','?')}:{region.get('region_id','?')}:iter{st.get('iteration')}:{reason}"
                return seed in fresh_ids

            fresh_steps = [st for st in steps if _is_fresh_step(st)]
            fresh_traj = [
                r for r in run["trajectory"]
                if r.get("request_identity") in fresh_ids or r.get("row_kind") == "region"
            ]
            all_traj_rows.extend(fresh_traj)
            region_agg.extend(r for r in fresh_traj if r.get("row_kind") == "region")
            all_runs.extend(s for s in fresh_steps)

    _write_jsonl(root / _QUESTS_PATH, all_requests)
    _write_jsonl(root / _TRAJ_PATH, all_traj_rows)
    _write_jsonl(root / _RUNS_PATH, all_runs)

    summary = {
        "schema_version": TRAJECTORY_SCHEMA_VERSION,
        "family": args.family, "iterations": iterations,
        "executor": "real" if args.real else "smoke",
        "n_regions": len(regions),
        **count,
        "aggregates": region_agg,
    }
    # On resume with nothing fresh, preserve the prior FINAL aggregates instead of
    # overwriting with an empty list.
    if not region_agg and args.resume and (root / _FINAL_PATH).exists():
        try:
            prior = json.loads((root / _FINAL_PATH).read_text(encoding="utf-8"))
            summary["aggregates"] = prior.get("aggregates") or region_agg
        except Exception:  # noqa: BLE001
            pass
    _write_json(root / _FINAL_PATH, summary)

    _save_state(root, state)
    print(json.dumps({"schema_version": TRAJECTORY_SCHEMA_VERSION, "count": count,
                      "n_traj_rows": len(all_traj_rows),
                      "request_manifest": str(root / _QUESTS_PATH),
                      "trajectory": str(root / _TRAJ_PATH),
                      "run_state": str(root / _STATE_PATH),
                      "final": str(root / _FINAL_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
