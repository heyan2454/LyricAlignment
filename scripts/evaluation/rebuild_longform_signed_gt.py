#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild and verify the signed per-unit ground truth for the long-form panel.

    PYTHONPATH=src python scripts/evaluation/rebuild_longform_signed_gt.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import longform_signed_gt as G
from lyricalign.analysis import m4_longform_weakgt as L


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=G.PANEL.parent)
    args = ap.parse_args()
    gt, stats = G.build_unit_gt()
    panel = L.load_frame(G.PANEL)
    ver = G.verify_against_frozen_errors(gt, panel)
    stats["verification"] = ver
    args.out_dir.mkdir(parents=True, exist_ok=True)
    gt.to_pickle(args.out_dir / "signed_gt.pkl")
    (args.out_dir / "SIGNED_GT_STATS.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = (ver["raw"]["max_deviation_sec"] == 0.0
          and ver["official"]["max_deviation_sec"] == 0.0)
    print(json.dumps({"units": int(len(gt)), "merged_rows": ver["merged_rows"],
                      "verification_exact": ok,
                      "fabricated_axis_within_100ms": ver["fabricated_axis_contrast"]["share_within_100ms_panel_gt"],
                      "rebuilt_within_100ms": ver["fabricated_axis_contrast"]["share_within_100ms_rebuilt"]},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
