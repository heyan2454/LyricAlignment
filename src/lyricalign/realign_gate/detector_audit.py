"""01_detector_audit: production detector audit + realign gate.

Read-only stage: recompute the frozen Raw detector shadow on the old E5
REQUESTS rows whose evidence still content-matches the forward identity, and
summarize unit / interval / window metrics plus a case pool for the 02 stage.
No GPU forward is run here; non-matching requests only count as missing.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lyricalign.realign_gate import identity
from lyricalign.realign_recovery.candidate_scores import (
    build_frozen_scorer_from_artifacts,
    evidence_rows_from_request,
    score_units,
)
from lyricalign.research_v7.detector_v2_contract import UnitInterval, output_from_probabilities

SCHEMA_VERSION = "detector_audit_raw_metrics_v1"
OUTPUT_KEYS = ("schema", "inputs", "command", "generated_at_utc", "result_status")

TRIGGER_IDENTITY = {
    "schema": "research_v7_detector_v2_raw_shadow_v1",
    "unsafe_window": "decision != accept (non-empty unsafe_intervals from FrozenScorer.score)",
    "interval_rule": "FrozenScorer.score raw R combo; tristate_from_p_bad with light_merge",
    "thresholds": {
        "T_accept": identity.RAW_T_ACCEPT,
        "T_reject": identity.RAW_T_REJECT,
    },
    "reused_from": "research_v7.detector_v2_intervals.light_merge / tristate_from_p_bad",
}


def _coerce_frozen_op(frozen_op: Any) -> Path:
    if isinstance(frozen_op, (str, Path)) and Path(frozen_op).is_file():
        return Path(frozen_op)
    if isinstance(frozen_op, Mapping):
        fd, tmp = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(frozen_op, fh)
        return Path(tmp)
    raise FileNotFoundError(f"frozen operating points not resolvable: {frozen_op!r}")


def _load_requests(requests_path, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with open(requests_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit is not None and limit > 0 and len(rows) >= limit:
                break
    return rows


def _song_id(row: Mapping[str, Any]) -> str:
    sid = row.get("source_song_id")
    if sid:
        return str(sid)
    prov = row.get("provenance") or {}
    window_id = prov.get("source_window_id") or ""
    if window_id:
        return str(window_id.split(":")[0])
    return str(row.get("request_id") or "unknown")


def _window_id(row: Mapping[str, Any]) -> str:
    prov = row.get("provenance") or {}
    wid = prov.get("source_window_id")
    if wid:
        return str(wid)
    return f"{_song_id(row)}:w0:full"


def _file_sha(path: str | Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _index_evidence_by_request_id(evidence_roots) -> dict[str, Path]:
    """Scan evidence roots -> {request_id: evidence_path}.

    Evidence files are named ``sha256:<content_identity>.json`` where the
    identity is the research_v7 ``request_identity(context)`` (content-addressed
    incl. audio/model/code context), NOT the realign_recovery forward digest.
    The only stable joinable key to the old REQUESTS rows is the evidence
    top-level ``metadata.request_id``.
    """
    index: dict[str, Path] = {}
    for root in evidence_roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            rid = (payload.get("metadata") or {}).get("request_id")
            if rid:
                index.setdefault(str(rid), path)
    return index


def _request_content_ok(request_row: Mapping[str, Any], evidence_payload: Mapping) -> bool:
    """Content-level match: audio/text hashes recomputed from the REQUESTS row.

    Mirrors the producer formula in research_v7.attempt.EvidencePack:
    audio_hash = sha256(f"{audio_source}|{start:.6f}|{end:.6f}")
    text_hash  = sha256("\x1f".join(text_units))
    """
    import hashlib

    ev_audio = evidence_payload.get("audio_hash")
    ev_text = evidence_payload.get("text_hash")
    if not ev_audio and not ev_text:
        return False
    audio_source = request_row.get("audio_path") or request_row.get("audio_source") or "demucs_vocal"
    audio_hash = hashlib.sha256(
        f"{audio_source}|{request_row.get('audio_start_sec', 0.0):.6f}|"
        f"{request_row.get('audio_end_sec', 60.0):.6f}".encode()
    ).hexdigest()
    text_units = request_row.get("text_units") or []
    text_hash = hashlib.sha256(
        "\x1f".join(text_units).encode()
    ).hexdigest()
    if ev_audio and ev_audio != audio_hash:
        return False
    if ev_text and ev_text != text_hash:
        return False
    return True


def locate_old_evidence(
    request_row: Mapping[str, Any],
    evidence_roots,
    index: dict[str, Path] | None = None,
) -> Path | None:
    rid = str(request_row.get("request_id") or "")
    if not rid:
        return None
    idx = index if index is not None else _index_evidence_by_request_id(evidence_roots)
    candidate = idx.get(rid)
    if candidate is None:
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not _request_content_ok(request_row, payload):
        return None
    return candidate


def recompute_window_shadow(
    request_row: Mapping[str, Any],
    evidence_payload: Mapping[str, Any],
    scorer,
) -> dict:
    rows = evidence_rows_from_request(request_row, evidence_payload)
    shadow = dict(scorer.score(rows))
    scored = score_units(scorer, rows)
    units = scored.get("units", [])
    cids = sorted(int(u["canonical_unit_id"]) for u in units)
    raw_states: dict[int, str] = {}
    if cids:
        probs = {int(u["canonical_unit_id"]): float(u["p_bad"]) for u in units}
        intervals = _consecutive_intervals(cids)
        output = output_from_probabilities(
            request_identity=str(request_row.get("request_id") or "detector_audit"),
            queried_intervals=intervals,
            probabilities=probs,
            accept_threshold=float(scorer.t_accept),
            reject_threshold=float(scorer.t_reject),
        )
        raw_states = {
            unit: interval.state.value
            for interval in output.state_intervals
            for unit in interval.interval.units()
        }
    merged_states = {int(u["canonical_unit_id"]): u["state"] for u in units}
    return {
        "shadow": shadow,
        "unit_states": raw_states,
        "merged_states": merged_states,
        "units": units,
        "n_units": scored.get("n_units", len(units)),
    }


def _consecutive_intervals(cids: list[int]) -> list[UnitInterval]:
    """Split sorted unit ids into minimal consecutive runs -> UnitIntervals."""
    if not cids:
        return []
    intervals: list[UnitInterval] = []
    start = prev = cids[0]
    for cid in cids[1:]:
        if cid == prev + 1:
            prev = cid
            continue
        intervals.append(UnitInterval(start, prev + 1))
        start = prev = cid
    intervals.append(UnitInterval(start, prev + 1))
    return intervals


def _unit_tally(states: dict[int, str]) -> dict:
    state_to_key = {"accept": "n_accept", "uncertain": "n_uncertain", "reject": "n_reject"}
    tally = {"n_units": len(states), "n_accept": 0, "n_uncertain": 0, "n_reject": 0}
    for state in states.values():
        key = state_to_key.get(str(state))
        if key is not None:
            tally[key] += 1
    tally["accept_ratio"] = _rate(tally["n_accept"], tally["n_units"])
    tally["uncertain_ratio"] = _rate(tally["n_uncertain"], tally["n_units"])
    tally["reject_ratio"] = _rate(tally["n_reject"], tally["n_units"])
    return tally


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def _window_tally(windows: list[dict]) -> dict:
    n_unsafe = sum(1 for w in windows if w["decision"] != "accept")
    n_reject = sum(1 for w in windows if w["decision"] == "reject")
    n_uncertain = sum(1 for w in windows if w["decision"] == "uncertain")
    n_intervals = sum(len(w["unsafe_intervals"]) for w in windows)
    return {
        "n_windows": len(windows),
        "n_unsafe_windows": n_unsafe,
        "n_safe_windows": len(windows) - n_unsafe,
        "n_reject_windows": n_reject,
        "n_uncertain_windows": n_uncertain,
        "unsafe_trigger_rate": _rate(n_unsafe, len(windows)),
        "n_unsafe_intervals_total": n_intervals,
        "mean_unsafe_intervals_per_window": _rate(n_intervals, len(windows)),
    }


def audit_raw_metrics(
    requests_path,
    evidence_roots,
    frozen_op,
    labels_path,
    evidence_dir_for_scorer,
    items_dirs,
    limit: int | None = None,
) -> dict:
    scorer = build_frozen_scorer_from_artifacts(
        _coerce_frozen_op(frozen_op),
        labels_path,
        evidence_dir_for_scorer,
        list(items_dirs),
        target="raw",
    )
    # Full population is read unconditionally so limit semantics are explicit
    # (B9: requested_limit / full_population_size / is_smoke persisted).
    all_requests = _load_requests(requests_path)
    full_population_size = len(all_requests)
    requests = all_requests if not limit else all_requests[:limit]
    evaluated_count = len(requests)
    windows: list[dict] = []
    missing_ids: list[str] = []
    evidence_index = _index_evidence_by_request_id(evidence_roots)
    for row in requests:
        located = locate_old_evidence(row, evidence_roots, index=evidence_index)
        if located is None:
            missing_ids.append(str(row.get("request_id") or "unknown"))
            continue
        payload = json.loads(located.read_text(encoding="utf-8"))
        recomputed = recompute_window_shadow(row, payload, scorer)
        windows.append({
            "request_id": str(row.get("request_id") or "unknown"),
            "song_id": _song_id(row),
            "window_id": _window_id(row),
            "decision": recomputed["shadow"]["decision"],
            "unsafe_intervals": recomputed["shadow"]["unsafe_intervals"],
            "target_unit_ids": sorted(recomputed["unit_states"]),
            "unit_states": recomputed["unit_states"],
            "n_units": recomputed["n_units"],
            "old_units": recomputed["units"],
        })

    return {
        "schema": SCHEMA_VERSION,
        "requested_limit": limit if limit else 0,
        "full_population_size": full_population_size,
        "evaluated_count": evaluated_count,
        "is_smoke": bool(limit),
        "n_requests": evaluated_count,
        "n_hits": len(windows),
        "n_missing": len(missing_ids),
        "missing_request_ids": missing_ids[:100],
        "tri_unit_metrics": {
            "per_song": {song: _unit_tally_states(song, windows) for song in _songs(windows)},
            "pooled": _unit_tally_states(None, windows),
        },
        "interval_metrics": {
            "per_song": {song: _window_tally(song_windows(song, windows))
                         for song in _songs(windows)},
            "pooled": _window_tally(windows),
        },
        "windows": windows,
        "trigger_identity": TRIGGER_IDENTITY,
    }


def _songs(windows: list[dict]) -> list[str]:
    seen: list[str] = []
    for w in windows:
        if w["song_id"] not in seen:
            seen.append(w["song_id"])
    return seen


def song_windows(song: str, windows: list[dict]) -> list[dict]:
    return [w for w in windows if w["song_id"] == song]


def _unit_tally_states(song, windows: list[dict]) -> dict:
    """Aggregate per-unit states, keyed by ``(song_id, cid)``.

    cid is a per-song local index (each song restarts at 0), so a pooled tally
    keyed on cid alone would let songs overwrite each other's counts. Per-song
    and pooled both key on (song_id, cid); when the same unit appears in several
    windows with different states we keep the conservative one
    (reject > uncertain > accept).
    """
    rank = {"accept": 0, "uncertain": 1, "reject": 2}
    states: dict[tuple, str] = {}
    for w in song_windows(song, windows) if song else windows:
        for cid, state in (w.get("unit_states") or {}).items():
            key = (w.get("song_id"), int(cid))
            if key not in states or rank.get(state, 0) > rank.get(states[key], 0):
                states[key] = state
    return _unit_tally(states)


def _old_unit_error_ms(old_by_cid: dict, gt_units: dict, cid) -> float | None:
    """Per-unit old alignment error vs real GT (max of |dstart|, |dend|), ms."""
    old = old_by_cid.get(int(cid))
    gt = gt_units.get(int(cid))
    if old is None or gt is None:
        return None
    ps = old.get("start_sec")
    pe = old.get("end_sec")
    if ps is None or pe is None:
        return None
    return max(abs(float(ps) - float(gt["start_sec"])),
               abs(float(pe) - float(gt["end_sec"]))) * 1000.0


def build_case_pool(audit_result: dict, real_gt: dict | None = None) -> list[dict]:
    """Build the 02 case pool. With ``real_gt`` (nested {song_id: {cid: ...}}),
    ``old_error_ms`` is derived from real GT over the old baseline alignment;
    without it every case stays ``old_error_ms=None`` (unclassifiable by GT).
    """
    real_gt = real_gt or {}
    pool: list[dict] = []
    for index, w in enumerate(audit_result.get("windows", [])):
        song = w["song_id"]
        gt_song = real_gt.get(song) or {}
        gt_units = {int(k): v for k, v in gt_song.items()}
        old_units = w.get("old_units") or []
        old_by_cid = {
            int(u.get("canonical_unit_id")): u
            for u in old_units if u.get("canonical_unit_id") is not None
        }
        target_cids = list(w.get("target_unit_ids") or [])
        bound = 0
        old_error_ms: float | None = None
        for cid in target_cids:
            if int(cid) not in gt_units:
                continue
            err = _old_unit_error_ms(old_by_cid, gt_units, cid)
            if err is None:
                continue
            bound += 1
            old_error_ms = err if old_error_ms is None else max(old_error_ms, err)
        pool.append({
            "case_id": f"{w['song_id']}:{w['window_id']}:{index}",
            "song_id": w["song_id"],
            "window_id": w["window_id"],
            "target_unit_ids": target_cids,
            "stratum_placeholder": None,
            "old_detector_state": w["decision"],
            "old_error_ms": old_error_ms,
            "gt_bound_target_units": bound,
            "gt_target_units": len(target_cids),
            "old_units": old_units,
            "source": "01_detector_audit",
        })
    return pool


def historical_bridge() -> dict:
    return {
        "schema": "historical_bridge_v1",
        "frozen_val": {
            "safe_accept_rate": identity.RAW_VAL_SAFE_ACCEPT_RATE,
            "protected_recall_95": identity.RAW_VAL_PROTECTED_RECALL,
            "n_val_units": 761,
        },
        "retrospective": dict(identity.RETROSPECTIVE_SOURCE_MISSING),
        "note": "retrospective is prose-only (source artifact missing); "
                "audit never treats it as its own metric.",
    }


def _load_cfg(cfg_path) -> dict:
    if cfg_path is None:
        return {}
    path = Path(cfg_path)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs_record(sources: dict) -> dict:
    record: dict = {}
    for name, path in sources.items():
        if path and Path(path).is_file():
            record[name] = {"path": str(Path(path).resolve()), "sha256": _file_sha(path)}
    return record


def _stage_status(audit: dict) -> tuple[str, str]:
    """Derive stage result status from hit coverage (B1 contract).

    Returns (status, reason). status in {"ok", "incomplete", "blocked"}:
    - n_requests == 0                -> blocked (no input rows)
    - n_hits == 0                    -> blocked (no usable evidence at all)
    - n_missing == n_requests        -> blocked (all evidence missing)
    - 0 < n_hits < n_requests        -> incomplete (partial evidence coverage)
    - n_hits == n_requests           -> ok
    """
    n_req = audit.get("n_requests", 0)
    n_hits = audit.get("n_hits", 0)
    n_missing = audit.get("n_missing", 0)
    if n_req == 0:
        return "blocked", "no_requests"
    if n_hits == 0 or n_missing == n_req:
        return "blocked", "no_evidence_hits"
    if n_hits < n_req:
        return "incomplete", "partial_evidence_coverage"
    return "ok", "full_evidence_coverage"


def _load_real_gt(cfg: dict) -> dict:
    """Load real GT for the audit windows from real_gt_annotations + cohort
    manifests (same projection as 03_gate). Empty dict when inputs absent."""
    inputs = cfg.get("inputs") or {}
    annotations = inputs.get("real_gt_annotations")
    manifests = inputs.get("cohort_manifests") or []
    if not annotations or not manifests:
        return {}
    from lyricalign.research_transition_recovery_detector.real_gt import (
        load_real_gt_with_audit,
    )
    real_gt: dict = {}
    for manifest in manifests:
        rg, _audit = load_real_gt_with_audit(annotations, manifest)
        for song, units in rg.items():
            real_gt.setdefault(song, {}).update(units)
    return real_gt


def run_stage(run_root, cfg_path=None, limit: int | None = None) -> dict:
    run_root = Path(run_root)
    cfg = _load_cfg(cfg_path or run_root / "00_meta" / "CONFIG.json")
    inputs = cfg.get("inputs") or {}
    old_requests = inputs.get("old_run_requests") or str(
        identity.OLD_RUN / "e5_proposals/raw/REQUESTS.jsonl")
    frozen_op = _coerce_frozen_op(inputs.get("frozen_op") or str(identity.FROZEN_OP_PATH))
    evidence_roots = inputs.get("old_run_evidence_roots") or [
        str(identity.OLD_RUN / "e5_proposals/formal/out/evidence")]
    labels_path = inputs.get("labels_path") or str(
        identity.HANDOFF_RUN / "stage3b_cohort_ab_eval/LABELS.jsonl")
    evidence_dir_for_scorer = inputs.get("evidence_dir_for_scorer") or str(
        identity.HANDOFF_RUN / "stage3b_cohort_ab_eval/evidence_v2")
    items_dirs = inputs.get("items_dirs") or [
        str(identity.HANDOFF_RUN / "stage3b_cohort_a_reagg/rerun_gpu/items"),
        str(identity.HANDOFF_RUN / "stage3b_cohort_b_dev/items"),
    ]

    audit = audit_raw_metrics(
        old_requests, evidence_roots, frozen_op, labels_path,
        evidence_dir_for_scorer, items_dirs, limit=limit)

    out_dir = run_root / "01_detector_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    command = json.dumps(sys.argv, ensure_ascii=False)
    inputs_record = _inputs_record({
        "old_run_requests": old_requests,
        "frozen_op": frozen_op,
        "labels_path": labels_path,
        "evidence_dir_for_scorer": evidence_dir_for_scorer,
        **{f"evidence_root_{i}": r for i, r in enumerate(evidence_roots)},
    })

    status, status_reason = _stage_status(audit)
    is_smoke = audit.get("is_smoke", bool(limit))
    production_audit_complete = (not is_smoke) and status == "ok"

    unit_metrics = {
        "schema": SCHEMA_VERSION,
        "inputs": inputs_record,
        "command": command,
        "generated_at_utc": generated_at,
        "result_status": status,
        "status_reason": status_reason,
        "requested_limit": audit.get("requested_limit", limit if limit else 0),
        "full_population_size": audit.get("full_population_size", audit["n_requests"]),
        "evaluated_count": audit["n_requests"],
        "is_smoke": is_smoke,
        "production_audit_complete": production_audit_complete,
        "n_requests": audit["n_requests"],
        "n_hits": audit["n_hits"],
        "n_missing": audit["n_missing"],
        "missing_request_ids": audit["missing_request_ids"],
        "tri_unit_metrics": audit["tri_unit_metrics"],
        "historical_bridge": historical_bridge(),
    }
    (out_dir / "RAW_UNIT_METRICS.json").write_text(
        json.dumps(unit_metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    window_metrics = {
        "schema": SCHEMA_VERSION,
        "inputs": inputs_record,
        "command": command,
        "generated_at_utc": generated_at,
        "result_status": status,
        "status_reason": status_reason,
        "requested_limit": audit.get("requested_limit", limit if limit else 0),
        "full_population_size": audit.get("full_population_size", audit["n_requests"]),
        "evaluated_count": audit["n_requests"],
        "is_smoke": is_smoke,
        "production_audit_complete": production_audit_complete,
        "interval_metrics": audit["interval_metrics"],
        "trigger_identity": audit["trigger_identity"],
    }
    (out_dir / "RAW_WINDOW_METRICS.json").write_text(
        json.dumps(window_metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    songs = _songs(audit["windows"])
    csv_path = out_dir / "PER_SONG.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["song_id", "n_windows", "n_unsafe_windows", "unsafe_trigger_rate",
                         "n_units", "n_accept", "n_uncertain", "n_reject"])
        for song in songs:
            tally = audit["tri_unit_metrics"]["per_song"][song]
            win = audit["interval_metrics"]["per_song"][song]
            writer.writerow([song, win["n_windows"], win["n_unsafe_windows"],
                             win["unsafe_trigger_rate"], tally["n_units"],
                             tally["n_accept"], tally["n_uncertain"], tally["n_reject"]])

    cases = build_case_pool(audit, _load_real_gt(cfg))
    with open(out_dir / "CASE_POOL.jsonl", "w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    return {
        "stage": "01_detector_audit",
        "run_root": str(run_root),
        "requested_limit": unit_metrics["requested_limit"],
        "full_population_size": unit_metrics["full_population_size"],
        "evaluated_count": audit["n_requests"],
        "is_smoke": is_smoke,
        "production_audit_complete": production_audit_complete,
        "n_requests": audit["n_requests"],
        "n_hits": audit["n_hits"],
        "n_missing": audit["n_missing"],
        "unsafe_trigger_rate": audit["interval_metrics"]["pooled"]["unsafe_trigger_rate"],
        "n_case_pool": len(cases),
        "outputs": {
            "raw_unit_metrics": str(out_dir / "RAW_UNIT_METRICS.json"),
            "raw_window_metrics": str(out_dir / "RAW_WINDOW_METRICS.json"),
            "per_song_csv": str(csv_path),
            "case_pool": str(out_dir / "CASE_POOL.jsonl"),
        },
        "result_status": status,
        "status_reason": status_reason,
    }
