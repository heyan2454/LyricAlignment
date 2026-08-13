"""Realign Gate stage 02: case selection + no-GT realign behavior requests.

Consumes the stage-01 CASE_POOL (per-song detector audit) and produces S1..S4
strata plus research_v7-compatible R-A/R-B proposal requests that all pass the
GT firewall. Forward execution is delegated to
``scripts/research_v7/run_behavior_suite.py`` via an injectable subprocess hook
(``_invoke_suite``) so tests never touch the real executor.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from lyricalign.realign_gate import identity
from lyricalign.realign_recovery.e5_proposals import E5_WORKFLOW_MODE, load_timeline_manifest
from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request

_WINDOW_RE = re.compile(r":w(\d+)")
_DETECTOR_STATES = ("ACCEPT", "UNCERTAIN", "REJECT")
_STRATA_ORDER = ("S3", "S1", "S4")
CORRECT_MAX_ERROR_MS = 200.0
BAD_MIN_ERROR_MS = 1000.0

R_A_CONTEXT_SEC = 2.0
R_A_TEXT_K = 2
R_B_TEXT_K = 2
R_A_VARIANT = "R-A_unsafe_old_range"
R_B_VARIANT = "R-B_safe_anchor_bounded"
R_U_VARIANT = "R-U_unit_local"
R_S_VARIANT = "R-S_sparse_fixed"
MAX_LOCAL_TARGET_UNITS = 8


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
        if case.get("detector_shadow") is not None:
            entry["detector_shadow"] = case["detector_shadow"]
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


def sample_strata_adaptive(case_pool: list[dict], *, n_target: int, s2_min: int = 20,
                           s3_min: int = 20, seed: int = 0,
                           initial_song_cap: int = 4, max_song_cap: int = 8) -> tuple[list[dict], dict]:
    """Escalate diversity caps before declaring a stratum exhausted.

    The accounting artifact makes an unmet target evidence, rather than an
    excuse to silently continue with a biased case pool.
    """
    attempts = []
    chosen: list[dict] = []
    for cap in range(initial_song_cap, max_song_cap + 1):
        chosen = sample_strata(case_pool, n_target=n_target, s2_share=.35, seed=seed,
                               max_per_song=cap, max_per_song_stratum=cap)
        counts = {s: sum(1 for x in chosen if x["stratum"] == s) for s in ("S1", "S2", "S3", "S4")}
        attempts.append({"per_song_cap": cap, "selected": len(chosen), "strata": counts})
        if counts["S2"] >= s2_min and counts["S3"] >= s3_min:
            return chosen, {"status": "targets_met", "attempts": attempts}
    eligible = {s: 0 for s in ("S1", "S2", "S3", "S4", "SG", "unbound")}
    for row in case_pool:
        label, _ = _classify(row)
        state = _normalize_state(row.get("old_detector_state"))
        eligible[_stratum_for(label, state) or ("SG" if label is None else "unbound")] += 1
    return chosen, {"status": "exhausted", "targets": {"S2": s2_min, "S3": s3_min},
                    "eligible": eligible, "attempts": attempts}


def _parse_window_index(window_id) -> int:
    if window_id is None:
        return 0
    if isinstance(window_id, int):
        return window_id
    s = str(window_id)
    m = _WINDOW_RE.search(s)
    if m:
        return int(m.group(1))
    tail = s.rsplit(":", 1)[-1]
    if tail.isdigit():
        return int(tail)
    return 0


def _window_text_unit_ids(window_row: dict | None = None) -> list[int]:
    """Window-restricted text unit ids (B11 fix).

    Reads ``text_unit_start``/``text_unit_end`` from the P0
    BASELINE_WINDOW_INDEX row (or its ``provenance``), returning only the
    actual 60s window's text ids — never the full-song unit list.
    """
    if not window_row:
        return []
    start = window_row.get("text_unit_start")
    end = window_row.get("text_unit_end")
    if start is None or end is None:
        prov = window_row.get("provenance") or {}
        start = prov.get("text_unit_start")
        end = prov.get("text_unit_end")
    if start is None or end is None:
        return []
    lo, hi = sorted((int(start), int(end)))
    return list(range(lo, hi + 1))


def _window_key(song_id, window_index):
    return str(song_id), int(window_index or 0)


def _load_rows(path):
    if isinstance(path, (str, os.PathLike)):
        return load_jsonl(path)
    return path or []


def _index_rows(rows, key_fn) -> dict:
    out = {}
    for r in rows:
        out[key_fn(r)] = r
    return out


def _unsafe_intervals(shadow: dict) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in shadow.get("unsafe_intervals", [])
            if float(b) > float(a)]


def _units_overlapping(units_meta: dict, ids: list[int], start: float, end: float) -> list[int]:
    return sorted(
        c for c in ids
        if float(units_meta[c]["end_sec"]) > float(start)
        and float(units_meta[c]["start_sec"]) < float(end)
    )


def _expand_neighbours(ids: list[int], allowed: list[int], k: int) -> list[int]:
    """Expand ids by up to k neighbours, restricted to the window's ``allowed``."""
    allowed_sorted = sorted(set(allowed))
    want = set(int(c) for c in ids)
    if k <= 0:
        return [c for c in allowed_sorted if c in want]
    pos = {c: i for i, c in enumerate(allowed_sorted)}
    out = set()
    for c in want:
        i = pos.get(c)
        if i is None:
            continue
        for j in range(max(0, i - k), min(len(allowed_sorted), i + k + 1)):
            out.add(allowed_sorted[j])
    return [c for c in allowed_sorted if c in out]


