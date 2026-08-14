#!/usr/bin/env python3
"""Build mechanism (R-U/R-S/R-CF) regions for non-core songs that lack detector
evidence, using the Current full-song alignment's ANOMALY units (zero-duration
or adjacent-overlap chars) as detector-unsafe targets.

Region per contiguous anomaly run: units = anomaly span + context neighbors,
targets = the anomaly chars (clamped to <=3 contiguous for R-CF stage-A).
audio = the alignment's own mix/vocals wav.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/build_noncore_mech_regions.py \
     --songs "song:lang:currentalign:audio" ... --identity-template <E1 manifest> \
     --out <regions.jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", action="append", default=[])
    ap.add_argument("--identity-template", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
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
        for i, run in enumerate(runs):
            lo, hi = min(run), max(run)
            ctx = [c for c in chars if lo - 3 <= int(c["global_character_index"]) <= hi + 3]
            # targets: anomaly chars, but clamp to <=3 contiguous from the middle
            targets = run[:]  # may be up to ~few
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
