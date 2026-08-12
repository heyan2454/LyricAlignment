"""B3 layered runners for realign-recovery (WP B3).

Six pure-logic layers, each consuming explicit manifest paths / injected
objects rather than implicitly scanning directories:

1. ``serial_baseline_runner``  -- frozen baseline over a long-slot request.
2. ``episode_builder``         -- natural episodes + one-shot P1..P5 propagation.
3. ``proposal_runner``         -- R-A / R-B / R-C no-GT proposals.
4. ``candidate_runner``        -- forward cache reuse / new forward.
5. ``decision_writeback_runner`` -- pre-registered policy decision + continuation.
6. ``evaluator``               -- the only GT-aware post-processing layer.

No model library is imported; ``backend`` is a duck-typed object exposing
``align(request) -> {"raw_output_path", "raw_output_sha256"}``. GT never enters
layers 1--5: any GT-bearing field raises ``ValueError`` (or is recorded as a
per-case failure for the baseline runner, which continues the batch).

Status contract: a candidate produced from a *new* forward has
``status="succeeded"``; a candidate served from the content-addressed cache
(no forward executed) has ``status="skipped"`` -- it is never elevated to any
kind of "realign" status. Both values are within the B1 allowed status set.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from dataclasses import asdict, is_dataclass

from lyricalign.realign_recovery.baseline_identity import identity_digest
from lyricalign.realign_recovery.forward_cache import (
    ContentAddressedCache,
    build_forward_key,
    forward_digest,
)
from lyricalign.realign_recovery.frozen_baseline import FROZEN_BASELINE_IDENTITY
from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request
from lyricalign.realign_recovery.run_objects import (
    MANIFEST_SCHEMA_VERSION,
    Candidate,
    Continuation,
    Decision,
    Episode,
    Evaluation,
    Proposal,
    append_failure,
    append_jsonl,
    stage_completed,
)

BASELINE_ARTIFACTS_NAME = "baseline.jsonl"
EPISODES_NAME = "episodes.jsonl"
PROPOSALS_NAME = "proposals.jsonl"
CANDIDATES_NAME = "candidates.jsonl"
DECISIONS_NAME = "decisions.jsonl"
CONTINUATIONS_NAME = "continuation.jsonl"
EVALUATIONS_NAME = "evaluations.jsonl"

STATUS_SUCCEEDED = "succeeded"
STATUS_CACHE_REUSED = "skipped"

_METHOD_OWNERSHIP = {"R-A": "unsafe", "R-B": "safe", "R-C": "unsafe"}


def _as_dict(obj):
    if is_dataclass(obj):
        return asdict(obj)
    return dict(obj)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _span_hash(unit_ids) -> str:
    return _sha256_text(_canonical(list(unit_ids)))


def _load_jsonl(source) -> list[dict]:
    if isinstance(source, (list, tuple)):
        return [_as_dict(item) for item in source]
    path = str(source)
    if not os.path.exists(path):
        return []
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _existing_ids(path: str) -> set:
    return {row.get("id") for row in _load_jsonl(path) if row.get("id")}


def _gt_names(obj: dict) -> list[str]:
    return validate_no_gt_request(obj)


def _raise_gt(found: list[str]) -> None:
    raise ValueError(
        "no-GT layer received GT-bearing fields: " + ", ".join(sorted(set(found)))
    )


def _resolved_request(row: dict) -> dict:
    resolved = dict(FROZEN_BASELINE_IDENTITY)
    resolved.update(
        {k: v for k, v in row.items() if v is not None and k != "id"}
    )
    return resolved


def serial_baseline_runner(
    request,
    backend,
    out_root,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    detector=None,
) -> dict:
    """Consume long-slot baseline request(s), run the fake backend, snapshot state.

    ``request`` is either a single request dict or a path to a JSONL manifest of
    requests. Each case writes one row into ``<out_root>/baseline.jsonl``. State
    is only read (never mutated); the detector shadow is either produced by the
    injected ``detector(request, raw) -> dict`` or defaults to recording the raw
    output path + sha256. GT-bearing requests are recorded as per-case failures
    and skipped, so the rest of the batch keeps running.
    """
    rows = _load_jsonl(request) if isinstance(request, str) else [_as_dict(request)]
    out_root = str(out_root)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, BASELINE_ARTIFACTS_NAME)
    existing = _existing_ids(out_path)
    summary = {"cases_total": len(rows), "cases_processed": 0, "skipped": 0, "failed": 0}
    count = 0
    for raw_row in rows:
        if limit is not None and count >= limit:
            break
        count += 1
        row = copy.deepcopy(raw_row)
        row.setdefault("window_index", 0)
        row.setdefault("song_id", "song")
        row.setdefault("id", "baseline-" + identity_digest(row))
        if row["id"] in existing:
            summary["skipped"] += 1
            continue
        if _gt_names(row):
            summary["failed"] += 1
            append_failure(
                out_root, "baseline", {"id": row["id"], "error": "GT-bearing request"}
            )
            continue
        resolved = _resolved_request(row)
        try:
            raw = backend.align(resolved)
            raw_path = str(raw["raw_output_path"])
            raw_sha = str(raw["raw_output_sha256"])
        except Exception as exc:  # noqa: BLE001 -- per-case failure, keep batch alive
            summary["failed"] += 1
            append_failure(
                out_root, "baseline", {"id": row["id"], "error": str(exc)}
            )
            continue
        shadow = detector(resolved, raw) if detector else {
            "raw_output_path": raw_path,
            "raw_output_sha256": raw_sha,
        }
        key = build_forward_key(resolved)
        artifact = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "id": row["id"],
            "case_id": row.get("case_id", row["id"]),
            "song_id": row["song_id"],
            "window_index": int(row["window_index"]),
            "window": {
                "audio_start_sec": row.get("audio_start_sec"),
                "audio_end_sec": row.get("audio_end_sec"),
                "text_unit_ids": list(row.get("text_unit_ids", [])),
            },
            "request": resolved,
            "forward_key": key,
            "forward_identity": forward_digest(key),
            "raw_output_path": raw_path,
            "raw_output_sha256": raw_sha,
            "state_checkpoint": {
                "forward": dict(resolved),
                "ownership": dict(row.get("ownership", {})),
                "anchors": dict(row.get("anchors", {})),
                "pending_windows": list(row.get("pending_windows", [])),
            },
            "detector_shadow": shadow,
        }
        if not dry_run:
            append_jsonl(out_path, artifact)
        summary["cases_processed"] += 1
    if not dry_run:
        stage_completed(out_root, "baseline", summary)
    return summary


def episode_builder(
    baseline_artifacts,
    out_root,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    propagation_stages=None,
) -> tuple[str, dict]:
    """Build natural episodes from baseline artifacts; inject P1..P5 once.

    Propagation stages are only injected on the first window of each song
    (the window whose ``window_index`` equals the song minimum): from the
    second window onward ``attempted`` is always 0. A stage is ``effective``
    when it produces a propagated episode; a stage whose target units are all
    already covered by the first window is ``no_effect`` (counted separately,
    never part of the effective denominator).
    """
    rows = _load_jsonl(baseline_artifacts)
    out_root = str(out_root)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, EPISODES_NAME)
    existing = _existing_ids(out_path)
    stages = list(propagation_stages) if propagation_stages else []

    min_window: dict[str, int] = {}
    for row in rows:
        song = row.get("song_id", "song")
        idx = int(row.get("window_index", 0))
        if song not in min_window or idx < min_window[song]:
            min_window[song] = idx

    summary = {"natural": 0, "propagated": 0, "attempted": 0, "no_effect": 0, "effective": 0}
    processed = 0
    for row in rows:
        if limit is not None and processed >= limit:
            break
        processed += 1
        song = row.get("song_id", "song")
        window = dict(row.get("window", {}))
        window_index = int(row.get("window_index", 0))
        window["window_index"] = window_index
        natural_id = f"ep-nat-{row.get('id', 'case')}"
        natural = Episode(
            id=natural_id,
            song_id=song,
            source_role="baseline",
            kind="natural",
            source_window=window,
            state_checkpoint=dict(row.get("state_checkpoint", {})),
            target_unit_ids=list(window.get("text_unit_ids", [])),
            family="natural",
            attempt_status="succeeded",
            effective_status="succeeded",
        )
        if natural.id not in existing:
            if not dry_run:
                append_jsonl(out_path, natural.to_dict())
            summary["natural"] += 1

        is_first = int(row.get("window_index", 0)) == min_window.get(song, 0)
        if is_first:
            covered = set(natural.target_unit_ids)
            song_stages = [
                s for s in stages
                if not s.get("song_id") or s["song_id"] == song
            ]
            for stage in song_stages:
                summary["attempted"] += 1
                units = [int(u) for u in stage.get("units", [])]
                if not units or all(u in covered for u in units):
                    summary["no_effect"] += 1
                    continue
                propagated = Episode(
                    id=f"ep-{stage.get('id', 'P')}-{natural.id}",
                    song_id=song,
                    source_role="propagation",
                    kind="propagated",
                    source_window=dict(natural.source_window),
                    state_checkpoint=dict(natural.state_checkpoint),
                    target_unit_ids=units,
                    family=stage.get("id", "P"),
                    attempt_status="succeeded",
                    effective_status="succeeded",
                )
                if propagated.id not in existing:
                    if not dry_run:
                        append_jsonl(out_path, propagated.to_dict())
                    summary["propagated"] += 1
                    summary["effective"] += 1
    if not dry_run:
        stage_completed(out_root, "episodes", summary)
    return out_path, summary


def proposal_runner(
    episode,
    state,
    raw_detector_signal,
    out_root,
    *,
    dry_run: bool = False,
) -> list[Proposal]:
    """Build R-A / R-B / R-C proposals from a no-GT episode/state/signal.

    Every proposal carries only no-GT inputs (audio span, text span, anchors,
    context); each is validated with ``gt_firewall.validate_no_gt_request``.
    Any GT-bearing field in the inputs raises ``ValueError``.
    """
    ep = _as_dict(episode)
    st = _as_dict(state)
    signal = _as_dict(raw_detector_signal)
    found = set(_gt_names(ep)) | set(_gt_names(st)) | set(_gt_names(signal))
    if found:
        _raise_gt(sorted(found))

    out_root = str(out_root)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, PROPOSALS_NAME)
    existing = _existing_ids(out_path)

    forward = dict(st.get("forward", {}))
    window = dict(ep.get("source_window") or ep.get("window") or {})
    audio = [
        float(window.get("audio_start_sec", 0.0)),
        float(window.get("audio_end_sec", 0.0)),
    ]
    units = list(ep.get("target_unit_ids", []))
    anchors = dict(st.get("anchors", {}))

    specs: list[tuple[str, list[float], list[int], dict]] = []
    specs.append(("R-A", audio, units, dict(anchors)))
    bad = signal.get("bad_window") or signal.get("unsafe_range") or audio
    bad = [float(bad[0]), float(bad[1])]
    if anchors:
        left = float(anchors.get("left", audio[0]))
        right = float(anchors.get("right", audio[1]))
        rb_span = [left, right]
    elif bad[0] - audio[0] > 1e-9:
        rb_span = [audio[0], bad[0]]
    else:
        rb_span = [bad[1], audio[1]]
    specs.append(("R-B", rb_span, list(units), {"left": rb_span[0], "right": rb_span[1]}))
    mid = (bad[0] + bad[1]) / 2.0
    specs.append(("R-C", [bad[0], mid], list(units), {"parent": list(bad)}))
    specs.append(("R-C", [mid, bad[1]], list(units), {"parent": list(bad)}))

    proposals: list[Proposal] = []
    for index, (method, span, text_span, anch) in enumerate(specs):
        no_gt = dict(forward)
        no_gt["audio_start_sec"] = span[0]
        no_gt["audio_end_sec"] = span[1]
        no_gt["text_unit_ids"] = list(text_span)
        no_gt["text_content_hash"] = _span_hash(list(text_span))
        no_gt["audio_span"] = list(span)
        no_gt["text_span"] = list(text_span)
        if _gt_names(no_gt):
            _raise_gt(_gt_names(no_gt))
        proposal = Proposal(
            id=f"prop-{ep['id']}-{method}-{index}",
            method=method,
            audio_span=list(span),
            text_span=list(text_span),
            anchors=dict(anch),
            context={
                "episode_id": ep["id"],
                "signal": copy.deepcopy(signal),
            },
            no_gt_inputs=no_gt,
            identity=_sha256_text(_canonical({"method": method, "no_gt_inputs": no_gt})),
        )
        if proposal.id not in existing:
            if not dry_run:
                append_jsonl(out_path, proposal.to_dict())
        proposals.append(proposal)
    return proposals


def candidate_runner(
    proposal,
    backend,
    cache,
    out_root,
    *,
    dry_run: bool = False,
) -> Candidate:
    """Resolve a proposal against the forward cache, running a new forward on miss.

    GT fields anywhere on the proposal (top-level or ``no_gt_inputs``) raise
    ``ValueError``. On a cache hit the stored raw output is reused with
    ``status="skipped"`` (no new forward, never "realign"); on a miss the
    backend runs and the result is published to the content-addressed cache
    with ``status="succeeded"``. GT is never scored here.
    """
    prop = _as_dict(proposal)
    found = set(_gt_names(prop)) | set(_gt_names(prop.get("no_gt_inputs", {})))
    if found:
        _raise_gt(sorted(found))
    no_gt = dict(prop["no_gt_inputs"])
    key = build_forward_key(no_gt)
    digest = forward_digest(key)
    cache_obj = cache if isinstance(cache, ContentAddressedCache) else ContentAddressedCache(cache)

    entry = cache_obj.resolve(key)
    if entry is not None and entry.reusable:
        raw_path = entry.raw_output_path
        raw_sha = entry.raw_output_sha256
        status = STATUS_CACHE_REUSED
    else:
        raw = backend.align(prop)
        raw_path = str(raw["raw_output_path"])
        raw_sha = str(raw["raw_output_sha256"])
        status = STATUS_SUCCEEDED
        if not dry_run:
            cache_obj.publish(key, raw_path, raw_sha)

    candidate = Candidate(
        id=f"cand-{prop['id']}",
        proposal_id=prop["id"],
        forward_identity=digest,
        raw_output_path=raw_path,
        raw_output_sha256=raw_sha,
        ownership=_METHOD_OWNERSHIP.get(prop.get("method"), "unknown"),
        status=status,
        failure=None,
    )
    out_root = str(out_root)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, CANDIDATES_NAME)
    existing = _existing_ids(out_path)
    if not dry_run and candidate.id not in existing:
        append_jsonl(out_path, candidate.to_dict())
    return candidate


def decision_writeback_runner(
    candidates,
    pre_registered_policy,
    out_root,
    *,
    dry_run: bool = False,
) -> tuple[Decision | None, Continuation | None]:
    """Apply a pre-registered policy to candidates, then continue serial state.

    ``pre_registered_policy`` is either a callable ``policy(candidate) -> {
    "accept": bool, "reason": str, "writeback_span": list[int]|None,
    "score": float}`` or a dict holding the same keys applied to every
    candidate. Writeback only ever touches non-safe ownership entries, so an
    unsafe-only writeback never changes safe ownership. The ``Continuation``
    carries before/after state and provenance for E9 paired comparison.
    """
    cands = _load_jsonl(candidates)
    out_root = str(out_root)
    os.makedirs(out_root, exist_ok=True)
    dec_path = os.path.join(out_root, DECISIONS_NAME)
    cont_path = os.path.join(out_root, CONTINUATIONS_NAME)
    existing_dec = _existing_ids(dec_path)
    existing_cont = _existing_ids(cont_path)

    if not cands:
        return None, None
    before = copy.deepcopy(
        dict(cands[0].get("state_checkpoint") or cands[0].get("before_state") or {})
    )
    ownership = copy.deepcopy(dict(before.get("ownership", {})))
    after = copy.deepcopy(before)
    after["ownership"] = ownership

    decisions: list[Decision] = []
    accepted_ids: list[str] = []
    for rank, cand in enumerate(cands, start=1):
        if isinstance(pre_registered_policy, dict):
            dec = dict(pre_registered_policy)
        else:
            dec = dict(pre_registered_policy(cand))
        accept = bool(dec.get("accept", False))
        span = dec.get("writeback_span")
        score = float(dec.get("score", 0.0))
        decision = Decision(
            id=f"dec-{cand['id']}",
            trigger="pre_registered_policy",
            old_no_gt_scores={"candidate_id": cand["id"], "score": score},
            new_no_gt_scores={"candidate_id": cand["id"], "score": score},
            rank=rank,
            accept_reject_reason=str(dec.get("reason", "policy")),
            writeback_span=[int(u) for u in span] if (accept and span) else None,
        )
        if accept and span:
            for unit in span:
                uid = str(unit)
                if ownership.get(uid) != "safe":
                    ownership[uid] = "safe"
            accepted_ids.append(cand["id"])
        decisions.append(decision)

    continuation = Continuation(
        id=f"cont-{cands[0]['id']}",
        before_state=before,
        after_state=after,
        committed_provenance={
            "decision_ids": [d.id for d in decisions],
            "accepted_candidate_ids": accepted_ids,
        },
        next_windows=list(before.get("pending_windows", [])),
        cost={
            "forwards": sum(1 for c in cands if c.get("status") == STATUS_SUCCEEDED),
            "reused": sum(1 for c in cands if c.get("status") == STATUS_CACHE_REUSED),
        },
    )
    if not dry_run:
        for decision in decisions:
            if decision.id not in existing_dec:
                append_jsonl(dec_path, decision.to_dict())
        if continuation.id not in existing_cont:
            append_jsonl(cont_path, continuation.to_dict())
    return decisions[-1], continuation


def evaluator(
    candidates,
    gt_binding,
    out_root,
    *,
    dry_run: bool = False,
) -> Evaluation:
    """Read-only GT post-processing: join candidates with a real-GT binding.

    The control artifact (candidate rows) is never mutated -- only copied --
    and GT fields never flow back into layers 1--5. ``gt_binding`` is a dict
    such as ``{"expected_sha": "<sha256>"}`` used purely for scoring.
    """
    cands = [copy.deepcopy(_as_dict(c)) for c in _load_jsonl(candidates)]
    binding = dict(gt_binding)
    binding_hash = _sha256_text(_canonical(binding))
    expected = binding.get("expected_sha")
    matched = sum(1 for c in cands if c.get("raw_output_sha256") == expected)
    evaluation = Evaluation(
        id=f"eval-{binding_hash[:12]}",
        gt_binding_hash=binding_hash,
        labeled=matched,
        unlabeled=len(cands) - matched,
        metrics={
            "raw_sha_matched": matched,
            "total_candidates": len(cands),
        },
        stage_labels=["baseline", "proposal", "candidate"],
    )
    out_root = str(out_root)
    os.makedirs(out_root, exist_ok=True)
    out_path = os.path.join(out_root, EVALUATIONS_NAME)
    existing = _existing_ids(out_path)
    if not dry_run and evaluation.id not in existing:
        append_jsonl(out_path, evaluation.to_dict())
    return evaluation


def main(argv=None) -> int:
    """Argparse skeleton for the B3 layers (function-level API, thin CLI).

    Each layer shares ``--resume --dry-run --limit --out-root`` plus positional
    inputs; real wiring lives in the per-layer functions, this only normalizes
    the invocation surface.
    """
    parser = argparse.ArgumentParser(
        description="B3 realign-recovery layered runner (skeleton CLI)"
    )
    parser.add_argument(
        "layer",
        nargs="?",
        choices=["baseline", "episodes", "proposals", "candidates", "decision", "evaluation"],
    )
    parser.add_argument("--input", dest="inputs", action="append", default=[])
    parser.add_argument("--out-root", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            {
                "layer": args.layer,
                "resume": args.resume,
                "dry_run": args.dry_run,
                "limit": args.limit,
                "out_root": args.out_root,
                "inputs": args.inputs,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
