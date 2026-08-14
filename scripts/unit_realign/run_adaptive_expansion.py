"""WP8 P6 adaptive expansion runner (pure CPU).

Reads E1..E6 FINAL aggregate JSONs + a larger region population, ranks the top-K
mechanisms by strict recovery + safety, stratifies >= target_n independent
regions per mechanism + a song-held-out confirmation population, and emits an
expansion REQUESTS.jsonl manifest. Forward cost is only book-kept in the budget
ledger (no GPU forward).

Outputs under ``--out-root``:
    01_ranking/MECHANISM_RANKING.json
    02_expansion/EXPANSION_MANIFEST.jsonl  (>= target_n + confirmation rows)
    02_expansion/CONFIRMATION_MANIFEST.jsonl  (song-held-out confirmation only)
    06_runtime/RUN_STATE.json
    FINAL_EXPANSION.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lyricalign.unit_realign.adaptive_expansion import (
    EXPANSION_SCHEMA,
    EXPANSION_SCHEMA_VERSION,
    build_confirmation_manifest,
    rank_mechanisms,
    select_regions_for_expansion,
)

DEFAULT_BUDGET = {"expansion_fws_estimate": 200 * 6, "budget_projection_path": None}


def _load_json(path: Path | str) -> dict[str, Any]:
    with open(os.fspath(path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(os.fspath(path), "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path | str, obj: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _write_jsonl(path: Path | str, rows: Sequence[dict[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(os.fspath(path), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")


def _digest_of_screening(screening_results: dict[str, list[dict[str, Any]]]) -> str:
    h = hashlib.sha256()
    for mech in sorted(screening_results):
        h.update(mech.encode("utf-8"))
        h.update("\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str)
                           for r in screening_results[mech]).encode("utf-8"))
    return h.hexdigest()[:16]


# filename stem -> mechanism id for known WP3/4/6 FINAL outputs.
FILENAME_MECHANISM = {
    "FINAL_TRAJECTORY": "E1_direct_i5",
    "FINAL_SPLIT": "E2_adaptive",
    "FINAL_COARSE_FINE": "E4_coarse_fine",
}


def _load_screening(paths: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    """Load E1..E6 FINAL_*.json and key each mechanism's aggregate list."""
    out: dict[str, list[dict[str, Any]]] = {}
    for p in paths:
        fp = Path(p)
        data = _load_json(fp)
        stem = fp.stem
        # Prefer an embedded explicit mechanism id, else a known filename mapping.
        if data.get("mechanism_id"):
            base = str(data["mechanism_id"])
        elif data.get("family"):
            base = str(data["family"])
        else:
            for token, mech in FILENAME_MECHANISM.items():
                if token in stem:
                    base = mech
                    break
            else:
                base = stem
        aggregates = data.get("aggregates") or []
        # Some FINAL files may have per-mechanism aggregates under a nested map.
        if isinstance(aggregates, dict):
            for sub, rows in aggregates.items():
                out[f"{base}:{sub}"] = list(rows) if rows else []
        else:
            out[str(base)] = list(aggregates)
    return out


def _collect_screening_region_ids(screening_results: dict[str, list[dict[str, Any]]]) -> list[str]:
    ids: list[str] = []
    for rows in screening_results.values():
        for r in rows:
            rid = r.get("region_id")
            if rid:
                ids.append(str(rid))
    return ids


