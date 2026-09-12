"""Signed, per-unit ground truth for the long-form panel (reconstructed, then verified).

Why this module exists
----------------------
The long-form panel's ``label_raw_*_err_sec`` columns are **absolute** errors, so ``raw - err``
recovers the reference boundary only up to a sign: two thirds of the units looked consistent and a
quarter looked wildly inconsistent under that reconstruction, and that ambiguity was an artefact of
the sign, not of the model.  The panel's own ``gt_*`` columns cannot resolve it either — they live on
the fabricated uniform axis (round 3).

The genuine reference is available, though: ``m4singer_qwen_fa_labels.jsonl`` gives per-character
quantised boundaries *per source segment*, and the timeline manifest gives each segment's
``global_start_sec``.  Adding the two reproduces exactly what the project's own labeler
(``scripts/research_v7/label_detector_v2_run.py``) used, and the reconstruction is verified here by
requiring ``|raw - gt|`` to reproduce the frozen absolute errors.

Reference status (state it in every claim)
------------------------------------------
``mapping_status=accepted_rule_based_pinyin_validated``, ``validation_basis=rule_validated``: these
are **rule-validated weak labels produced by the same model family** (Qwen FA on the original short
M4Singer segments), quantised to ``timestamp_segment_sec`` (0.08 s).  They are not human GT, and the
quantisation puts a ±40 ms floor under any agreement measured against them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DATA = Path("/home/hyan/Data/lyricalign")
GT_LABELS = DATA / "derived/20260723_qwen_fa_lora_v1/labels/m4singer_qwen_fa_labels.jsonl"
TIMELINE_GLOBS = ("timeline_v4/LONG_TIMELINE_MANIFEST.jsonl",
                  "*/manifests/LONG_TIMELINE_MANIFEST.jsonl")
PANEL = DATA / "runs/20260912_m4_longform_weakgt/longform_units.jsonl.gz"


def _f(x: Any) -> float | None:
    try:
        return None if x is None else round(float(x), 4)
    except (TypeError, ValueError):
        return None


def load_segment_gt(path: Path = GT_LABELS) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """item_id -> {chars, starts, ends} in segment-local seconds."""
    out: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {"path": str(path)}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            item = str(row.get("item_id"))
            ids = row.get("timestamp_class_ids") or []
            step = float(row.get("timestamp_segment_sec") or 0.0)
            text = str(row.get("lyrics_normalized") or "")
            if not item or step <= 0 or len(ids) < 2:
                continue
            starts = np.empty(len(ids) // 2)
            ends = np.empty(len(ids) // 2)
            for i in range(len(ids) // 2):
                # the project's labeler uses e = ids[2i+1]*seg (a boundary index, not a bin end);
                # adding one bin inflated every end by 80 ms in the first version of this module
                starts[i] = ids[2 * i] * step
                ends[i] = ids[2 * i + 1] * step
            out[item] = {"chars": text, "starts": starts, "ends": ends,
                         "duration_sec": float(row.get("duration_sec") or 0.0),
                         "singer_id": row.get("singer_id"), "song_id": row.get("song_id"),
                         "split": row.get("split"),
                         "mapping_status": row.get("mapping_status"),
                         "validation_basis": row.get("validation_basis")}
    meta["segments"] = len(out)
    meta["quantisation_sec"] = step
    return out, meta


def build_unit_gt(timelines_dir: Path = DATA / "runs/research_v7_detector_v2",
                  seg_gt: dict[str, dict[str, Any]] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per (timeline, song, canonical_unit_id) with the signed reference boundary."""
    quantisation = 0.0
    if seg_gt is None:
        seg_gt, meta0 = load_segment_gt()
        quantisation = float(meta0.get("quantisation_sec") or 0.0)
    seen: set[Path] = set()
    paths: list[Path] = []
    for pat in TIMELINE_GLOBS:
        for p in sorted(timelines_dir.glob(pat)):
            if p.exists() and p.resolve() not in seen:
                seen.add(p.resolve())
                paths.append(p)
    rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"schema": "longform_signed_gt_v1", "manifests": [str(p) for p in paths],
                            "reference": {}}
    unmatched_segment = unmatched_index = char_mismatch = 0
    for tl_path in paths:
        for line in tl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            offsets = {str(s.get("source_segment_id")): s
                       for s in row.get("segment_offsets", []) if isinstance(s, dict)}
            song = str(row.get("song_id", ""))
            for u in row.get("canonical_units", []) or []:
                seg_id = str(u.get("source_segment_id", ""))
                seg_off = offsets.get(seg_id)
                seg_lab = seg_gt.get(seg_id)
                if seg_off is None or seg_lab is None:
                    unmatched_segment += 1
                    continue
                idx = u.get("source_unit_index")
                starts = seg_lab["starts"]
                if idx is None or not (0 <= int(idx) < len(starts)):
                    unmatched_index += 1
                    continue
                idx = int(idx)
                gs = float(seg_off.get("global_start_sec") or 0.0)
                text = str(u.get("text", ""))
                chars = seg_lab["chars"]
                mismatch = bool(text and idx < len(chars) and text != chars[idx])
                char_mismatch += int(mismatch)
                rows.append({"timeline_path": str(tl_path), "timeline_id": row.get("timeline_id"),
                             "song": song, "singer": row.get("singer_id"),
                             "canonical_unit_id": int(u["canonical_unit_id"]),
                             "source_segment_id": seg_id, "source_unit_index": idx,
                             "text": text, "gt_char": chars[idx] if idx < len(chars) else "",
                             "char_mismatch": int(mismatch),
                             "segment_global_start_sec": round(gs, 4),
                             "segment_duration_sec": _f(seg_off.get("duration_sec")),
                             "n_segment_units": seg_off.get("n_units"),
                             "gt_start_sec": round(gs + float(starts[idx]), 4),
                             "gt_end_sec": round(gs + float(seg_lab["ends"][idx]), 4),
                             "timeline_duration_sec": _f(row.get("duration_sec")),
                             "artificial_silence_sec": _f(row.get("artificial_silence_sec"))})
    stats["units"] = len(rows)
    stats["dropped_missing_segment_label"] = unmatched_segment
    stats["dropped_index_out_of_range"] = unmatched_index
    stats["char_mismatches"] = char_mismatch
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["timeline_path", "song", "canonical_unit_id"], keep="first")
        stats["unique_units"] = int(len(df))
        stats["reference"] = {"mapping_status": sorted({str(v) for v in
                                                        {k: v.get("mapping_status")
                                                         for k, v in seg_gt.items()}.values()}),
                              "validation_basis": "rule_validated (model-derived, not human GT)",
                              "quantisation_sec": quantisation or None,
                              "note": "80 ms grid implies a +-40 ms floor on any agreement measured "
                                      "against this reference"}
    return df, stats


