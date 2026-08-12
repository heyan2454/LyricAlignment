"""E5 no-GT realign proposals: offline GT evaluation of repair quality.

D1 requires per-episode comparison of original vs R-A/R-B/R-C vs oracle best,
measured only *after* proposal execution (offline). This module is the only
place allowed to read real GT for E5; it never writes GT back into
REQUESTS/evidence.

Metrics per episode/variant:
- repair rate at catastrophic thresholds: align each output row to a canonical
  unit via ``request.text_units`` character order, compare
  err_s = max(|Δstart|, |Δend|) against the real-GT interval; repaired if
  err_s <= threshold (same counting as E1 ``evaluate_oracle_runs``).
- coverage/missing/excess/occurrence via ``evaluate_tolerant`` (reference rows
  = target-range GT units; prediction rows = output rows).

Aggregation: per_method / per_family / per_song; oracle best = best repair
rate over O0..O3 per episode/threshold. Episodes without GT are recorded in
``unlabeled_episodes`` and excluded from denominators.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lyricalign.metrics.character import evaluate_tolerant
from lyricalign.realign_recovery.e5_proposals import load_timeline_manifest
from lyricalign.research_transition_recovery_detector.real_gt import (
    load_real_gt_with_audit,
)

E5_EVAL_SCHEMA_VERSION = "realign_recovery_e5_eval_v1"
ORACLE_METHODS: tuple[str, ...] = ("oracle_O0", "oracle_O1", "oracle_O2", "oracle_O3")
METHOD_ORDER: tuple[str, ...] = (
    "original", "oracle_O0", "oracle_O1", "oracle_O2", "oracle_O3",
    "R-A", "R-B", "R-C",
)


def _load_requests(requests_path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(requests_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows[r["request_id"]] = r
    return rows


def _load_evidence(evidence_dir) -> list[tuple[dict, str]]:
    """(attempt payload, evidence filename) list, sorted for determinism."""
    out: list[tuple[dict, str]] = []
    for f in sorted(Path(evidence_dir).glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        out.append((payload, f.name))
    return out


def _unit_id_for_text_index(text_unit_ids: list[int], unit_idx: int) -> int | None:
    if not (0 <= unit_idx < len(text_unit_ids)):
        return None
    return text_unit_ids[unit_idx]


def _map_rows_to_units(rows: list[dict], text_units: list[str], text_unit_ids: list[int]) -> list[tuple[int, dict]]:
    """Map output rows to canonical unit ids via request-local char index.

    ``global_character_index`` is a request-local character index into the
    concatenation of ``text_units``. Text units are single characters for E5,
    so unit ``unit_idx`` starts at cumulative character offset. ``text_unit_ids``
    holds the canonical unit id for each text position (NOT necessarily
    contiguous: oracle rows pass the episode target ids, which may contain
    windowing gaps). Rows whose index falls outside the text are appended
    with ``unit_id=None`` (excess).
    """
    boundaries: list[int] = []
    total = 0
    for t in text_units:
        total += len(t)
        boundaries.append(total)
    mapped: list[tuple[int, dict]] = []
    for row in rows:
        gci = row.get("global_character_index")
        if gci is None or not isinstance(gci, int):
            continue
        unit_id: int | None = None
        for unit_idx, cum in enumerate(boundaries):
            if gci < cum:
                prev = boundaries[unit_idx - 1] if unit_idx > 0 else 0
                if prev <= gci:
                    unit_id = _unit_id_for_text_index(text_unit_ids, unit_idx)
                break
        mapped.append((unit_id, row))
    return mapped


def _row_time(row: dict) -> tuple[float, float]:
    start = row.get("raw_global_start_sec")
    if start is None:
        start = row.get("fixed_global_start_sec", 0.0)
    end = row.get("raw_global_end_sec")
    if end is None:
        end = row.get("fixed_global_end_sec", 0.0)
    return float(start), float(end)


def _eval_variant(
    *,
    song: str,
    episode_id: str,
    target_ids: list[int],
    method: str,
    variant: str,
    gt_song: dict,
    text_units: list[str],
    text_unit_ids: list[int],
    rows: list[dict],
    catastrophic_sec: tuple[float, ...],
) -> dict | None:
    """Evaluate one request's output against the real-GT target range."""
    n_units = 0
    n_repaired = {t: 0 for t in catastrophic_sec}
    abs_errors: list[float] = []
    mapped = _map_rows_to_units(rows, text_units, text_unit_ids)

    item_id = f"{episode_id}|{song}"
    ref_rows: list[dict] = []
    for cid in target_ids:
        gt = gt_song.get(int(cid))
        if gt is None:
            continue
        ref_rows.append({
            "item_id": item_id,
            "character_index": int(cid),
            "start_sec": float(gt["start_sec"]),
            "end_sec": float(gt["end_sec"]),
            "normalized_character": str(gt.get("text") or ""),
        })
    if not ref_rows:
        return None

    pred_rows: list[dict] = []
    out_by_unit: dict[int, tuple[float, float]] = {}
    for unit_id, row in mapped:
        start, end = _row_time(row)
        if unit_id is None:
            pred_rows.append({
                "item_id": item_id,
                "character_index": -(len(pred_rows) + 1),
                "start_sec": start,
                "end_sec": end,
                "normalized_character": str(row.get("character") or ""),
            })
            continue
        pred_rows.append({
            "item_id": item_id,
            "character_index": int(unit_id),
            "start_sec": start,
            "end_sec": end,
            "normalized_character": str(row.get("character") or ""),
        })
        out_by_unit.setdefault(int(unit_id), (start, end))

    for cid in target_ids:
        gt = gt_song.get(int(cid))
        if gt is None:
            continue
        out = out_by_unit.get(int(cid))
        if out is None:
            continue
        n_units += 1
        err_s = max(abs(float(gt["start_sec"]) - out[0]), abs(float(gt["end_sec"]) - out[1]))
        abs_errors.append(err_s)
        for t in catastrophic_sec:
            if err_s <= t:
                n_repaired[t] += 1

    tolerant = evaluate_tolerant(ref_rows, pred_rows)
    return {
        "method": method,
        "variant": variant,
        "n_units": n_units,
        "n_repaired": {str(t): n_repaired[t] for t in catastrophic_sec},
        "repair_rate": {
            str(t): round(n_repaired[t] / n_units, 6) if n_units else 0.0
            for t in catastrophic_sec
        },
        "mae_sec": round(sum(abs_errors) / len(abs_errors), 6) if abs_errors else None,
        "character_coverage": tolerant["character_coverage"],
        "missing_prediction_count": tolerant["missing_prediction_count"],
        "missing_prediction_rate": tolerant["missing_prediction_rate"],
        "extra_prediction_count": tolerant["extra_prediction_count"],
        "invalid_prediction_rate": tolerant["invalid_prediction_rate"],
        "unusable_prediction_rate": tolerant["unusable_prediction_rate"],
        "reference_character_count": tolerant["character_count"],
        "prediction_row_count": tolerant["prediction_row_count"],
    }


