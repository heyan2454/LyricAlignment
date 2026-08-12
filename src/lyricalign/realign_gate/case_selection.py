"""Realign Gate stage 02: case selection + no-GT realign behavior requests.

Consumes the stage-01 CASE_POOL (per-song detector audit) and produces S1..S4
strata plus research_v7-compatible R-A/R-B proposal requests that all pass the
GT firewall. Forward execution is delegated to
``scripts/research_v7/run_behavior_suite.py`` via an injectable subprocess hook
(``_invoke_suite``) so tests never touch the real executor.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from lyricalign.realign_gate import identity
from lyricalign.realign_recovery.e5_proposals import build_proposals, load_timeline_manifest
from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request

_WINDOW_RE = re.compile(r":w(\d+)")
_DETECTOR_STATES = ("ACCEPT", "UNCERTAIN", "REJECT")
_STRATA_ORDER = ("S1", "S3", "S4")
CORRECT_MAX_ERROR_MS = 200.0
BAD_MIN_ERROR_MS = 1000.0


def load_jsonl(path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path, rows: Iterable[dict]) -> str:
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    return path


def _normalize_state(state):
    if state is None:
        return None
    s = str(state).strip().upper()
    return s if s in _DETECTOR_STATES else None


def _classify(case: dict) -> tuple[str | None, bool]:
    """Return (sampling_label, approximate); None label means unclassifiable.

    Main label from real GT: old_error_ms <= 200ms -> correct, > 1s -> bad.
    Without GT error the case is unclassifiable (approximate=True) and must be
    excluded, never approximated from the detector state."""
    err = case.get("old_error_ms")
    if err is not None:
        try:
            e = float(err)
        except (TypeError, ValueError):
            return None, True
        if e <= CORRECT_MAX_ERROR_MS:
            return "correct", False
        if e > BAD_MIN_ERROR_MS:
            return "bad", False
        return None, False
    return None, True


def _stratum_for(label: str | None, state: str | None) -> str | None:
    if label is None or state is None:
        return None
    if label == "correct" and state == "ACCEPT":
        return "S1"
    if label == "correct" and state in ("UNCERTAIN", "REJECT"):
        return "S2"
    if label == "bad" and state in ("UNCERTAIN", "REJECT"):
        return "S3"
    if label == "bad" and state == "ACCEPT":
        return "S4"
    return None


def sample_strata(
    case_pool: list[dict],
    *,
    n_target: int,
    s2_share: float,
    seed: int,
    max_per_song: int,
    max_per_song_stratum: int,
) -> list[dict]:
    """Select stratified cases: S1 correct+ACCEPT, S2 correct+UNCERTAIN/REJECT,
    S3 bad+UNCERTAIN/REJECT, S4 bad+ACCEPT.

    Constraints: at most ``max_per_song_stratum`` per song per stratum,
    at most ``max_per_song`` per song overall, S2 share within
    ``s2_share`` (25-35%), total 60-100. S4 is never force-filled.
    """
    n_target = int(n_target)
    s2_share = float(s2_share)
    if not 60 <= n_target <= 100:
        raise ValueError(f"n_target must be in [60, 100], got {n_target}")
    if not 0.25 <= s2_share <= 0.35:
        raise ValueError(f"s2_share must be in [0.25, 0.35], got {s2_share}")

    buckets: dict[str, list[dict]] = {"S1": [], "S2": [], "S3": [], "S4": []}
    for case in case_pool:
        label, approximate = _classify(case)
        state = _normalize_state(case.get("old_detector_state"))
        stratum = _stratum_for(label, state)
        if stratum is None:
            continue
        entry = {
            "case_id": case.get("case_id"),
            "song_id": case.get("song_id"),
            "window_id": case.get("window_id"),
            "stratum": stratum,
            "target_unit_ids": case.get("target_unit_ids"),
            "old_detector_state": case.get("old_detector_state"),
            "old_error_ms": case.get("old_error_ms"),
            "old_units": case.get("old_units"),
            "sampling_label": label,
            "sampling_label_approximate": bool(approximate),
        }
        if case.get("source") is not None:
            entry["source"] = case["source"]
        buckets[stratum].append(entry)

    rng = random.Random(seed)
    for st in buckets:
        buckets[st].sort(key=lambda e: (str(e.get("song_id")), str(e.get("case_id"))))
        rng.shuffle(buckets[st])

    selected: list[dict] = []
    song_total: dict[str, int] = defaultdict(int)
    song_stratum_count: dict[tuple[str, str], int] = defaultdict(int)

    def can_add(entry: dict) -> bool:
        song = str(entry.get("song_id"))
        if song_total[song] >= max_per_song:
            return False
        if song_stratum_count[(song, entry["stratum"])] >= max_per_song_stratum:
            return False
        return True

    def add(entry: dict) -> None:
        song = str(entry.get("song_id"))
        song_total[song] += 1
        song_stratum_count[(song, entry["stratum"])] += 1
        selected.append(entry)

    s2_target = int(round(n_target * s2_share))
    s2_taken = 0
    for entry in buckets["S2"]:
        if s2_taken >= s2_target or len(selected) >= n_target:
            break
        if can_add(entry):
            add(entry)
            s2_taken += 1

    for st in _STRATA_ORDER:
        for entry in buckets[st]:
            if len(selected) >= n_target:
                break
            if can_add(entry):
                add(entry)

    return selected


def _parse_window_index(window_id) -> int:
    if window_id is None:
        return 0
    if isinstance(window_id, int):
        return window_id
    m = _WINDOW_RE.search(str(window_id))
    return int(m.group(1)) if m else 0


def _window_text_unit_ids(timeline: dict, song_id: str) -> list[int]:
    meta = timeline.get(song_id)
    if not meta:
        return []
    return sorted(int(c) for c in meta["units"])


def build_requests(
    cases: list[dict],
    timeline_manifest_paths,
    baseline_rows: list[dict],
    *,
    model_id: str,
    checkpoint_id: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Convert cases to R-A/R-B episodes, build proposals, enforce GT firewall.

    Returns (requests, plan, skipped). Every returned request carries the
    research_v7_long_slot_v1 schema and passes validate_no_gt_request; rows that
    fail the firewall go to ``skipped`` (never into requests).
    """
    timeline = load_timeline_manifest(timeline_manifest_paths)
    episodes: list[dict] = []
    for case in cases:
        song_id = case.get("song_id")
        if song_id is None:
            continue
        episodes.append({
            "id": case.get("case_id") or f"case-{len(episodes)}",
            "song_id": song_id,
            "target_unit_ids": list(case.get("target_unit_ids") or []),
            "source_window": {
                "text_unit_ids": _window_text_unit_ids(timeline, song_id),
                "window_index": _parse_window_index(case.get("window_id")),
            },
            "family": "realign_gate",
            "kind": case.get("stratum", "unknown"),
        })

    requests, plan = build_proposals(
        episodes,
        timeline_manifest_paths,
        baseline_rows,
        include_original=False,
        include_oracle=False,
        include_ra=True,
        include_rb=True,
        include_rc=False,
        model_id=model_id,
        checkpoint_id=checkpoint_id,
    )

    kept: list[dict] = []
    skipped: list[dict] = []
    for row in requests:
        forbidden = validate_no_gt_request(row)
        if forbidden:
            skipped.append({
                "request_id": row.get("request_id"),
                "case_id": (row.get("provenance") or {}).get("episode_id"),
                "forbidden": sorted(forbidden),
                "reason": "no_gt_violation",
            })
        else:
            kept.append(row)
    return kept, plan, skipped


