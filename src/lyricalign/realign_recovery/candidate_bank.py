"""D1 candidate bank: fold E1 oracle + E5 proposal GPU forwards into one bank.

Every valid episode contributes 10-20 candidates; normal windows are never
cartesian-expanded.  A bank row is a ``Candidate`` (see run_objects.py) whose
``raw_output_path`` points at the content-addressed evidence file.  GT never
enters the bank: region->episode resolution uses only episodes.jsonl coverage
(window text units union target units) and the no-GT proposals' own provenance.

Ownership split:
- ``e5_proposal`` : E5 REQUESTS rows, grouped by ``provenance.episode_id``,
  identity shorthand is the request-level ``input_variant`` field.
- ``e1_oracle``   : E1 oracle REQUESTS rows; provenance carries only
  ``region_id`` (``song:start-end``, unit level).  The region is reverse-mapped
  to the covering episode via the song->unit->episode coverage index; regions
  that no episode covers are recorded in ``unmapped_regions`` (never dropped
  silently).

Identity semantics:
- ``Candidate.forward_identity`` = evidence top-level ``content_identity``
  (content hash of the whole request, includes context).  This differs from
  ``forward_cache.forward_digest`` which hashes only the canonical forward key
  (model/checkpoint/audio/text spans, no context); the bank notes that口径 in
  the summary, so forward_identity must never be passed to a forward-cache
  lookup directly.
- ``Candidate.status`` is the evidence ``attempt.status`` mapped to the
  run_objects vocabulary: ``"ok" -> "succeeded"``; any ``attempt.error`` makes
  it ``"failed"``.
- ``raw_output_sha256`` is recomputed with ``file_sha256(evidence_path)``.
"""
from __future__ import annotations

import hashlib
import json
import os

from lyricalign.realign_recovery.e5_proposals import load_timeline_manifest
from lyricalign.realign_recovery.run_objects import (
    Candidate,
    append_jsonl,
    file_sha256,
    write_jsonl,
)

BANK_SCHEMA_VERSION = "realign_recovery_candidate_bank_v1"

_GATE_MIN = 10
_GATE_MAX = 20

_STATUS_OK = "ok"


class CandidateBankError(ValueError):
    """Raised on inconsistent bank inputs."""


