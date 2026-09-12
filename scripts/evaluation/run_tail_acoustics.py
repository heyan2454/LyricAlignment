#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Energy-decay tail anchoring: derive on GTSinger (human GT), transfer frozen to MIR-1K.

    PYTHONPATH=src python scripts/evaluation/run_tail_acoustics.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gtsinger_gt_deep as GG
from lyricalign.analysis import tail_acoustics as T

MIR_VOCAL = Path("/home/hyan/Data/lyricalign/derived/20260722_mir1k_vocal_channel1_ood/vocal_wavs")
MIR_PANEL = Path("/home/hyan/Data/lyricalign/runs/20260912_mir1k_natural_panel/panel.csv.gz")
OUT = Path("/home/hyan/Data/lyricalign/runs/20260912_tail_acoustics")


def gtsinger_rows() -> pd.DataFrame:
    df = GG.load_panel(Path("/home/hyan/Data/lyricalign/runs/20260912_gtsinger_gt_deep"
                            "/unit_evidence.jsonl.gz"))
    d = df[(df["pipeline"] == "official") & (df["model"] == "r2")
           & (df["audio_input"] == "vocal") & (df["mode"] == "windowed")].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec", "audio_path"])
    return pd.DataFrame({"item": d["item"].astype(str), "audio_path": d["audio_path"].astype(str),
                         "pred_start_sec": d["pred_start_sec"].to_numpy(dtype=float),
                         "pred_end_sec": d["pred_end_sec"].to_numpy(dtype=float),
                         "gt_start_sec": d["gt_start_sec"].to_numpy(dtype=float),
                         "gt_end_sec": d["gt_end_sec"].to_numpy(dtype=float),
                         "gt_dur_sec": d["gt_dur_sec"].to_numpy(dtype=float),
                         "is_last": d["unit_index"].to_numpy(dtype=float)
                         >= d.groupby("item", observed=True)["unit_index"].transform("max").to_numpy()})


def mir_rows() -> pd.DataFrame:
    p = pd.read_json(MIR_PANEL, lines=False) if MIR_PANEL.suffix == ".json" else pd.read_csv(MIR_PANEL)
    p = p[p["predictor"] == "r2_full_20260723"].dropna(
        subset=["pred_start_sec", "pred_end_sec", "gt_start_sec", "gt_end_sec"])
    paths = p["item_id"].astype(str).map(lambda s: str(MIR_VOCAL / f"{s}.wav"))
    keep = np.array([Path(x).exists() for x in paths], dtype=bool)
    return pd.DataFrame({"item": p["item_id"].astype(str).to_numpy()[keep],
                         "audio_path": np.asarray(paths, dtype=object)[keep],
                         "pred_start_sec": p["pred_start_sec"].to_numpy(dtype=float)[keep],
                         "pred_end_sec": p["pred_end_sec"].to_numpy(dtype=float)[keep],
                         "gt_start_sec": p["gt_start_sec"].to_numpy(dtype=float)[keep],
                         "gt_end_sec": p["gt_end_sec"].to_numpy(dtype=float)[keep],
                         "gt_dur_sec": p["gt_dur_sec"].to_numpy(dtype=float)[keep],
                         "is_last": p["is_last_char"].to_numpy(dtype=float)[keep] == 1.0})


