#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where does the product's zero-length damage sit?  Context profile of degenerate units.

    PYTHONPATH=src python scripts/evaluation/run_zero_length_profile.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import raw_degeneracy_forensics as RDF
from lyricalign.analysis import structural_compliance as SC

RDF_ZERO_COL = "flag_zero_or_negative"

RUNS = Path("/home/hyan/Data/lyricalign/runs")
OUT = RUNS / "20260912_zero_length_profile"
BATCH = RUNS / "20260814_ktv_current_silence"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--batch", type=Path, default=BATCH)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    units, _meta = SC.load_batch(args.batch, stage="selected")
    flagged = SC.flag_violations(units)
    res: dict[str, Any] = {"schema": "zero_length_profile_v1", "batch": str(args.batch),
                           "stages": {}}
    for stage in ("selected", "fixed", "raw"):
        try:
            frame, _ = SC.load_batch(args.batch, stage=stage)
        except Exception as exc:                                     # noqa: BLE001
            res["stages"][stage] = {"available": False, "reason": str(exc)}
            continue
        if frame.empty:
            res["stages"][stage] = {"available": False, "reason": "empty"}
            continue
        fl = SC.flag_violations(frame)
        prof = RDF.zero_length_profile(fl)
        prof["runs"] = RDF.zero_runs(fl)
        per_lang = {}
        for lang, g in frame.assign(_z=fl["flag_zero_or_negative"].to_numpy()).groupby(
                "language", observed=True):
            per_lang[str(lang)] = {"units": int(len(g)), "zero_share": round(float(g["_z"].mean()), 4)}
        prof["by_language"] = per_lang
        per_song_zero = (fl.assign(_z=fl["flag_zero_or_negative"].to_numpy())
                         .groupby(["song", "language"], observed=True)["_z"]
                         .agg(units="size", zero_share="mean").reset_index())
        prof["per_song"] = {
            "songs": int(len(per_song_zero)),
            "songs_over_30pct_zero": int((per_song_zero["zero_share"] > 0.30).sum()),
            "songs_over_50pct_zero": int((per_song_zero["zero_share"] > 0.50).sum()),
            "worst": [{"song": str(r["song"]), "language": str(r["language"]),
                       "units": int(r["units"]), "zero_share": round(float(r["zero_share"]), 4)}
                      for _, r in per_song_zero.sort_values("zero_share", ascending=False).head(6)
                      .iterrows()],
            "best": [{"song": str(r["song"]), "language": str(r["language"]),
                      "units": int(r["units"]), "zero_share": round(float(r["zero_share"]), 4)}
                     for _, r in per_song_zero.sort_values("zero_share").head(4).iterrows()]}
        # non-circular: song-level lyric density vs that song's zero-length share
        cf = RDF.context_features(fl)
        per_song = cf.groupby("song", observed=True).agg(
            density=("song_density_chars_per_sec", "median"),
            zero_share=(RDF_ZERO_COL, "mean"), units=("unit_index", "size"))
        per_song = per_song[per_song["units"] >= 50]
        if len(per_song) >= 6:
            rho = per_song["density"].corr(per_song["zero_share"], method="spearman")
            prof["song_density_vs_zero_share"] = {
                "songs": int(len(per_song)), "spearman_rho": round(float(rho), 4),
                "density_tercile_zero_share": [
                    {"tercile": int(k), "songs": int(len(g)),
                     "median_density": round(float(g["density"].median()), 3),
                     "median_zero_share": round(float(g["zero_share"].median()), 4)}
                    for k, g in per_song.assign(_t=pd.qcut(per_song["density"], 3, labels=False,
                                                           duplicates="drop"))
                    .groupby("_t", observed=True)]}
        res["stages"][stage] = prof
    (args.out_dir / "ZERO_LENGTH_PROFILE.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for stage, blk in res["stages"].items():
        if not blk.get("available", True) or "by_context" not in blk:
            print(f"== {stage}: {blk.get('reason')}")
            continue
        print(f"\n== {stage}: units={blk['units']:,} zero={blk['zero_units']:,} "
              f"({100 * blk['zero_share']:.2f}%) ==")
        print("   by language: " + ", ".join(f"{k} {100 * v['zero_share']:.1f}%"
                                             for k, v in blk["by_language"].items()))
        for c, v in blk["by_context"].items():
            print(f"   {c:22s} zero_median={v['zero_median']} other_median={v['other_median']}")
        print("   local-window density quintiles (CIRCULAR: only shows co-location): " + ", ".join(
            f"Q{x['quintile']} {100 * x['zero_share']:.1f}%" for x in blk["by_density_quintile"]))
        print("   zero runs: " + json.dumps({k: v for k, v in blk.get("runs", {}).items()
                                             if k != "longest_runs"}, ensure_ascii=False))
        print("   position quartiles: " + ", ".join(
            f"Q{x['quartile']} {100 * x['zero_share']:.1f}%" for x in blk["by_position_quartile"]))
        print("   edges: " + json.dumps(blk["edge_effects"], ensure_ascii=False))
        print("   context AUC: " + json.dumps(blk["auc_context_predicts_zero"], ensure_ascii=False))
        ps = blk.get("per_song")
        if ps:
            print(f"   per song: {ps['songs']} songs, >30% zero = {ps['songs_over_30pct_zero']}, "
                  f">50% zero = {ps['songs_over_50pct_zero']}; worst="
                  + ", ".join(f"{x['song'][:12]}({x['language'][:3]}) {100 * x['zero_share']:.0f}%"
                              for x in ps["worst"][:4]))
        sd = blk.get("song_density_vs_zero_share")
        if sd:
            print(f"   song-level density vs zero share: rho={sd['spearman_rho']} over {sd['songs']} songs; "
                  + ", ".join(f"T{x['tercile']} density {x['median_density']} -> zero {100 * x['median_zero_share']:.1f}%"
                              for x in sd["density_tercile_zero_share"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
