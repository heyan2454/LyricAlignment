#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the label-free cross-window selection experiment on the long-form panel.

    PYTHONPATH=src python scripts/evaluation/run_cross_window_selection.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import cross_window_selection as X


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=X.PANEL.parent)
    args = ap.parse_args()
    d, info = X.load_attempts()
    d = X.add_features(d)
    res = X.run_selectors(d)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "CROSS_WINDOW_SELECTION.json").write_text(
        json.dumps({"panel": info, **res}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gap = res["gap_closed_vs_oracle"]
    print(json.dumps({"units": info["units"], "rows": info["rows"],
                      "headroom_pp": res["reference_headroom"]["headroom_pp"],
                      "single_window_penalty_pp": abs(gap["A_first_attempt"]["delta_pp_vs_median_attempt"]),
                      "best_selector": max((k for k in gap if k.startswith(("C_", "D_", "E_", "F_", "G_", "H_"))),
                                           key=lambda k: gap[k]["hit100"]),
                      "best_gain_pp": max(gap[k]["delta_pp_vs_median_attempt"]
                                          for k in gap if k.startswith(("C_", "D_", "E_", "F_", "G_", "H_")))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