def no_gt_check(requests: list[dict]) -> list[dict]:
    """Per-request GT firewall audit: {request_id, validated, forbidden}."""
    out: list[dict] = []
    for row in requests:
        forbidden = validate_no_gt_request(row)
        out.append({
            "request_id": row.get("request_id"),
            "validated": not forbidden,
            "forbidden": sorted(forbidden),
        })
    return out


def build_candidate_index(suite_out_root, requests: list[dict]) -> list[dict]:
    """Rebuild candidate linkage from the forward suite output.

    Each row: {request_id, variant, case_id, content_idn, evidence_path}.
    Identity comes from RUN_MANIFEST.json requests_identity/cache_keys; the
    evidence path is resolved from evidence/<content_idn>.json or
    cached/<content_idn>.json.
    """
    root = Path(suite_out_root)
    manifest: dict = {}
    manifest_path = root / "RUN_MANIFEST.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    identity_by_request: dict[str, str] = {}
    status_by_request: dict[str, str] = {}
    for item in manifest.get("requests_identity") or []:
        rid = item.get("request_id")
        if rid:
            identity_by_request[rid] = item.get("request_identity")
            status_by_request[rid] = item.get("status")

    out: list[dict] = []
    for row in requests:
        rid = row.get("request_id")
        content_idn = identity_by_request.get(rid)
        variant = row.get("input_variant")
        if not variant and row.get("provenance"):
            variant = row["provenance"].get("proposal_method")
        case_id = (row.get("provenance") or {}).get("episode_id")
        evidence_path: str | None = None
        if content_idn:
            for candidate in (root / "evidence" / f"{content_idn}.json",
                              root / "cached" / f"{content_idn}.json"):
                if candidate.exists():
                    evidence_path = str(candidate)
                    break
        out.append({
            "request_id": rid,
            "variant": variant,
            "case_id": case_id,
            "content_idn": content_idn,
            "evidence_path": evidence_path,
            "status": status_by_request.get(rid),
        })
    return out