def _load_jsonl(path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_plan(plan_path) -> dict[str, dict]:
    """PROPOSAL_PLAN.json -> {request_id: plan_row}.

    Accepts both a JSON array document and a JSONL list.
    """
    with open(plan_path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        raw = _load_jsonl(plan_path)
    if isinstance(raw, dict):
        raw = [raw]
    return {r["request_id"]: r for r in raw}


def _index_episode_coverage(episodes: list[dict]) -> tuple[dict[str, dict[str, set[str]]], list[str]]:
    """episodes -> (song -> unit -> set(episode_id), ordered episode ids).

    Coverage of an episode is ``source_window.text_unit_ids ∪ target_unit_ids``.
    """
    index: dict[str, dict[str, set[str]]] = {}
    order: list[str] = []
    seen: set[str] = set()
    for ep in episodes:
        song = str(ep.get("song_id") or "")
        ep_id = str(ep.get("id") or "")
        if not song or not ep_id:
            continue
        if ep_id not in seen:
            seen.add(ep_id)
            order.append(ep_id)
        cover = set(int(u) for u in (ep.get("source_window") or {}).get("text_unit_ids", []))
        cover |= set(int(u) for u in ep.get("target_unit_ids", []))
        song_idx = index.setdefault(song, {})
        for unit in cover:
            song_idx.setdefault(str(unit), set()).add(ep_id)
    return index, order


def _parse_region(region_id: str) -> tuple[str, int, int] | None:
    """'song:start-end' -> (song, start, end); None when malformed."""
    if not isinstance(region_id, str):
        return None
    idx = region_id.rfind(":")
    if idx <= 0:
        return None
    song = region_id[:idx]
    rest = region_id[idx + 1:]
    parts = rest.split("-")
    if len(parts) != 2:
        return None
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if start < 0 or end < start:
        return None
    return song, start, end


def _region_covering_episode(
    region_id: str, coverage_index: dict[str, dict[str, set[str]]], episode_sizes: dict[str, int]
) -> str | None:
    """Return the most specific episode covering the region, or None.

    A region is covered only when *every* unit in ``start..end`` is covered by
    the episode (window units ∪ target units).  Multiple candidates pick the one
    with the smallest coverage; ties break natural kind then lexicographic id.
    """
    parsed = _parse_region(region_id)
    if parsed is None:
        return None
    song, start, end = parsed
    song_idx = coverage_index.get(song)
    if not song_idx:
        return None
    covering: set[str] | None = None
    for unit in range(start, end + 1):
        eps = song_idx.get(str(unit))
        if not eps:
            return None
        covering = set(eps) if covering is None else (covering & eps)
        if not covering:
            return None
    if not covering:
        return None
    return min(
        covering,
        key=lambda e: (episode_sizes.get(e, 1 << 30), e.startswith("ep-nat") is False, e),
    )


def _map_status(attempt_status: str | None, error: str | None) -> str:
    if error:
        return "failed"
    if attempt_status == _STATUS_OK:
        return "succeeded"
    if attempt_status in ("succeeded", "pending", "in_progress", "skipped", "failed"):
        return attempt_status
    return "failed"


def _stable_id(ownership: str, episode_id: str, variant: str, request_id: str) -> str:
    digest = hashlib.sha256(f"{ownership}:{episode_id}:{variant}:{request_id}".encode("utf-8"))
    return f"{episode_id}:{variant}:{digest.hexdigest()[:8]}"


def _index_evidence(evidence_dir: str) -> dict[str, dict]:
    """Scan one evidence dir -> {request_id: evidence info}.

    ``forward_identity`` is the evidence top-level ``content_identity`` (the
    content-addressed filename stem without the ``.json`` suffix is equivalent).
    """
    out: dict[str, dict] = {}
    if not os.path.isdir(evidence_dir):
        return out
    for name in sorted(os.listdir(evidence_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(evidence_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            continue
        attempt = data.get("attempt") or {}
        request = attempt.get("request") or {}
        request_id = request.get("request_id")
        if not request_id:
            continue
        out[str(request_id)] = {
            "path": path,
            "forward_identity": data.get("content_identity"),
            "attempt_status": attempt.get("status"),
            "attempt_error": attempt.get("error"),
        }
    return out


def _emit_candidate(
    candidates: list[Candidate],
    ep_id: str,
    variant: str,
    request_id: str,
    ownership: str,
    evidence: dict,
    missing: list[dict],
) -> None:
    if not evidence:
        missing.append({"request_id": request_id, "episode_id": ep_id, "ownership": ownership})
        return
    path = evidence["path"]
    candidates.append(
        Candidate(
            id=_stable_id(ownership, ep_id, variant, request_id),
            proposal_id=f"{ep_id}:{variant}",
            forward_identity=evidence["forward_identity"] or "",
            raw_output_path=path,
            raw_output_sha256=file_sha256(path),
            ownership=ownership,
            status=_map_status(evidence["attempt_status"], evidence["attempt_error"]),
            failure=evidence["attempt_error"] or None,
        )
    )


def build_candidate_bank(
    e5_requests,
    e5_evidence_dir,
    e1_requests,
    e1_evidence_dir,
    episodes_path,
    plan_path,
    timeline_manifests,
    out_jsonl,
    *,
    limit: int | None = None,
    resume: bool = False,
) -> dict:
    """Build the candidate bank JSONL and return a statistics dict.

    ``e5_requests`` / ``e1_requests`` are JSONL paths; the four evidence
    dirs/requests plus ``episodes_path`` / ``plan_path`` / ``timeline_manifests``
    are paths.  Rows written are exactly ``Candidate.to_dict()`` (schema
    ``realign_recovery_run_objects_v1``), so no GT field can leak into the bank.
    """
    e5_rows = _load_jsonl(e5_requests)
    e1_rows = _load_jsonl(e1_requests)
    episodes = _load_jsonl(episodes_path)
    plan = _load_plan(plan_path) if plan_path else {}
    timeline = load_timeline_manifest(timeline_manifests)

    coverage_index, episode_order = _index_episode_coverage(episodes)
    episode_sizes = {
        ep_id: sum(len(v.get(song, set())) for song, v in coverage_index.items()) for ep_id in episode_order
    }
    limited = set(episode_order[:limit]) if limit else set(episode_order)

    e5_ev = _index_evidence(e5_evidence_dir)
    e1_ev = _index_evidence(e1_evidence_dir)

    candidates: list[Candidate] = []
    missing_evidence: list[dict] = []
    unmapped_regions: list[dict] = []
    skipped_out_of_limit: int = 0

    for row in e5_rows:
        provenance = row.get("provenance") or {}
        ep_id = provenance.get("episode_id") or (plan.get(row.get("request_id")) or {}).get("episode_id")
        variant = row.get("input_variant") or (plan.get(row.get("request_id")) or {}).get("variant")
        if not ep_id or not variant:
            raise CandidateBankError(f"E5 request {row.get('request_id')} lacks episode_id/variant")
        if ep_id not in limited:
            skipped_out_of_limit += 1
            continue
        _emit_candidate(candidates, ep_id, variant, row["request_id"], "e5_proposal",
                        e5_ev.get(row["request_id"]), missing_evidence)

    for row in e1_rows:
        provenance = row.get("provenance") or {}
        region_id = provenance.get("region_id") or (row.get("mutation_parameters") or {}).get("region_id")
        variant = row.get("input_variant") or "oracle"
        if not region_id:
            unmapped_regions.append({"request_id": row.get("request_id"), "region_id": None, "reason": "no_region_id"})
            continue
        ep_id = _region_covering_episode(region_id, coverage_index, episode_sizes)
        if ep_id is None:
            unmapped_regions.append({"request_id": row.get("request_id"), "region_id": region_id, "reason": "no_covering_episode"})
            continue
        if ep_id not in limited:
            skipped_out_of_limit += 1
            continue
        _emit_candidate(candidates, ep_id, variant, row["request_id"], "e1_oracle",
                        e1_ev.get(row["request_id"]), missing_evidence)

    per_episode = {}
    for c in candidates:
        ep = c.proposal_id.rsplit(":", 1)[0]
        per_episode[ep] = per_episode.get(ep, 0) + 1
    gate_violations = [
        {"episode_id": ep, "n_candidates": n, "reason": "too_few" if n < _GATE_MIN else "too_many"}
        for ep, n in sorted(per_episode.items())
        if n < _GATE_MIN or n > _GATE_MAX
    ]

    rows = [c.to_dict() for c in candidates]
    os.makedirs(os.path.dirname(os.path.abspath(out_jsonl)), exist_ok=True)
    if resume and os.path.exists(out_jsonl):
        existing = {r.get("id") for r in _load_jsonl(out_jsonl)}
        pending = [r for r in rows if r["id"] not in existing]
        for r in pending:
            append_jsonl(out_jsonl, r)
    else:
        write_jsonl(out_jsonl, rows)

    summary = {
        "schema_version": BANK_SCHEMA_VERSION,
        "n_candidates": len(rows),
        "per_episode": {k: per_episode[k] for k in sorted(per_episode)},
        "gate_violations": gate_violations,
        "gate": {"min": _GATE_MIN, "max": _GATE_MAX},
        "unmapped_regions": unmapped_regions,
        "missing_evidence": missing_evidence,
        "n_skipped_out_of_limit": skipped_out_of_limit,
        "n_episodes_limited": len(limited),
        "ownership": {
            "e1_oracle": sum(1 for c in candidates if c.ownership == "e1_oracle"),
            "e5_proposal": sum(1 for c in candidates if c.ownership == "e5_proposal"),
        },
        "forward_identity_note": (
            "Candidate.forward_identity is the evidence top-level content_identity "
            "(request content hash incl. context), NOT forward_cache.forward_digest "
            "(canonical forward-key hash); do not feed it to a forward-cache lookup."
        ),
        "note": f"bank rows are Candidate rows; {len(timeline)} song(s) from timeline manifests.",
    }
    return summary
