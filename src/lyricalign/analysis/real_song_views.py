"""Cross-view disagreement census on 25 real long songs (no ground truth needed).

Why these three views
---------------------
``20260814_ktv_B4`` (60 s windowed baseline), ``20260814_ktv_current_silence``
(silence-aware + skip-silent Current) and ``20260815_slot_vs_b4/align`` (full-slot Current) are three
*planning views* over the same real songs (2–5 min, accompanied pop, zh/en/ja/yue) with per-character
decoder posteriors retained.  Round 1 showed GTSinger cannot test the planning factor (single window
per 5-15 s clip) and round 5 showed consensus over inference configurations buys ~0.3 pp on natural
Mandarin — but neither answers the question that matters for long-form work:

    how much does the answer move when only the *planning view* changes, and is the movement
    concentrated at window seams?

Everything here is GT-free by construction: disagreement is measured, not validated.  Where the
GTSinger/MIR-1K panels already validated disagreement as an error predictor (AUC 0.78 / 0.84 for
>=250 ms), the numbers here can be read as a targeting prior; the audio hashes are recorded so a
"view" that secretly re-used the same wav cannot be mistaken for an independent one.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RUNS = Path("/home/hyan/Data/lyricalign/runs")
VIEWS = {
    "b4_60s_windowed": RUNS / "20260814_ktv_B4",
    "current_silence_aware": RUNS / "20260814_ktv_current_silence",
    "full_slot": RUNS / "20260815_slot_vs_b4/align",
}
MIN_UNITS = 8
SEED = 20260912


def _f(x: Any) -> float | None:
    try:
        return None if x is None else round(float(x), 4)
    except (TypeError, ValueError):
        return None


def _window_edges(trace: list[dict] | None) -> list[dict[str, float]]:
    edges: list[dict[str, float]] = []
    if not isinstance(trace, list):
        return edges
    for i, win in enumerate(trace):
        if not isinstance(win, dict):
            continue
        cs, ce = win.get("committed_character_start"), win.get("committed_character_end")
        edges.append({"window_index": i,
                      "char_start": cs if cs is not None else -1,
                      "char_end": ce if ce is not None else -1,
                      "core_start_sec": _f(win.get("core_start_sec")) or 0.0,
                      "core_end_sec": _f(win.get("core_end_sec")) or 0.0})
    return edges


def _song_dirs(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        p = d / "alignments" / "r2" / "vocal" / "windowed" / "alignment.json"
        if p.exists():
            out[d.name] = p
    return out


def build_panel(out_dir: Path) -> dict[str, Any]:
    """Collect per-unit boundaries + posteriors + window provenance for each planning view."""
    out_dir.mkdir(parents=True, exist_ok=True)
    per_view = {name: _song_dirs(root) for name, root in VIEWS.items()}
    songs = sorted(set.intersection(*[set(v) for v in per_view.values()]) or set())
    stats: dict[str, Any] = {"schema": "real_song_views_panel_v1",
                            "views": {k: {"songs": len(v), "root": str(VIEWS[k])}
                                      for k, v in per_view.items()},
                            "songs_in_all_views": len(songs), "dropped_songs": sorted(
                                set().union(*[set(v) for v in per_view.values()]) - set(songs))}
    rows: list[dict[str, Any]] = []
    lang_of: dict[str, str] = {}
    for song in songs:
        per_view_units: dict[str, list[dict]] = {}
        per_view_meta: dict[str, dict] = {}
        for view, paths in per_view.items():
            doc = json.loads(paths[song].read_text(encoding="utf-8"))
            chars = doc.get("characters") or []
            s = doc.get("summary") or {}
            ident = doc.get("identity") or {}
            audio = ident.get("audio") or {}
            per_view_units[view] = chars
            win_id = ident.get("window") or {}
            win_keys = sorted(k for k, v in win_id.items() if v is not None) \
                if isinstance(win_id, dict) else []
            per_view_meta[view] = {
                "n_units": len(chars),
                "schema_version": str(ident.get("schema_version", "")),
                "decoder_kind": str((ident.get("decoder") or {}).get("kind", "")
                                    if isinstance(ident.get("decoder"), dict) else ""),
                "window_flags_recorded": win_keys,
                "silence_flags_recorded": int(any("silence" in k or "silent" in k for k in win_keys)),
                "audio_duration_sec": _f(s.get("audio_duration_sec")),
                "audio_sha256": str(audio.get("sha256", "")),
                "language": str(s.get("language") or ""),
                "unit_mode": str(s.get("alignment_unit_mode") or ""),
                "windows": len(doc.get("window_trace") or []),
                "edges": _window_edges(doc.get("window_trace")),
                "mode": ident.get("mode", ""),
            }
            if view == "b4_60s_windowed":
                lang_of[song] = str(s.get("language") or "")
        n_ref = per_view_meta["b4_60s_windowed"]["n_units"]
        counts = {v: per_view_meta[v]["n_units"] for v in per_view_meta}
        if any(c != n_ref for c in counts.values()) or n_ref < MIN_UNITS:
            stats.setdefault("skipped_unit_count_mismatch", []).append(
                {"song": song, "counts": counts})
            continue
        edges_by_view = {v: per_view_meta[v]["edges"] for v in per_view_meta}
        for i in range(n_ref):
            texts = {v: str((units[i] or {}).get("character", "")) for v, units in per_view_units.items()}
            row: dict[str, Any] = {
                "song": song, "language": lang_of.get(song, ""), "unit_index": i,
                "text": texts["b4_60s_windowed"],
                "text_cur": texts["current_silence_aware"],
                "text_slot": texts["full_slot"],
                # a cross-view comparison is only meaningful when the *same* unit is at this index;
                # b4 vs full_slot shifts by 23.6% of positions because that run skips/repeats units
                "agree_b4_cur": int(texts["b4_60s_windowed"] == texts["current_silence_aware"]),
                "agree_b4_slot": int(texts["b4_60s_windowed"] == texts["full_slot"]),
                "agree_all": int(texts["b4_60s_windowed"] == texts["current_silence_aware"]
                                 == texts["full_slot"]),
                "unit_type": str(per_view_units["b4_60s_windowed"][i].get("unit_type", "")),
                "audio_dur_b4": per_view_meta["b4_60s_windowed"]["audio_duration_sec"],
                "n_windows_b4": per_view_meta["b4_60s_windowed"]["windows"],
                "n_windows_cur": per_view_meta["current_silence_aware"]["windows"],
                "audio_same_sha_b4_cur": int(per_view_meta["b4_60s_windowed"]["audio_sha256"]
                                             == per_view_meta["current_silence_aware"]["audio_sha256"]),
                "audio_same_sha_b4_slot": int(per_view_meta["b4_60s_windowed"]["audio_sha256"]
                                              == per_view_meta["full_slot"]["audio_sha256"]),
            }
            for view, units in per_view_units.items():
                c = units[i]
                row[f"{view}__s"] = _f(c.get("selected_start_sec", c.get("start_sec")))
                row[f"{view}__e"] = _f(c.get("selected_end_sec", c.get("end_sec")))
                row[f"{view}__rs"] = _f(c.get("raw_global_start_sec"))
                row[f"{view}__re"] = _f(c.get("raw_global_end_sec"))
                row[f"{view}__ent_s"] = _f(c.get("raw_start_entropy"))
                row[f"{view}__ent_e"] = _f(c.get("raw_end_entropy"))
                row[f"{view}__mar_min"] = None
            # seam geometry from the silence-aware windowed plan (the real multi-window view)
            gidx = None
            for win in edges_by_view["current_silence_aware"]:
                if win["char_start"] <= i < win["char_end"]:
                    gidx = win
                    break
            if gidx is not None:
                row["window_index"] = gidx["window_index"]
                row["units_from_window_start"] = i - int(gidx["char_start"])
                row["units_from_window_end"] = int(gidx["char_end"]) - 1 - i
            row["ent_max_b4"] = max(filter(lambda x: x is not None,
                                           [row["b4_60s_windowed__ent_s"],
                                            row["b4_60s_windowed__ent_e"]]), default=None)
            rows.append(row)
        stats[f"units_{song}"] = n_ref
    out_path = out_dir / "real_song_views.jsonl.gz"
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    # per-view identity provenance: which runner produced it and which planning flags it records
    prov: dict[str, Any] = {}
    for view, paths in per_view.items():
        schemas: dict[str, int] = {}
        flags_seen: set[str] = set()
        silence_recorded = 0
        for song in songs:
            if song not in paths:
                continue
            doc = json.loads(paths[song].read_text(encoding="utf-8"))
            ident = doc.get("identity") or {}
            schemas[str(ident.get("schema_version", ""))] = schemas.get(
                str(ident.get("schema_version", "")), 0) + 1
            win = ident.get("window") or {}
            if isinstance(win, dict):
                flags_seen |= {k for k, v in win.items() if v is not None}
                silence_recorded += int(any("silence" in k or "silent" in k
                                            for k, v in win.items() if v is not None))
        prov[view] = {"schema_versions": schemas,
                      "songs_recording_silence_flags": silence_recorded,
                      "n_songs": len(paths),
                      "window_flag_names": sorted(flags_seen)}
    stats["identity_provenance"] = prov
    stats["rows"] = len(rows)
    stats["songs_used"] = len({r["song"] for r in rows})
    stats["out"] = str(out_path)
    stats["bytes"] = out_path.stat().st_size
    (out_dir / "VIEWS_PANEL_SUMMARY.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
    return stats


PAIRS = {
    # only pairs whose character sequence is identical at this index are comparable
    "b4_vs_cur": ("b4_60s_windowed", "current_silence_aware", "agree_b4_cur"),
    "b4_vs_slot": ("b4_60s_windowed", "full_slot", "agree_b4_slot"),
}


def load_frame(path: Path) -> pd.DataFrame:
    df = pd.read_json(path, lines=True, compression="infer")
    for name, (a, b, agree) in PAIRS.items():
        ds = np.abs(df[f"{a}__s"].to_numpy(dtype=float) - df[f"{b}__s"].to_numpy(dtype=float))
        de = np.abs(df[f"{a}__e"].to_numpy(dtype=float) - df[f"{b}__e"].to_numpy(dtype=float))
        df[f"d_{name}"] = np.maximum(ds, de)
    # headline spread uses the valid pair only
    df["spread"] = df["d_b4_vs_cur"]
    df["comparable"] = df["agree_b4_cur"] == 1
    df["unit_dur_b4"] = df["b4_60s_windowed__e"] - df["b4_60s_windowed__s"]
    df["zero_dur_b4"] = (df["unit_dur_b4"] <= 1e-6).astype(float)
    df["zero_dur_cur"] = ((df["current_silence_aware__e"] - df["current_silence_aware__s"])
                          <= 1e-6).astype(float)
    df["zero_dur_slot"] = ((df["full_slot__e"] - df["full_slot__s"]) <= 1e-6).astype(float)
    df["b4_vs_cur_gt100"] = (df["spread"] > 0.1).astype(float)
    df["b4_vs_slot_gt100"] = np.maximum(
        (df["b4_60s_windowed__s"] - df["full_slot__s"]).abs(),
        (df["b4_60s_windowed__e"] - df["full_slot__e"]).abs()) > 0.1
    return df


# ---------------------------------------------------------------------------
# post-processing attribution without ground truth (structural, not accuracy)
# ---------------------------------------------------------------------------

def analyse_postprocess_attribution(df: pd.DataFrame) -> dict[str, Any]:
    """Separate defects the decoder produced from defects the post-processor produced.

    No ground truth is available on these songs, so the question is structural and answerable from
    the two recorded stages alone: does the cleanup *create*, *heal*, or merely *move* degenerate
    (zero/negative length) units, and does it resolve overlaps the way the demo pipeline does
    (pinning a start to the previous tail, see the 2026-09-12 round-2 finding)?
    """
    out: dict[str, Any] = {"schema": "real_song_postprocess_attribution_v1",
                           "tolerance_sec": 1e-3, "views": {}}
    for view in VIEWS:
        s_col, e_col = f"{view}__s", f"{view}__e"
        rs_col, re_col = f"{view}__rs", f"{view}__re"
        if not all(c in df for c in (s_col, e_col, rs_col, re_col)):
            continue
        d = df.dropna(subset=[s_col, e_col, rs_col, re_col]).sort_values(["song", "unit_index"])
        if d.empty:
            continue
        raw_dur = (d[re_col] - d[rs_col]).to_numpy(dtype=float)
        sel_dur = (d[e_col] - d[s_col]).to_numpy(dtype=float)
        raw_bad, sel_bad = raw_dur <= 1e-6, sel_dur <= 1e-6
        created = int(((~raw_bad) & sel_bad).sum())
        healed = int((raw_bad & (~sel_bad)).sum())
        ds = (d[s_col] - d[rs_col]).to_numpy(dtype=float)
        de = (d[e_col] - d[re_col]).to_numpy(dtype=float)
        moved = np.maximum(np.abs(ds), np.abs(de)) > 1e-3
        # overlaps before/after, per song (contiguity is a song-level property)
        def overlaps(col_s: str, col_e: str) -> float:
            nxt_s = d.groupby("song", observed=True)[col_s].shift(-1).to_numpy(dtype=float)
            cur_e = d[col_e].to_numpy(dtype=float)
            ok = np.isfinite(nxt_s)
            return float(np.mean((cur_e[ok] - nxt_s[ok]) > 1e-3)) if ok.any() else float("nan")

        ov_raw = overlaps(rs_col, re_col)
        ov_sel = overlaps(s_col, e_col)
        entry: dict[str, Any] = {
            "units": int(len(d)), "songs": int(d["song"].nunique()),
            "raw_degenerate_share": round(float(raw_bad.mean()), 4),
            "selected_degenerate_share": round(float(sel_bad.mean()), 4),
            "created_by_postprocess": created,
            "healed_by_postprocess": healed,
            "net_change_in_degenerate": created - healed,
            "share_units_touched": round(float(moved.mean()), 4),
            # robust statistics only: a handful of gross raw intervals make the mean meaningless
            "median_abs_shift_start_sec": round(float(np.median(np.abs(ds[moved]))), 4) if moved.any() else None,
            "p90_abs_shift_start_sec": round(float(np.percentile(np.abs(ds[moved]), 90)), 4) if moved.any() else None,
            "mean_abs_shift_start_sec_USE_WITH_CARE": round(float(np.abs(ds[moved]).mean()), 4) if moved.any() else None,
            "median_abs_shift_end_sec": round(float(np.median(np.abs(de[moved]))), 4) if moved.any() else None,
            "start_moves_later_share": round(float((ds[moved] > 0).mean()), 4) if moved.any() else None,
            "end_moves_earlier_share": round(float((de[moved] < 0).mean()), 4) if moved.any() else None,
            "raw_overlap_rate": round(ov_raw, 4), "selected_overlap_rate": round(ov_sel, 4),
        }
        # structural defects in the raw decoder output itself (no GT needed)
        neg = raw_dur < -1e-6
        huge = raw_dur > 3.0
        sarr = d[rs_col].to_numpy(dtype=float)
        earr = d[re_col].to_numpy(dtype=float)
        non_mono = d.groupby("song", observed=True)[rs_col].diff().to_numpy(dtype=float)
        entry["raw_structural_defects"] = {
            "negative_duration_share": round(float(neg.mean()), 4),
            "duration_over_3s_share": round(float(huge.mean()), 4),
            "max_raw_duration_sec": round(float(np.nanmax(raw_dur)), 2),
            "start_regression_share": round(float(np.nanmean(non_mono < -1e-6)), 4),
            "median_raw_duration_sec": round(float(np.median(raw_dur)), 4),
        }
        sel_sarr = d[s_col].to_numpy(dtype=float)
        sel_non_mono = d.groupby("song", observed=True)[s_col].diff().to_numpy(dtype=float)
        entry["selected_structural_defects"] = {
            "negative_duration_share": round(float((sel_dur < -1e-6).mean()), 4),
            "duration_over_3s_share": round(float((sel_dur > 3.0).mean()), 4),
            "start_regression_share": round(float(np.nanmean(sel_non_mono < -1e-6)), 4),
        }
        created_mask = (~raw_bad) & (sel_dur <= 1e-6)
        if created_mask.any():
            entry["created_degenerate_origin"] = {
                "n": int(created_mask.sum()),
                "share_from_negative_raw_duration": round(float(neg[created_mask].mean()), 4),
                "share_from_overshoot_gt1s": round(float((raw_dur[created_mask] > 1.0).mean()), 4),
                "median_raw_duration_of_created_sec": round(float(np.median(raw_dur[created_mask])), 4),
            }
        if moved.any():
            prev_sel_end = d.groupby("song", observed=True)[e_col].shift(1).to_numpy(dtype=float)
            ms = np.abs(ds) > 1e-3
            if ms.any():
                entry["share_start_moves_pinned_to_prev_end"] = round(float(
                    np.nanmean(np.abs(d[s_col].to_numpy()[ms] - prev_sel_end[ms]) <= 2e-3)), 4)
            me = np.abs(de) > 1e-3
            if me.any():
                nxt_sel_start = d.groupby("song", observed=True)[s_col].shift(-1).to_numpy(dtype=float)
                entry["share_end_moves_pinned_to_next_start"] = round(float(
                    np.nanmean(np.abs(d[e_col].to_numpy()[me] - nxt_sel_start[me]) <= 2e-3)), 4)
        per_lang = {}
        for lang, sub in d.groupby("language", observed=True):
            r = (sub[re_col] - sub[rs_col]).to_numpy(dtype=float)
            q = (sub[e_col] - sub[s_col]).to_numpy(dtype=float)
            per_lang[str(lang)] = {
                "units": int(len(sub)),
                "raw_degenerate_share": round(float((r <= 1e-6).mean()), 4),
                "selected_degenerate_share": round(float((q <= 1e-6).mean()), 4),
                "created": int((((r > 1e-6) & (q <= 1e-6)).sum())),
                "healed": int((((r <= 1e-6) & (q > 1e-6)).sum())),
            }
        entry["by_language"] = per_lang
        by_type = {}
        if "unit_type" in d:
            for ut, sub in d.groupby("unit_type", observed=True):
                r = (sub[re_col] - sub[rs_col]).to_numpy(dtype=float)
                q = (sub[e_col] - sub[s_col]).to_numpy(dtype=float)
                by_type[str(ut)] = {
                    "units": int(len(sub)),
                    "raw_degenerate_share": round(float((r <= 1e-6).mean()), 4),
                    "selected_degenerate_share": round(float((q <= 1e-6).mean()), 4),
                    "raw_negative_share": round(float((r < -1e-6).mean()), 4),
                    "max_raw_duration_sec": round(float(np.nanmax(r)), 2) if r.size else None,
                }
        entry["by_unit_type"] = by_type
        out["views"][view] = entry
    if out["views"]:
        b4 = out["views"].get("b4_60s_windowed")
        if b4:
            out["headline"] = {
                "degenerates_before_cleanup": b4["raw_degenerate_share"],
                "degenerates_after_cleanup": b4["selected_degenerate_share"],
                "created_by_cleanup": b4["created_by_postprocess"],
                "healed_by_cleanup": b4["healed_by_postprocess"],
                "verdict": ("cleanup is degenerate-neutral" if abs(
                    b4["created_by_postprocess"] - b4["healed_by_postprocess"]) <= 2
                    else ("cleanup CREATES degenerate units"
                          if b4["created_by_postprocess"] > b4["healed_by_postprocess"]
                          else "cleanup REMOVES degenerate units")),
                "mechanism": {
                    "start_pinned_to_prev_end": b4.get("share_start_moves_pinned_to_prev_end"),
                    "end_pinned_to_next_start": b4.get("share_end_moves_pinned_to_next_start"),
                    "overlap_rate_before": b4["raw_overlap_rate"],
                    "overlap_rate_after": b4["selected_overlap_rate"],
                    "created_from_negative_duration_share": (
                        b4.get("created_degenerate_origin", {}).get("share_from_negative_raw_duration")),
                    "created_from_overshoot_gt1s_share": (
                        b4.get("created_degenerate_origin", {}).get("share_from_overshoot_gt1s")),
                },
                "note": ("cleanup enforces contiguity (overlaps ~12% -> ~0.1%) but does so by "
                         "collapsing gross raw intervals to zero length rather than repairing them"),
            }
    return out


def analyse(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": "real_song_views_analysis_v1",
                           "caveat": "no ground truth here: disagreement is measured, not validated",
                           "panel": {"units": int(len(df)), "songs": int(df["song"].nunique()),
                                     "languages": {str(k): int(v) for k, v in
                                                   df["language"].value_counts().items()},
                                     "audio_identical_b4_vs_cur_share": round(
                                         float(df["audio_same_sha_b4_cur"].mean()), 4),
                                     "audio_identical_b4_vs_slot_share": round(
                                         float(df["audio_same_sha_b4_slot"].mean()), 4),
                                     "windows_b4": sorted({int(v) for v in df['n_windows_b4'].dropna()}),
                                     "windows_cur": sorted({int(v) for v in df['n_windows_cur'].dropna()})}}
    comp = df[df["comparable"] == 1] if "comparable" in df else df
    out["comparability"] = {
        "units_total": int(len(df)),
        "share_b4_cur_character_identical": round(float(df["agree_b4_cur"].mean()), 4),
        "share_b4_slot_character_identical": round(float(df["agree_b4_slot"].mean()), 4),
        "audio_sha_identical_b4_cur": round(float(df["audio_same_sha_b4_cur"].mean()), 4),
        "audio_sha_identical_b4_slot": round(float(df["audio_same_sha_b4_slot"].mean()), 4),
        "decision": "quantitative cross-view numbers use b4 vs current_silence_aware only; "
                    "full_slot is excluded because 23.6% of its indices hold a different "
                    "character (that run skips/repeats units) and its audio hash is unrecorded",
    }
    for pname, (_a, _b, agree) in PAIRS.items():
        col = f"d_{pname}"
        v = df[df[agree] == 1][col].to_numpy(dtype=float)
        out.setdefault("pair_disagreement", {})[pname] = {
            "comparable_units": int(v.size),
            "median_sec": round(float(np.median(v)), 4) if v.size else None,
            "p90_sec": round(float(np.percentile(v, 90)), 4) if v.size else None,
            "p99_sec": round(float(np.percentile(v, 99)), 4) if v.size else None,
            "share_gt_100ms": round(float((v > 0.1).mean()), 4) if v.size else None,
            "share_gt_250ms": round(float((v > 0.25).mean()), 4) if v.size else None,
        }
    df = comp
    sp = df["spread"].to_numpy(dtype=float)
    out["disagreement_distribution"] = {
        "median_sec": round(float(np.median(sp)), 4),
        "p75": round(float(np.percentile(sp, 75)), 4),
        "p90": round(float(np.percentile(sp, 90)), 4),
        "p99": round(float(np.percentile(sp, 99)), 4),
        "max_sec": round(float(np.nanmax(sp)), 3),
        "share_gt_20ms": round(float((sp > 0.02).mean()), 4),
        "share_gt_100ms": round(float((sp > 0.1).mean()), 4),
        "share_gt_250ms": round(float((sp > 0.25).mean()), 4),
    }
    per_song = df.groupby(["song", "language"], observed=True).agg(
        units=("spread", "size"), median_spread=("spread", "median"),
        p90_spread=("spread", lambda x: float(np.percentile(x, 90))),
        share_gt100=("spread", lambda x: float((x > 0.1).mean())),
        zero_b4=("zero_dur_b4", "mean"), zero_cur=("zero_dur_cur", "mean"),
        zero_slot=("zero_dur_slot", "mean")).reset_index()
    out["per_song"] = [{"song": str(r.song), "language": str(r.language), "units": int(r.units),
                        "median_spread_sec": round(float(r.median_spread), 4),
                        "p90_spread_sec": round(float(r.p90_spread), 4),
                        "share_gt100": round(float(r.share_gt100), 4),
                        "zero_dur_b4": round(float(r.zero_b4), 4),
                        "zero_dur_cur": round(float(r.zero_cur), 4),
                        "zero_dur_slot": round(float(r.zero_slot), 4)}
                       for r in per_song.sort_values("share_gt100", ascending=False).itertuples()]
    tab = df.groupby("language", observed=True).agg(
        units=("spread", "size"), songs=("song", "nunique"),
        median_spread=("spread", "median"),
        share_gt100=("spread", lambda x: float((x > 0.1).mean())),
        share_gt250=("spread", lambda x: float((x > 0.25).mean())),
        zero_b4=("zero_dur_b4", "mean"), zero_slot=("zero_dur_slot", "mean")).reset_index()
    out["by_language"] = [{"language": str(r.language), "units": int(r.units), "songs": int(r.songs),
                            "median_spread_sec": round(float(r.median_spread), 4),
                            "share_gt100": round(float(r.share_gt100), 4),
                            "share_gt250": round(float(r.share_gt250), 4),
                            "zero_dur_b4": round(float(r.zero_b4), 4),
                            "zero_dur_slot": round(float(r.zero_slot), 4)}
                           for r in tab.itertuples()]

    # seam effect: only defined for the multi-window view
    seam = df[df["units_from_window_start"].notna()].copy()
    out["seam_warning"] = ("the window trace of the B4 view lists one merged window per committed "
                           "range; seam buckets are therefore an approximation")
    if len(seam) > 200:
        head = pd.cut(seam["units_from_window_start"].astype(float), [-0.5, 0.5, 1.5, 2.5, 4.5, 1e9],
                      labels=["1st unit of window", "2nd", "3rd", "4th-5th", "later"])
        tab = seam.assign(hb=head).groupby("hb", observed=True).agg(
            n=("spread", "size"), median_spread=("spread", "median"),
            share_gt100=("spread", lambda x: float((x > 0.1).mean()))).reset_index()
        out["seam_head_profile"] = [{"bucket": str(r.hb), "n": int(r.n),
                                     "median_spread_sec": round(float(r.median_spread), 4),
                                     "share_gt100": round(float(r.share_gt100), 4)}
                                    for r in tab.itertuples()]
        tail = pd.cut(seam["units_from_window_end"].astype(float), [-0.5, 0.5, 1.5, 2.5, 4.5, 1e9],
                      labels=["last unit of window", "2nd last", "3rd", "4th-5th", "earlier"])
        tab = seam.assign(tb=tail).groupby("tb", observed=True).agg(
            n=("spread", "size"), median_spread=("spread", "median"),
            share_gt100=("spread", lambda x: float((x > 0.1).mean()))).reset_index()
        out["seam_tail_profile"] = [{"bucket": str(r.tb), "n": int(r.n),
                                     "median_spread_sec": round(float(r.median_spread), 4),
                                     "share_gt100": round(float(r.share_gt100), 4)}
                                    for r in tab.itertuples()]
        base_mid = float(seam[(seam["units_from_window_start"] > 4)]["spread"].median())
        first_head = float(seam[seam["units_from_window_start"] == 0]["spread"].median())
        out["seam_vs_interior_ratio"] = round(first_head / base_mid, 3) if base_mid > 0 else None
        out["seam_note"] = ("disagreement of the first unit of a window versus interior units; "
                            "a ratio >>1 means the seam itself destabilises the answer")
    else:
        out["seam_head_profile"] = {"available": False, "n_units": int(len(seam))}

    # confidence vs disagreement: does the recorded posterior flag the unstable units?
    def _auc(y: np.ndarray, s: np.ndarray) -> float | None:
        ok = np.isfinite(y) & np.isfinite(s)
        y, s = y[ok], s[ok]
        if len(y) < 50 or y.min() == y.max():
            return None
        order = np.argsort(s, kind="mergesort")
        ranks = np.empty(len(s))
        ranks[order] = np.arange(1, len(s) + 1)
        n_pos = float(y.sum())
        n_neg = float(len(y) - n_pos)
        return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))

    y2 = (df["spread"] > 0.1).to_numpy(dtype=float)
    auc = {}
    for col in ("ent_max_b4", "b4_60s_windowed__ent_s", "b4_60s_windowed__ent_e",
                "current_silence_aware__ent_s", "current_silence_aware__ent_e"):
        if col in df:
            a = _auc(y2, pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float))
            auc[col] = None if a is None else round(a, 4)
    out["posterior_predicts_disagreement_auc"] = auc
    out["postprocess_attribution"] = analyse_postprocess_attribution(df)
    out["targeting_summary"] = {
        "units_gt250ms_spread": int((df["spread"] > 0.25).sum()),
        "share_of_all_units": round(float((df["spread"] > 0.25).mean()), 4),
        "suggested_recompute_budget": {
            "top_10pct_spread_sec": round(float(np.percentile(sp, 90)), 3),
            "top_20pct_spread_sec": round(float(np.percentile(sp, 80)), 3),
            "top_5pct_spread_sec": round(float(np.percentile(sp, 95)), 3)},
        "note": "with no GT, a re-compute budget must be chosen from the disagreement quantiles",
    }
    return out
