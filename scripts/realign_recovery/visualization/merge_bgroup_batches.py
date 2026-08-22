#!/usr/bin/env python3
"""Merge per-batch B-group mechanism outputs (bgroup_<FAM>_b1..b17) into a
single family dir (bgroup_<FAM>): concatenates REQUESTS/TRAJECTORY/CHAIN_RUNS,
merges RUN_STATE identity buckets and FINAL_TRAJECTORY aggregates.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

FAMILIES = ["R-U", "R-S", "R-CF"]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--families", default=",".join(FAMILIES))
    ap.add_argument("--n-batches", type=int, default=18)
    args = ap.parse_args()

    root = Path(args.run_root)
    for fam in [f.strip() for f in args.families.split(",") if f.strip()]:
        out = root / f"bgroup_{fam}"
        # reset target (idempotent rebuild from batches)
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        (out / "01_requests").mkdir()
        (out / "02_trajectory").mkdir()

        reqs, traj, runs = [], [], []
        state = {"schema": "unit_realign_run_state_v2", "completed_identities": [],
                 "queued_identities": [], "planned_identities": [],
                 "failed_identities": [], "not_constructible_identities": [],
                 "updated_at_utc": None}
        aggs = []
        for b in range(1, args.n_batches + 1):
            bdir = root / f"bgroup_{fam}_b{b}"
            if not bdir.is_dir():
                print(f"WARN: {bdir} missing", flush=True)
                continue
            reqs += _read_jsonl(bdir / "01_requests" / "REQUESTS.jsonl")
            traj += _read_jsonl(bdir / "02_trajectory" / "TRAJECTORY.jsonl")
            runs += _read_jsonl(bdir / "02_trajectory" / "CHAIN_RUNS.jsonl")
            bs = _read_json(bdir / "06_runtime" / "RUN_STATE.json")
            for k in ("completed_identities", "queued_identities", "planned_identities",
                      "failed_identities", "not_constructible_identities"):
                state[k] = list(dict.fromkeys(state[k] + bs.get(k, [])))
            final = _read_json(bdir / "FINAL_TRAJECTORY.json")
            aggs += [a for a in (final.get("aggregates") or []) if a.get("row_kind") == "region"]

        # batches partition the region pool (no region spans two batches), so
        # plain concatenation cannot duplicate rows; keep files verbatim
        uniq_reqs, uniq_traj, uniq_runs = reqs, traj, runs

        _write_jsonl(out / "01_requests" / "REQUESTS.jsonl", uniq_reqs)
        _write_jsonl(out / "02_trajectory" / "TRAJECTORY.jsonl", uniq_traj)
        _write_jsonl(out / "02_trajectory" / "CHAIN_RUNS.jsonl", uniq_runs)
        _write_json(out / "06_runtime" / "RUN_STATE.json", state)

        from collections import Counter
        c = Counter(r.get("row_kind") or r.get("schema") or "?" for r in uniq_reqs)
        summary = {
            "schema_version": "unit_realign_run_state_v2",
            "family": fam,
            "executor": "real",
            "n_regions": len(aggs),
            "ok": len(state["completed_identities"]),
            "not_constructible": len(state["not_constructible_identities"]),
            "failed": len(state["failed_identities"]),
            "resume_skipped": 0,
            "aggregates": aggs,
        }
        _write_json(out / "FINAL_TRAJECTORY.json", summary)
        print(f"{fam}: regions={len(aggs)} ok={summary['ok']} nc={summary['not_constructible']} "
              f"failed={summary['failed']} reqs={len(uniq_reqs)} traj={len(uniq_traj)} "
              f"runs={len(uniq_runs)}", flush=True)
    print("MERGE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
