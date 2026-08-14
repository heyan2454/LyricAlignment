#!/usr/bin/env python3
"""Build mechanism (R-U/R-S/R-CF) regions for non-core songs that lack detector
evidence, using the Current full-song alignment's ANOMALY units (zero-duration
or adjacent-overlap chars) as detector-unsafe targets.

Region per contiguous anomaly run: units = anomaly span + context neighbors,
targets = the anomaly chars (clamped to <=3 contiguous for R-CF stage-A).
audio = the alignment's own mix/vocals wav.

Context is **silence-aware**: units whose time gap to a neighbour exceeds
``--context-gap-sec`` (default = the frozen baseline strong_silence_anchor_sec,
i.e. 1.5 s, shared with Current/B4 window planning) are not carried across the
gap, so acoustically separated segments never share a region.  Pass
``--context-gap-sec 0`` to keep the legacy pure-id behaviour.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_noncore_mech_regions.py \
     --songs "song:lang:currentalign:audio" ... --identity-template <E1 manifest> \
     --out <regions.jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from region_silence import context_units_silence_aware, split_into_time_clusters  # noqa: E402

# Frozen silence boundary semantics shared with Current/B4 (build_resolved_baseline).
DEFAULT_GAP_SEC = 1.5  # == WINDOW_SILENCE_RESOLVED["strong_silence_anchor_sec"]


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[])
    ap.add_argument("--identity-template", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--context-gap-sec", type=float, default=DEFAULT_GAP_SEC,
                    help="max time gap (s) between neighbouring units allowed inside one "
                         "region's context; 0 disables (legacy pure-id context). "
                         f"default {DEFAULT_GAP_SEC} (= strong_silence_anchor_sec)")
    args = ap.parse_args()

    ident = json.loads(args.identity_template.read_text(
        encoding="utf-8").splitlines()[0]).get("identity_context") or {}

    rows = []
    for spec in args.songs:
        lang, name, align_path, audio = spec.split("=")
        d = json.loads(Path(align_path).read_text(encoding="utf-8"))
        chars = sorted(
            [c for c in d["characters"] if (c.get("selected_start_sec") or c.get("start_sec")) is not None],
            key=lambda c: (c.get("selected_start_sec") or c.get("start_sec")),
        )
        byidx = {int(c["global_character_index"]): c for c in chars}
        # anomaly chars
        anom = [c for c in chars
                if ((c.get("selected_end_sec") or c.get("end_sec"))
                    - (c.get("selected_start_sec") or c.get("start_sec"))) <= 1e-6]
        # contiguous runs (by index) -> one region per run
        anom_ids = sorted(int(c["global_character_index"]) for c in anom)
        runs = []
        for cid in anom_ids:
            if runs and cid == runs[-1][-1] + 1:
                runs[-1].append(cid)
            else:
                runs.append([cid])
        sha = hashlib.sha256(Path(audio).read_bytes()).hexdigest()
        idctx = dict(ident); idctx["audio_sha256"] = sha
        idctx["context_gap_sec"] = args.context_gap_sec
        for i, run in enumerate(runs):
            # Silence-aware: an id-contiguous run may still span a long unvoiced
            # interval (e.g. 月半 a16: id236@119.8s vs id237@151.3s, gap ~31s).
            # Split the run into time clusters and emit one region per cluster.
            run_units = [byidx[cid] for cid in run]
            clusters = split_into_time_clusters(run_units, args.context_gap_sec)
            for ci, cluster in enumerate(clusters):
                cids = [int(c["global_character_index"]) for c in cluster]
                lo, hi = min(cids), max(cids)
                # context = silence-aware neighbours of this cluster
                ctx = context_units_silence_aware(
                    chars, cids, args.context_gap_sec, context_neighbors=3)
                # targets: anomaly chars of this cluster, clamped to <=3 contiguous
                targets = cids[:]
                if len(targets) > 3:
                    mid = len(targets) // 2
                    targets = targets[max(0, mid - 1): mid + 2]
                units = [{
                    "canonical_unit_id": int(c["global_character_index"]),
                    "start_sec": c.get("selected_start_sec") or c.get("start_sec"),
                    "end_sec": c.get("selected_end_sec") or c.get("end_sec"),
                    "text": c.get("display_text"),
                } for c in ctx]
                if len(units) <= len(targets):
                    continue
                rows.append({
                    "region_id": f"noncore-{lang}-{name.replace(' ','_')}-a{i}",
                    "song_id": f"{lang}/{name}.mp3",
                    "window_index": i,
                    "language": d.get("summary", {}).get("language"),
                    "detector_state": "UNSAFE",
                    "seed_kind": "anomaly_region",
                    "baseline_available": True,
                    "target_unit_ids": targets,
                    "audio_path": audio,
                    "units": units,
                    "identity_context": idctx,
                })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} anomaly-based regions -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
