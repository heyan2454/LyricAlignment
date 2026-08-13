"""Emit per-request detector rows for the unit-realign gate.

The v2 evidence layer stores flat baseline/candidate times only (no raw/official
dual decode, no entropy/margin/audio support), so a trained detector p_bad
(e.g. detector_v5_RNN_TV) is not reproducible from this corpus.  This producer
computes an explicit, content-addressed *proxy* p_bad from evidence-only,
no-GT signals:

  p_bad_before = baseline structural risk (zero/short/long duration, overlap)
  p_bad_after  = candidate structural risk + cross-family disagreement
                 (span across R-A/R-B/R-S/R-U candidate views of the same unit)
                 + missing-view penalty, both mapped to [0,1] via the logistic
                 of a small additive score.

detector_identity = "unit_realign_p_bad_proxy_cross_family_spread_v1" marks it
as a proxy, never a trained detector.  Schema: unit_realign_detector_row_v1.

Consumers: extract_unit_gate_features.py --detector-rows (fills
detector_p_bad_before/after, signed_detector_delta, state_before/after).
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

SCHEMA = "unit_realign_detector_row_v1"
IDENTITY = "unit_realign_p_bad_proxy_cross_family_spread_v1"

# logistic on additive score: score=0 -> 0.5; +/-1.0 -> ~0.27/0.73
SHORT_DURATION_S = 0.02
LONG_DURATION_S = 1.5
SPREAD_500MS_SATURATION = 0.5


def _logit(score: float) -> float:
    return 1.0 / (1.0 + math.exp(-score))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8")] if path.exists() else []


def _struct_risk(start: float | None, end: float | None,
                 prev_end: float | None, next_start: float | None) -> float:
    """Evidence-only structural risk of one interval, additive score."""
    score = 0.0
    if start is None or end is None:
        return 1.0
    dur = end - start
    if dur <= 0:
        score += 2.0
    elif dur < SHORT_DURATION_S:
        score += 1.0
    elif dur > LONG_DURATION_S:
        score += 0.75
    if prev_end is not None and start < prev_end:
        score += min(1.5, (prev_end - start) * 4.0)
    return _logit(score)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main-run", required=True)
    ap.add_argument("--out", default=None,
                    help="default <main-run>/02_forwards/detector_rows.jsonl")
    args = ap.parse_args()

    run = Path(args.main_run)
    out_path = Path(args.out) if args.out else run / "02_forwards" / "detector_rows.jsonl"
    ev_dir = run / "02_forwards" / "evidence"

    requests = [r for r in _load_jsonl(run / "01_requests" / "REQUESTS.jsonl")
                if r.get("status") is None and r.get("request_id")]
    pool = _load_jsonl(run / "00_population" / "REGION_POOL.jsonl")
    pool_by_key = {(str(p.get("song_id") or ""), str(p.get("region_id") or "")): p for p in pool}

    # region -> family -> {cid: candidate (start, end)} and row presence
    fam_views: dict[tuple[str, str], dict[str, dict[int, tuple[float, float] | None]]] = defaultdict(dict)
    for req in requests:
        key = (str(req.get("song_id") or ""), str(req.get("region_id") or ""))
        fam = str(req.get("family") or "?")
        fam_views[key][fam] = {}
        cand = ev_dir / f"{req['request_id']}.candidate.jsonl"
        if not cand.exists():
            continue
        for row in _load_jsonl(cand):
            cid = int(row["canonical_unit_id"])
            fam_views[key][fam][cid] = (float(row["start_sec"]), float(row["end_sec"]))

    rows: list[dict] = []
    n_target = 0
    n_multiview = 0
    for req in requests:
        key = (str(req.get("song_id") or ""), str(req.get("region_id") or ""))
        fam = str(req.get("family") or "?")
        region = pool_by_key.get(key)
        units = (region or {}).get("units") or ()
        units_by_id = {int(u.get("canonical_unit_id")): u for u in units}
        targets = [int(x) for x in (req.get("target_unit_ids") or [])]
        base_f = ev_dir / f"{req['request_id']}.baseline.jsonl"
        baseline = {int(r["canonical_unit_id"]): (float(r["start_sec"]), float(r["end_sec"]))
                    for r in _load_jsonl(base_f)}
        ordered_ids = sorted(baseline)
        for cid in targets:
            n_target += 1
            base_t = baseline.get(cid)
            # baseline structural risk from neighbors in this request's window
            idx = ordered_ids.index(cid) if cid in ordered_ids else None
            prev_end = None if idx is None or idx == 0 else baseline.get(ordered_ids[idx - 1], (None, None))[1]
            next_start = None if idx is None or idx == len(ordered_ids) - 1 else baseline.get(ordered_ids[idx + 1], (None, None))[0]
            p_before = _struct_risk(*(base_t or (None, None)), prev_end, next_start)

            # candidate views of this unit across families
            views: list[tuple[float, float]] = []
            missing = 0
            for f, vt in fam_views[key].items():
                if cid in vt:
                    if vt[cid] is not None:
                        views.append(vt[cid])
                else:
                    missing += 1
            n_views = len(views)
            if n_views >= 2:
                n_multiview += 1
            starts = [v[0] for v in views]
            span_ms = (max(starts) - min(starts)) * 1000.0 if len(starts) >= 2 else 0.0
            total_fams = len(fam_views.get(key, {}))
            missing_penalty = (missing / total_fams) if total_fams else 0.0
            c_struct = min(_struct_risk(*v, None, None) for v in views) if views else 1.0
            spread_norm = min(1.0, span_ms / (SPREAD_500MS_SATURATION * 1000.0))
            p_after_score = (1.0 * c_struct + 1.0 * spread_norm + 1.5 * missing_penalty)
            p_after = _logit(p_after_score)

            ts_delta_ms = None
            rel_ms = None
            if base_t is not None:
                base_center = (base_t[0] + base_t[1]) / 2.0
                rel_ms = round(base_center * 1000.0, 3)
                if views:
                    c_center = sum(v[0] + v[1] for v in views) / (2.0 * len(views))
                    ts_delta_ms = round((c_center - base_center) * 1000.0, 3)

            rows.append({
                "schema": SCHEMA, "request_id": req["request_id"],
                "song_id": req.get("song_id"), "region_id": req.get("region_id"),
                "family": fam, "unit_id": cid, "row_index": len(rows),
                "p_bad_before": round(p_before, 6), "p_bad_after": round(p_after, 6),
                "signed_detector_delta": round(p_after - p_before, 6),
                "relative_timestamp_ms": rel_ms, "timestamp_delta_ms": ts_delta_ms,
                "n_views": n_views, "missing_views": missing,
                "span_ms": round(span_ms, 3),
                "detector_identity": IDENTITY,
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({
        "schema": SCHEMA, "identity": IDENTITY,
        "n_requests": len(requests), "n_target_rows": len(rows),
        "n_multiview_targets": n_multiview,
        "p_bad_before_mean": round(sum(r["p_bad_before"] for r in rows) / len(rows), 4) if rows else None,
        "p_bad_after_mean": round(sum(r["p_bad_after"] for r in rows) / len(rows), 4) if rows else None,
        "delta_negative_frac": round(sum(1 for r in rows if r["signed_detector_delta"] < 0) / len(rows), 4) if rows else None,
        "out": str(out_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
