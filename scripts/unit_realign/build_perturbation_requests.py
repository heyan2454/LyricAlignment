#!/usr/bin/env python3
"""Build P6 extended-perturbation requests centered on the R-O oracle requests.

For 9 representative cases (recovery 3 / harm 3 / catastrophic 3) from the
frozen P6 R-O run we take the R-O GT-prompted request as the zero point and
apply per-axis small perturbations (no cartesian product): audio left/right
boundary shifts of a few representative magnitudes, and text context
expand/contract by a few units.  Anchor perturbation is not applicable to
this population (all 40 R-O regions have ``anchors.left is None``) and is
recorded as such.

Each variant is a deep copy of the R-O request with only the perturbed axis
changed; the identity context (baseline_digest, audio_sha256, model/checkpoint
identity ...) is carried over unchanged so identity differences come exactly
from the perturbation payload.  ``request_identity`` and the legacy
``intervention_identity`` are recomputed with ``build_request_identity`` /
``intervention_payload``.  Family stays R-O; ``request_id`` keeps the
``song:region:family:PERT:axis`` structure.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.unit_realign.request_families import (  # noqa: E402
    UNIT_REQUEST_SCHEMA, build_request_identity, intervention_payload,
)

SOURCE_ORACLE_RUN = "/home/hyan/Data/lyricalign/runs/unit_realign_r_o_oracle_20260813"
SOURCE_MAIN_RUN = "/home/hyan/Data/lyricalign/runs/unit_realign_smoke_v2_verify"
DEFAULT_OUT_ROOT = "/home/hyan/Data/lyricalign/runs/unit_realign_perturbation_20260813"

# Per-case schedules: (axis tag, kind) relative to the R-O zero point.
# audio: boundary in {"left","right"}, delta_sec signed (negative left / positive right = extend).
# text:  side in {"left","right"}, delta_units signed (negative = contract, positive = expand).
SCHEDULE = {
    "recovery": [
        ("audioL-1s", "audio_left", -1.0),
        ("audioR+1s", "audio_right", 1.0),
        ("textR+1u", "text_right", 1),
    ],
    "harm": [
        ("audioL-2s", "audio_left", -2.0),
        ("audioR+2s", "audio_right", 2.0),
        ("textL-1u", "text_left", -1),
        ("textL-2u", "text_left", -2),
        ("textR+2u", "text_right", 2),
    ],
    "catastrophic": [
        ("audioL-0.5s", "audio_left", -0.5),
        ("audioR+0.5s", "audio_right", 0.5),
        ("audioL-2s", "audio_left", -2.0),
        ("textR+1u", "text_right", 1),
    ],
}


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    path.write_text(payload, encoding="utf-8")


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _select_cases(requests: list[dict], pool_by_region: dict[str, dict]) -> list[dict]:
    """Pick 3 regions per oracle_bucket, preferring varied strata."""
    buckets = {"recovery": [], "harm": [], "catastrophic": []}
    for req in requests:
        bucket = str(req.get("oracle_bucket") or "unknown")
        if bucket not in buckets:
            continue
        if str(req.get("region_id")) not in pool_by_region:
            continue
        buckets[bucket].append(req)
    selected = []
    for bucket, reqs in buckets.items():
        reqs.sort(key=lambda r: (str(r.get("stratum") or "zz"), str(r.get("region_id"))))
        for r in reqs[:3]:
            selected.append(r)
    return selected


def _text_shift_ids(units: list[dict], targets: list[int], side: str, delta: int) -> list[int] | None:
    """Return the new context id slice after expanding/contracting one side.

    base R-O context is target +/- 1.  Positive delta widens that side,
    negative delta contracts it.  None if the shift is not representable.
    """
    ids = [int(u["canonical_unit_id"]) for u in units]
    tlo, thi = min(ids.index(t) for t in targets), max(ids.index(t) for t in targets)
    cur_lo = max(0, tlo - 1)
    cur_hi = min(len(ids) - 1, thi + 1)
    if side == "left":
        new_lo = cur_lo + delta if delta < 0 else tlo - (1 + delta)
        new_lo = max(0, min(new_lo, tlo))
        new_hi = cur_hi
    else:
        new_hi = cur_hi - delta if delta < 0 else thi + (1 + delta)
        new_hi = min(len(ids) - 1, max(new_hi, thi))
        new_lo = cur_lo
    if new_lo > tlo or new_hi < thi or new_lo > new_hi:
        return None
    return ids[new_lo:new_hi + 1]


def _apply_text_variant(base: dict, units: list[dict], side: str, delta: int) -> dict | None:
    targets = [int(x) for x in base.get("target_unit_ids") or ()]
    new_ids = _text_shift_ids(units, targets, side, delta)
    if not new_ids:
        return None
    by_id = {int(u["canonical_unit_id"]): u for u in units}
    out = copy.deepcopy(base)
    out["canonical_ids"] = new_ids
    out["local_to_canonical"] = list(new_ids)
    out["canonical_to_local"] = {str(cid): i for i, cid in enumerate(new_ids)}
    out["text_units"] = [str(by_id[c]["text"]) for c in new_ids]
    out["candidate_text_ids"] = list(new_ids)
    out["baseline_text_ids"] = list(new_ids)
    out["fixed_context_unit_ids"] = [c for c in new_ids if c not in targets]
    return out


def _apply_audio_variant(base: dict, boundary: str, delta_sec: float,
                         gt_by_key: dict) -> dict | None:
    a0, a1 = (float(x) for x in base["candidate_audio_range_sec"])
    targets = [int(x) for x in base.get("target_unit_ids") or ()]
    ts = [gt_by_key[(str(base["song_id"]), str(t))] for t in targets if (str(base["song_id"]), str(t)) in gt_by_key]
    t_start = min(float(g["start_sec"]) for g in ts)
    t_end = max(float(g["end_sec"]) for g in ts)
    if boundary == "left":
        new_a0 = max(0.0, a0 + delta_sec)
        if new_a0 >= t_start:
            return None
        new_a1 = a1
    else:
        new_a1 = a1 + delta_sec
        if new_a1 <= t_end:
            return None
        new_a0 = a0
    out = copy.deepcopy(base)
    out["candidate_audio_range_sec"] = [new_a0, new_a1]
    out["baseline_audio_range_sec"] = [new_a0, new_a1]
    out["audio_start_sec"] = new_a0
    out["audio_end_sec"] = new_a1
    return out


def _finalize(variant: dict, region_id: str, song_id: str, tag: str) -> dict:
    variant["request_id"] = f"{song_id}:{region_id}:R-O:PERT:{tag}"
    variant["perturbation_tag"] = tag
    variant["is_zero_point"] = tag == "base"
    variant["intervention_identity"] = intervention_payload(variant)
    try:
        variant["request_identity"] = build_request_identity(variant)
    except ValueError:
        variant["request_identity"] = None
    return variant


def build(out_root: str, source_oracle_run: str) -> dict:
    root = Path(out_root)
    source = Path(source_oracle_run)
    oracle_reqs = _read_jsonl(source / "01_requests" / "REQUESTS_R_O.jsonl")
    oracle_pool = _read_jsonl(source / "00_population" / "REGION_POOL.jsonl")
    pool_by_region = {str(r.get("region_id")): r for r in oracle_pool}

    cases = _select_cases(oracle_reqs, pool_by_region)
    cases_by_region = {str(c.get("region_id")): c for c in cases}
    req_by_region = {str(r.get("region_id")): r for r in oracle_reqs}

    gt_rows = _read_jsonl(Path(SOURCE_MAIN_RUN) / "06_evaluator_only" / "BASELINE_GT.jsonl")
    gt_by_key = {(str(g["song_id"]), str(g["canonical_unit_id"])): g for g in gt_rows}

    requests, forwards, pool_rows, case_meta = [], [], [], []
    for case in cases:
        region_id = str(case["region_id"])
        bucket = str(case["oracle_bucket"])
        region = pool_by_region[region_id]
        base = copy.deepcopy(req_by_region[region_id])
        base["_region_units"] = region.get("units") or ()
        units = base["_region_units"]
        variants = [_finalize(copy.deepcopy(base), region_id, str(case["song_id"]), "base")]
        perturbed_tags = []
        for tag, kind, param in SCHEDULE[bucket]:
            if kind.startswith("audio"):
                boundary = kind.split("_", 1)[1]
                variant = _apply_audio_variant(base, boundary, float(param), gt_by_key)
            else:
                side = kind.split("_", 1)[1]
                variant = _apply_text_variant(base, units, side, int(param))
            if variant is None:
                perturbed_tags.append((tag, "not_constructible"))
                continue
            variants.append(_finalize(variant, region_id, str(case["song_id"]), tag))
            perturbed_tags.append((tag, "ok"))
        pool_rows.append(region)
        case_meta.append({"region_id": region_id, "song_id": str(case["song_id"]),
                          "bucket": bucket, "stratum": str(case.get("stratum")),
                          "n_variants": len(variants), "perturbations": perturbed_tags,
                          "anchor": "not_applicable_no_anchor"})
        for v in variants:
            v.pop("_region_units", None)
            requests.append(v)
            forwards.append({
                "schema": "unit_realign_forward_v1", "status": "queued",
                "request_identity": v.get("request_identity"),
                "request_id": v.get("request_id"), "region_id": region_id,
                "song_id": str(case["song_id"]), "family": "R-O:PERT",
                "stratum": str(case.get("stratum")),
                "forwarding": {"executor": "scripts/unit_realign/run_forward_real.py",
                               "evidence_dir": str(root / "02_forwards" / "evidence")},
            })

    _write_jsonl(root / "00_population" / "REGION_POOL.jsonl", pool_rows)
    _write_jsonl(root / "01_requests" / "REQUESTS_PERT.jsonl", requests)
    _write_jsonl(root / "02_forwards" / "FORWARDS.jsonl", forwards)
    _write_json(root / "01_requests" / "PERT_CONSTRUCTION.json", {
        "schema": "unit_realign_p6_perturbation_construction_v1",
        "source_oracle_run": str(source),
        "n_cases": len(cases),
        "n_requests": len(requests),
        "n_forwards": len(forwards),
        "by_bucket": {b: sum(1 for m in case_meta if m["bucket"] == b) for b in SCHEDULE},
        "cases": case_meta,
        "n_identity_none": sum(1 for r in requests if not r.get("request_identity")),
        "n_not_evaluation_only": sum(1 for r in requests if not r.get("evaluation_only")),
        "n_audio_same_as_base": sum(
            1 for r in requests
            if r.get("perturbation_tag") != "base" and not r.get("status")
            and r.get("candidate_audio_range_sec") == req_by_region[str(r["region_id"])].get("candidate_audio_range_sec")),
        "n_whole_item": sum(1 for r in requests if len(r.get("canonical_ids") or []) == len(r.get("target_unit_ids") or [])),
        "outputs": {"pool": str(root / "00_population" / "REGION_POOL.jsonl"),
                    "requests": str(root / "01_requests" / "REQUESTS_PERT.jsonl"),
                    "forwards": str(root / "02_forwards" / "FORWARDS.jsonl")},
    })
    return {"n_cases": len(cases), "n_requests": len(requests), "n_forwards": len(forwards),
            "n_identity_none": sum(1 for r in requests if not r.get("request_identity")),
            "n_audio_same_as_base": "see PERT_CONSTRUCTION.json"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-oracle-run", default=SOURCE_ORACLE_RUN)
    p.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    args = p.parse_args(argv)
    summary = build(out_root=args.out_root, source_oracle_run=args.source_oracle_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
