#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview the batch audit *after* the recommended change, without touching the product path.

Reads each song's stored rows, rebuilds the timeline under a chosen fixed-timestamp policy offline,
and evaluates both the shipped and the shadow timeline with the same structural checks the batch audit
uses.  The result is what the mainline should expect to see in `audit_batch.py` once the flag is on,
plus the exact per-check delta.

    PYTHONPATH=src python scripts/evaluation/run_shadow_batch_audit.py [--policy raw_with_targeted_repair]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import monotone_repair as MR
from lyricalign.analysis import structural_compliance as SC

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_shadow_batch_audit"
BATCH = RUNS / "20260814_ktv_current_silence"
ALIGN_RELPATH = Path("alignments/r2/vocal/windowed/alignment.json")


def load_rows(batch: Path) -> pd.DataFrame:
    frames = []
    for song_dir in sorted(p for p in batch.iterdir() if p.is_dir()):
        path = song_dir / ALIGN_RELPATH
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("characters") or []
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        frame["song"] = song_dir.name
        # the per-row language is not stored; the bundle's audit block carries it
        lang = (payload.get("audit") or {}).get("language")
        if lang is None and "language" not in frame.columns:
            frame["language"] = song_dir.name  # fall back to the song id so grouping still works
        elif lang is not None:
            frame["language"] = lang
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def timeline(rows: pd.DataFrame, *, policy: str) -> pd.DataFrame:
    """Rebuild per-song start/end under the chosen policy, per window (as the writer does)."""
    parts = []
    for (song, window), sub in rows.groupby(["song", "window_index"], observed=True, dropna=False):
        sub = sub.sort_values("global_character_index")
        offset = float(sub["raw_global_start_sec"].iloc[0]) - float(sub["raw_local_start_sec"].iloc[0])
        res = MR.apply_fixed_timestamp_policy(
            sub["raw_local_start_sec"].to_numpy(dtype=float),
            sub["raw_local_end_sec"].to_numpy(dtype=float),
            sub["official_fixed_local_start_sec"].to_numpy(dtype=float),
            sub["official_fixed_local_end_sec"].to_numpy(dtype=float),
            policy=policy,
            duration=float(np.nanmax(sub["raw_local_end_sec"].to_numpy(dtype=float))) + 1.0)
        parts.append(pd.DataFrame({
            "song": sub["song"].to_numpy(),
            "language": sub["language"].to_numpy() if "language" in sub.columns else "unknown",
            "unit_index": np.arange(len(sub)),
            "start_sec": res["starts"] + offset,
            "end_sec": res["ends"] + offset,
            "ent_end": pd.to_numeric(sub.get("raw_end_entropy"), errors="coerce").to_numpy()
            if "raw_end_entropy" in sub.columns else np.nan,
        }))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def checks(frame: pd.DataFrame) -> dict:
    flagged = SC.flag_violations(frame)
    blocks = SC.identical_start_blocks(flagged)
    proj = SC.gate_projection(flagged.rename(columns={"ent_end": "ent_end"})) \
        if "ent_end" in flagged.columns else {"available": False}
    out = {
        "units": int(len(flagged)),
        "zero_share": round(float(flagged["flag_zero_or_negative"].mean()), 4),
        "illegal_share": round(float(flagged["is_illegal"].mean()), 4),
        "overlap_share": round(float(flagged["flag_overlaps_next"].mean()), 4),
        "overshoot_share": round(float(flagged["flag_overshoot"].mean()), 4),
        "regression_share": round(float(flagged["flag_start_regression"].mean()), 4),
        "collapse_blocks": blocks,
        "by_language_zero_share": {
            str(k): round(float(g["flag_zero_or_negative"].mean()), 4)
            for k, g in flagged.groupby("language", observed=True)},
    }
    if proj.get("available"):
        out["gate_projection"] = {
            "accept_share": proj["accept_share"],
            "residual_illegal_in_accepted": proj["illegal_in_accepted_share"],
            "illegal_captured_by_review": proj["illegal_capture_of_all_illegal"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    ap.add_argument("--policy", default="raw_with_targeted_repair",
                    choices=MR.FIXED_POLICIES)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.batch)
    if rows.empty:
        print("no rows found")
        return 1
    shipped = timeline(rows, policy="upstream_repaired")
    shadow = timeline(rows, policy=args.policy)
    res = {"schema": "shadow_batch_audit_v1", "batch": str(args.batch), "rows": int(len(rows)),
           "policy": args.policy, "policy_measured": args.policy in MR.MEASURED_POLICIES,
           "shipped": checks(shipped), "shadow": checks(shadow)}
    s, h = res["shipped"], res["shadow"]
    res["delta_pp"] = {k: round(100 * (h[k] - s[k]), 2)
                       for k in ("zero_share", "illegal_share", "overlap_share",
                                 "overshoot_share", "regression_share")}
    (args.out_dir / "SHADOW_BATCH_AUDIT.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rows={res['rows']:,} policy={args.policy} (measured={res['policy_measured']})")
    for name in ("shipped", "shadow"):
        v = res[name]
        print(f"   {name:8s} zero={100 * v['zero_share']:6.2f}% illegal={100 * v['illegal_share']:6.2f}% "
              f"overlap={100 * v['overlap_share']:5.2f}% regression={100 * v['regression_share']:5.2f}% "
              f"collapse_blocks={v['collapse_blocks']['blocks']}")
    print("   delta_pp: " + json.dumps(res["delta_pp"], ensure_ascii=False))
    print("   by language zero (shipped -> shadow): " + ", ".join(
        f"{k} {100 * v:.1f}%→{100 * h['by_language_zero_share'].get(k, float('nan')):.1f}%"
        for k, v in s["by_language_zero_share"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
