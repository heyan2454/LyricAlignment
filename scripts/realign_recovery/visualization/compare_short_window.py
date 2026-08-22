#!/usr/bin/env python3
"""Compare short-window (line/cluster) vs C1/Current vs B4 on the 3 Chinese
songs: MAE, overlap (stacked-word) counts, coverage, and per-song summary.

Usage:
  PYTHONPATH=src python scripts/realign_recovery/visualization/compare_short_window.py \
      --songs 祈愿花开,人造卫星,本草纲目 \
      --b4-root <dir with <song>/alignments/r2/vocal/windowed/alignment.json> \
      --c1-root <dir> --short-root <dir> [--short-root2 <dir>] --out <summary.json>
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load(p: Path, geom: str = "selected") -> dict[int, dict]:
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    out = {}
    for c in d.get("characters", []):
        g = int(c["global_character_index"])
        if geom == "raw":
            s = float(c.get("raw_global_start_sec") or c.get("start_sec") or 0.0)
            e = float(c.get("raw_global_end_sec") or c.get("end_sec") or s)
        elif geom == "official":
            s = float(c.get("official_fixed_global_start_sec")
                      if c.get("official_fixed_global_start_sec") is not None
                      else c.get("selected_start_sec") or c.get("start_sec") or 0.0)
            e = float(c.get("official_fixed_global_end_sec")
                      if c.get("official_fixed_global_end_sec") is not None
                      else c.get("selected_end_sec") or c.get("end_sec") or s)
        else:  # selected
            s = float(c.get("selected_start_sec") or c.get("start_sec") or 0.0)
            e = float(c.get("selected_end_sec") or c.get("end_sec") or s)
        out[g] = {"s": s, "e": e,
                  "text": c.get("display_text") or c.get("character") or "",
                  "line": int(c.get("line_index", 0)),
                  "idx": int(c.get("index_in_line", 0))}
    return out


def mae(a: dict, b: dict) -> tuple[float, int]:
    d = [abs(a[k]["s"] - b[k]["s"]) for k in a if k in b]
    return (sum(d) / len(d), len(d)) if d else (float("nan"), 0)


def overlap_count(a: dict) -> int:
    """Count adjacent-in-id characters whose spans overlap by >50% AND whose
    start is not reversed (a later id landing before an earlier id is an
    occurrence-selection artifact, not a stacked render)."""
    ks = sorted(a)
    n = 0
    for i in range(1, len(ks)):
        p, c = ks[i - 1], ks[i]
        s0, e0 = a[p]["s"], a[p]["e"]
        s1, e1 = a[c]["s"], a[c]["e"]
        if s1 < e0 and s1 >= s0 and (e0 - s1) / max(e1 - s0, 1e-9) > 0.5:
            n += 1
    return n


def dur_stats(a: dict) -> dict:
    durs = [v["e"] - v["s"] for v in a.values()]
    return {"mean": round(statistics.mean(durs), 3),
            "max": round(max(durs), 3),
            "p90": round(sorted(durs)[int(len(durs) * 0.9)], 3) if durs else 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", required=True, help="comma list")
    ap.add_argument("--b4-root", required=True, type=Path)
    ap.add_argument("--c1-root", required=True, type=Path)
    ap.add_argument("--short-root", required=True, type=Path)
    ap.add_argument("--short2-root", type=Path, default=None)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--geom", choices=("selected", "official", "raw"), default="selected",
                    help="geometry for ALL lanes (Codex 20260812: Raw is main output view)")
    args = ap.parse_args()

    result = {"schema": "short_window_comparison_v1", "geom": args.geom, "songs": {}}
    for song in args.songs.split(","):
        b4 = load(args.b4_root / song / "alignments/r2/vocal/windowed/alignment.json", args.geom)
        c1 = load(args.c1_root / song / "alignments/r2/vocal/windowed/alignment.json", args.geom)
        short = load(args.short_root / song / "alignments/r2/vocal/windowed/alignment.json", args.geom)
        short2 = load(args.short2_root / song / "alignments/r2/vocal/windowed/alignment.json", args.geom) \
            if args.short2_root else None
        entry = {
            "n_chars": len(b4),
            "mae_c1_vs_b4": round(mae(c1, b4)[0], 3),
            "mae_short_vs_b4": round(mae(short, b4)[0], 3),
            "mae_short_vs_c1": round(mae(short, c1)[0], 3),
            "overlap_b4": overlap_count(b4),
            "overlap_c1": overlap_count(c1),
            "overlap_short": overlap_count(short),
            "dur_b4": dur_stats(b4),
            "dur_c1": dur_stats(c1),
            "dur_short": dur_stats(short),
            "coverage_short": round(len(short) / max(len(b4), 1), 4),
        }
        if short2:
            entry["mae_short2_vs_b4"] = round(mae(short2, b4)[0], 3)
            entry["mae_short2_vs_short"] = round(mae(short2, short)[0], 3)
            entry["overlap_short2"] = overlap_count(short2)
            entry["dur_short2"] = dur_stats(short2)
            entry["coverage_short2"] = round(len(short2) / max(len(b4), 1), 4)
        result["songs"][song] = entry
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
