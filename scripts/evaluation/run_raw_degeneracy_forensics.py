#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where do raw-stage negative intervals come from, and do they predict the fixed-stage collapse?

    PYTHONPATH=src python scripts/evaluation/run_raw_degeneracy_forensics.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import raw_degeneracy_forensics as F

OUT = Path("/home/hyan/Data/lyricalign/runs/20260912_raw_degeneracy")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path,
                    default=Path("/home/hyan/Data/lyricalign/runs/20260814_ktv_current_silence"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    df = F.load_all_stages(args.batch)
    if df.empty:
        print(json.dumps({"available": False, "batch": str(args.batch)}))
        return 1
    res = {"schema": "raw_degeneracy_forensics_v1", "batch": str(args.batch),
           "profile": F.profile(df), "predicts_collapse": F.predicts_collapse(df),
           "examples": F.top_examples(df)}
    (args.out_dir / "RAW_DEGENERACY.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    p, c = res["profile"], res["predicts_collapse"]
    print(f"batch {args.batch.name}: units={p['units']:,} songs={p['songs']} "
          f"raw negative={p['raw_negative_units']:,} ({100*p['raw_negative_share']:.2f}%) "
          f"raw zero={p['raw_zero_units']:,}")
    print("\nby language:")
    for k, v in sorted(p["by_language"].items(), key=lambda kv: -kv[1]["share"]):
        print(f"   {k:10s} units={v['units']:6,} neg={v['negative']:5,} share={100*v['share']:5.2f}% "
              f"median|mag|={v['median_magnitude_sec']}s worst={v['worst_sec']}s "
              f"songs={v['songs_affected']} pinned_share={v['pinned_share']}")
    print("\nby unit_type:", json.dumps(p["by_unit_type"], ensure_ascii=False))
    print("by inference_source:", json.dumps(p["by_inference_source"], ensure_ascii=False))
    print("\nmagnitude:", json.dumps(p.get("magnitude"), ensure_ascii=False))
    print("by window position:", json.dumps(p.get("negative_by_window_position"), ensure_ascii=False))
    print("\nposteriors:")
    for col, v in (p.get("posteriors") or {}).items():
        n_, c_ = v.get("raw_negative"), v.get("clean")
        print(f"   {col:7s} negative={n_} clean={c_}")
    print("\ncollapse prediction:", json.dumps(c, ensure_ascii=False, indent=1)[:900])
    print("\nexamples (largest reversals):")
    for r in res["examples"][:6]:
        print(f"   {r['song'][:14]:14s} {r['language'][:9]:9s} i={r['unit_index']:4d} raw={r['raw']} "
              f"dur={r['raw_dur_sec']}s sel={r['sel']} pinned={r['pinned']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
