#!/usr/bin/env python3
"""Build 'real' E7 serial episodes from E1 multi-realign trajectories.

E1 CHAIN_RUNS holds per-region per-iteration candidate vs baseline rows.  We
interpret each multi-realign iteration as one serial 'window': the target error
for that window = max |candidate_start - baseline_start| over the region's
target units.  This yields episodes whose injected_cursor_error_ms is the REAL
observed target displacement, not a synthetic value, so E7 downstream-error /
recovery metrics are grounded in actual alignment drift.

recovery_strategy: E1 has no reset, so 'none' (persistent cursor) for the
window that carries the error; later near-zero-error windows use 'none' too.
A region whose error clears across iterations is naturally represented by the
error values themselves.

Usage:
  PYTHONPATH=src python scripts/unit_realign/build_e1_serial_episodes.py \
     --chains <E1>/02_trajectory/CHAIN_RUNS.jsonl \
     --out <SERIAL_EPISODES_IN.jsonl>
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    runs = [json.loads(l) for l in args.chains.read_text(encoding="utf-8").splitlines() if l.strip()]
    # group by region_id
    by_region = defaultdict(list)
    for r in runs:
        rq = r.get("request") or {}
        by_region[str(rq.get("region_id") or r["request_identity"])].append(r)

    episodes = []
    for rid, chains in by_region.items():
        chains.sort(key=lambda c: c.get("iteration") or 0)
        # baseline = first chain's baseline_rows (frozen detector baseline)
        base = chains[0].get("baseline_rows") or []
        base_by = {int(b.get("canonical_unit_id")): b for b in base}
        # target units: any id in request's active_target / or use changed in candidates
        windows = []
        for c in chains:
            cand = c.get("candidate_rows") or []
            # target error: for each baseline unit whose candidate differs, the diff
            cand_by = {int(x.get("canonical_unit_id")): x for x in cand}
            errs = []
            all_ids = set(base_by) | set(cand_by)
            for cid in all_ids:
                bs = (base_by.get(cid) or {}).get("start_sec")
                cs = (cand_by.get(cid) or {}).get("start_sec")
                if bs is None or cs is None:
                    continue
                errs.append(abs(float(cs) - float(bs)) * 1000.0)
            err = max(errs) if errs else 0.0
            windows.append({
                "window_id": int(c.get("iteration") or 0),
                "target_unit_ids": sorted(int(x) for x in all_ids)[:8],
                "injected_cursor_error_ms": round(err, 4),
                "recovery_strategy": "none",
                "is_safe": err <= 0.0,
            })
        episodes.append({"episode_id": rid, "windows": windows})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for e in episodes:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"wrote {len(episodes)} episodes -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
