"""E5 no-GT realign proposals: build candidate REQUESTS from episodes + detector shadow.

E5 semantics (03_REALIGN_EXPERIMENT_PLAN §6, 10_EXECUTION §D1):
- proposals are constructed from *no-GT* signals only: episode target units,
  baseline window coverage, and the Raw detector's unsafe time intervals.
- audio/text spans come from the synthetic (non-GT) timeline manifest used to
  build the frozen baseline; GT never enters any request row
  (``validate_no_gt_request`` must pass for every row).
- R-A unsafe-old-range: audio = unsafe interval span +/- context;
  text = target units +/- K neighbours.
- R-B safe-anchor bounded: audio/text delimited by the nearest non-unsafe
  (anchor) units on both sides of the target span.
- R-C bad-window subdivision: split the bad 60s window into two 30s halves and
  budget lyrics by timeline coverage (no trust in unsafe timestamps).

Every request row is research_v7-compatible (schema ``research_v7_long_slot_v1``)
so the GPU forward is driven by ``scripts/research_v7/run_behavior_suite.py
--real``. Identity fields (model/checkpoint/audio/text) are never mixed with
detector thresholds or GT labels.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request

PROPOSAL_SCHEMA_VERSION = "realign_recovery_e5_proposal_v1"
E5_WORKFLOW_MODE = "recovery_e5_proposal"

ORACLE_MODES_SEC: dict[str, float] = {
    "O0": 0.0,
    "O1": 2.0,
    "O2": 5.0,
    "O3": 10.0,
}


class E5Error(ValueError):
    """Raised on inconsistent no-GT inputs (never on missing GT)."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_timeline_manifest(manifest_paths) -> dict[str, dict]:
    """timeline manifest(s) -> {song_id: {units, audio_path, duration_sec}}.

    ``manifest_paths`` may be a single path or a list; later files override
    earlier ones for the same song.
    """
    if isinstance(manifest_paths, (str, os.PathLike)):
        manifest_paths = [manifest_paths]
    out: dict[str, dict] = {}
    for path in manifest_paths:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                song = r["song_id"]
                out[song] = {
                    "units": {
                        int(u["canonical_unit_id"]): {
                            "start_sec": float(u["start_sec"]),
                            "end_sec": float(u["end_sec"]),
                            "text": u.get("text"),
                        }
                        for u in r.get("canonical_units", [])
                    },
                    "audio_path": r.get("concat_audio_path"),
                    "duration_sec": float(r.get("duration_sec", 0.0) or 0.0),
                }
    return out


