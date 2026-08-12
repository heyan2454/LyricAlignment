"""E7/E8 shared adapter: E5 candidate evidence -> FrozenScorer evidence rows.

The E5 evidence payloads use the old flat row schema (``raw_global_start_sec``,
``raw_start_entropy``, ``raw_start_topk_probabilities`` ...) while
``FrozenScorer`` consumes EvidenceRow dicts (``canonical_unit_id`` / ``raw`` /
``official`` / ``hidden`` / ``cross_view``) that must stay byte-compatible with
the upstream stage3b evidence_v2 used to fit the frozen model -- same raw-field
names, same topk nesting (``[[start_pairs], [end_pairs]]``), same missing-value
semantics, so the feature chain reproduces identical numbers.  This module owns
that mapping so E7 (quality gate) and E8 (writeback policy) never duplicate it.

GT contract: this module is no-GT.  It consumes only E5 REQUESTS rows + the
content-addressed evidence payloads.  Every produced row is leak-checked
(``assert_no_label_leak`` recursively) before it is handed to a scorer.

canonical binding: E5 REQUESTS carry no ``canonical_to_local``; the binding is
rebuilt from ``text_units`` (request-local character list) + provenance text
range, mirroring ``e5_eval._map_rows_to_units`` exactly (oracle variants bind
to ``target_unit_ids``, proposals to ``range(text_unit_start, text_unit_end+1)``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from lyricalign.research_v7.detector_v2_evidence import (
    EvidenceRow,
    assert_no_label_leak,
)
from lyricalign.research_v7.detector_v2_intervals import tristate_from_p_bad
from lyricalign.realign_recovery.frozen_scorer import (
    FrozenScorer,
    _evidence_rows,
    _feature_matrix,
    _unit_end_sec,
    _unit_start_sec,
    build_frozen_scorer,
)

_SCHEMA_VERSION = "realign_recovery_candidate_scores_v1"

_RAW_FIELDS = ("start_sec", "end_sec", "start_entropy", "end_entropy",
               "start_margin", "end_margin", "topk")
_ITEM_RE = None


def _load_jsonl_any(path) -> list[dict]:
    """JSONL or single-line JSON array -> list of dicts."""
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    rows: list[dict] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, list):
            rows.extend(obj)
        elif isinstance(obj, dict):
            rows.append(obj)
    return rows


def _parse_items(items_dir) -> list[dict]:
    """items/<song>:w<wi>:<view>/sha256:<digest>.json -> (song, wi, view, digest)."""
    mapping: list[dict] = []
    if not Path(items_dir).is_dir():
        return mapping
    import re
    global _ITEM_RE
    if _ITEM_RE is None:
        _ITEM_RE = re.compile(r"^(?P<song>.+?):(?P<wi>w\d+):(?P<view>.+)$")
    for d in sorted(Path(items_dir).iterdir()):
        if not d.is_dir():
            continue
        m = _ITEM_RE.match(d.name)
        if not m:
            continue
        for f in sorted(d.iterdir()):
            if not f.name.endswith(".json"):
                continue
            mapping.append({
                "song_id": m.group("song"),
                "window_index": int(m.group("wi")[1:]),
                "view": m.group("view"),
                "digest": f.stem,
            })
    return mapping


def build_frozen_scorer_from_artifacts(
    frozen_op,
    labels_path,
    evidence_dir,
    items_dirs,
    target: str = "raw",
) -> FrozenScorer:
    """Rebuild the E3 frozen scorer for ``target`` from the upstream artifacts.

    Identical training set as ``run_e3_shadow``: LABELS(train, target) joined
    onto the evidence files reachable from the items dirs.  Evidence files may
    be either JSONL or a single-line JSON array.  Missing/empty train rows
    raise (fail-fast, never a silently under-fitted scorer).
    """
    evidence_cache: dict[str, list[dict]] = {}
    for f in Path(evidence_dir).glob("*.jsonl"):
        rows = _load_jsonl_any(f)
        if rows:
            evidence_cache[f.stem] = rows

    labels = {}
    for row in _load_jsonl_any(labels_path):
        if row.get("split") != "train":
            continue
        if row.get("target") != target:
            continue
        rid = row.get("request_identity")
        cid = row.get("canonical_unit_id")
        if rid is None or cid is None:
            continue
        labels[(rid, int(cid))] = row.get("label")

    items: list[dict] = []
    for it_dir in items_dirs:
        items.extend(_parse_items(it_dir))

    train_rows: list[dict] = []
    for item in items:
        digest = item["digest"]
        rows = evidence_cache.get(digest)
        if not rows:
            continue
        for row in rows:
            cid = row.get("canonical_unit_id")
            key = (digest, int(cid)) if cid is not None else None
            if key in labels:
                merged = dict(row)
                merged["label"] = labels[key]
                train_rows.append(merged)
    if not train_rows:
        raise ValueError("train rows empty; check labels/evidence/items inputs")
    return build_frozen_scorer(
        frozen_op, train_rows, model_kind="standardized_logistic",
        seed=0, target=target)


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _recursive_leak_check(value: Any) -> None:
    """Recursive assert_no_label_leak (top-level + nested dict/list)."""
    if isinstance(value, Mapping):
        assert_no_label_leak(value)
        for v in value.values():
            _recursive_leak_check(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _recursive_leak_check(v)


def _text_unit_ids(request_row: Mapping[str, Any]) -> list[int]:
    """Canonical unit id per request-local text position (mirrors e5_eval)."""
    provenance = request_row.get("provenance") or {}
    method = provenance.get("proposal_method") or ""
    text_unit_start = int(provenance.get("text_unit_start") or 0)
    text_unit_end = int(provenance.get("text_unit_end") or text_unit_start)
    if str(method).startswith("oracle"):
        return [int(c) for c in (provenance.get("target_unit_ids") or [])]
    return list(range(text_unit_start, text_unit_end + 1))


def canonical_unit_id_for_index(
    request_row: Mapping[str, Any], gci: int
) -> int | None:
    """Map request-local character index -> canonical unit id (e5_eval parity).

    ``text_units`` is a character list; unit ``unit_idx`` starts at the
    cumulative character offset.  Rows outside the text return ``None``.
    """
    text_units = request_row.get("text_units") or []
    text_unit_ids = _text_unit_ids(request_row)
    boundaries: list[int] = []
    total = 0
    for t in text_units:
        total += len(t)
        boundaries.append(total)
    for unit_idx, cum in enumerate(boundaries):
        if gci < cum:
            prev = boundaries[unit_idx - 1] if unit_idx > 0 else 0
            if prev <= gci and 0 <= unit_idx < len(text_unit_ids):
                return text_unit_ids[unit_idx]
            break
    return None


def _topk_pairs(request_row: Mapping[str, Any], row: Mapping[str, Any],
                side: str) -> list[list[float]]:
    """(class, prob) pairs for one boundary, mirroring the v2 converter."""
    classes = row.get(f"raw_{side}_topk_classes") or ()
    probs = row.get(f"raw_{side}_topk_probabilities") or ()
    return [[int(c), float(p)] for c, p in zip(classes, probs)]


def evidence_rows_from_request(
    request_row: Mapping[str, Any],
    evidence_payload: Mapping[str, Any],
) -> list[dict]:
    """E5 REQUESTS row + evidence payload -> EvidenceRow dict list.

    Rows are taken from ``attempt.decoder_outputs.raw.rows`` (raw view,
    mirroring ``e5_eval``), bound to canonical units, wrapped into the v2
    evidence dict shape, and leak-checked.  ``official`` carries the raw view
    times (no repair shift: the detector raw path never consumes repair
    signals, and the frozen raw combo is ``R`` only).
    """
    attempt = evidence_payload.get("attempt") or {}
    decoder_outputs = attempt.get("decoder_outputs") or {}
    raw_blk = decoder_outputs.get("raw") or {}
    rows = raw_blk.get("rows") or []
    request_identity = (
        evidence_payload.get("content_identity")
        or request_row.get("request_identity")
        or (attempt.get("request") or {}).get("request_id")
    )

    out: list[dict] = []
    for row in rows:
        gci = row.get("global_character_index")
        if gci is None:
            continue
        cid = canonical_unit_id_for_index(request_row, int(gci))
        if cid is None:
            continue
        start = _to_float(row.get("raw_global_start_sec"))
        if start is None:
            start = _to_float(row.get("fixed_global_start_sec"))
        end = _to_float(row.get("raw_global_end_sec"))
        if end is None:
            end = _to_float(row.get("fixed_global_end_sec"))
        topk = [[_topk_pairs(request_row, row, "start")],
                [_topk_pairs(request_row, row, "end")]]
        raw = {
            "start_sec": start,
            "end_sec": end,
            "start_entropy": _to_float(row.get("raw_start_entropy")),
            "end_entropy": _to_float(row.get("raw_end_entropy")),
            "start_margin": _to_float(row.get("raw_start_margin")),
            "end_margin": _to_float(row.get("raw_end_margin")),
            "topk": topk,
        }
        official = {
            "start_sec": _to_float(row.get("official_fixed_global_start_sec"))
            if _to_float(row.get("official_fixed_global_start_sec")) is not None
            else start,
            "end_sec": _to_float(row.get("official_fixed_global_end_sec"))
            if _to_float(row.get("official_fixed_global_end_sec")) is not None
            else end,
            "repair_start_shift_sec": None,
            "repair_end_shift_sec": None,
        }
        ev = {
            "request_identity": str(request_identity or "e5_candidate"),
            "view_id": "",
            "canonical_unit_id": cid,
            "raw": raw,
            "official": official,
            "hidden": {"available": False, "schema": None, "start": {}, "end": {}},
            "cross_view": {},
        }
        _recursive_leak_check(ev)
        out.append(ev)
    return out


def load_requests(requests_path) -> dict[str, dict]:
    """E5 REQUESTS.jsonl -> {request_id: row}."""
    rows: dict[str, dict] = {}
    with open(requests_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows[r["request_id"]] = r
    return rows


def load_bank(bank_path) -> list[dict]:
    """candidate bank JSONL -> list of Candidate dicts."""
    rows: list[dict] = []
    with open(bank_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def evidence_for_candidate(candidate: Mapping[str, Any]) -> dict:
    """Load the content-addressed evidence payload for one candidate row."""
    with open(candidate["raw_output_path"], encoding="utf-8") as fh:
        return json.load(fh)


def candidate_evidence_rows(
    candidate: Mapping[str, Any],
    requests: Mapping[str, dict],
) -> tuple[dict | None, list[dict]]:
    """(request_row, EvidenceRow dicts) for one candidate; missing -> (None, []).

    The candidate's evidence payload carries ``attempt.request.request_id``;
    the corresponding E5 REQUESTS row supplies the text/canonical binding.
    """
    payload = evidence_for_candidate(candidate)
    attempt = payload.get("attempt") or {}
    req = attempt.get("request") or {}
    request_id = req.get("request_id")
    request_row = requests.get(str(request_id)) if request_id else None
    if request_row is None:
        return None, []
    rows = evidence_rows_from_request(request_row, payload)
    return request_row, rows


def score_units(
    scorer: FrozenScorer,
    evidence_rows: list[dict],
) -> dict:
    """Per-unit detector decision for an E5 candidate.

    Returns ``{"units": [per-unit dict], "n_units", "decision"}`` with the same
    feature chain and thresholds as ``FrozenScorer.score``; each unit carries
    ``canonical_unit_id`` / ``start_sec`` / ``end_sec`` / ``p_bad`` / ``state``
    where ``state`` is accept|uncertain|reject (frozen tristate semantics).
    """
    if not evidence_rows:
        return {"units": [], "n_units": 0, "decision": "accept"}
    evs, _ = _evidence_rows(evidence_rows)
    X = _feature_matrix(evs, scorer.feat_keys)
    Xte = X[:, scorer.idx] if scorer.idx else np.zeros((len(X), 1))
    if scorer.predict_fn is not None:
        p_bad = np.asarray(scorer.predict_fn(Xte), dtype=float).ravel()
    else:
        p_bad = np.asarray(
            scorer.trainer(scorer.x_train, scorer.y_train, Xte),
            dtype=float).ravel()
    probs = {i: float(p) for i, p in enumerate(p_bad)}
    output = tristate_from_p_bad(
        probs, scorer.t_accept, scorer.t_reject,
        request_identity="frozen_shadow")
    states = ["accept"] * len(evs)
    decision = "accept"
    for iv in output.state_intervals:
        st = iv.state.value
        if st == "reject":
            decision = "reject"
        elif st == "uncertain" and decision != "reject":
            decision = "uncertain"
        if st in ("reject", "uncertain"):
            for i in range(int(iv.interval.start),
                           min(int(iv.interval.end), len(evs))):
                states[i] = st
    units = []
    for i, ev in enumerate(evs):
        units.append({
            "canonical_unit_id": int(ev.canonical_unit_id),
            "start_sec": _unit_start_sec(ev),
            "end_sec": _unit_end_sec(ev),
            "p_bad": float(p_bad[i]),
            "state": states[i],
        })
    return {
        "units": units,
        "n_units": len(units),
        "decision": decision,
    }