def _budget_projection(manifest_rows: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    n_main = sum(1 for r in manifest_rows if not r.get("confirmation"))
    n_conf = sum(1 for r in manifest_rows if r.get("confirmation"))
    # Conservative forward-per-region estimate for the expansion (EPR) umbrella.
    epr = 6.0
    estimate = int((n_main + n_conf) * epr)
    return {
        "schema": EXPANSION_SCHEMA_VERSION,
        "top_k": top_k,
        "n_mechanisms": top_k,
        "n_main_regions": n_main,
        "n_confirmation_regions": n_conf,
        "forward_per_region_estimate": epr,
        "forward_budget_projection": estimate,
        "unit": "forwards",
        "note": "estimation only; real forwards run via WP3/4/6 runners consuming the manifest",
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="run_adaptive_expansion", description="WP8 P6 adaptive expansion (pure CPU)")
    ap.add_argument("--screening-results", nargs="+", required=True,
                    help="E1..E6 FINAL aggregate jsons, e.g. WP3 FINAL_TRAJECTORY.json etc.")
    ap.add_argument("--population", required=True, help="larger REGION_POOL.jsonl")
    ap.add_argument("--target-n", type=int, default=200, help=">= target main regions per mechanism (default 200)")
    ap.add_argument("--confirmation-target", type=int, default=40, help="song-held-out confirmation regions (default 40)")
    ap.add_argument("--top-k", type=int, default=2, help="number of top mechanisms to expand (default 2)")
    ap.add_argument("--per-song-cap", type=int, default=6, help="max regions per song (default 6)")
    ap.add_argument("--confirmation-per-song-cap", type=int, default=6)
    ap.add_argument("--out-root", required=True, help="output root (under /home/hyan/Data/lyricalign/runs/...)")
    ap.add_argument("--mechanism-ids", nargs="*", default=None,
                    help="explicit mechanism override (skips ranking); used for resume/inspection")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true", help="resume: reuse prior RUN_STATE if screening digest matches")
    args = ap.parse_args(argv)

    root = Path(args.out_root)
    root.mkdir(parents=True, exist_ok=True)
    rank_dir = root / "01_ranking"
    exp_dir = root / "02_expansion"
    runtime_dir = root / "06_runtime"
    rank_dir.mkdir(parents=True, exist_ok=True)
    exp_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    screening_results = _load_screening(args.screening_results)
    screening_ids = _collect_screening_region_ids(screening_results)
    digest = _digest_of_screening(screening_results)
    run_state_path = runtime_dir / "RUN_STATE.json"

    if args.resume and run_state_path.exists():
        prior = _load_json(run_state_path)
        if prior.get("screening_digest") == digest:
            print(json.dumps({"resumed": True, "note": "screening digest unchanged; reuse prior outputs"},
                             ensure_ascii=False))
            ranking = _load_json(rank_dir / "MECHANISM_RANKING.json").get("ranking") or []
        else:
            # digest changed -> full recompute (do not silently keep stale outputs)
            ranking = list(rank_mechanisms(screening_results, top_k=args.top_k))
    else:
        ranking = list(rank_mechanisms(screening_results, top_k=args.top_k))

    if args.mechanism_ids:
        ranking = [r for r in ranking]  # keep ranking list shape; override chosen set below
        chosen_ids = list(args.mechanism_ids)
    else:
        chosen_ids = [r["mechanism_id"] for r in ranking]

    # Fallback: if ranked set didn't yield any mechanism, force top-k from ranking if present.
    if not chosen_ids:
        chosen_ids = [r["mechanism_id"] for r in ranking[:args.top_k]]

    population = _load_jsonl(args.population)
    sel = select_regions_for_expansion(
        population, chosen_ids,
        target_n=args.target_n,
        per_song_cap=args.per_song_cap,
        screening_region_ids=screening_ids,
        confirmation_target=args.confirmation_target,
        confirmation_per_song_cap=args.confirmation_per_song_cap,
        seed=args.seed,
    )

    # One manifest per chosen mechanism (dispatch target for the runner).
    manifest_rows: list[dict[str, Any]] = []
    all_rows = sel["main"] + sel["confirmation"]
    by_mech: dict[str, list[dict[str, Any]]] = {}
    for row in all_rows:
        for mech in chosen_ids:
            tagged = dict(row, mechanism=mech, confirmation=bool(row.get("confirmation")))
            by_mech.setdefault(mech, []).append(tagged)
            manifest_rows.append(tagged)
    # Combine every mechanism's rows into one MANIFEST; also emit per-mechanism.
    _write_jsonl(exp_dir / "EXPANSION_MANIFEST.jsonl", manifest_rows)
    for mech, rows in by_mech.items():
        _write_jsonl(exp_dir / f"EXPANSION_MANIFEST_{mech}.jsonl", rows)

    # Confirmation-only manifest (song-held-out), for ledger/runner packaging.
    conf_rows = [dict(r, mechanism=mech) for r in sel["confirmation"] for mech in chosen_ids]
    _write_jsonl(exp_dir / "CONFIRMATION_MANIFEST.jsonl", conf_rows)

    budget = _budget_projection(manifest_rows, len(chosen_ids))

    result = {
        "schema_version": EXPANSION_SCHEMA_VERSION,
        "screening_digest": digest,
        "n_screening_jsons": len(args.screening_results),
        "n_screening_regions_excluded": len(screening_ids),
        "top_k": len(chosen_ids),
        "chosen_mechanisms": chosen_ids,
        "ranking": ranking,
        "selection_audit": sel["audit"],
        "budget_projection": budget,
    }
    _write_json(rank_dir / "MECHANISM_RANKING.json", {"schema_version": EXPANSION_SCHEMA_VERSION,
                                                       "digest": digest, "ranking": ranking})
    _write_json(root / "FINAL_EXPANSION.json", result)
    _write_json(runtime_dir / "RUN_STATE.json", {
        "schema": EXPANSION_SCHEMA_VERSION,
        "screening_digest": digest,
        "top_k": chosen_ids,
        "out_root": str(root),
        "completed": True,
    })

    # Emit a runnable REQUESTS.jsonl (one request per region x mechanism).
    requests: list[dict[str, Any]] = []
    for row in all_rows:
        for mech in chosen_ids:
            requests.extend(build_confirmation_manifest(
                [dict(row, confirmation=bool(row.get("confirmation")))], mech))
    _write_jsonl(exp_dir / "REQUESTS.jsonl", requests)

    print(json.dumps({
        "schema_version": EXPANSION_SCHEMA_VERSION,
        "screening_digest": digest,
        "ranking": [(r["mechanism_id"], r["composite_score"]) for r in ranking],
        "chosen_mechanisms": chosen_ids,
        "main_selected": sel["audit"]["selected_main"],
        "confirmation_selected": sel["audit"]["selected_confirmation"],
        "budget_projection": budget,
        "manifest": str(exp_dir / "EXPANSION_MANIFEST.jsonl"),
        "requests": str(exp_dir / "REQUESTS.jsonl"),
        "final": str(root / "FINAL_EXPANSION.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
