#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grid stability of the frozen detector_v2 band labels (reads LABELS.jsonl audit errors).

    PYTHONPATH=src python scripts/evaluation/run_detector_label_stability.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import label_noise_ceiling as LN

OUT = Path("/home/hyan/Data/lyricalign/runs/20260912_label_noise_ceiling")
GLOB = "/home/hyan/Data/lyricalign/runs/research_v7_detector_v2/*/LABELS.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(glob.glob(GLOB)):
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                a = d.get("audit") or {}
                se, ee = a.get("start_abs_error_sec"), a.get("end_abs_error_sec")
                if se is None or ee is None:
                    continue
                rows.append((max(abs(float(se)), abs(float(ee))), str(d.get("label"))))
        if not rows:
            files.append({"file": Path(path).parent.name, "available": False})
            continue
        frame = pd.DataFrame(rows, columns=["err", "label"])
        res = LN.detector_label_stability(frame["err"], frame["label"])
        res["file"] = Path(path).parent.name
        # the fragile edge is the safe/grey one; report the actionable split too
        e = frame["err"].to_numpy(dtype=float)
        res["safe_share_at_160ms"] = round(float((e < 0.16).mean()), 4)
        files.append(res)
    out = {"schema": "detector_label_stability_v1", "quantum_sec": 0.08,
           "edges_sec": {"safe_max": 0.10, "unsafe_min": 0.25},
           "source_glob": GLOB, "files": files}
    usable = [f["file"] for f in files
              if f.get("available") and "grey_unsafe_250ms" in f.get("usable_gate_edges", [])]
    out["summary"] = {
        "files_total": len(files),
        "files_250ms_edge_grid_stable": len(usable),
        "all_units_labelled": int(sum(f.get("units", 0) for f in files)),
        "min_agreement": min((f.get("agreement_frozen_vs_recomputed") or 1.0)
                             for f in files if f.get("available")),
        "max_knife_edge_share_100ms": max((f["edges"]["safe_grey_100ms"]["knife_edge_share"])
                                          for f in files if f.get("available")),
        "max_knife_edge_share_250ms": max((f["edges"]["grey_unsafe_250ms"]["knife_edge_share"])
                                          for f in files if f.get("available"))}
    (args.out_dir / "DETECTOR_LABEL_STABILITY.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(files)} LABELS files, {out['summary']['all_units_labelled']:,} labelled units")
    print(f"  frozen-vs-recomputed agreement: min {out['summary']['min_agreement']:.4f}")
    print(f"  knife-edge share within 1 quantum: 100ms edge up to "
          f"{100*out['summary']['max_knife_edge_share_100ms']:.1f}%, "
          f"250ms edge up to {100*out['summary']['max_knife_edge_share_250ms']:.1f}%")
    for f in files:
        if not f.get("available"):
            print(f"  {f['file']:14s} unavailable")
            continue
        e100, e250 = f["edges"]["safe_grey_100ms"], f["edges"]["grey_unsafe_250ms"]
        print(f"  {f['file']:14s} n={f['units']:7,} agree={f['agreement_frozen_vs_recomputed']:.4f} | "
              f"100ms: 刀尖{100*e100['knife_edge_share']:5.1f}% 摆幅{e100['swing_pp_if_edge_moved_one_quantum']:5.1f}pp ({e100['verdict']}) | "
              f"250ms: 刀尖{100*e250['knife_edge_share']:4.1f}% 摆幅{e250['swing_pp_if_edge_moved_one_quantum']:4.1f}pp ({e250['verdict']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