def load_episodes(episodes_path) -> list[dict]:
    rows: list[dict] = []
    with open(episodes_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _clip(start: float, end: float, duration: float, margin: float = 0.001) -> tuple[float, float]:
    cap = max(0.0, duration - margin)
    lo = max(0.0, min(start, cap))
    hi = max(lo, min(end, cap))
    return round(lo, 6), round(hi, 6)


def _span(unit_ids: list[int], units_meta: dict[int, dict]) -> tuple[float, float] | None:
    """Return (start_sec, end_sec) covering the given unit ids, or None."""
    start = None
    end = None
    for cid in unit_ids:
        u = units_meta.get(int(cid))
        if u is None:
            continue
        s = float(u["start_sec"])
        e = float(u["end_sec"])
        start = s if start is None else min(start, s)
        end = e if end is None else max(end, e)
    if start is None or end is None:
        return None
    return start, end


def _units_in_span(units_meta: dict[int, dict], start: float, end: float) -> list[int]:
    return sorted(
        cid for cid, u in units_meta.items()
        if float(u["end_sec"]) > start and float(u["start_sec"]) < end
    )


def _neighbour_text_units(
    unit_ids: list[int], units_meta: dict[int, dict], k: int = 0,
) -> list[int]:
    """Expand target units by up to k neighbours each side (within the song)."""
    ids = [int(c) for c in unit_ids]
    if k <= 0 or not ids:
        return ids
    all_ids = sorted(units_meta)
    lo = max(0, ids[0] - k)
    hi = min(len(all_ids) - 1, ids[-1] + k)
    return [c for c in all_ids if lo <= c <= hi]


def unsafe_intervals_for_window(
    baseline_rows: list[dict], song_id: str, window_index: int,
) -> list[list[float]]:
    """Read detector_shadow.unsafe_intervals for a song/window from E3 baseline."""
    for row in baseline_rows:
        if row.get("song_id") == song_id and int(row.get("window_index", -1)) == window_index:
            shadow = row.get("detector_shadow") or {}
            return [[float(a), float(b)] for a, b in shadow.get("unsafe_intervals", [])]
    return []


def build_proposals(
    episodes: list[dict],
    timeline_manifest_paths,
    baseline_rows: list[dict],
    *,
    r_a_context_sec: float = 2.0,
    r_a_text_k: int = 2,
    r_b_text_k: int = 2,
    r_c_split: tuple[float, float] = (0.5,),
    include_original: bool = True,
    include_oracle: bool = True,
    include_ra: bool = True,
    include_rb: bool = True,
    include_rc: bool = True,
    short_window_sec: float = 4.0,
    model_id: str = "Qwen3-ForcedAligner-0.6B-hf",
    checkpoint_id: str = "r2-step-000750",
) -> tuple[list[dict], list[dict]]:
    """Build E5 proposal requests + a proposal plan for a batch of episodes.

    ``episodes`` entries must carry ``song_id``, ``target_unit_ids``,
    ``source_window`` (with ``text_unit_ids``) and ``family``. Returns
    (requests, plan); every request passes ``validate_no_gt_request``.
    """
    timeline = load_timeline_manifest(timeline_manifest_paths)
    requests: list[dict] = []
    plan: list[dict] = []

    for ep in episodes:
        song = ep.get("song_id")
        meta = timeline.get(song)
        if meta is None or not meta.get("audio_path"):
            continue
        units_meta = meta["units"]
        audio = meta["audio_path"]
        duration = meta["duration_sec"]

        target_ids = [int(u) for u in ep.get("target_unit_ids", [])]
        if not target_ids:
            continue
        src_window_ids = [int(u) for u in (ep.get("source_window") or {}).get("text_unit_ids", [])]
        if not src_window_ids:
            continue

        window_index = int((ep.get("source_window") or {}).get("window_index", 0) or 0)
        unsafe = unsafe_intervals_for_window(baseline_rows, song, window_index)
        ep_id = ep.get("id", "ep-unknown")
        family = ep.get("family", "natural")
        kind = ep.get("kind", "natural")

        target_span = _span(target_ids, units_meta)
        window_span = _span(src_window_ids, units_meta)
        if target_span is None or window_span is None:
            continue

        target_texts = [str(units_meta[c]["text"] or "") for c in target_ids]
        window_texts = [str(units_meta[c]["text"] or "") for c in src_window_ids]

        row_index = 0

        def make_request(
            method: str,
            audio_start: float,
            audio_end: float,
            text_ids: list[int],
            params: dict,
            variant: str,
        ) -> dict:
            nonlocal row_index
            texts = [str(units_meta[c]["text"] or "") for c in text_ids]
            text_hash = _sha256_text(_canonical(texts))
            a0, a1 = _clip(audio_start, audio_end, duration)
            if a1 - a0 <= 0:
                return None
            no_gt = {
                "model_id": model_id,
                "checkpoint_id": checkpoint_id,
                "audio_source": audio,
                "audio_start_sec": a0,
                "audio_end_sec": a1,
                "text_units": list(texts),
                "text_content_hash": text_hash,
                "workflow_mode": E5_WORKFLOW_MODE,
                "mutation_type": "e5_proposal",
                "input_variant": variant,
            }
            found = validate_no_gt_request(no_gt)
            if found:
                raise E5Error(f"E5 request carries GT-bearing fields: {sorted(found)}")
            row_index += 1
            request_id = f"e5-{ep_id}:{variant}:{row_index}"
            row = {
                "request_id": request_id,
                "item_id": song,
                "parent_request_id": None,
                "audio_path": audio,
                "audio_source": "m4singer_segment_concat",
                "audio_start_sec": a0,
                "audio_end_sec": a1,
                "text_source": "labels",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": list(texts),
                "timestamp_slot_indices": None,
                "workflow_mode": E5_WORKFLOW_MODE,
                "mutation_type": "e5_proposal",
                "mutation_parameters": {
                    **params,
                    "episode_id": ep_id,
                    "proposal_method": method,
                    "audio_extra_sec": round(max(0.0, (a1 - a0) - (params.get("base_span_sec") or 0.0)), 6),
                },
                "model_id": model_id,
                "checkpoint_id": checkpoint_id,
                "input_variant": variant,
                "evaluation_role": None,
                "language": "Chinese",
                "source_song_id": song,
                "source_window_start_sec": a0,
                "source_window_end_sec": a1,
                "schema_version": "research_v7_long_slot_v1",
                "provenance": {
                    "realign_recovery_stage": "E5_proposal",
                    "episode_id": ep_id,
                    "episode_family": family,
                    "episode_kind": kind,
                    "source_window_id": f"{song}:w{window_index}:full",
                    "target_unit_start": int(target_ids[0]),
                    "target_unit_end": int(target_ids[-1]),
                    "target_unit_ids": target_ids,
                    "audio_start_sec": a0,
                    "audio_end_sec": a1,
                    "text_unit_start": int(text_ids[0]) if text_ids else None,
                    "text_unit_end": int(text_ids[-1]) if text_ids else None,
                    "proposal_method": method,
                    "context": params,
                    "window_size_sec": round(a1 - a0, 6),
                },
            }
            return row

        def emit(method: str, audio_span: tuple[float, float], text_ids: list[int],
                 params: dict, variant: str) -> None:
            row = make_request(method, audio_span[0], audio_span[1], text_ids, params, variant)
            if row is not None:
                requests.append(row)
                plan.append({
                    "request_id": row["request_id"],
                    "episode_id": ep_id,
                    "family": family,
                    "kind": kind,
                    "song_id": song,
                    "source_window_id": f"{song}:w{window_index}:full",
                    "proposal_method": method,
                    "variant": variant,
                    "target_unit_start": int(target_ids[0]),
                    "target_unit_end": int(target_ids[-1]),
                    "audio_start_sec": row["audio_start_sec"],
                    "audio_end_sec": row["audio_end_sec"],
                    "text_unit_start": row["provenance"]["text_unit_start"],
                    "text_unit_end": row["provenance"]["text_unit_end"],
                    "window_size_sec": row["provenance"]["window_size_sec"],
                })

        ts, te = target_span
        base_span = {"base_span_sec": te - ts}

        if include_original:
            ws, we = window_span
            emit("original", (ws, we), src_window_ids,
                 {"base_span_sec": we - ws, "window_size_sec": we - ws}, "original_full")

        if include_oracle:
            for mode, extra in ORACLE_MODES_SEC.items():
                emit(f"oracle_{mode}", (ts - extra, te + extra), target_ids,
                     {**base_span, "audio_extra_sec": extra}, f"oracle_{mode}")

        if include_ra:
            if unsafe:
                lo = min(a for a, _ in unsafe)
                hi = max(b for _, b in unsafe)
                ra_text = _neighbour_text_units(target_ids, units_meta, r_a_text_k)
                emit("R-A", (lo - r_a_context_sec, hi + r_a_context_sec), ra_text,
                     {**base_span, "unsafe_span_sec": hi - lo,
                      "audio_extra_sec": r_a_context_sec * 2,
                      "text_k": r_a_text_k}, "R-A_unsafe_old_range")

        if include_rb:
            safe_left: int | None = None
            safe_right: int | None = None
            if unsafe:
                unsafe_lo = min(a for a, _ in unsafe)
                unsafe_hi = max(b for _, b in unsafe)
            else:
                unsafe_lo = unsafe_hi = None
            for cid in sorted(units_meta):
                u = units_meta[cid]
                if unsafe_lo is not None and float(u["end_sec"]) < unsafe_lo:
                    safe_left = cid
            for cid in sorted(units_meta, reverse=True):
                u = units_meta[cid]
                if unsafe_hi is not None and float(u["start_sec"]) > unsafe_hi:
                    safe_right = cid
            rb_ids = [int(c) for c in target_ids]
            rb_span = _span(rb_ids, units_meta) or target_span
            rb_start, rb_end = rb_span
            if safe_left is not None:
                rb_start = min(rb_start, float(units_meta[safe_left]["end_sec"]))
            if safe_right is not None:
                rb_end = max(rb_end, float(units_meta[safe_right]["start_sec"]))
            rb_text = _neighbour_text_units(target_ids, units_meta, r_b_text_k)
            emit("R-B", (rb_start, rb_end), rb_text,
                 {**base_span, "left_anchor": safe_left, "right_anchor": safe_right,
                  "text_k": r_b_text_k}, "R-B_safe_anchor_bounded")

        if include_rc:
            ws, we = window_span
            bad_lo = unsafe[0][0] if unsafe else ws
            bad_hi = unsafe[-1][1] if unsafe else we
            for frac in r_c_split:
                cut = bad_lo + (bad_hi - bad_lo) * frac
                rc_ids = _units_in_span(units_meta, bad_lo, cut)
                rc_text = _neighbour_text_units(rc_ids or target_ids, units_meta, r_b_text_k)
                emit("R-C", (bad_lo, cut), rc_text,
                     {**base_span, "parent_span": [bad_lo, bad_hi], "split": frac},
                     f"R-C_subdiv_{frac}")
                rc_ids2 = _units_in_span(units_meta, cut, bad_hi)
                rc_text2 = _neighbour_text_units(rc_ids2 or target_ids, units_meta, r_b_text_k)
                emit("R-C", (cut, bad_hi), rc_text2,
                     {**base_span, "parent_span": [bad_lo, bad_hi], "split": frac},
                     f"R-C_subdiv_{frac}_hi")

    return requests, plan


def write_requests(requests: list[dict], out_path: str | os.PathLike) -> str:
    out_path = str(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in requests]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    return out_path