def _localize_target_ids(
    requested_ids: list[int], units: dict[int, dict], *, max_units: int = MAX_LOCAL_TARGET_UNITS,
) -> list[int]:
    """Convert legacy whole-window targets to one detector-contiguous local span.

    The old CASE_POOL predates unit-level experiments and can name every unit
    in a 60s window.  Prefer the highest-risk contiguous UNCERTAIN/REJECT span,
    capped at 1..8 units; only fall back to the first capped requested span
    when the detector provides no unsafe unit.
    """
    requested = sorted(set(int(x) for x in requested_ids if int(x) in units))
    unsafe = [cid for cid in requested
              if str(units[cid].get("state") or "").upper() in {"UNCERTAIN", "REJECT"}]
    groups: list[list[int]] = []
    for cid in unsafe:
        if not groups or cid != groups[-1][-1] + 1:
            groups.append([cid])
        else:
            groups[-1].append(cid)
    if groups:
        groups.sort(key=lambda g: (
            -max(float(units[c].get("p_bad") or 0.0) for c in g), -len(g), g[0]))
        return groups[0][:max_units]
    return requested[:max_units]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _skip_entry(case: dict, reason: str) -> dict:
    return {
        "song_id": case.get("song_id"),
        "window_id": case.get("window_id"),
        "case_id": case.get("case_id"),
        "reason": reason,
    }


def _make_pair_request(
    case: dict, win: dict, units_meta: dict, audio_path: str, window_index: int,
    window_span_sec: float, target_ids: list[int], method: str, variant: str,
    a0: float, a1: float, text_ids: list[int], params: dict, *,
    model_id: str, checkpoint_id: str,
) -> dict | None:
    texts = [str(units_meta[c]["text"] or "") for c in text_ids]
    if a1 - a0 <= 0 or not texts:
        return None
    text_hash = _sha256_text(_canonical(texts))
    case_id = case.get("case_id")
    request_id = f"realign_gate-{case_id}:{variant}"
    return {
        "request_id": request_id,
        "item_id": str(case.get("song_id")),
        "parent_request_id": None,
        "audio_path": audio_path,
        "audio_source": "production_baseline_window",
        "audio_start_sec": round(a0, 6),
        "audio_end_sec": round(a1, 6),
        "text_source": "labels",
        "text_start_index": 0,
        "text_end_index": len(texts),
        "text_units": texts,
        "timestamp_slot_indices": None,
        "canonical_text_start": int(text_ids[0]),
        "canonical_text_end": int(text_ids[-1]) + 1,
        "canonical_ids": list(text_ids),
        "canonical_to_local": {str(cid): i for i, cid in enumerate(text_ids)},
        "canonical_adapter_version": "realign_gate_local_mapping_v1",
        "workflow_mode": E5_WORKFLOW_MODE,
        "mutation_type": "p2_dual_variant_proposal",
        "mutation_parameters": {
            **params,
            "episode_id": case_id,
            "proposal_method": method,
            "audio_extra_sec": round(max(0.0, (a1 - a0) - float(params.get("base_span_sec") or 0.0)), 6),
        },
        "model_id": model_id,
        "checkpoint_id": checkpoint_id,
        "input_variant": variant,
        "evaluation_role": None,
        "language": "Chinese",
        "source_song_id": str(case.get("song_id")),
        "source_window_start_sec": round(float(win.get("audio_start_sec", 0.0)), 6),
        "source_window_end_sec": round(float(win.get("audio_end_sec", window_span_sec)), 6),
        "schema_version": "research_v7_long_slot_v1",
        "provenance": {
            "realign_recovery_stage": "realign_gate_p2",
            "episode_id": case_id,
            "episode_family": "realign_gate",
            # Sampling stratum is GT-derived and must remain evaluator-side.
            "episode_kind": "realign_gate_region",
            "source_window_id": f"{case.get('song_id')}:w{window_index}:full",
            "window_start_sec": round(float(win.get("window_start_sec", 0.0)), 6),
            "window_end_sec": round(float(win.get("window_end_sec", 0.0)), 6),
            "target_unit_ids": list(target_ids),
            "target_unit_start": int(target_ids[0]),
            "target_unit_end": int(target_ids[-1]),
            "audio_start_sec": round(float(win.get("audio_start_sec", a0)), 6),
            "audio_end_sec": round(float(win.get("audio_end_sec", a1)), 6),
            "text_unit_start": int(text_ids[0]),
            "text_unit_end": int(text_ids[-1]),
            "proposal_method": method,
            "context": params,
            "window_size_sec": round(a1 - a0, 6),
        },
    }