def _oracle_best(variants: dict[str, dict], catastrophic_sec: tuple[float, ...]) -> dict:
    best: dict[str, dict] = {}
    for t in catastrophic_sec:
        best_t = None
        best_rate = -1.0
        for v in variants.values():
            if v["method"] not in ORACLE_METHODS:
                continue
            if v["n_units"] == 0:
                continue
            rate = v["n_repaired"][str(t)] / v["n_units"]
            if rate > best_rate:
                best_rate = rate
                best_t = v["variant"]
        best[str(t)] = {
            "repair_rate": round(best_rate, 6) if best_t else 0.0,
            "variant": best_t,
        }
    return best


def _merge_audit(audits: list[dict]) -> dict:
    merged: dict = {}
    for au in audits:
        for song, reasons in au.items():
            merged[song] = reasons
    return merged


def _add_bucket(bucket: dict, result: dict, catastrophic_sec: tuple[float, ...]) -> None:
    bucket["n_units"] += result["n_units"]
    for t in catastrophic_sec:
        bucket["n_repaired"][str(t)] += result["n_repaired"][str(t)]
    bucket["missing_prediction_count"] += result["missing_prediction_count"]
    bucket["extra_prediction_count"] += result["extra_prediction_count"]
    bucket["reference_character_count"] += result["reference_character_count"]


