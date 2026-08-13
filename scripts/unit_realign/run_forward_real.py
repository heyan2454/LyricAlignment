#!/usr/bin/env python3
"""Run v2 unit-realign requests through the frozen Qwen executor and emit
the flat baseline/candidate evidence pairs the evaluator consumes.

Contract (R4 of the round-2 data review): ``run_unit_realign.py execute``
writes FORWARDS.jsonl, but model forwards must produce exactly
``<request_id>.baseline.jsonl`` / ``<request_id>.candidate.jsonl`` in the
evidence dir (see ``run_unit_realign.py evaluate``).  The research_v7
behavior suite emits a different, content-addressed evidence layout and is not
the v2 forward path.

This script is the v2 forward adapter:
  - baseline rows are the request window's baseline alignment
    (canonical_unit_id, start_sec, end_sec) -- the detector shadow alignment
    the realign intervention moves, not the GT reference -- no model forward.
    In this corpus BASELINE_UNITS is the GT reference timeline; the baseline
    alignment times come from the region units (detector shadow) attached by
    source_adapter.attach_real_units.
  - candidate rows come from the real (or smoke) executor over the request's
    candidate audio range + text units, mapped back to canonical_unit_id via
    local_to_canonical.

Smoke mode uses a deterministic fake executor, so the whole CPU pipeline
(population -> screen -> execute -> forward -> evaluate) is testable without a
GPU.  Real mode requires --model-dir/--checkpoint-path/--revision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    _atomic_write(path, payload)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _atomic_write(path: Path, payload: str) -> None:
    fd, tmp = Path(str(path) + ".tmp"), None
    try:
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _make_smoke_executor():
    """Deterministic CPU executor mirroring research_v7's fake for v2 requests.

    Produces one row per text unit; active targets are nudged +0.1s so the
    candidate differs from baseline while context units stay frozen.  All
    times are offset by the request's audio_start_sec (as the real executor
    does), so downstream absolute-time logic is exercised.
    """
    from lyricalign.research_v7.attempt import AlignmentAttempt

    def ex(req):
        n = len(req.text_units)
        offset = req.audio_start_sec
        active = set(req.active_slot_indices or ())
        rows = []
        for i in range(n):
            delta = 0.10 if i in active else 0.0
            start = offset + i * 0.5 + delta
            end = start + 0.4
            rows.append({
                "global_character_index": i,
                "raw_global_start_sec": start, "raw_global_end_sec": end,
                "fixed_global_start_sec": start, "fixed_global_end_sec": end,
                "start_sec": start, "end_sec": end,
                "decoder_kind": "official",
            })
        return AlignmentAttempt(
            request=req, attempt_id=f"F-{req.item_id}-{req.mutation_type}",
            decoder_outputs={"official": {"rows": rows}, "raw": {"rows": rows}},
            cursor_after=float(n) * 0.5 + offset, committed=True, status="ok",
        )

    return ex


def _make_real_executor(args):
    from lyricalign.research_v7.real_executor import RealAligner, make_real_executor
    return make_real_executor(RealAligner(args.model_dir, args.revision, args.checkpoint_path))


def _to_v7_request(v2: dict, audio_path: str):
    """Translate one v2 unit-realign request into a research_v7 AlignmentRequest."""
    from lyricalign.research_v7.requests import AlignmentRequest

    text_units = tuple(str(u) for u in v2.get("text_units") or ())
    ids = [int(x) for x in v2.get("canonical_ids") or ()]
    local_to_canonical = [int(x) for x in v2.get("local_to_canonical") or ids]
    a0, a1 = (float(x) for x in (v2.get("candidate_audio_range_sec") or [0.0, 0.0]))
    family = str(v2.get("family") or "R-U")
    c2l = {int(k): int(v) for k, v in (v2.get("canonical_to_local") or {}).items()}
    if ids and len(c2l) != len(ids):
        c2l = {cid: i for i, cid in enumerate(ids)}
    return AlignmentRequest(
        request_id=str(v2.get("request_id") or ""),
        item_id=str(v2.get("region_id") or ""),
        parent_request_id=None,
        audio_source=audio_path,
        audio_start_sec=a0,
        audio_end_sec=a1,
        text_source="unit_realign_v2",
        text_start_index=0,
        text_end_index=len(text_units),
        text_units=text_units,
        timestamp_slot_indices=tuple(int(x) for x in v2["timestamp_slot_indices"]) if v2.get("timestamp_slot_indices") is not None else None,
        workflow_mode="unit_realign_v2",
        mutation_type=family,
        mutation_parameters={"request_identity": v2.get("request_identity")},
        model_id=str(v2.get("model_identity") or "unknown"),
        checkpoint_id=str(v2.get("checkpoint_identity") or "unknown"),
        input_variant=f"unit_realign_{family}",
        active_slot_indices=tuple(int(x) for x in v2["active_slot_indices"]) if v2.get("active_slot_indices") is not None else None,
        fixed_slot_rows=v2.get("fixed_slot_rows") or None,
        slot_constraint_schema=v2.get("slot_constraint_schema"),
        canonical_text_start=min(ids) if ids else None,
        canonical_text_end=(max(ids) + 1) if ids else None,
        canonical_to_local=c2l or None,
        canonical_ids=ids or None,
        metadata={"song_id": str(v2.get("song_id") or ""), "region_id": str(v2.get("region_id") or ""),
                  "family": family, "stratum": v2.get("stratum")},
    )


def _baseline_rows(region: dict, canonical_ids: list[int]) -> list[dict]:
    """Frozen detector baseline rows for the request window (no forward)."""
    units = region.get("units") or ()
    by_id = {int(u.get("canonical_unit_id")): u for u in units}
    rows = []
    for cid in canonical_ids:
        u = by_id.get(int(cid))
        if u is None:
            continue
        rows.append({"canonical_unit_id": int(cid),
                     "start_sec": float(u["start_sec"]), "end_sec": float(u["end_sec"])})
    return rows


def _candidate_rows(attempt, local_to_canonical: list[int]) -> tuple[list[dict], str | None]:
    """Map executor rows (global_character_index) back to canonical_unit_id."""
    if getattr(attempt, "status", "") != "ok":
        return [], getattr(attempt, "error", None) or f"status={getattr(attempt, 'status', 'unknown')}"
    rows = (attempt.decoder_outputs or {}).get("official", {}).get("rows") or []
    out = []
    for row in rows:
        gci = row.get("global_character_index")
        if not isinstance(gci, int):
            continue
        if gci < 0 or gci >= len(local_to_canonical):
            continue
        start = row.get("fixed_global_start_sec", row.get("start_sec"))
        end = row.get("fixed_global_end_sec", row.get("end_sec"))
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            continue
        out.append({"canonical_unit_id": int(local_to_canonical[gci]),
                    "start_sec": float(start), "end_sec": float(end)})
    out.sort(key=lambda r: r["canonical_unit_id"])
    return out, None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-root", required=True)
    p.add_argument("--requests", help="01_requests/REQUESTS.jsonl (default: <out-root>/01_requests/REQUESTS.jsonl)")
    p.add_argument("--forwards", help="02_forwards/FORWARDS.jsonl (default: <out-root>/02_forwards/FORWARDS.jsonl)")
    p.add_argument("--regions", help="00_population/REGION_POOL.jsonl (default: <out-root>/00_population/REGION_POOL.jsonl)")
    p.add_argument("--evidence-dir", help="02_forwards/evidence (default)")
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
    requests_path = Path(args.requests) if args.requests else root / "01_requests" / "REQUESTS.jsonl"
    forwards_path = Path(args.forwards) if args.forwards else root / "02_forwards" / "FORWARDS.jsonl"
    regions_path = Path(args.regions) if args.regions else root / "00_population" / "REGION_POOL.jsonl"
    if not requests_path.exists() or not forwards_path.exists() or not regions_path.exists():
        p.error(f"REQUESTS/FORWARDS/REGION_POOL required "
                f"(requests={requests_path.exists()}, forwards={forwards_path.exists()}, "
                f"regions={regions_path.exists()})")
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else root / "02_forwards" / "evidence"

    requests_by_id = {str(r.get("request_id") or r.get("request_identity") or ""): r
                      for r in _read_jsonl(requests_path)}
    forwards = _read_jsonl(forwards_path)
    if args.limit:
        forwards = forwards[: args.limit]
    regions_by_key = {}
    for region in _read_jsonl(regions_path):
        regions_by_key[(str(region.get("song_id") or ""), str(region.get("region_id") or ""))] = region

    executor = _make_real_executor(args) if args.real else _make_smoke_executor()

    executed, skipped, failed = [], [], []
    for fwd in forwards:
        rid = str(fwd.get("request_id") or fwd.get("request_identity") or "")
        v2 = requests_by_id.get(rid)
        if v2 is None:
            failed.append({"request_id": rid, "status": "failed", "error": "request_not_in_requests_manifest"})
            continue
        baseline_path = evidence_dir / f"{rid}.baseline.jsonl"
        candidate_path = evidence_dir / f"{rid}.candidate.jsonl"
        if args.resume and baseline_path.exists() and candidate_path.exists():
            skipped.append({"request_id": rid, "status": "skipped_resume"})
            continue
        region = regions_by_key.get((str(v2.get("song_id") or ""), str(v2.get("region_id") or "")))
        if region is None:
            failed.append({"request_id": rid, "status": "failed", "error": "region_not_in_pool"})
            continue
        audio_path = str(v2.get("audio_path") or "")
        if not audio_path or (args.real and not Path(audio_path).is_file()):
            failed.append({"request_id": rid, "status": "failed", "error": f"audio_missing:{audio_path}"})
            continue
        ids = [int(x) for x in v2.get("canonical_ids") or ()]
        local_to_canonical = [int(x) for x in v2.get("local_to_canonical") or ids]
        baseline_rows = _baseline_rows(region, ids)
        try:
            req = _to_v7_request(v2, audio_path)
            req.validate()
        except Exception as exc:
            failed.append({"request_id": rid, "status": "failed", "error": f"request_build:{exc}"})
            continue
        try:
            attempt = executor(req)
            candidate_rows, error = _candidate_rows(attempt, local_to_canonical)
        except Exception as exc:
            failed.append({"request_id": rid, "status": "failed", "error": f"forward:{exc}"})
            continue
        if error:
            failed.append({"request_id": rid, "status": "failed", "error": error})
            continue
        _write_jsonl(baseline_path, baseline_rows)
        _write_jsonl(candidate_path, candidate_rows)
        executed.append({"request_id": rid, "status": "executed",
                         "n_baseline": len(baseline_rows), "n_candidate": len(candidate_rows)})

    result = {"schema": "unit_realign_forward_execution_v1",
              "executor": "real" if args.real else "smoke",
              "n_executed": len(executed), "n_skipped_resume": len(skipped), "n_failed": len(failed),
              "evidence_dir": str(evidence_dir),
              "executed": executed, "skipped": skipped, "failed": failed}
    out_path = root / "02_forwards" / "FORWARD_EXECUTION.json"
    _write_json(out_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