def envs_for(rows: pd.DataFrame) -> dict[str, T.Envelope]:
    out: dict[str, T.Envelope] = {}
    for path in sorted(set(rows["audio_path"].astype(str))):
        try:
            out[path] = T.load_envelope(path)
        except Exception as exc:            # unreadable/missing audio -> that unit gets NaN
            print(f"  audio load failed {path}: {exc}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"schema": "tail_acoustics_v1",
                              "discipline": "thresholds derived on GTSinger, applied frozen to MIR-1K "
                                            "(test-only); zero GPU, audio never copied"}
    for name, loader in (("gtsinger_derivation", gtsinger_rows), ("mir1k_transfer", mir_rows)):
        rows = loader()
        rows = rows.sort_values(["item"]).reset_index(drop=True)
        print(f"{name}: units={len(rows)} audio_files={rows['audio_path'].nunique()} "
              f"long_notes>={T.LONG_NOTE_SEC}s={int((rows['gt_dur_sec'] >= T.LONG_NOTE_SEC).sum())} "
              f"last_char={int(rows['is_last'].sum())}")
        ev = envs_for(rows)
        r = T.apply_rules(rows, ev)
        res = T.evaluate(r, name)
        anchors = [c for c in r.columns if c.startswith("anchor_theta")]
        res["anchor_coverage"] = {c: round(float(np.isfinite(r[c]).mean()), 4) for c in anchors}
        result[name] = res
        # per-unit rows are large; keep only a compact error table for the last-char subset
        last = r[r["is_last"] == 1.0]
        if len(last):
            res["last_char_only"] = {c: T.score_ends(last, c) for c in
                                     ["model_end_sec"] + anchors + ["blend_close100", "blend_mean"]}
    stereo = Path("/home/hyan/Data/datasets/mir1k/raw/MIR-1K/UndividedWavfile")
    mir = mir_rows().sort_values(["item"]).reset_index(drop=True)
    if stereo.exists():
        result["mir1k_ratio_family"] = T.evaluate_ratio_family(mir, stereo)
    # choose theta on the derivation set only, then report the frozen transfer
    der = result["gtsinger_derivation"]["rules"]
    cand = {k: v["long_notes"].get("hit100", -1) for k, v in der.items() if k.startswith("anchor_theta")}
    best = max(cand, key=lambda k: cand[k]) if cand else None
    result["derived_theta_rule"] = best
    result["derived_theta_hit100_long_notes"] = cand.get(best)
    if best:
        result["frozen_transfer"] = {
            "rule": best,
            "mir1k_long_notes_hit100_model": result["mir1k_transfer"]["rules"]["model_end_sec"]["long_notes"]["hit100"],
            "mir1k_long_notes_hit100_anchor": result["mir1k_transfer"]["rules"][best]["long_notes"]["hit100"],
            "mir1k_delta_pp_long_notes": result["mir1k_transfer"]["delta_pp_hit100_long_notes_vs_model"][best],
            "mir1k_delta_pp_all": result["mir1k_transfer"]["delta_pp_hit100_vs_model"][best],
        }
    (args.out_dir / "TAIL_ACOUSTICS.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key in ("gtsinger_derivation", "mir1k_transfer"):
        print(f"\n== {key} (units={result[key]['units']}, long={result[key]['long_note_units']}) ==")
        print(f"{'rule':22s} {'all hit50':>9s} {'all hit100':>10s} {'all MAE':>8s} "
              f"{'long hit100':>11s} {'long MAE':>9s} {'Δlong pp':>9s}")
        for c, v in result[key]["rules"].items():
            a, l = v["all_units"], v["long_notes"]
            if a.get("n", 0) == 0:
                continue
            print(f"{c:22s} {a.get('hit50', float('nan')):9.4f} {a.get('hit100', float('nan')):10.4f} "
                  f"{a.get('mae_end_sec', float('nan')):8.4f} {l.get('hit100', float('nan')):11.4f} "
                  f"{l.get('mae_end_sec', float('nan')):9.4f} "
                  f"{result[key]['delta_pp_hit100_long_notes_vs_model'].get(c, float('nan')):+9.2f}")
    print("\nderived rule:", result["derived_theta_rule"], "coverage:",
          json.dumps(result["gtsinger_derivation"]["anchor_coverage"], ensure_ascii=False))
    print("frozen transfer:", json.dumps(result.get("frozen_transfer"), ensure_ascii=False))
    rf = result.get("mir1k_ratio_family")
    if rf:
        print(f"\n== MIR-1K vocal/accompaniment ratio family (test-only, no rho selected) =="
              f"  files={rf['stereo_files_used']}")
        mb = rf["model_baseline"]
        print(f"   model: all hit100={mb['all_units']['hit100']:.4f} "
              f"last hit100={mb['last_char']['hit100']:.4f} (n={mb['last_char']['n']}) "
              f"long hit100={mb['long_notes']['hit100']:.4f}")
        for rho, v in rf["rhos"].items():
            print(f"   rho={rho:>4s} coverage={v['coverage']:.3f} "
                  f"anchor_all={v['anchor_all_units'].get('hit100')} "
                  f"model_same_units={v['model_on_covered_all'].get('hit100')} | "
                  f"anchor_last={v['anchor_last_char'].get('hit100')} (n={v['anchor_last_char'].get('n')}) "
                  f"model_last={v['model_on_covered_last'].get('hit100')}")
    return 0


if __name__ == "__main__":
    from typing import Any
    raise SystemExit(main())
