#!/usr/bin/env python3
"""E7/E8 shared GT input: per-unit real-GT error for every E5 candidate variant.

Consumes exactly the E5 offline evaluation inputs (REQUESTS + evidence +
real GT annotations + timeline manifests) and emits one JSONL row per
``(episode, variant, canonical_unit_id)`` with the predicted interval, the
GT interval, and per-unit absolute errors for both the candidate (``new``)
and the episode's ``original_full`` baseline (``old``).  Rows of the
``original_full`` variant itself carry old == new.

This is the ONLY GT-bearing input E7 (quality gate) and E8 (writeback policy)
are allowed to read; neither may touch the raw annotations directly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.realign_recovery.e5_eval import (  # noqa: E402
    _load_evidence,
    _load_requests,
    _map_rows_to_units,
    _row_time,
)
from lyricalign.research_transition_recovery_detector.real_gt import (  # noqa: E402
    load_real_gt_with_audit,
)

SCHEMA_VERSION = "realign_recovery_e7_per_unit_gt_v1"
ORIGINAL_VARIANT = "original_full"


def _collect_units(
    evidence_dir, requests: dict, real_gt: dict,
) -> tuple[list[dict], dict[str, dict]]:
    rows: list[dict] = []
    meta: dict[str, dict] = {}
    for payload, _fname in _load_evidence(evidence_dir):
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
        variant = req_row.get("input_variant") or "unknown"
        method = provenance.get("proposal_method")
        target_ids = [int(c) for c in (provenance.get("target_unit_ids") or [])]
        if not target_ids or not song:
            continue
        family = provenance.get("episode_family") or "unknown"
        raw_rows = ((attempt.get("decoder_outputs") or {}).get("raw") or {}).get("rows") or []
        text_units = req_row.get("text_units") or []
        text_unit_start = int(provenance.get("text_unit_start") or 0)
        text_unit_end = int(provenance.get("text_unit_end") or text_unit_start)
        if str(method).startswith("oracle"):
            text_unit_ids = [int(c) for c in (provenance.get("target_unit_ids") or [])]
        else:
            text_unit_ids = list(range(text_unit_start, text_unit_end + 1))
        if not text_unit_ids:
            continue

        mapped = _map_rows_to_units(raw_rows, text_units, text_unit_ids)
        out_by_unit: dict[int, tuple[float, float]] = {}
        for unit_id, row in mapped:
            if unit_id is None:
                continue
            start, end = _row_time(row)
            out_by_unit.setdefault(int(unit_id), (start, end))

        gt_song = real_gt.get(song) or {}
        for cid in target_ids:
            gt = gt_song.get(int(cid))
            if gt is None:
                continue
            out = out_by_unit.get(int(cid))
            if out is None:
                continue
            new_start, new_end = out
            err = max(abs(float(gt["start_sec"]) - new_start),
                      abs(float(gt["end_sec"]) - new_end))
            rows.append({
                "episode_id": episode_id,
                "variant": variant,
                "method": str(method),
                "song_id": song,
                "family": family,
                "source_window_id": provenance.get("source_window_id"),
                "canonical_unit_id": int(cid),
                "new_start_sec": new_start,
                "new_end_sec": new_end,
                "gt_start_sec": float(gt["start_sec"]),
                "gt_end_sec": float(gt["end_sec"]),
                "new_error_sec": err,
                "old_start_sec": None,
                "old_end_sec": None,
                "old_error_sec": None,
                "old_covered": False,
            })
        m = meta.setdefault(episode_id, {
            "episode_id": episode_id,
            "song_id": song,
            "family": family,
            "source_window_id": provenance.get("source_window_id"),
            "variants": [],
            "original_variant": ORIGINAL_VARIANT,
        })
        if variant not in m["variants"]:
            m["variants"].append(variant)
    return rows, meta


def _attach_old_baseline(rows: list[dict]) -> None:
    old_by_epi: dict[str, dict[int, dict]] = {}
    for r in rows:
        if r["variant"] == ORIGINAL_VARIANT:
            old_by_epi.setdefault(r["episode_id"], {})[r["canonical_unit_id"]] = r
    for r in rows:
        old = (old_by_epi.get(r["episode_id"]) or {}).get(r["canonical_unit_id"])
        if old is not None and r["variant"] != ORIGINAL_VARIANT:
            r["old_start_sec"] = old["new_start_sec"]
            r["old_end_sec"] = old["new_end_sec"]
            r["old_error_sec"] = old["new_error_sec"]
            r["old_covered"] = True
        elif r["variant"] == ORIGINAL_VARIANT:
            r["old_start_sec"] = r["new_start_sec"]
            r["old_end_sec"] = r["new_end_sec"]
            r["old_error_sec"] = r["new_error_sec"]
            r["old_covered"] = True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Extract per-unit real-GT errors for E5 candidates")
    p.add_argument("--requests", required=True)
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--annotations", required=True)
    p.add_argument("--timeline-manifest", required=True, nargs="+")
    p.add_argument("--out", required=True, help="directory for E7_PER_UNIT_GT.jsonl + E7_INPUT_META.json")
    args = p.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    real_gt: dict = {}
    for mp in args.timeline_manifest:
        rg, _au = load_real_gt_with_audit(args.annotations, mp)
        real_gt.update(rg)
    requests = _load_requests(args.requests)
    rows, meta = _collect_units(args.evidence_dir, requests, real_gt)
    if not rows:
        raise SystemExit("no per-unit rows produced; check inputs")
    _attach_old_baseline(rows)
    rows.sort(key=lambda r: (r["episode_id"], r["variant"], r["canonical_unit_id"]))

    out_path = out_dir / "E7_PER_UNIT_GT.jsonl"
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(out_dir / "E7_INPUT_META.json", "w", encoding="utf-8") as fh:
        json.dump({
            "schema_version": SCHEMA_VERSION,
            "row_count": len(rows),
            "episode_count": len(meta),
            "per_unit_path": str(out_path),
            "episodes": meta,
        }, fh, ensure_ascii=False, indent=1)
    print(f"per-unit rows: {len(rows)} episodes: {len(meta)} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