_MODEL_DIR_CANDIDATES = (
    "/root/autodl-tmp/AST_storage/Data/lyricalign/models/hf_cache"
    "/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots",
    "/home/hyan/Data/lyricalign/models/hf_cache"
    "/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots",
    "/root/.cache/huggingface/hub/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots",
)


def resolve_model_dir(model_revision: str) -> str | None:
    for snap_root in _MODEL_DIR_CANDIDATES:
        candidate = Path(snap_root) / model_revision
        if (candidate / "model.safetensors").exists():
            return str(candidate)
    return None


def _suite_argv(
    manifest_path,
    out_root,
    *,
    smoke: bool,
    gpu: bool,
    limit: int,
    model_id: str,
    checkpoint_id: str,
    model_revision: str,
    checkpoint_path: str | None,
    resume: bool,
) -> list[str]:
    script = identity.REPO_ROOT / "scripts" / "research_v7" / "run_behavior_suite.py"
    argv = [sys.executable, str(script), "--manifest", str(manifest_path),
            "--out-root", str(out_root)]
    if limit:
        argv += ["--limit", str(int(limit))]
    if smoke:
        argv.append("--smoke")
    else:
        model_dir = resolve_model_dir(model_revision)
        argv += ["--real", "--model", model_id, "--checkpoint", checkpoint_id,
                 "--revision", model_revision, "--model-dir", str(model_dir)]
        if checkpoint_path:
            argv += ["--checkpoint-path", str(checkpoint_path)]
        if resume:
            argv.append("--resume")
    return argv


def _invoke_suite(argv: list[str], env: dict | None = None) -> dict:
    """Injected subprocess seam; tests monkeypatch this to avoid real runs."""
    proc = subprocess.run(argv, capture_output=True, text=True, env=env)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _load_cfg(cfg_path) -> dict:
    if not cfg_path:
        return {}
    with open(cfg_path, encoding="utf-8") as fh:
        return json.load(fh)