def _finalize_bucket(bucket: dict, catastrophic_sec: tuple[float, ...]) -> dict:
    n = bucket["n_units"]
    out = {
        "n_units": n,
        "n_repaired": bucket["n_repaired"],
        "repair_rate": {
            str(t): round(bucket["n_repaired"][str(t)] / n, 6) if n else 0.0
            for t in catastrophic_sec
        },
        "missing_prediction_count": bucket["missing_prediction_count"],
        "extra_prediction_count": bucket["extra_prediction_count"],
        "mean_coverage": (
            round(bucket["coverage_sum"] / bucket["reference_character_count"], 6)
            if bucket["reference_character_count"] else 0.0
        ),
    }
    return out


def _new_bucket(catastrophic_sec: tuple[float, ...]) -> dict:
    return {
        "n_units": 0,
        "n_repaired": {str(t): 0 for t in catastrophic_sec},
        "missing_prediction_count": 0,
        "extra_prediction_count": 0,
        "reference_character_count": 0,
        "coverage_sum": 0.0,
    }


def evaluate_e5_episodes(
    requests_path,
    evidence_dir,
    annotations_path,
    timeline_manifests,
    out_path,
    *,
    catastrophic_sec: tuple[float, ...] = (1, 2, 5, 10),
) -> dict:
    """Offline real-GT evaluation of E5 no-GT proposals. Writes summary JSON + returns it."""
    if isinstance(timeline_manifests, (str, os.PathLike)):
        timeline_manifests = [timeline_manifests]
    catastrophic_sec = tuple(float(t) for t in catastrophic_sec)

    real_gt: dict = {}
    audits: list[dict] = []
    for mp in timeline_manifests:
        rg, au = load_real_gt_with_audit(annotations_path, mp)
        real_gt.update(rg)
        audits.append(au)
    gt_audit = _merge_audit(audits)
    timeline = load_timeline_manifest(timeline_manifests)

    requests = _load_requests(requests_path)

    episodes: dict[str, dict] = {}

    for payload, fname in _load_evidence(evidence_dir):
        attempt = payload.get("attempt") or {}
        req = attempt.get("request") or {}
        rid = req.get("request_id")
        req_row = requests.get(rid)
        if req_row is None:
            continue
        provenance = req_row.get("provenance") or {}
        episode_id = provenance.get("episode_id")
        if not episode_id:
            continue
        song = req_row.get("source_song_id")
        method = provenance.get("proposal_method")
        variant = req_row.get("input_variant") or "unknown"
        target_ids = [int(c) for c in (provenance.get("target_unit_ids") or [])]
        if not target_ids or not song:
            continue
        family = provenance.get("episode_family") or "unknown"
        rows = ((attempt.get("decoder_outputs") or {}).get("raw") or {}).get("rows") or []
        text_units = req_row.get("text_units") or []
        text_unit_start = int(provenance.get("text_unit_start") or 0)
        text_unit_end = int(provenance.get("text_unit_end") or text_unit_start)
        method = provenance.get("proposal_method")
        if str(method).startswith("oracle"):
            text_unit_ids = [int(c) for c in (provenance.get("target_unit_ids") or [])]
        else:
            text_unit_ids = list(range(text_unit_start, text_unit_end + 1))
        if not text_unit_ids:
            continue

        ep = episodes.setdefault(episode_id, {
            "episode_id": episode_id,
            "song_id": song,
            "family": family,
            "source_window_id": provenance.get("source_window_id"),
            "target_unit_start": int(provenance.get("target_unit_start") or 0),
            "target_unit_end": int(provenance.get("target_unit_end") or 0),
            "target_unit_ids": target_ids,
            "variants": {},
        })
        result = _eval_variant(
            song=song,
            episode_id=episode_id,
            target_ids=target_ids,
            method=method,
            variant=variant,
            gt_song=real_gt.get(song) or {},
            text_units=text_units,
            text_unit_ids=text_unit_ids,
            rows=rows,
            catastrophic_sec=catastrophic_sec,
        )
        if result is None:
            ep["variants"][variant] = {"method": method, "no_gt_in_target": True}
            continue
        ep["variants"][variant] = result

    per_episode: dict[str, dict] = {}
    labeled_episodes: list[str] = []
    unlabeled_episodes: list[dict] = []
    for ep_id, ep in episodes.items():
        has_gt = any(
            v.get("n_units", 0) > 0 for v in ep["variants"].values()
        )
        entry = {
            "episode_id": ep_id,
            "song_id": ep["song_id"],
            "family": ep["family"],
            "source_window_id": ep["source_window_id"],
            "target_unit_start": ep["target_unit_start"],
            "target_unit_end": ep["target_unit_end"],
            "target_unit_count": len(ep["target_unit_ids"]),
            "labeled": has_gt,
            "variants": ep["variants"],
        }
        if not has_gt:
            entry["variants"] = {}
            entry["no_gt_reason"] = "no accepted GT units in target range"
            unlabeled_episodes.append(entry)
            per_episode[ep_id] = entry
            continue
        labeled_episodes.append(ep_id)
        entry["oracle_best"] = _oracle_best(ep["variants"], catastrophic_sec)
        per_episode[ep_id] = entry

    buckets: dict[str, dict] = {}
    for method in METHOD_ORDER:
        buckets[method] = _new_bucket(catastrophic_sec)
    family_buckets: dict[str, dict] = {}
    song_buckets: dict[str, dict] = {}

    for ep_id in labeled_episodes:
        ep = episodes[ep_id]
        fam = ep["family"]
        song = ep["song_id"]
        if fam not in family_buckets:
            family_buckets[fam] = _new_bucket(catastrophic_sec)
        if song not in song_buckets:
            song_buckets[song] = _new_bucket(catastrophic_sec)
        for variant, result in ep["variants"].items():
            if result.get("no_gt_in_target"):
                continue
            method = result["method"]
            _add_bucket(buckets[method], result, catastrophic_sec)
            _add_bucket(family_buckets[fam], result, catastrophic_sec)
            _add_bucket(song_buckets[song], result, catastrophic_sec)

    per_method = {
        method: _finalize_bucket(bucket, catastrophic_sec)
        for method, bucket in buckets.items()
        if bucket["n_units"] or bucket["reference_character_count"]
    }
    per_family = {
        fam: _finalize_bucket(bucket, catastrophic_sec)
        for fam, bucket in sorted(family_buckets.items())
        if bucket["n_units"] or bucket["reference_character_count"]
    }
    per_song = {
        song: _finalize_bucket(bucket, catastrophic_sec)
        for song, bucket in sorted(song_buckets.items())
        if bucket["n_units"] or bucket["reference_character_count"]
    }

    summary = {
        "schema_version": E5_EVAL_SCHEMA_VERSION,
        "catastrophic_sec": [float(t) for t in catastrophic_sec],
        "inputs": {
            "requests": str(requests_path),
            "evidence_dir": str(evidence_dir),
            "annotations": str(annotations_path),
            "timeline_manifests": [str(m) for m in timeline_manifests],
        },
        "episode_count": len(per_episode),
        "labeled_episode_count": len(labeled_episodes),
        "unlabeled_episode_count": len(unlabeled_episodes),
        "unlabeled_episodes": unlabeled_episodes,
        "per_episode": per_episode,
        "per_method": per_method,
        "per_family": per_family,
        "per_song": per_song,
        "gt_audit": gt_audit,
    }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
