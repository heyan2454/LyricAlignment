#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replicate the free triggers on M4Singer long-form (independent corpus, weak labels).

Round 27's triggers (boundary entropy, gap residual) were validated on GTSinger studio clips with
human word-level labels.  A trigger that only works there is a dataset artifact, so this replicates on
M4Singer: different singers, different recording conditions, timelines *synthesised* from real
segments, and **rule-validated weak labels** (80 ms quantised) instead of human GT.

Caveats carried into the output: weak labels, quantisation, and the fact that a timeline is stitched
from independent segments (so gap windows are clipped to the segment end).

    PYTHONPATH=src python scripts/evaluation/run_trigger_replication.py [--max-segments 1200]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lyricalign.analysis import gap_shape as GS
from lyricalign.realign_gate.gate_features import roc_auc

RUNS = Path("/home/hyan/Data/lyricalign/runs")
M4_ROOT = Path("/home/hyan/Data/datasets/m4singer/raw/extracted/m4singer")
OUT = RUNS / "20260912_trigger_replication"
GT_QUANTISATION_SEC = 0.08


def segment_path(source_segment_id: str) -> Path | None:
    # "Tenor-1#交换余生#0024" -> <root>/Tenor-1#交换余生/0024.wav
    parts = str(source_segment_id).split("#")
    if len(parts) < 3:
        return None
    singer, song, idx = parts[0], parts[1], parts[-1]
    p = M4_ROOT / f"{singer}#{song}" / f"{idx}.wav"
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--max-segments", type=int, default=1200)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    L = pd.read_json(RUNS / "20260912_m4_longform_weakgt/longform_units.jsonl.gz", lines=True)
    segs = sorted(L["source_segment_id"].astype(str).unique())
    step = max(1, len(segs) // max(args.max_segments, 1))
    chosen = set(segs[::step][:args.max_segments])
    work = L[L["source_segment_id"].astype(str).isin(chosen)].copy()
    rows: list[dict[str, Any]] = []
    files_used = 0
    for seg, sub in work.groupby("source_segment_id", observed=True):
        path = segment_path(seg)
        if path is None:
            continue
        try:
            t, env = GS_env(str(path))
        except Exception:
            continue
        files_used += 1
        offset = float(sub["segment_start_sec"].iloc[0])
        s = sub.sort_values("source_unit_index").reset_index()
        starts = (s["off_start_sec"].to_numpy(dtype=float) - offset)
        ends = (s["off_end_sec"].to_numpy(dtype=float) - offset)
        nxt = np.concatenate([starts[1:], [np.inf]])
        gt_e = (s["gt_end_sec"].to_numpy(dtype=float) - offset)
        gt_s = (s["gt_start_sec"].to_numpy(dtype=float) - offset)
        for i in range(len(s)):
            if not np.isfinite(ends[i]) or not np.isfinite(gt_e[i]):
                continue
            hi = min(ends[i] + GS.LEAD_SEC, float(nxt[i]))
            lo = ends[i] + GS.GUARD_SEC
            if hi - lo < GS.MIN_GAP_SEC - GS.GUARD_SEC:
                continue
            core_lo, core_hi = max(0.0, starts[i]), max(0.0, ends[i])
            cm = (t >= core_lo) & (t <= core_hi)
            core = float(np.sqrt(np.mean(env[cm] ** 2))) if cm.any() else float("nan")
            sh = GS.shape_features(t, env, gap_lo=lo, gap_hi=hi, core_rms=core)
            if not np.isfinite(sh.get("gap_over_core", np.nan)):
                continue
            pred_err = max(abs(starts[i] - gt_s[i]), abs(ends[i] - gt_e[i]))
            rows.append({"segment": str(seg), "split": str(s["split"].iloc[i]),
                         "family": str(s["family"].iloc[i]),
                         "singer": str(s["singer"].iloc[i]),
                         "gt_dur_sec": float(gt_e[i] - gt_s[i]),
                         "gap_over_core": sh["gap_over_core"], "rise_ratio": sh["rise_ratio"],
                         "end_entropy": float(s["end_entropy"].iloc[i]),
                         "end_margin": float(s["end_margin"].iloc[i]),
                         "pred_err_sec": float(pred_err),
                         "truncated": bool((gt_e[i] - ends[i]) > GT_QUANTISATION_SEC + 0.08),
                         "any_error_gt_100ms": bool(pred_err > 0.1)})
    d = pd.DataFrame(rows)
    out: dict[str, Any] = {"schema": "trigger_replication_v1",
                           "corpus": "M4Singer long-form (timelines synthesised from real segments)",
                           "label_kind": "rule_validated weak labels, 80 ms quantised (not human GT)",
                           "segments_with_audio": files_used, "units_scored": int(len(d)),
                           "truncation_tol_sec": GT_QUANTISATION_SEC + 0.08, "aucs": {}, "slices": {}}
    if len(d) < 50:
        out["status"] = "insufficient_overlap_between_panel_and_available_audio"
        (args.out_dir / "REPLICATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False))
        return 1

    def aucs(frame: pd.DataFrame) -> dict[str, Any]:
        res: dict[str, Any] = {"units": int(len(frame))}
        for label in ("truncated", "any_error_gt_100ms"):
            y = frame[label].to_numpy(dtype=float)
            res[label] = {"prevalence": round(float(y.mean()), 4)}
            for score in ("gap_over_core", "end_entropy", "end_margin", "rise_ratio"):
                v = pd.to_numeric(frame[score], errors="coerce").to_numpy(dtype=float)
                ok = np.isfinite(v)
                if ok.sum() < 50 or y[ok].sum() in (0, ok.sum()):
                    continue
                a = roc_auc(y[ok], v[ok])
                if a is not None:
                    res[label][f"auc_{score}"] = round(float(a), 4)
        return res
    out["aucs"]["all"] = aucs(d)
    out["aucs"]["train_split"] = aucs(d[d["split"] == "train"])
    out["aucs"]["validation_split"] = aucs(d[d["split"] == "validation"])
    out["slices"] = {"by_family": {str(k): aucs(sub) for k, sub in d.groupby("family", observed=True)},
                     "long_note": aucs(d[d["gt_dur_sec"] >= 1.0])}
    d.to_csv(args.out_dir / "m4_gap_features.csv.gz", index=False, compression="gzip")
    (args.out_dir / "REPLICATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    print(f"M4 replication: segments_with_audio={files_used} units_scored={len(d):,} "
          f"truncated prevalence={out['aucs']['all']['truncated']['prevalence']:.3f}")
    for scope in ("all", "train_split", "validation_split"):
        b = out["aucs"][scope]
        print(f"   {scope:16s} trunc: gap={b['truncated'].get('auc_gap_over_core')} "
              f"ent={b['truncated'].get('auc_end_entropy')} margin={b['truncated'].get('auc_end_margin')} "
              f"rise={b['truncated'].get('auc_rise_ratio')} | any_err>100ms: gap={b['any_error_gt_100ms'].get('auc_gap_over_core')} "
              f"ent={b['any_error_gt_100ms'].get('auc_end_entropy')}")
    ln = out["slices"]["long_note"]
    print(f"   long_note (n={ln['units']:,}) trunc: gap={ln['truncated'].get('auc_gap_over_core')} "
          f"ent={ln['truncated'].get('auc_end_entropy')}")
    # continuous lateness for the decile view, recomputed from the panel with the same offsets used above
    late_rows = []
    for seg, sub in work.groupby("source_segment_id", observed=True):
        if segment_path(seg) is None:
            continue
        off = float(sub["segment_start_sec"].iloc[0])
        s = sub.sort_values("source_unit_index")
        late_rows.append(pd.DataFrame({"segment": str(seg),
                                       "unit_rank": np.arange(len(s)),
                                       "gt_end_sec": s["gt_end_sec"].to_numpy(dtype=float) - off,
                                       "pred_end_sec": s["off_end_sec"].to_numpy(dtype=float) - off}))
    if late_rows:
        lt = pd.concat(late_rows, ignore_index=True)
        m = d.copy()
        m["unit_rank"] = m.groupby("segment").cumcount()
        j = m.merge(lt, on=["segment", "unit_rank"], how="inner")
        out["deciles_m4"] = {name: GS.lateness_deciles(j, score_col=name)
                             for name in ("gap_over_core", "end_entropy", "rise_ratio")}
        g = pd.read_csv(RUNS / "20260912_gap_shape/gtsinger_gap_features.csv.gz")
        out["deciles_gtsinger"] = {name: GS.lateness_deciles(g, score_col=name)
                                   for name in ("gap_over_core", "rise_ratio")}
        for corpus in ("deciles_m4", "deciles_gtsinger"):
            for name, blk in out[corpus].items():
                if not blk.get("available"):
                    continue
                print(f"{corpus:18s} {name:14s} n={blk['units']:6,} rho={blk['spearman_rho']:+.4f} "
                      f"monotone={blk['monotone_increasing_median']} spread={blk['spread_median_ms']}ms "
                      f"share_gt_later={blk['share_gt_later_than_pred']:.3f}")
    print("\nGTSinger AUC reference: gap_over_core 0.921 (truncation), high_entropy 0.845 (end error)")
    # rewrite the artifact now that the decile diagnostics exist (they are computed after the first write)
    (args.out_dir / "REPLICATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    return 0


def GS_env(path: str) -> tuple[np.ndarray, np.ndarray]:
    import soundfile as sf
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = x.mean(axis=1).astype(np.float64)
    target = 16000
    if sr != target:
        factor = int(round(sr / target))
        n = mono.size // max(factor, 1)
        mono = mono[:n * factor].reshape(n, factor).mean(axis=1) if factor > 1 else mono
    win = max(1, int(round(GS.FRAME_SEC if hasattr(GS, "FRAME_SEC") else 0.025 * target)))
    hop = max(1, int(round(0.010 * target)))
    nf = 1 + max(0, (mono.size - win) // hop)
    idx = np.arange(win)[None, :] + hop * np.arange(nf)[:, None]
    env = np.sqrt(np.mean(mono[idx] ** 2, axis=1)) if nf else np.zeros(0)
    t = (np.arange(nf) * hop + win / 2) / float(target)
    return t, env


if __name__ == "__main__":
    from typing import Any
    raise SystemExit(main())
