#!/usr/bin/env python3
"""WP5 — E3-B audio recrop / multi-scale study runner (shadow-only, no-GT).

For each region (from REGIONS), pre-register a small set of audio views
(base / wider / left_enriched / recentered), build one v2 request per view
(distinct ``recrop_view_id`` => distinct request_identity), run each view
candidate through an executor (smoke fake or real), and then select a canonical
view WITHOUT GT using only actual available no-GT signals (see
``audio_views.select_view_no_gt``).  When no usable signal exists, selection is
reported ``not_selected / indeterminate`` rather than GT-hard-selected
(GT firewall).

Outputs (schema ``audio_view_study_v1``):
  - ``01_requests/REQUESTS.jsonl``: every (region, view) request materialized.
  - ``02_views/VIEW_OUTCOMES.jsonl``: per-view outcome incl. candidate signals,
    request_identity, recrop_view_id, view_kind and the no-GT selection result.
  - ``06_runtime/RUN_STATE.json``: resume ledger (completed/skipped view identities).
  - ``FINAL_VIEWS.json``: per-region selection summary + selection trigger counts.

Smoke mode synthesizes deterministic regions (or accepts ``--regions``) and a
deterministic fake executor so the whole CPU pipeline is testable without a GPU.
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

from lyricalign.unit_realign import audio_views
from lyricalign.unit_realign.audio_views import AUDIO_VIEW_SCHEMAS, build_view_requests, select_view_no_gt

VIEW_STUDY_SCHEMA = "audio_view_study_v1"
RUN_STATE_SCHEMA = "audio_view_run_state_v1"


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _write_json(path, value):
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _write_jsonl(path, rows):
    _atomic_write(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def _smoke_identity_context() -> dict:
    return {
        "audio_sha256": "sha256:smoke-audio",
        "baseline_digest": "sha256:smoke-baseline",
        "model_identity": "smoke:model",
        "checkpoint_identity": "smoke:checkpoint",
        "decoder_identity": "official",
        "mapping_schema": "unit_realign_local_v2",
        "code_identity": "git:smoke",
        "text_adapter_identity": "pypinyin-zh",
    }


def _synthesize_regions(n, *, duration_sec=30.0) -> list[dict]:
    """Deterministic CPU smoke regions: 8 units, target span of 3 units at index 3..5."""
    out = []
    for i in range(n):
        song_id = f"smoke-song-{i}"
        region_id = f"smoke-song-{i}:w0:unsafe:0"
        units = []
        t0 = 3.0 + 3.5 * i % 10
        for j in range(8):
            units.append({
                "canonical_unit_id": j,
                "start_sec": t0 + j * 0.5,
                "end_sec": t0 + j * 0.5 + 0.4,
                "text": "汉" if j % 2 == 0 else "字",
            })
        out.append({
            "schema": "unit_realign_region_v1", "song_id": song_id, "region_id": region_id,
            "window_index": 0, "language": "zh", "detector_state": "UNSAFE",
            "target_unit_ids": [3, 4, 5], "units": units, "family": "R-U",
            "audio_path": f"{song_id}.wav", "identity_context": _smoke_identity_context(),
            "duration_sec": duration_sec,
        })
    return out


def _candidate_rows_to_v7(req_v2, baseline_rows):
    """Translate a v2 request to a research_v7-style object consumed by the fake
    executor, mirroring run_forward_real._to_v7_request.  Returns (req, None) or
    (None, error)."""
    from lyricalign.research_v7.requests import AlignmentRequest

    ids = [int(x) for x in req_v2.get("canonical_ids") or ()]
    local_to_canonical = [int(x) for x in req_v2.get("local_to_canonical") or ids]
    c2l = {int(k): int(v) for k, v in (req_v2.get("canonical_to_local") or {}).items()}
    if ids and len(c2l) != len(ids):
        c2l = {cid: i for i, cid in enumerate(ids)}
    a0, a1 = (float(x) for x in (req_v2.get("candidate_audio_range_sec") or [0.0, 0.0]))
    return AlignmentRequest(
        request_id=str(req_v2.get("request_id") or ""),
        item_id=str(req_v2.get("region_id") or ""),
        parent_request_id=None,
        audio_source=str(req_v2.get("audio_path") or ""),
        audio_start_sec=a0,
        audio_end_sec=a1,
        text_source="unit_realign_v2",
        text_start_index=0,
        text_end_index=len(req_v2.get("text_units") or ()),
        text_units=tuple(str(u) for u in req_v2.get("text_units") or ()),
        timestamp_slot_indices=tuple(int(x) for x in req_v2["timestamp_slot_indices"]) if req_v2.get("timestamp_slot_indices") is not None else None,
        workflow_mode="unit_realign_v2",
        mutation_type=str(req_v2.get("family") or "R-U"),
        mutation_parameters={"request_identity": req_v2.get("request_identity"),
                             "recrop_view_id": req_v2.get("recrop_view_id")},
        model_id=str(req_v2.get("model_identity") or "unknown"),
        checkpoint_id=str(req_v2.get("checkpoint_identity") or "unknown"),
        input_variant=f"unit_realign_{req_v2.get('family', 'R-U')}",
        active_slot_indices=tuple(int(x) for x in req_v2["active_slot_indices"]) if req_v2.get("active_slot_indices") is not None else None,
        fixed_slot_rows=req_v2.get("fixed_slot_rows") or None,
        slot_constraint_schema=req_v2.get("slot_constraint_schema"),
        canonical_text_start=min(ids) if ids else None,
        canonical_text_end=(max(ids) + 1) if ids else None,
        canonical_to_local=c2l or None,
        canonical_ids=ids or None,
        metadata={"song_id": str(req_v2.get("song_id") or ""),
                  "region_id": str(req_v2.get("region_id") or ""),
                  "family": req_v2.get("family"), "recrop_view_id": req_v2.get("recrop_view_id")},
    )


def _baseline_rows(region, canonical_ids):
    by_id = {int(u.get("canonical_unit_id")): u for u in (region.get("units") or ())}
    rows = []
    for cid in canonical_ids:
        u = by_id.get(int(cid))
        if u is None:
            continue
        rows.append({"canonical_unit_id": int(cid),
                     "start_sec": float(u["start_sec"]), "end_sec": float(u["end_sec"])})
    return rows


def _make_smoke_executor():
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


def _candidate_rows(attempt, local_to_canonical):
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


# no-GT structural enrichment: displacement/geometric flags only, never outcome/GT.
def _enrich_no_gt_candidate_rows(candidate_rows, baseline_rows, targets):
    bl = {int(r["canonical_unit_id"]): r for r in baseline_rows}
    target_set = {int(x) for x in targets}
    out = []
    for row in candidate_rows:
        cid = int(row["canonical_unit_id"])
        old = bl.get(cid, {})
        os_, oe = old.get("start_sec"), old.get("end_sec")
        ns, ne = row.get("start_sec"), row.get("end_sec")
        disp = None
        if None not in (os_, oe, ns, ne):
            disp = round((abs(ns - os_) + abs(ne - oe)) * 500.0, 4)
        out.append({
            **row,
            "mean_boundary_displacement_ms": disp,
            "candidate_missing": False,
            "context_protected": None if cid in target_set or disp is None else disp <= 10.0,
        })
    return out


def _state(path):
    if not Path(path).exists():
        return {"schema": RUN_STATE_SCHEMA, "completed_view_identities": [],
                "completed_region_ids": [], "skipped_resume": [], "updated_at_utc": None}
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    state.setdefault("schema", RUN_STATE_SCHEMA)
    state.setdefault("completed_view_identities", [])
    state.setdefault("completed_region_ids", [])
    state.setdefault("skipped_resume", [])
    return state


def _per_view_summary(vr):
    return {
        "recrop_view_id": vr.get("recrop_view_id"),
        "view_kind": vr.get("view_kind"),
        "request_identity": vr.get("request_identity"),
        "status": vr.get("status"),
        "candidate_row_count": len(vr.get("candidate_rows") or ()),
    }


def _view_result(request, view_out, candidate_rows, region, baselines):
    req_id = str(request.get("request_id") or request.get("request_identity") or request.get("region_id"))
    targets = request.get("active_target_unit_ids") or request.get("target_unit_ids") or ()
    if view_out is not None:
        rows = []
    else:
        rows = _enrich_no_gt_candidate_rows(
            candidate_rows, baselines.get(req_id, []), targets)
    return {
        "schema": VIEW_STUDY_SCHEMA, "song_id": str(request.get("song_id") or ""),
        "region_id": str(request.get("region_id") or ""),
        "request_id": str(request.get("request_id") or ""),
        "request_identity": request.get("request_identity"),
        "recrop_view_id": request.get("recrop_view_id"),
        "view_kind": request.get("view_kind"),
        "family": request.get("family"),
        "audio_start_sec": request.get("audio_start_sec"),
        "audio_end_sec": request.get("audio_end_sec"),
        "status": "ok",
        "candidate_rows": rows,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-root", required=True)
    p.add_argument("--regions", help="REGION jsonl; synth smoke regions when absent/--smoke")
    p.add_argument("--views", default="base,wider,left_enriched,recentered",
                   help="comma-separated subset of " + ",".join(AUDIO_VIEW_SCHEMAS))
    p.add_argument("--family", default="R-U")
    p.add_argument("--duration-sec", type=float, default=30.0,
                   help="audio clip duration used to clip the pre-registered view crops")
    p.add_argument("--limit", type=int, default=0, help="limit processed regions (smoke)")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--real", action="store_true")
    p.add_argument("--model-dir")
    p.add_argument("--revision", default="main")
    p.add_argument("--checkpoint-path")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    if args.smoke == args.real:
        p.error("choose exactly one of --smoke or --real")
    if args.real and (not args.model_dir or not args.checkpoint_path):
        p.error("--real requires --model-dir and --checkpoint-path")

    view_kinds = [v.strip() for v in args.views.split(",") if v.strip()]
    unknown = [v for v in view_kinds if v not in AUDIO_VIEW_SCHEMAS]
    if unknown:
        p.error("unknown --views: " + ", ".join(unknown))

    if args.regions:
        regions = _read_jsonl(args.regions)
    elif args.smoke:
        regions = _synthesize_regions(3 if args.limit == 0 else args.limit,
                                      duration_sec=args.duration_sec)
    else:
        p.error("--regions required (or use --smoke to synthesize)")

    root = Path(args.out_root)
    if args.limit:
        regions = regions[:args.limit]

    executor = _make_smoke_executor()
    state = _state(root / "06_runtime" / "RUN_STATE.json")
    completed = set(state["completed_view_identities"])

    # 1) Materialize requests for every (region, view).
    requests, view_index = [], {}
    baseline_cache = {}
    for region in regions:
        song, region_id = str(region.get("song_id") or ""), str(region.get("region_id") or "")
        duration_sec = float(region.get("duration_sec") or args.duration_sec)
        # GPU-real fix: when no explicit duration_sec, infer it from the region's
        # actual unit span + margin so a target deep into a long audio isn't
        # clipped into an empty crop by a default like 30s.
        if not region.get("duration_sec"):
            unit_ends = [float(u.get("end_sec") or 0.0) for u in (region.get("units") or ())]
            if unit_ends:
                inferred = max(unit_ends) + 5.0
                duration_sec = max(duration_sec, inferred)
        region_requests = build_view_requests(
            region, [int(x) for x in region.get("target_unit_ids") or ()],
            family=args.family, duration_sec=duration_sec,
            identity_context=region.get("identity_context"),
            view_kinds=view_kinds,
        )
        for r in region_requests:
            rid = str(r.get("request_id") or r.get("region_id"))
            requests.append(r)
            view_index[(song, region_id, r.get("recrop_view_id"))] = r
            baseline_cache[rid] = _baseline_rows(region, [int(x) for x in r.get("canonical_ids") or ()])
    _write_jsonl(root / "01_requests" / "REQUESTS.jsonl", requests)

    # 2) Execute each view (smoke) or forward (real), then select no-GT per region.
    outcomes, skipped_ids, failed, region_summaries = [], [], [], []
    for region in regions:
        song, region_id = str(region.get("song_id") or ""), str(region.get("region_id") or "")
        region_requests = [r for r in requests
                           if r.get("song_id") == song and r.get("region_id") == region_id]
        view_results = []
        for request in region_requests:
            identity = request.get("request_identity")
            rid = str(request.get("request_id") or request.get("region_id"))
            if args.resume and identity and identity in completed:
                skipped_ids.append(identity)
                continue
            if request.get("status") in {"not_constructible", "null"}:
                vr = _view_result(request, None, [], region, baseline_cache)
                vr["status"] = request.get("status")
                vr["reason"] = request.get("reason")
                vr["candidate_rows"] = []
                view_results.append(vr)
                failed.append({"song_id": song, "region_id": region_id,
                               "recrop_view_id": request.get("recrop_view_id"),
                               "status": request.get("status"), "reason": request.get("reason"),
                               "request_identity": identity})
                continue
            try:
                v7 = _candidate_rows_to_v7(request, baseline_cache[rid])
                v7.validate()
                attempt = executor(v7)
                cand, error = _candidate_rows(attempt,
                                              [int(x) for x in request.get("local_to_canonical") or ()])
                vr = _view_result(request, None, cand, region, baseline_cache)
                if error:
                    vr["status"] = "failed"
                    vr["reason"] = error
                    vr["candidate_rows"] = []
            except Exception as exc:  # noqa: BLE001
                vr = _view_result(request, None, [], region, baseline_cache)
                vr["status"] = "failed"
                vr["reason"] = f"forward:{exc}"
            view_results.append(vr)
            if identity and vr["status"] == "ok":
                state["completed_view_identities"].append(identity)
            if vr["status"] != "ok":
                failed.append({"song_id": song, "region_id": region_id,
                               "recrop_view_id": request.get("recrop_view_id"),
                               "status": vr["status"], "reason": vr.get("reason"),
                               "request_identity": identity})

        # No-GT selection over this region's executed views.
        ok_views = [vr for vr in view_results if vr["status"] == "ok"]
        if not ok_views:
            summary = {"schema": VIEW_STUDY_SCHEMA, "song_id": song, "region_id": region_id,
                       "selected": None, "selected_view": None, "status": "no_ok_view",
                       "reason": "no region view executed successfully",
                       "per_view": [_per_view_summary(vr) for vr in view_results]}
        else:
            summary = select_view_no_gt(ok_views)
            summary["song_id"] = song
            summary["region_id"] = region_id
        # Attach the GLOBAL no-GT selection decision to every view row of the region.
        global_sel = {k: summary.get(k) for k in ("selected", "selected_view", "status", "reason")
                      if k in summary}
        triggered = summary.get("status") == "selected_no_gt"
        for vr in view_results:
            vr["selection"] = dict(global_sel)
            vr["no_gt_selection_triggered"] = triggered
            vr["is_selected_view"] = bool(triggered) and vr.get("recrop_view_id") == summary.get("selected_view")
            if vr.get("request_identity"):
                outcomes.append(vr)
        summary["views"] = len(view_results)
        region_summaries.append(summary)

    _write_jsonl(root / "02_views" / "VIEW_OUTCOMES.jsonl", outcomes)
    state["skipped_resume"] = sorted(set(skipped_ids))
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(root / "06_runtime" / "RUN_STATE.json", state)

    # 3) FINAL_VIEWS.json: per-region selection summary + trigger accounting.
    final_views = []
    for summary in region_summaries:
        song, region_id = str(summary.get("song_id") or ""), str(summary.get("region_id") or "")
        region_outcomes = [vr for vr in outcomes if vr.get("region_id") == region_id]
        selected_views = [vr.get("recrop_view_id") for vr in region_outcomes
                          if vr.get("is_selected_view")]
        final_views.append({
            "song_id": song, "region_id": region_id,
            "n_views": len(region_outcomes),
            "n_ok_views": len([vr for vr in region_outcomes if vr.get("status") == "ok"]),
            "selection_status": summary.get("status"),
            "selected": summary.get("selected_view"),
            "selection_triggered": summary.get("status") == "selected_no_gt",
            "selected_view_row": selected_views[0] if len(set(selected_views)) == 1
                                 else ("conflict" if selected_views else None),
        })
    _write_jsonl(root / "02_views" / "FINAL_VIEWS.jsonl", final_views)

    result = {
        "schema": VIEW_STUDY_SCHEMA, "executor": "real" if args.real else "smoke",
        "n_regions": len(regions), "n_requests": len(requests),
        "n_views": len(requests), "n_completed": len(state["completed_view_identities"]),
        "n_skipped_resume": len(skipped_ids), "n_failed": len(failed),
        "n_selected_no_gt": sum(1 for s in region_summaries if s.get("status") == "selected_no_gt"),
        "n_indeterminate": sum(1 for s in region_summaries if s.get("status") == "indeterminate"),
        "n_no_signal": sum(1 for s in region_summaries if s.get("status") == "no_signal"),
        "views": view_kinds, "out_root": str(root),
    }
    _write_json(root / "FINAL_VIEWS.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
