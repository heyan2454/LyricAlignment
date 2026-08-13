#!/usr/bin/env python3
"""Build evaluator-only BASELINE_GT.jsonl for unit-level realign.

Semantics (data-review P1-1 resolution): in this corpus the frozen inventory
has two timelines per canonical unit:

  - BASELINE_UNITS.jsonl  == GT reference timeline (matches LONG_TIMELINE_MANIFEST
    canonical_units); start_sec/end_sec are the "true" boundaries.
  - BASELINE_DETECTOR_SHADOW.jsonl units are the detector alignment (model output),
    so the current baseline error is detector-vs-GT.

Every output row is keyed by (song_id, canonical_unit_id) and carries:
  - start_sec / end_sec            GT reference interval (pair_unit_outcomes GT)
  - max_boundary_error_ms          detector-vs-GT max boundary error (stratum gate)

GT rows are emitted for every valid GT interval even when the detector shadow
interval is degenerate (start >= end) or absent: those rows carry
detector_start_sec/detector_end_sec = None and max_boundary_error_ms = None,
so the evaluator never reports a valid canonical unit as an "extra prediction".

The file is evaluator-only and must never enter no-GT features.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _valid_interval(start, end) -> bool:
    return (isinstance(start, (int, float)) and isinstance(end, (int, float))
            and float(end) > float(start) >= 0.0)


def build_baseline_gt(baseline_units: list[dict], shadow_rows: list[dict]) -> tuple[list[dict], dict]:
    """Join BASELINE_UNITS (GT) with detector shadow alignment -> GT rows + audit."""
    shadow_by: dict[tuple[str, int], dict] = {}
    n_shadow_units = 0
    for sh in shadow_rows:
        for key, row in ((sh.get("detector_shadow") or {}).get("units") or {}).items():
            try:
                cid = int(key)
            except (TypeError, ValueError):
                continue
            shadow_by[(str(sh.get("song_id") or ""), cid)] = row
            n_shadow_units += 1

    out: list[dict] = []
    audit: dict = {
        "schema": "unit_realign_baseline_gt_v1",
        "n_baseline_units": len(baseline_units),
        "n_shadow_units": n_shadow_units,
        "matched": 0,
        "matched_time_mismatch": 0,
        "gt_row_with_degenerate_detector": 0,
        "no_shadow_unit": [],
        "invalid_interval": [],
        "max_boundary_error_ms": {"min": None, "max": None, "mean": None},
    }
    errors: list[float] = []
    for u in baseline_units:
        song = str(u.get("song_id") or "")
        cid = int(u.get("canonical_unit_id"))
        gt = (u.get("start_sec"), u.get("end_sec"))
        if not _valid_interval(*gt):
            audit["invalid_interval"].append({"song_id": song, "canonical_unit_id": cid})
            continue
        shadow = shadow_by.get((song, cid))
        if shadow is None:
            audit["no_shadow_unit"].append({"song_id": song, "canonical_unit_id": cid})
            out.append({
                "song_id": song,
                "canonical_unit_id": cid,
                "start_sec": float(gt[0]),
                "end_sec": float(gt[1]),
                "detector_start_sec": None,
                "detector_end_sec": None,
                "max_boundary_error_ms": None,
            })
            continue
        det = (shadow.get("start_sec"), shadow.get("end_sec"))
        if not _valid_interval(*det):
            audit["gt_row_with_degenerate_detector"] += 1
            audit["no_shadow_unit"].append({"song_id": song, "canonical_unit_id": cid, "detector": det})
            out.append({
                "song_id": song,
                "canonical_unit_id": cid,
                "start_sec": float(gt[0]),
                "end_sec": float(gt[1]),
                "detector_start_sec": None,
                "detector_end_sec": None,
                "max_boundary_error_ms": None,
            })
            continue
        audit["matched"] += 1
        if abs(float(det[0]) - float(gt[0])) > 1e-6 or abs(float(det[1]) - float(gt[1])) > 1e-6:
            audit["matched_time_mismatch"] += 1
        max_err = 1000.0 * max(abs(float(det[0]) - float(gt[0])), abs(float(det[1]) - float(gt[1])))
        errors.append(max_err)
        out.append({
            "song_id": song,
            "canonical_unit_id": cid,
            "start_sec": float(gt[0]),
            "end_sec": float(gt[1]),
            "detector_start_sec": float(det[0]),
            "detector_end_sec": float(det[1]),
            "max_boundary_error_ms": round(max_err, 4),
        })
    if errors:
        audit["max_boundary_error_ms"] = {
            "min": round(min(errors), 4), "max": round(max(errors), 4),
            "mean": round(sum(errors) / len(errors), 4),
        }
    return out, audit


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", required=True, help="detector 00_inventory/ dir (BASELINE_UNITS.jsonl + BASELINE_DETECTOR_SHADOW.jsonl)")
    p.add_argument("--out", required=True, help="output BASELINE_GT.jsonl path (run 06_evaluator_only/)")
    p.add_argument("--audit", help="optional audit JSON path")
    args = p.parse_args(argv)
    inv = Path(args.inventory)
    units = _read_jsonl(inv / "BASELINE_UNITS.jsonl")
    shadow = _read_jsonl(inv / "BASELINE_DETECTOR_SHADOW.jsonl")
    rows, audit = build_baseline_gt(units, shadow)
    _write_jsonl(Path(args.out), rows)
    if args.audit:
        Path(args.audit).parent.mkdir(parents=True, exist_ok=True)
        Path(args.audit).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema": audit["schema"], "n_rows": len(rows), "audit": audit}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