def verify_against_frozen_errors(gt: pd.DataFrame, panel: pd.DataFrame,
                                 tol_sec: float = 1e-3) -> dict[str, Any]:
    """The reconstruction is only usable if it reproduces the frozen absolute errors."""
    key = ["song", "canonical_unit_id"]
    g = gt.drop_duplicates(subset=key)
    merged = panel.merge(g[key + ["gt_start_sec", "gt_end_sec"]], on=key, how="inner",
                         suffixes=("", "_rebuilt"))
    assert "gt_start_sec_rebuilt" in merged.columns, "merge produced no rebuilt reference column"
    out: dict[str, Any] = {"panel_rows": int(len(panel)), "merged_rows": int(len(merged)),
                           "merge_share": round(float(len(merged) / max(len(panel), 1)), 4)}
    for stage, (p_s, p_e), (e_s, e_e) in (
            ("raw", ("raw_start_sec", "raw_end_sec"),
             ("label_raw_start_err_sec", "label_raw_end_err_sec")),
            ("official", ("off_start_sec", "off_end_sec"),
             ("label_off_start_err_sec", "label_off_end_err_sec"))):
        if p_s not in merged or e_s not in merged:
            continue
        pe = merged[e_s].to_numpy(dtype=float)
        qe = merged[e_e].to_numpy(dtype=float)
        ds = np.abs(merged[p_s].to_numpy(dtype=float) - merged["gt_start_sec_rebuilt"].to_numpy(dtype=float))
        de = np.abs(merged[p_e].to_numpy(dtype=float) - merged["gt_end_sec_rebuilt"].to_numpy(dtype=float))
        ok = np.isfinite(pe) & np.isfinite(qe) & np.isfinite(ds) & np.isfinite(de)
        dev_s, dev_e = np.abs(ds - pe), np.abs(de - qe)
        out[stage] = {
            "n": int(ok.sum()),
            "start_within_tol_share": round(float(np.mean(dev_s[ok] <= tol_sec)), 4),
            "end_within_tol_share": round(float(np.mean(dev_e[ok] <= tol_sec)), 4),
            "max_deviation_sec": round(float(np.max(np.maximum(dev_s, dev_e)[ok])), 5) if ok.any() else None,
            "median_deviation_sec": round(float(np.median(np.maximum(dev_s, dev_e)[ok])), 6) if ok.any() else None,
            "correlation_start": round(float(np.corrcoef(pe[ok], ds[ok])[0, 1]), 4) if ok.sum() > 10 else None,
        }
    # the panel's own gt_* column, for contrast (expected: a fabricated uniform axis)
    if "gt_start_sec" in merged and "gt_start_sec_rebuilt" in merged:
        bad = np.abs(merged["raw_start_sec"].to_numpy(dtype=float)
                     - merged["gt_start_sec"].to_numpy(dtype=float))
        good = np.abs(merged["raw_start_sec"].to_numpy(dtype=float)
                      - merged["gt_start_sec_rebuilt"].to_numpy(dtype=float))
        out["fabricated_axis_contrast"] = {
            "share_within_100ms_panel_gt": round(float(np.mean(bad <= 0.1)), 4),
            "share_within_100ms_rebuilt": round(float(np.mean(good <= 0.1)), 4),
            "median_distance_panel_gt_sec": round(float(np.median(bad)), 4),
            "median_distance_rebuilt_sec": round(float(np.median(good)), 4)}

    # cross-attempt agreement of the rebuilt reference (the sign ambiguity check)
    if {"view_id", "gt_start_sec"} <= set(merged.columns):
        grp = merged.groupby(["view_id", "song", "canonical_unit_id"], observed=True)
        sp = np.maximum((grp["gt_start_sec"].max() - grp["gt_start_sec"].min()).to_numpy(dtype=float),
                        (grp["gt_end_sec"].max() - grp["gt_end_sec"].min()).to_numpy(dtype=float))
        cnt = grp.size().to_numpy()
        multi = cnt > 1
        out["cross_attempt_reference_spread"] = {
            "units": int(sp.size), "multi_attempt_units": int(multi.sum()),
            "median_spread_sec": round(float(np.median(sp[multi])), 5) if multi.any() else None,
            "p90_spread_sec": round(float(np.percentile(sp[multi], 90)), 5) if multi.any() else None,
            "share_within_5ms": round(float(np.mean(sp[multi] <= 5e-3)), 4) if multi.any() else None}
    return out