def run_stage(
    run_root,
    cfg_path=None,
    *,
    smoke: bool = False,
    limit: int = 0,
    gpu: bool = False,
    checkpoint_path: str | None = None,
    resume: bool = False,
    case_pool=None,
    timeline_manifests=None,
    baseline_rows=None,
    n_target: int | None = None,
    s2_share: float | None = None,
    seed: int | None = None,
    max_per_song: int | None = None,
    max_per_song_stratum: int | None = None,
    model_id: str | None = None,
    checkpoint_id: str | None = None,
    model_revision: str | None = None,
) -> dict:
    """Run stage 02: CASES.jsonl -> REQUESTS.jsonl -> forward suite ->
    CANDIDATE_INDEX.jsonl. Subprocess is injected via ``_invoke_suite``."""
    run_root = Path(run_root)
    cfg = _load_cfg(cfg_path)

    def pick(key: str, default):
        return cfg.get(key) if cfg.get(key) is not None else default

    n_target = int(n_target if n_target is not None else pick("n_target", 60))
    s2_share = float(s2_share if s2_share is not None else pick("s2_share", 0.30))
    seed = int(seed if seed is not None else pick("seed", 0))
    max_per_song = int(max_per_song if max_per_song is not None else pick("max_per_song", 3))
    max_per_song_stratum = int(
        max_per_song_stratum if max_per_song_stratum is not None
        else pick("max_per_song_stratum", 1)
    )
    model_id = model_id or identity.MODEL_ID
    checkpoint_id = checkpoint_id or identity.CHECKPOINT_ID
    model_revision = model_revision or identity.MODEL_REVISION

    stage_dir = run_root / "02_behavior"
    stage_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir = stage_dir / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)

    if case_pool is None:
        case_pool = run_root / "01_detector_audit" / "CASE_POOL.jsonl"
    case_pool_path = Path(case_pool)
    cases = sample_strata(
        load_jsonl(case_pool_path),
        n_target=n_target, s2_share=s2_share, seed=seed,
        max_per_song=max_per_song, max_per_song_stratum=max_per_song_stratum,
    )
    cases_path = stage_dir / "CASES.jsonl"
    write_jsonl(cases_path, cases)

    if timeline_manifests is None:
        timeline_manifests = (cfg.get("timeline_manifests")
                              or (cfg.get("inputs") or {}).get("cohort_manifests") or [])
    if baseline_rows is None:
        baseline_rows = (cfg.get("baseline_rows")
                         or (cfg.get("inputs") or {}).get("old_run_requests") or [])
    if isinstance(baseline_rows, (str, Path)):
        baseline_rows = load_jsonl(baseline_rows)

    requests, plan, skipped = build_requests(
        cases, timeline_manifests, baseline_rows,
        model_id=model_id, checkpoint_id=checkpoint_id,
    )
    requests_path = stage_dir / "REQUESTS.jsonl"
    write_jsonl(requests_path, requests)
    write_jsonl(proposals_dir / "PROPOSAL_PLAN.json", plan)

    checks = no_gt_check(requests)
    no_gt_path = stage_dir / "NO_GT_CHECK.jsonl"
    write_jsonl(no_gt_path, checks)

    failures_dir = run_root / "00_meta"
    failures_dir.mkdir(parents=True, exist_ok=True)
    if skipped:
        existing = []
        failures_path = failures_dir / "failures.jsonl"
        if failures_path.exists():
            existing = load_jsonl(failures_path)
        write_jsonl(failures_path, existing + skipped)

    forward_root = stage_dir / "forward"
    argv = _suite_argv(
        requests_path, forward_root,
        smoke=smoke, gpu=gpu, limit=limit,
        model_id=model_id, checkpoint_id=checkpoint_id,
        model_revision=model_revision, checkpoint_path=checkpoint_path, resume=resume,
    )
    suite = _invoke_suite(argv)

    candidate_index: list[dict] = []
    candidate_path = stage_dir / "CANDIDATE_INDEX.jsonl"
    if (forward_root / "RUN_MANIFEST.json").exists():
        candidate_index = build_candidate_index(forward_root, requests)
        write_jsonl(candidate_path, candidate_index)

    suite_ok = bool(suite.get("returncode") == 0)
    summary = {
        "stage": "02_behavior",
        "result_status": "ok" if suite_ok else "suite_failed",
        "n_cases": len(cases),
        "n_requests": len(requests),
        "n_skipped": len(skipped),
        "n_gt_violations": sum(1 for c in checks if not c["validated"]),
        "n_candidate_index": len(candidate_index),
        "executor": "smoke" if smoke else ("real" if gpu else "smoke"),
        "suite": {k: suite.get(k) for k in ("returncode", "stdout", "stderr")},
        "artifacts": {
            "cases": str(cases_path),
            "requests": str(requests_path),
            "no_gt_check": str(no_gt_path),
            "proposal_plan": str(proposals_dir / "PROPOSAL_PLAN.json"),
            "forward": str(forward_root),
            "candidate_index": str(candidate_path) if candidate_index else None,
        },
    }
    return summary
