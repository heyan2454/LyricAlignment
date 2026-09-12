#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prove where the zero-length collapse comes from, by reproducing the shipped values offline.

Chain: the shipped ``fixed_global_*`` timestamps are copied verbatim from the upstream Qwen processor
(`decode_forced_alignment` -> `_fix_timestamps`), so re-running that same function on the recorded
raw timestamps must reproduce the shipped values.  If it does, the collapse is upstream's monotonicity
repair, not our post-processing.

    PYTHONPATH=src python scripts/evaluation/run_fixed_stage_root_cause.py [--songs N]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_fixed_stage_root_cause"
BATCH = RUNS / "20260814_ktv_current_silence"
SEGMENT_SEC = 0.08
ALIGN_RELPATH = Path("alignments/r2/vocal/windowed/alignment.json")


def load_fixer():
    from transformers.models.qwen3_asr.processing_qwen3_asr import _fix_timestamps
    return _fix_timestamps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    ap.add_argument("--songs", type=int, default=6)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    fix_timestamps = load_fixer()
    import transformers

    res: dict = {
        "schema": "fixed_stage_root_cause_v1",
        "claim": "shipped fixed_* timestamps are the upstream processor's _fix_timestamps output, and "
                 "that repair collapses whole outlier blocks onto one constant timestamp",
        "upstream": {
            "module": "transformers.models.qwen3_asr.processing_qwen3_asr",
            "function": "_fix_timestamps",
            "caller": "Qwen3ASRProcessor.decode_forced_alignment",
            "transformers_version": getattr(transformers, "__version__", "unknown"),
            "upstream_reference": "QwenLM/Qwen3-ASR qwen_asr/inference/qwen3_forced_aligner.py L147 (per docstring)",
            "mechanism": "outlier blocks (not in the longest increasing subsequence) are filled: blocks "
                         "of <=2 snap to a neighbour (duplicates), longer blocks interpolate when both "
                         "bounding values exist, but a block touching either end -- or whose two "
                         "bounding good values are equal -- is filled with a single constant, which "
                         "makes every timestamp in the block identical",
        },
        "minimal_reproduction": {},
        "songs": [],
    }
    # 1) minimal reproduction of the constant-fill fallback
    decreasing_tail = np.array([0.0, 50, 40, 30, 20, 10, 0.0])
    distinct_middle = np.array([0.0, 80, 160, 240] + [240 - 10 * i for i in range(1, 21)] + [400, 480],
                               dtype=float)
    out_tail = [int(v) for v in fix_timestamps(decreasing_tail)]
    out_mid = [int(v) for v in fix_timestamps(distinct_middle)]
    res["minimal_reproduction"] = {
        "decreasing_tail_input": [int(v) for v in decreasing_tail],
        "decreasing_tail_output": out_tail,
        "decreasing_tail_distinct_before_after": [len(set(map(int, decreasing_tail))), len(set(out_tail))],
        "bounded_block_input_distinct": len(set(map(int, distinct_middle))),
        "bounded_block_output_distinct": len(set(out_mid)),
        "bounded_block_stays_distinct": len(set(out_mid)) >= len(set(map(int, distinct_middle))),
    }
    # 2) real songs: does the upstream function reproduce the shipped values, and does it add collapses?
    songs = [d for d in sorted(p for p in args.batch.iterdir() if p.is_dir())
             if (d / ALIGN_RELPATH).exists()]
    # keep the worst offenders first (round 43 profile) but stay bounded
    priority = ["初音未来的消失", "I See Fire", "画下灯塔水母", "冬之花"]
    ordered = [d for name in priority for d in songs if d.name == name] + \
              [d for d in songs if d.name not in priority]
    for d in ordered[: args.songs]:
        rows = json.load(open(d / ALIGN_RELPATH))["characters"]
        by_win: dict = defaultdict(list)
        for r in rows:
            by_win[r.get("window_index")].append(r)
        slots = matched = 0
        zero_raw = zero_fixed = 0
        windows: list[dict] = []
        for w, rs in sorted(by_win.items(), key=lambda kv: (kv[0] is None, kv[0])):
            rs = sorted(rs, key=lambda r: r["global_character_index"])
            raw_ms, fix_ms = [], []
            for r in rs:
                raw_ms += [round(float(r["raw_local_start_sec"]) / SEGMENT_SEC) * 80,
                           round(float(r["raw_local_end_sec"]) / SEGMENT_SEC) * 80]
                fix_ms += [float(r["fixed_local_start_sec"]) * 1000.0,
                           float(r["fixed_local_end_sec"]) * 1000.0]
            pred = fix_timestamps(np.array(raw_ms, dtype=float))
            m = sum(1 for a, b in zip(pred, fix_ms) if abs(float(a) - float(b)) < 1.5)
            zr = sum(1 for r in rs if float(r["raw_local_end_sec"]) - float(r["raw_local_start_sec"]) <= 1e-9)
            zf = sum(1 for r in rs if float(r["fixed_local_end_sec"]) - float(r["fixed_local_start_sec"]) <= 1e-9)
            slots += len(fix_ms)
            matched += m
            zero_raw += zr
            zero_fixed += zf
            windows.append({"window_index": w, "units": len(rs), "slot_match_share": round(m / max(len(fix_ms), 1), 4),
                            "zero_raw": zr, "zero_fixed": zf,
                            "distinct_predicted_values": len(set(map(int, pred)))})
        res["songs"].append({
            "song": d.name, "units": len(rows), "windows": len(by_win),
            "slot_match_share": round(matched / max(slots, 1), 4),
            "zero_length_raw": zero_raw, "zero_length_fixed": zero_fixed,
            "collapse_multiplier": round(zero_fixed / max(zero_raw, 1), 3),
            "worst_window": max(windows, key=lambda w: w["zero_fixed"] - w["zero_raw"]) if windows else None,
            "per_window": windows})
    res["summary"] = {
        "songs": len(res["songs"]),
        "median_slot_match_share": round(float(np.median([s["slot_match_share"] for s in res["songs"]])), 4),
        "total_zero_raw": int(sum(s["zero_length_raw"] for s in res["songs"])),
        "total_zero_fixed": int(sum(s["zero_length_fixed"] for s in res["songs"])),
    }
    (args.out_dir / "FIXED_STAGE_ROOT_CAUSE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mr = res["minimal_reproduction"]
    print("minimal repro: decreasing tail", mr["decreasing_tail_input"], "->", mr["decreasing_tail_output"])
    print(f"  distinct values {mr['decreasing_tail_distinct_before_after'][0]} -> "
          f"{mr['decreasing_tail_distinct_before_after'][1]}; "
          f"bounded block stays distinct: {mr['bounded_block_stays_distinct']}")
    for s in res["songs"]:
        print(f"{s['song'][:16]:16s} units={s['units']:4d} slot_match={100 * s['slot_match_share']:.1f}% "
              f"zero raw->fixed {s['zero_length_raw']} -> {s['zero_length_fixed']} "
              f"(x{s['collapse_multiplier']}) worst_window={s['worst_window']}")
    print("summary: " + json.dumps(res["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