def _plan_entry(row: dict, case: dict, window_index: int, method: str, variant: str) -> dict:
    prov = row["provenance"]
    return {
        "request_id": row["request_id"],
        "case_id": case.get("case_id"),
        "family": "realign_gate",
        "kind": case.get("stratum", "unknown"),
        "song_id": row["item_id"],
        "source_window_id": prov["source_window_id"],
        "proposal_method": method,
        "variant": variant,
        "target_unit_start": prov["target_unit_start"],
        "target_unit_end": prov["target_unit_end"],
        "audio_start_sec": row["audio_start_sec"],
        "audio_end_sec": row["audio_end_sec"],
        "text_unit_start": prov["text_unit_start"],
        "text_unit_end": prov["text_unit_end"],
        "window_size_sec": prov["window_size_sec"],
    }


def construct_case_pairs(
    cases: list[dict],
    timeline_manifest_paths,
    *,
    window_index_rows=None,
    detector_shadow_rows=None,
    r_a_context_sec: float = R_A_CONTEXT_SEC,
    r_a_text_k: int = R_A_TEXT_K,
    r_b_text_k: int = R_B_TEXT_K,
    include_sparse: bool = False,
    require_paired_rb: bool = True,
    model_id: str = identity.MODEL_ID,
    checkpoint_id: str = identity.CHECKPOINT_ID,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Build paired R-A/R-B requests per case (B11/B15 P2).

    Each constructible case emits R-U/R-A/R-B sharing case_id / song_id / window / target
    ids — only the intervention differs. A case that cannot yield both variants
    is written to ``skipped_cases`` and never becomes a single-variant sample.

    R-A centres a narrow local text/audio span on the P0 baseline detector's
    unsafe interval(s); R-B bounds its context with the nearest ACCEPT anchors
    inside the same 60s window. Returns (requests, plan, skipped_cases).
    """
    timeline = load_timeline_manifest(timeline_manifest_paths)
    win_index = _index_rows(
        _load_rows(window_index_rows),
        lambda r: _window_key(r.get("song_id"), r.get("window_index")),
    )
    shadow_index = _index_rows(
        _load_rows(detector_shadow_rows),
        lambda r: _window_key(r.get("song_id"), r.get("window_index")),
    )

    requests: list[dict] = []
    plan: list[dict] = []
    skipped_cases: list[dict] = []

    for case in cases:
        song_id = case.get("song_id")
        if song_id is None:
            continue
        case_id = case.get("case_id")
        window_id = case.get("window_id")
        window_index = _parse_window_index(window_id)
        key = _window_key(song_id, window_index)
        win = win_index.get(key)
        shadow = shadow_index.get(key)
        if win is None:
            skipped_cases.append(_skip_entry(case, "window_not_found_in_baseline_window_index"))
            continue
        if shadow is None:
            skipped_cases.append(_skip_entry(case, "detector_shadow_not_found"))
            continue

        shadow_data = shadow.get("detector_shadow") or {}
        units = {int(k): v for k, v in (shadow_data.get("units") or {}).items()}
        unsafe = _unsafe_intervals(shadow_data)
        if not unsafe:
            skipped_cases.append(_skip_entry(case, "no_unsafe_intervals"))
            continue

        meta = timeline.get(str(song_id))
        if meta is None:
            skipped_cases.append(_skip_entry(case, "timeline_song_not_found"))
            continue
        units_meta = meta["units"]
        duration = float(meta.get("duration_sec") or 0.0)

        window_text_ids = _window_text_unit_ids(win)
        if not window_text_ids:
            skipped_cases.append(_skip_entry(case, "window_text_units_missing"))
            continue
        window_text_ids = sorted(window_text_ids)

        target_ids = [int(c) for c in (case.get("target_unit_ids") or win.get("target_unit_ids") or [])]
        if not target_ids:
            skipped_cases.append(_skip_entry(case, "target_unit_ids_missing"))
            continue
        original_target_count = len(target_ids)
        target_ids = _localize_target_ids(target_ids, units)
        if not target_ids:
            skipped_cases.append(_skip_entry(case, "target_units_not_in_detector_shadow"))
            continue

        audio_path = win.get("audio_path") or meta.get("audio_path")
        if not audio_path:
            skipped_cases.append(_skip_entry(case, "audio_path_missing"))
            continue
        win_lo = float(win.get("audio_start_sec") if win.get("audio_start_sec") is not None else win.get("window_start_sec", 0.0))
        win_hi = float(win.get("audio_end_sec") if win.get("audio_end_sec") is not None else win.get("window_end_sec", duration))

        def clip(a: float, b: float) -> tuple[float, float]:
            lo = max(win_lo, min(a, win_hi))
            hi = max(lo, min(b, win_hi))
            return round(lo, 6), round(hi, 6)

        target_start = min(float(units_meta[c]["start_sec"]) for c in target_ids if c in units_meta)
        target_end = max(float(units_meta[c]["end_sec"]) for c in target_ids if c in units_meta)
        base_span = round(target_end - target_start, 6)

        # The case's actual units, not all unsafe spans in its window.
        # Detector times are a signal, not trusted geometry.  Cropping and
        # local request extent must use the canonical timeline, otherwise a
        # malformed detector row can silently turn a 1--8 unit span into an
        # entire window.
        target_rows = [units_meta.get(c) for c in target_ids]
        target_rows = [r for r in target_rows if r is not None]
        if not target_rows:
            skipped_cases.append(_skip_entry(case, "target_units_not_in_window"))
            continue
        u_lo = min(float(r["start_sec"]) for r in target_rows)
        u_hi = max(float(r["end_sec"]) for r in target_rows)
        ra_audio = clip(u_lo - r_a_context_sec, u_hi + r_a_context_sec)
        ra_ids = _units_overlapping(units_meta, window_text_ids, u_lo, u_hi)
        if not ra_ids:
            ra_ids = list(target_ids)
        ra_ids = _expand_neighbours(ra_ids, window_text_ids, r_a_text_k)

        # ---- R-B: context delimited by in-window ACCEPT anchors ----
        accept_left = [
            c for c in window_text_ids
            if c in units and str(units[c].get("state") or "").upper() == "ACCEPT"
            and float(units[c]["end_sec"]) <= target_start
        ]
        accept_right = [
            c for c in window_text_ids
            if c in units and str(units[c].get("state") or "").upper() == "ACCEPT"
            and float(units[c]["start_sec"]) >= target_end
        ]
        left_anchor = max(accept_left, key=lambda c: float(units[c]["end_sec"])) if accept_left else None
        right_anchor = min(accept_right, key=lambda c: float(units[c]["start_sec"])) if accept_right else None
        if left_anchor is None or right_anchor is None:
            skipped_cases.append(_skip_entry(case, "r_b_missing_bilateral_accept_anchors"))
            rb_spec = None
        else:
            rb_start = float(units_meta[left_anchor]["end_sec"])
            rb_end = float(units_meta[right_anchor]["start_sec"])
            rb_audio = clip(rb_start, rb_end)
            rb_ids = _expand_neighbours(target_ids, window_text_ids, r_b_text_k)
            rb_spec = ("R-B", R_B_VARIANT, rb_audio, rb_ids,
                       {"base_span_sec": base_span,
                        "left_anchor": left_anchor, "right_anchor": right_anchor,
                        "text_k": r_b_text_k})

        # R-U: minimal target request with one safe neighbour where available.
        ru_ids = _expand_neighbours(target_ids, window_text_ids, 1)
        ru_audio = clip(u_lo - 0.75, u_hi + 0.75)

        specs = [
            ("R-U", R_U_VARIANT, ru_audio, ru_ids,
             {"base_span_sec": base_span, "unit_local": True, "text_k": 1}),
            ("R-A", R_A_VARIANT, ra_audio, ra_ids,
             {"base_span_sec": base_span,
              "unsafe_span_sec": round(u_hi - u_lo, 6),
              "audio_extra_sec": round(ra_audio[1] - ra_audio[0] - (u_hi - u_lo), 6),
              "text_k": r_a_text_k}),
        ]
        if rb_spec is not None:
            specs.append(rb_spec)
        built = []
        for method, variant, (a0, a1), text_ids, params in specs:
            row = _make_pair_request(
                case, win, units_meta, audio_path, window_index,
                win_hi - win_lo, target_ids, method, variant,
                a0, a1, text_ids, params, model_id=model_id, checkpoint_id=checkpoint_id,
            )
            if row is None:
                continue
            # Requests must actually differ from full baseline forward inputs.
            if (round(a0, 6), round(a1, 6), text_ids) == (round(win_lo, 6), round(win_hi, 6), window_text_ids):
                skipped_cases.append(_skip_entry(case, f"{method.lower()}_null_intervention"))
                continue
            row["effective_intervention"] = True
            row["pairing_key"] = f"{song_id}:{case_id}:{window_index}"
            built.append((row, _plan_entry(row, case, window_index, method, variant)))
        # Legacy paired analysis requires all R-U/R-A/R-B.  Unit-level
        # adaptive execution must not discard a valid R-U/R-A/R-S candidate
        # merely because bilateral anchors are unavailable; R-B remains
        # explicitly recorded as unavailable and can be replenished later.
        built_variants = {r[0]["input_variant"] for r in built}
        required = {R_U_VARIANT, R_A_VARIANT, R_B_VARIANT}
        if require_paired_rb and built_variants != required:
            skipped_cases.append(_skip_entry(case, "incomplete_active_request_family"))
            continue
        if not require_paired_rb and not {R_U_VARIANT, R_A_VARIANT} <= built_variants:
            skipped_cases.append(_skip_entry(case, "incomplete_core_request_family"))
            continue
        for row, entry in built:
            requests.append(row)
            plan.append(entry)

        # R-S keeps the complete local R-A text context.  Only target units
        # retain timestamp slots; all context units are restored exactly from
        # the production baseline after sparse decoding.
        if include_sparse:
            sparse_ids = list(ra_ids)
            active_local = [i for i, cid in enumerate(sparse_ids) if cid in set(target_ids)]
            fixed_rows = []
            for i, cid in enumerate(sparse_ids):
                if i in active_local:
                    continue
                baseline = units.get(cid) or units_meta.get(cid)
                if baseline is None:
                    continue
                start = baseline.get("fixed_global_start_sec", baseline.get("start_sec"))
                end = baseline.get("fixed_global_end_sec", baseline.get("end_sec"))
                source = "production_detector_shadow"
                if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                        or float(end) < float(start)):
                    baseline = units_meta.get(cid)
                    start = None if baseline is None else baseline.get("start_sec")
                    end = None if baseline is None else baseline.get("end_sec")
                    source = "canonical_timeline_fallback_invalid_shadow_geometry"
                if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                        or float(end) < float(start)):
                    continue
                fixed_rows.append({
                    "local_index": i,
                    "canonical_unit_id": cid,
                    "fixed_global_start_sec": float(start),
                    "fixed_global_end_sec": float(end),
                    "baseline_source": source,
                })
            if active_local and len(active_local) + len(fixed_rows) == len(sparse_ids):
                rs = _make_pair_request(
                    case, win, units_meta, audio_path, window_index,
                    win_hi - win_lo, target_ids, "R-S", R_S_VARIANT,
                    ra_audio[0], ra_audio[1], sparse_ids,
                    {"base_span_sec": base_span, "sparse_semantics": "full_text_active_timestamp_fixed_remerge",
                     "active_local_slots": active_local, "fixed_slot_count": len(fixed_rows),
                     "legacy_target_count": original_target_count},
                    model_id=model_id, checkpoint_id=checkpoint_id,
                )
                if rs is not None:
                    rs["timestamp_slot_indices"] = active_local
                    rs["active_slot_indices"] = active_local
                    rs["fixed_slot_rows"] = fixed_rows
                    rs["slot_constraint_schema"] = "realign_sparse_fixed_v1"
                    rs["effective_intervention"] = True
                    rs["pairing_key"] = f"{song_id}:{case_id}:{window_index}"
                    requests.append(rs)
                    plan.append(_plan_entry(rs, case, window_index, "R-S", R_S_VARIANT))
            else:
                skipped_cases.append(_skip_entry(case, "r_s_incomplete_active_fixed_partition"))

    return requests, plan, skipped_cases


def build_requests(
    cases: list[dict],
    timeline_manifest_paths,
    window_index_rows=None,
    *,
    detector_shadow_rows=None,
    include_sparse: bool = False,
    require_paired_rb: bool = True,
    r_a_text_k: int = R_A_TEXT_K,
    model_id: str,
    checkpoint_id: str,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Convert cases to paired R-A/R-B requests and enforce the GT firewall.

    Returns (requests, plan, skipped_firewall, skipped_cases). Every returned
    request carries the research_v7_long_slot_v1 schema and passes
    ``validate_no_gt_request``; GT-bearing rows go to ``skipped_firewall``
    (failures.jsonl). A case that cannot construct both variants lands in
    ``skipped_cases`` (SKIPPED_CASES.jsonl) and never yields a single-variant
    request (B11/B15).
    """
    requests, plan, skipped_cases = construct_case_pairs(
        cases, timeline_manifest_paths,
        window_index_rows=window_index_rows,
        detector_shadow_rows=detector_shadow_rows,
        include_sparse=include_sparse,
        require_paired_rb=require_paired_rb,
        r_a_text_k=r_a_text_k,
        model_id=model_id, checkpoint_id=checkpoint_id,
    )

    kept: list[dict] = []
    skipped_firewall: list[dict] = []
    for row in requests:
        forbidden = validate_no_gt_request(row)
        if forbidden:
            skipped_firewall.append({
                "request_id": row.get("request_id"),
                "case_id": (row.get("provenance") or {}).get("episode_id"),
                "forbidden": sorted(forbidden),
                "reason": "no_gt_violation",
            })
        else:
            kept.append(row)
    return kept, plan, skipped_firewall, skipped_cases


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
    """Injected subprocess seam; tests monkeypatch this to avoid real runs.

    REQUESTS carry relative ``audio_path``/``raw_output_path`` resolved against the
    data directory (see realign_recovery run notes), so the suite must run with
    ``cwd=DATA_ROOT``. ``env`` is enriched with the subprocess environment.
    """
    cwd = str(identity.DATA_ROOT)
    if env is None:
        env = os.environ.copy()
    else:
        env = {**os.environ.copy(), **env}
    env.setdefault("LYRICALIGN_REPO_DIR", str(identity.REPO_ROOT))
    proc = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=cwd)
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
    window_index_rows=None,
    detector_shadow_rows=None,
    n_target: int | None = None,
    s2_share: float | None = None,
    seed: int | None = None,
    max_per_song: int | None = None,
    max_per_song_stratum: int | None = None,
    model_id: str | None = None,
    checkpoint_id: str | None = None,
    model_revision: str | None = None,
    include_sparse: bool | None = None,
    require_paired_rb: bool | None = None,
    r_a_text_k: int | None = None,
    selection_mode: str | None = None,
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
    include_sparse = bool(include_sparse if include_sparse is not None else pick("include_sparse", False))
    require_paired_rb = bool(require_paired_rb if require_paired_rb is not None
                             else pick("require_paired_rb", True))
    r_a_text_k = int(r_a_text_k if r_a_text_k is not None else pick("r_a_text_k", R_A_TEXT_K))
    selection_mode = str(selection_mode if selection_mode is not None else pick("selection_mode", "gt_stratified"))

    stage_dir = run_root / "02_behavior"
    stage_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir = stage_dir / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)

    if case_pool is None:
        case_pool = run_root / "01_detector_audit" / "CASE_POOL.jsonl"
    case_pool_path = Path(case_pool)
    pool_rows = load_jsonl(case_pool_path)
    if selection_mode == "preselected_no_gt":
        if any("old_error_ms" in row or "sampling_label" in row for row in pool_rows):
            raise ValueError("preselected_no_gt pool must not contain GT-derived fields")
        cases = pool_rows[:n_target]
        sample_accounting = {
            "status": "complete" if len(cases) == n_target else "exhausted",
            "selection_mode": selection_mode,
            "selected": len(cases), "available": len(pool_rows),
            "by_detector_state": {state: sum(row.get("old_detector_state") == state for row in cases)
                                  for state in ("ACCEPT", "UNCERTAIN", "REJECT")},
        }
    elif selection_mode == "gt_stratified":
        cases, sample_accounting = sample_strata_adaptive(
            pool_rows, n_target=n_target, seed=seed,
            initial_song_cap=max_per_song, max_song_cap=max(max_per_song, 8))
    else:
        raise ValueError(f"unknown selection_mode={selection_mode!r}")
    cases_path = stage_dir / "CASES.jsonl"
    write_jsonl(cases_path, cases)
    (stage_dir / "SAMPLE_ACCOUNTING.json").write_text(
        json.dumps(sample_accounting, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if timeline_manifests is None:
        timeline_manifests = (cfg.get("timeline_manifests")
                              or (cfg.get("inputs") or {}).get("cohort_manifests") or [])
    if baseline_rows is None:
        baseline_rows = (cfg.get("baseline_rows")
                         or (cfg.get("inputs") or {}).get("old_run_requests") or [])
    if isinstance(baseline_rows, (str, Path)):
        baseline_rows = load_jsonl(baseline_rows)

    if window_index_rows is None:
        window_index_rows = cfg.get("window_index_rows") or (
            run_root / "00_inventory" / "BASELINE_WINDOW_INDEX.jsonl")
    if isinstance(window_index_rows, (str, Path)):
        window_index_rows = load_jsonl(window_index_rows)

    if detector_shadow_rows is None:
        detector_shadow_rows = cfg.get("detector_shadow_rows") or (
            run_root / "00_inventory" / "BASELINE_DETECTOR_SHADOW.jsonl")
    if isinstance(detector_shadow_rows, (str, Path)):
        detector_shadow_rows = load_jsonl(detector_shadow_rows)

    requests, plan, skipped_firewall, skipped_cases = build_requests(
        cases, timeline_manifests,
        window_index_rows=window_index_rows,
        detector_shadow_rows=detector_shadow_rows,
        model_id=model_id, checkpoint_id=checkpoint_id,
        include_sparse=include_sparse,
        require_paired_rb=require_paired_rb,
        r_a_text_k=r_a_text_k,
    )
    requests_path = stage_dir / "REQUESTS.jsonl"
    write_jsonl(requests_path, requests)
    write_jsonl(proposals_dir / "PROPOSAL_PLAN.json", plan)
    skipped_cases_path = stage_dir / "SKIPPED_CASES.jsonl"
    write_jsonl(skipped_cases_path, skipped_cases)

    checks = no_gt_check(requests)
    no_gt_path = stage_dir / "NO_GT_CHECK.jsonl"
    write_jsonl(no_gt_path, checks)

    failures_dir = run_root / "00_meta"
    failures_dir.mkdir(parents=True, exist_ok=True)
    if skipped_firewall:
        existing = []
        failures_path = failures_dir / "failures.jsonl"
        if failures_path.exists():
            existing = load_jsonl(failures_path)
        write_jsonl(failures_path, existing + skipped_firewall)

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
        "sample_status": sample_accounting["status"],
        "n_requests": len(requests),
        "include_sparse": include_sparse,
        "require_paired_rb": require_paired_rb,
        "selection_mode": selection_mode,
        "n_skipped": len(skipped_cases),
        "n_gt_violations": sum(1 for c in checks if not c["validated"]),
        "n_candidate_index": len(candidate_index),
        "executor": "smoke" if smoke else ("real" if gpu else "smoke"),
        "suite": {k: suite.get(k) for k in ("returncode", "stdout", "stderr")},
        "artifacts": {
            "cases": str(cases_path),
            "requests": str(requests_path),
            "no_gt_check": str(no_gt_path),
            "proposal_plan": str(proposals_dir / "PROPOSAL_PLAN.json"),
            "skipped_cases": str(skipped_cases_path),
            "forward": str(forward_root),
            "candidate_index": str(candidate_path) if candidate_index else None,
        },
    }
    return summary
