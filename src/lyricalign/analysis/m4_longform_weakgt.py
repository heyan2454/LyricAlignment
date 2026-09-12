"""Long-form weak-GT panel assembled from the existing detector_v2 (M4Singer-concatenated) evidence.

Why this panel exists
---------------------
The 2026-09-12 GTSinger deep analysis could not answer the project's central long-form questions:
its clips are 5-15 s (window planning never activated, see ``MATRIX_AUDIT``) and every ground-truth
clip starts at 0.0 (so a hallucinated lead-in at a request start is unmeasurable there).

``research_v7_detector_v2/run{1,2}`` holds the missing substrate: per-unit predictions inside
200 s+ timelines, recorded for **both** the ``raw`` decoder stage and the ``official``
post-processed stage, with decoder entropies/margins, plus the project's own frozen per-unit quality
labels and absolute errors (``LABELS.jsonl``) computed against a canonical timeline.

Reference status (must be stated in every downstream claim)
----------------------------------------------------------
* the canonical timeline is derived from M4Singer note/phoneme annotations (``rule_validated`` weak
  supervision), **not** human ground truth;
* the "long" audio is produced by concatenating phrases with inserted silence (``m4singer_concat``,
  ``artificial_silence_sec``), i.e. synthetic length, which the current research_v7 formal policy
  forbids for headline results.  Conclusions here are about *seam* mechanics and stage-level
  post-processing, not about natural songs;
* provenance gap found while assembling this panel: the converted ``evidence_v2`` files are keyed by
  the attempt/evidence identity while ``manifests/ANOMALY_MANIFEST.jsonl`` keys requests by request
  identity, and the linking ``cached/`` attempt files were cleaned.  **Window/request-level
  attribution of this evidence is therefore not reconstructable**, so this module never claims a
  ``window_index``; it uses the timeline's own segment/seam structure instead.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

RUN_ROOT = Path("/home/hyan/Data/lyricalign/runs/research_v7_detector_v2")
SCHEMA_VERSION = "m4_longform_weakgt_panel_v1"
TOLS = (0.100, 0.200, 0.250)
SEED = 20260912


def timeline_paths() -> list[Path]:
    out: list[Path] = []
    for pat in ("*/manifests/LONG_TIMELINE_MANIFEST.jsonl",
                "timeline_v4/LONG_TIMELINE_MANIFEST.jsonl",
                "*/LONG_TIMELINE_MANIFEST.jsonl"):
        out.extend(p for p in sorted(RUN_ROOT.glob(pat)) if p.exists())
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _f(x: Any) -> float | None:
    try:
        return None if x is None else round(float(x), 4)
    except (TypeError, ValueError):
        return None


def load_timelines(paths: list[Path] | None = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Index canonical timelines (units, segment offsets, seam table) by song id."""
    index: dict[str, dict[str, Any]] = {}
    report: list[dict[str, Any]] = []
    for path in paths if paths is not None else timeline_paths():
        rows = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            song = row.get("song_id")
            if not song:
                continue
            units: dict[int, dict[str, Any]] = {}
            for u in row.get("canonical_units", []):
                try:
                    units[int(u["canonical_unit_id"])] = u
                except (KeyError, TypeError, ValueError):
                    continue
            segments = {str(seg.get("source_segment_id")): seg
                        for seg in row.get("segment_offsets", []) if isinstance(seg, dict)}
            seams = [{"left": s.get("left_source_segment_id"), "right": s.get("right_source_segment_id"),
                      "silence_sec": _f(s.get("inserted_silence_sec"))}
                     for s in row.get("seams", []) if isinstance(s, dict)]
            index[str(song)] = {"row": row, "units": units, "seams": seams, "segments": segments,
                                "duration_sec": _f(row.get("duration_sec")) or 0.0,
                                "artificial_silence_sec": _f(row.get("artificial_silence_sec"))}
            rows += 1
        report.append({"path": str(path), "rows": rows})
    return index, report


def iter_evidence_rows(path: Path) -> Iterator[list[dict[str, Any]]]:
    """Yield the per-unit record list of one converted evidence file."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, list):
                yield obj


def iter_label_rows(labels_path: Path) -> Iterator[dict[str, Any]]:
    with labels_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _counts(values: Iterator[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        key = str(v)
        out[key] = out.get(key, 0) + 1
    return out


@dataclass
class PanelStats:
    runs: list[dict[str, Any]]
    timelines: list[dict[str, Any]]
    rows: int = 0
    out: str = ""
    bytes: int = 0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "runs": self.runs,
                "timelines": self.timelines, "rows": self.rows, "out": self.out, "bytes": self.bytes}


def _load_boundaries(evidence_dir: Path, ident: str) -> dict[tuple[str, int], dict[str, Any]]:
    path = evidence_dir / f"{ident}.jsonl"
    if not path.exists():
        return {}
    for records in iter_evidence_rows(path):
        out: dict[tuple[str, int], dict[str, Any]] = {}
        for e in records:
            cid = e.get("canonical_unit_id")
            if cid is None:
                continue
            out[(str(e.get("view_id", "")), int(cid))] = e
        return out
    return {}


def build_run(run_dir: Path, timelines: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join one run's per-unit labels (raw + official) with its evidence boundaries and timeline GT."""
    labels_path = run_dir / "LABELS.jsonl"
    evidence_dir = run_dir / "evidence_v2"
    stats: dict[str, Any] = {"run": run_dir.name, "label_rows": 0, "label_requests": 0,
                            "requests_with_evidence": 0, "units": 0, "units_without_timeline": 0,
                            "families": {}, "raw_labels": {}}
    if not labels_path.exists():
        stats["missing"] = "LABELS.jsonl"
        return [], stats

    by_ident: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    meta: dict[str, dict[str, Any]] = {}
    for row in iter_label_rows(labels_path):
        stats["label_rows"] += 1
        ident = str(row.get("request_identity"))
        try:
            key = (str(row.get("view_id", "")), int(row.get("canonical_unit_id", -1)))
        except (TypeError, ValueError):
            continue
        cell = by_ident.setdefault(ident, {}).setdefault(key, {})
        target = str(row.get("target", ""))
        prefix = {"raw": "raw", "official": "off"}.get(target, target[:4])
        audit = row.get("audit") or {}
        cell[f"{prefix}_label"] = row.get("label")
        cell[f"{prefix}_reason"] = audit.get("reason")
        for src, dst in (("start_abs_error_sec", "start_err"), ("end_abs_error_sec", "end_err"),
                         ("worst_abs_error_sec", "both_err")):
            val = audit.get(src)
            if val is not None:
                cell[f"{prefix}_{dst}"] = round(float(val), 4)
        meta.setdefault(ident, {"song_id": row.get("song_id"), "family": row.get("family"),
                                "split": row.get("split")})
    stats["label_requests"] = len(by_ident)

    rows: list[dict[str, Any]] = []
    for ident, cells in by_ident.items():
        bounds = _load_boundaries(evidence_dir, ident)
        if not bounds:
            continue
        stats["requests_with_evidence"] += 1
        info = meta.get(ident, {})
        song = str(info.get("song_id", ""))
        tl = timelines.get(song)
        for (view, cid), cell in cells.items():
            ev = bounds.get((view, cid))
            if ev is None:
                continue
            gt_unit = tl["units"].get(cid) if tl else None
            if gt_unit is None:
                stats["units_without_timeline"] += 1
                continue
            gs, ge = _f(gt_unit.get("start_sec")), _f(gt_unit.get("end_sec"))
            if gs is None or ge is None:
                continue
            raw = ev.get("raw") or {}
            off = ev.get("official") or {}
            seg_id = str(gt_unit.get("source_segment_id", ""))
            seg = (tl.get("segments") or {}).get(seg_id) if tl else None
            rows.append({
                "run": run_dir.name,
                "request_identity": ident,
                "view_id": view,
                "song": song,
                "singer": (tl.get("row") or {}).get("singer_id", "") if tl else "",
                "family": info.get("family", ""),
                "split": info.get("split", ""),
                "canonical_unit_id": cid,
                "text": str(gt_unit.get("text", "")),
                "source_segment_id": seg_id,
                "source_unit_index": gt_unit.get("source_unit_index"),
                "segment_start_sec": _f(seg.get("global_start_sec")) if seg else None,
                "segment_n_units": seg.get("n_units") if seg else None,
                "timeline_duration_sec": round(float(tl["duration_sec"]) if tl else 0.0, 3),
                "artificial_silence_sec": tl.get("artificial_silence_sec") if tl else None,
                "gt_start_sec": gs, "gt_end_sec": ge, "gt_dur_sec": round(ge - gs, 4),
                "raw_start_sec": _f(raw.get("start_sec")), "raw_end_sec": _f(raw.get("end_sec")),
                "off_start_sec": _f(off.get("start_sec")), "off_end_sec": _f(off.get("end_sec")),
                "start_entropy": _f(raw.get("start_entropy")), "end_entropy": _f(raw.get("end_entropy")),
                "start_margin": _f(raw.get("start_margin")), "end_margin": _f(raw.get("end_margin")),
                "repair_start_shift_sec": _f(off.get("repair_start_shift_sec")),
                "repair_end_shift_sec": _f(off.get("repair_end_shift_sec")),
                "raw_label": cell.get("raw_label"), "raw_reason": cell.get("raw_reason"),
                "off_label": cell.get("off_label"), "off_reason": cell.get("off_reason"),
                "label_raw_start_err_sec": cell.get("raw_start_err"),
                "label_raw_end_err_sec": cell.get("raw_end_err"),
                "label_raw_both_err_sec": cell.get("raw_both_err"),
                "label_off_start_err_sec": cell.get("off_start_err"),
                "label_off_end_err_sec": cell.get("off_end_err"),
                "label_off_both_err_sec": cell.get("off_both_err"),
            })
    stats["units"] = len(rows)
    stats["families"] = _counts(r["family"] for r in rows)
    stats["raw_labels"] = _counts(r["raw_label"] for r in rows)
    return rows, stats


def run_timeline_manifest(run_dir: Path) -> Path | None:
    """Resolve the canonical timeline manifest a run was frozen against."""
    freeze = run_dir / "manifests" / "FREEZE.json"
    if not freeze.exists():
        return None
    try:
        blob = json.loads(freeze.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cli = blob.get("cli") or {}
    for key in ("timeline_manifest", "timeline", "long_timeline_manifest"):
        val = cli.get(key)
        if isinstance(val, str):
            path = Path(val)
            if path.name.endswith("LONG_TIMELINE_MANIFEST.jsonl"):
                return path
    return None


def build_panel(out_dir: Path, runs: tuple[str, ...] = ("run1", "run2")) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    run_stats: list[dict[str, Any]] = []
    tl_report: list[dict[str, Any]] = []
    cache: dict[Path, dict[str, dict[str, Any]]] = {}
    for name in runs:
        run_dir = RUN_ROOT / name
        manifest = run_timeline_manifest(run_dir)
        if manifest is None or not manifest.exists():
            # A run whose reference manifest is gone cannot be evaluated at all: joining it against
            # some other timeline of the same song name silently fabricates multi-second "errors".
            run_stats.append({"run": name, "excluded": "reference_timeline_missing",
                              "expected_timeline_manifest": str(manifest) if manifest else None})
            continue
        if manifest not in cache:
            indexed, report = load_timelines([manifest])
            cache[manifest] = indexed
            tl_report.extend(report)
        part, s = build_run(run_dir, cache[manifest])
        s["timeline_manifest"] = str(manifest)
        rows.extend(part)
        run_stats.append(s)
    out_path = out_dir / "longform_units.jsonl.gz"
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    stats = PanelStats(runs=run_stats, timelines=tl_report, rows=len(rows), out=str(out_path),
                       bytes=out_path.stat().st_size).to_dict()
    (out_dir / "PANEL_SUMMARY.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    return stats


# ---------------------------------------------------------------------------
# frame
# ---------------------------------------------------------------------------

def frame_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Same derivation as :func:`load_frame`, from in-memory panel rows (used by tests)."""
    return _derive(pd.DataFrame(rows))


def load_frame(path: Path) -> pd.DataFrame:
    return _derive(pd.read_json(path, lines=True, compression="infer"))


def _derive(df: pd.DataFrame) -> pd.DataFrame:
    df["req_key"] = df["run"] + "|" + df["request_identity"].astype(str) + "|" + df["view_id"].astype(str)
    df["final_start_sec"] = df["off_start_sec"].fillna(df["raw_start_sec"])
    df["final_end_sec"] = df["off_end_sec"].fillna(df["raw_end_sec"])
    # The timeline's ``canonical_units`` carry a **synthetic-uniform** time axis (see
    # scripts/research_v7/label_detector_v2_run.py header).  Predictions joined against it measure
    # that fabricated axis, not ground truth -- so the authoritative numbers are the run's own frozen
    # per-unit errors (label_*), which were computed against the real per-segment M4Singer GT.
    df["raw_both_err_uniformaxis"] = np.maximum((df["raw_start_sec"] - df["gt_start_sec"]).abs(),
                                                 (df["raw_end_sec"] - df["gt_end_sec"]).abs())
    df["final_both_err_uniformaxis"] = np.maximum(
        (df["final_start_sec"] - df["gt_start_sec"]).abs(),
        (df["final_end_sec"] - df["gt_end_sec"]).abs())
    for col, src in (("raw_start_err", "label_raw_start_err_sec"),
                     ("raw_end_err", "label_raw_end_err_sec"),
                     ("raw_both_err", "label_raw_both_err_sec"),
                     ("final_start_err", "label_off_start_err_sec"),
                     ("final_end_err", "label_off_end_err_sec"),
                     ("final_both_err", "label_off_both_err_sec")):
        # panels without the frozen label columns degrade to NaN (never to the fabricated axis)
        df[col] = df[src] if src in df.columns else np.nan
    for src in ("raw", "final"):
        df[f"{src}_dur"] = df[f"{src}_end_sec"] - df[f"{src}_start_sec"]
    # signed bias is NOT recoverable against real GT from these artifacts (the frozen audit stores
    # absolute errors only); these are uniform-axis quantities and are labelled as such.
    df["final_start_signed_uniformaxis"] = df["final_start_sec"] - df["gt_start_sec"]
    df["final_end_signed_uniformaxis"] = df["final_end_sec"] - df["gt_end_sec"]
    df["raw_start_signed_uniformaxis"] = df["raw_start_sec"] - df["gt_start_sec"]
    df["raw_end_signed_uniformaxis"] = df["raw_end_sec"] - df["gt_end_sec"]
    for tol in TOLS:
        tag = str(int(round(tol * 1000)))
        df[f"final_bad{tag}"] = (df["final_both_err"] > tol).astype(float)
        df[f"raw_bad{tag}"] = (df["raw_both_err"] > tol).astype(float)
    df["is_segment_first"] = ((df["source_unit_index"] == 0).astype(float)
                              if "source_unit_index" in df.columns else np.nan)
    # position inside the source phrase *on the fabricated uniform axis* (coarse rank only)
    df["dist_into_segment_uniformaxis"] = df["gt_start_sec"] - df["segment_start_sec"]
    df["max_ent"] = df[["start_entropy", "end_entropy"]].max(axis=1)
    df["min_ent"] = df[["start_entropy", "end_entropy"]].min(axis=1)
    df["min_margin"] = df[["start_margin", "end_margin"]].min(axis=1)
    df["ent_mean"] = df[["start_entropy", "end_entropy"]].mean(axis=1)
    return df


def baseline_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Baseline (unmutated-text) requests with both stages and a usable reference."""
    fam = df["family"].astype(str)
    ok = fam.str.startswith("baseline")
    out = df[ok].copy()
    return out[out["raw_both_err"].notna() & out["final_both_err"].notna()]


# ---------------------------------------------------------------------------
# analyses
# ---------------------------------------------------------------------------

def _auc(y: np.ndarray, s: np.ndarray, min_n: int = 50) -> float | None:
    y = np.asarray(y, dtype=float)
    s = np.asarray(s, dtype=float)
    mask = np.isfinite(y) & np.isfinite(s)
    y, s = y[mask], s[mask]
    if len(y) < min_n or y.min() == y.max():
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    n_pos = float(y.sum())
    n_neg = float(len(y) - n_pos)
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _paired(a: pd.Series, b: pd.Series, n_boot: int = 800) -> dict[str, Any]:
    d = (a.to_numpy(dtype=float) - b.to_numpy(dtype=float))
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return {"available": False}
    rng = np.random.default_rng(SEED)
    draws = np.array([d[rng.choice(len(d), len(d), True)].mean() for _ in range(n_boot)])
    return {"available": True, "n_units_paired": int(len(d)),
            "mean_diff_pp": round(float(d.mean() * 100), 3),
            "ci95_pp": [round(float(np.percentile(draws, 2.5) * 100), 3),
                        round(float(np.percentile(draws, 97.5) * 100), 3)],
            "a_better": int((d > 0).sum()), "b_better": int((d < 0).sum()), "tied": int((d == 0).sum())}


def _block(sub: pd.DataFrame, stage: str = "final") -> dict[str, Any]:
    """Band profile of a subset against the run's frozen real-GT errors."""
    if not len(sub):
        return {"n": 0}
    err = sub[f"{stage}_both_err"]
    lab = sub[f"{stage.replace('final', 'off')}_label"].astype(str)
    return {"n": int(len(sub)),
            "hit100": round(float((err <= 0.1).mean()), 4),
            "grey_100_250": round(float(((err > 0.1) & (err < 0.25)).mean()), 4),
            "unsafe_ge250": round(float((err >= 0.25).mean()), 4),
            "mae": round(float(err.mean()), 4),
            "median_abs": round(float(err.median()), 4),
            "p90_abs": round(float(np.percentile(err, 90)), 4),
            "label_unsafe_share": round(float((lab == "unsafe").mean()), 4),
            "label_safe_share": round(float((lab == "safe").mean()), 4)}


def analyse(df: pd.DataFrame) -> dict[str, Any]:
    base = baseline_frame(df)
    out: dict[str, Any] = {"schema": "m4_longform_weakgt_analysis_v1",
                           "reference_caveat": "M4Singer-derived weak supervision on synthetic "
                                               "concatenated timelines: not human GT, not natural length"}
    out["panel"] = {
        "unit_rows": int(len(df)), "baseline_unit_rows": int(len(base)),
        "requests": int(df["request_identity"].nunique()),
        "baseline_requests": int(base["request_identity"].nunique()),
        "songs": int(df["song"].nunique()),
        "singers": sorted({str(v) for v in df["singer"]}),
        "families": _counts(df["family"]), "views": _counts(df["view_id"]),
        "timeline_duration_sec": {"min": round(float(df["timeline_duration_sec"].min()), 1),
                                  "median": round(float(df["timeline_duration_sec"].median()), 1),
                                  "max": round(float(df["timeline_duration_sec"].max()), 1)},
        "artificial_silence_sec": sorted({float(v) for v in df["artificial_silence_sec"].dropna()}),
        "gt_dur_sec_quantiles": {str(q): round(float(np.percentile(base["gt_dur_sec"], q)), 4)
                                 for q in (1, 5, 25, 50, 75, 95, 99)},
    }
    # The fabricated-axis trap, quantified: joining predictions to timeline.canonical_units times
    # (a synthetic uniform axis) instead of using the run's frozen real-GT errors.
    chk = base.dropna(subset=["raw_both_err", "raw_both_err_uniformaxis"])
    if len(chk) > 200:
        delta = (chk["raw_both_err_uniformaxis"] - chk["raw_both_err"]).abs()
        corr = float(np.corrcoef(chk["raw_both_err_uniformaxis"], chk["raw_both_err"])[0, 1])
        out["uniform_axis_trap"] = {
            "n_units": int(len(chk)),
            "median_abs_disagreement_sec": round(float(delta.median()), 3),
            "p90_abs_disagreement_sec": round(float(np.percentile(delta, 90)), 3),
            "share_within_20ms": round(float((delta <= 0.02).mean()), 4),
            "hit100_if_uniform_axis_used": round(float((chk["raw_both_err_uniformaxis"] <= 0.1).mean()), 4),
            "hit100_with_frozen_real_gt": round(float((chk["raw_both_err"] <= 0.1).mean()), 4),
            "pearson_corr_of_two_error_definitions": round(corr, 4),
            "implication": "re-analysis that reads timeline.canonical_units[*].start_sec as ground "
                           "truth measures a fabricated uniform axis; only the frozen label_* "
                           "columns (built from per-segment M4Singer GT) are usable",
        }

    if base.empty:
        out["empty"] = True
        return out

    # A. what the reference actually is, and how much of it is usable
    out["reference_profile"] = {
        "kind": "M4Singer per-segment character GT offset into the concatenated timeline "
                "(labeler: scripts/research_v7/label_detector_v2_run.py build_song_gt)",
        "bands_sec": {"safe_max": 0.100, "unsafe_min": 0.250},
        "frozen_raw_label_shares": _counts(base["raw_label"].astype(str)),
        "frozen_official_label_shares": _counts(base["off_label"].astype(str)),
        "units_with_usable_real_gt": int(len(base)),
        "gt_dur_sec_is_fabricated_axis": True,
    }

    # B. stage comparison on long data (replication of the GTSinger post-processing finding)
    out["stage_comparison"] = {
        "micro_hit100_raw": round(float((base["raw_both_err"] <= 0.1).mean()), 4),
        "micro_hit100_official": round(float((base["final_both_err"] <= 0.1).mean()), 4),
        "micro_unsafe_ge250_raw": round(float((base["raw_both_err"] >= 0.25).mean()), 4),
        "micro_unsafe_ge250_official": round(float((base["final_both_err"] >= 0.25).mean()), 4),
        "mae_raw_sec": round(float(base["raw_both_err"].mean()), 4),
        "mae_official_sec": round(float(base["final_both_err"].mean()), 4),
        "median_raw_sec": round(float(base["raw_both_err"].median()), 4),
        "median_official_sec": round(float(base["final_both_err"].median()), 4),
        "zero_dur_raw": round(float((base["raw_dur"] <= 1e-6).mean()), 4),
        "zero_dur_official": round(float((base["final_dur"] <= 1e-6).mean()), 4),
        "paired_unit_hit100_official_minus_raw_pp": round(float(
            ((base["final_both_err"] <= 0.1).astype(float)
             - (base["raw_both_err"] <= 0.1).astype(float)).mean() * 100), 3),
    }
    seg_hit = base.groupby("req_key", observed=True).apply(
        lambda g: pd.Series({"raw": (g["raw_both_err"] <= 0.1).mean(),
                             "off": (g["final_both_err"] <= 0.1).mean()}), include_groups=False)
    out["stage_comparison"]["paired_segment_hit100_delta"] = _paired(
        seg_hit["raw"], seg_hit["off"])

    shift = np.maximum((base["off_start_sec"] - base["raw_start_sec"]).abs(),
                       (base["off_end_sec"] - base["raw_end_sec"]).abs())
    touched = base[shift.to_numpy() > 1e-3].copy()
    if len(touched):
        rb = touched["raw_both_err"].to_numpy(dtype=float)
        ob = touched["final_both_err"].to_numpy(dtype=float)
        mech: dict[str, Any] = {
            "n_touched": int(len(touched)),
            "share_units_touched": round(float(len(touched) / len(base)), 4),
            "repair_rate": round(float(((ob + 1e-9) < rb).mean()), 4),
            "damage_rate": round(float(((rb + 1e-9) < ob).mean()), 4),
            "mean_abs_err_raw_sec": round(float(rb.mean()), 4),
            "mean_abs_err_official_sec": round(float(ob.mean()), 4),
            "hit100_raw": round(float((rb <= 0.1).mean()), 4),
            "hit100_official": round(float((ob <= 0.1).mean()), 4),
        }
        moved_start = np.abs((touched["off_start_sec"] - touched["raw_start_sec"]).to_numpy(dtype=float)) > 1e-3
        if moved_start.any():
            sub_sorted = touched.sort_values(["req_key", "canonical_unit_id"])
            pe = sub_sorted.groupby("req_key", observed=True)["off_end_sec"].shift(1).to_numpy(dtype=float)
            ms = np.abs((sub_sorted["off_start_sec"] - sub_sorted["raw_start_sec"]).to_numpy(dtype=float)) > 1e-3
            mech["start_moved"] = {
                "n": int(ms.sum()),
                "share_pinned_to_prev_end": round(float(np.nanmean(
                    np.abs(sub_sorted["off_start_sec"].to_numpy()[ms] - pe[ms]) <= 2e-3)), 4),
                "mean_shift_sec": round(float(np.mean((sub_sorted["off_start_sec"] - sub_sorted["raw_start_sec"])
                                                      .to_numpy()[ms])), 4),
                "direction_later": int((np.mean(np.sign((sub_sorted["off_start_sec"] - sub_sorted["raw_start_sec"])
                                                        .to_numpy()[ms]))) > 0)}
        out["postprocess_on_longform"] = mech
    else:
        out["postprocess_on_longform"] = {"n_touched": 0, "share_units_touched": 0.0}

    # C. phrase-start effect (long-form analogue of the GTSinger request-start problem)
    first_mask = base["is_segment_first"] == 1
    out["segment_boundary_effect"] = {
        "segment_first_units_raw": _block(base[first_mask], "raw"),
        "segment_first_units_official": _block(base[first_mask], "final"),
        "other_units_raw": _block(base[~first_mask], "raw"),
        "other_units_official": _block(base[~first_mask], "final"),
        "n_segments": int(base["source_segment_id"].nunique()),
        "note": "band shares only: signed bias is unrecoverable from the frozen audit (absolute errors)"}

    b = base.copy()
    b["rank_bucket"] = pd.cut(b["source_unit_index"].astype(float),
                              [-0.5, 0.5, 1.5, 3.5, 7.5, 1e9],
                              labels=["1st unit", "2nd", "3rd-4th", "5th-8th", ">8th"])
    tab = b.groupby("rank_bucket", observed=True).agg(
        n=("raw_both_err", "size"), raw_hit100=("raw_both_err", lambda x: (x <= 0.1).mean()),
        off_hit100=("final_both_err", lambda x: (x <= 0.1).mean()),
        raw_unsafe=("raw_both_err", lambda x: (x >= 0.25).mean())).reset_index()
    out["position_in_phrase_profile"] = [{"bucket": str(r.rank_bucket), "n": int(r.n),
                                          "raw_hit100": round(float(r.raw_hit100), 4),
                                          "official_hit100": round(float(r.off_hit100), 4),
                                          "raw_unsafe_share": round(float(r.raw_unsafe), 4)}
                                         for r in tab.itertuples()]

    # D. no-GT signals on this panel (cross-domain transfer of the GTSinger finding)
    sig: dict[str, Any] = {}
    for name in ("start_entropy", "end_entropy", "max_ent", "min_ent", "ent_mean",
                 "start_margin", "end_margin", "min_margin",
                 "repair_start_shift_sec", "repair_end_shift_sec"):
        if name not in base:
            continue
        entry = {}
        for tol in TOLS:
            tag = str(int(round(tol * 1000)))
            a = _auc((base["final_both_err"] > tol).to_numpy(dtype=float),
                     base[name].to_numpy(dtype=float))
            entry[f"bad{tag}"] = None if a is None else round(a, 4)
        sig[name] = entry
    ranked = sorted(((k, (v.get("bad250") or 0)) for k, v in sig.items()), key=lambda kv: -kv[1])
    out["confidence_signals"] = {
        "auc_per_signal": sig,
        "ranking_by_bad250": [{"signal": k, "oriented_auc": round((v if v >= 0.5 else 1 - v), 4),
                              "higher_means_worse": bool(v >= 0.5)} for k, v in ranked],
        "comparison_with_gtsinger": {"gtsinger_end_entropy_auc_bad100": 0.8167,
                                     "note": "different reference kind (weak vs human) and different "
                                             "task length; compare direction, not absolute level"},
    }
    out["gate"] = _gate(base)

    # E. official-label cross-check: does the project's own unsafe label agree with >250ms error?
    lab = base.dropna(subset=["raw_label", "label_raw_both_err_sec"])
    if len(lab) > 200:
        agree = {}
        for name, err in (("raw_label", "label_raw_both_err_sec"),
                          ("off_label", "label_off_both_err_sec")):
            sub = lab.dropna(subset=[name, err])
            if sub.empty:
                continue
            y = (sub[err] > 0.25).astype(float).to_numpy(dtype=float)
            unsafe = (sub[name].astype(str) == "unsafe").to_numpy(dtype=float)
            if y.min() == y.max() or unsafe.min() == unsafe.max():
                continue
            agree[name] = {
                "n": int(len(sub)),
                "share_labelled_unsafe": round(float(unsafe.mean()), 4),
                "unsafe_precision_vs_250ms": round(float(y[unsafe > 0.5].mean()), 4),
                "unsafe_recall_of_250ms_errors": round(float(unsafe[y > 0.5].mean()), 4),
                "auc_label_vs_err": round(float(_auc(y, unsafe) or 0.0), 4),
                "mean_abs_err_when_unsafe_sec": round(float(sub.loc[unsafe > 0.5, err].mean()), 4),
                "mean_abs_err_when_safe_sec": round(float(
                    sub.loc[sub[name].astype(str) == "safe", err].mean()), 4)}
        out["frozen_label_crosscheck"] = agree
    out["view_agreement"] = _view_agreement(df)
    out["text_error_collateral"] = analyse_text_error_collateral(df)
    return out


def _gate(base: pd.DataFrame) -> dict[str, Any]:
    feats = ["start_entropy", "end_entropy", "start_margin", "end_margin",
             "repair_start_shift_sec", "repair_end_shift_sec"]
    feats = [f for f in feats if f in base.columns]
    work = base.assign(bad250=(base["final_both_err"] > 0.25).astype(float),
                       bad100=(base["final_both_err"] > 0.1).astype(float))
    sub = work[feats + ["bad250", "bad100", "req_key"]].replace(
        [np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 2000 or sub["req_key"].nunique() < 6:
        return {"available": False, "reason": "insufficient_complete_rows",
                "n_rows": int(len(sub))}
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    X = sub[feats].to_numpy(dtype=float)
    groups = sub["req_key"].to_numpy()
    res: dict[str, Any] = {"available": True, "features": feats,
                           "groups": int(sub["req_key"].nunique())}
    for label in ("bad250", "bad100"):
        y = sub[label].to_numpy(dtype=float)
        if y.min() == y.max():
            continue
        pipe = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression(max_iter=2000))])
        oof = np.zeros(len(y))
        for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
            pipe.fit(X[tr], y[tr])
            oof[te] = pipe.predict_proba(X[te])[:, 1]
        order = np.argsort(-oof)
        ys = y[order]
        res[label] = {"n_rows": int(len(y)), "positive_rate": round(float(y.mean()), 4),
                      "oof_auc": round(float(roc_auc_score(y, oof)), 4),
                      "oof_ap": round(float(average_precision_score(y, oof)), 4),
                      "review_budget_curve": {
                          f"flag_{int(f * 100)}pct": {
                              "precision": round(float(ys[:max(int(round(f * len(y))), 1)].mean()), 4),
                              "recall": round(float(ys[:max(int(round(f * len(y))), 1)].sum()
                                                    / max(ys.sum(), 1)), 4)}
                          for f in (0.05, 0.10, 0.20, 0.30)}}
    return res


# ---------------------------------------------------------------------------
# text-error collateral damage (mainline question: how much of an output is
# salvageable when the *lyric text* handed to the aligner is partly wrong?)
# ---------------------------------------------------------------------------

TAIL_FAMILIES = ("end_early", "end_late", "crop_late", "repeated_section")
HEAD_FAMILIES = ("crop_early",)
SHIFT_FAMILIES = ("cursor_shift",)


def _rank_profile(sub: pd.DataFrame) -> dict[str, Any]:
    """Error profile of surviving (non-mutated) units, positioned by rank from each edge."""
    if sub.empty:
        return {"n": 0}
    err = sub["final_both_err"]
    return {
        "n_units": int(len(sub)),
        "n_requests": int(sub["req_key"].nunique()),
        "hit100": round(float((err <= 0.1).mean()), 4),
        "unsafe_ge250": round(float((err >= 0.25).mean()), 4),
        "mae_sec": round(float(err.mean()), 4),
        "median_sec": round(float(err.median()), 4),
    }


def analyse_text_error_collateral(df: pd.DataFrame) -> dict[str, Any]:
    """Do mutated lyric texts corrupt the units that the mutation did *not* touch?

    Detector V2 spent its budget on *detecting* unsafe output.  The complementary quantity -- how
    far a text error propagates into otherwise-correct units -- decides how much of a window is
    salvageable and therefore how large a realign region has to be.  Both quantities are available
    from the same retained evidence: per-request text-mutation family plus per-unit frozen errors
    for units whose canonical id is untouched by the mutation.
    """
    d = df.dropna(subset=["final_both_err"]).copy()
    if d.empty:
        return {"available": False}
    rng = d.groupby(["req_key", "family"], observed=True)["canonical_unit_id"].agg(["min", "max"])
    d = d.merge(rng.rename(columns={"min": "cid_min", "max": "cid_max"}),
                left_on=["req_key", "family"], right_index=True, how="left")
    d["rank_from_start"] = d["canonical_unit_id"] - d["cid_min"]
    d["rank_from_end"] = d["cid_max"] - d["canonical_unit_id"]
    d["span"] = d["cid_max"] - d["cid_min"] + 1
    d["frac_pos"] = d["rank_from_start"] / d["span"].clip(lower=1)

    out: dict[str, Any] = {"schema": "m4_longform_text_error_collateral_v1",
                           "caveat": "canonical_unit_id rank is a proxy for text position; the "
                                     "mutation geometry itself is not retained per evidence identity"}
    base = d[d["family"].astype(str).str.startswith("baseline")]
    out["baseline_reference"] = _rank_profile(base)
    out["by_family"] = {str(f): _rank_profile(sub) for f, sub in d.groupby("family", observed=True)}

    # surviving-unit profiles, positioned relative to the damaged end
    def edge_profile(fams: tuple[str, ...], from_edge: str, label: str) -> dict[str, Any]:
        sub = d[d["family"].astype(str).isin(fams)].copy()
        if sub.empty:
            return {"available": False, "families": list(fams)}
        col = "rank_from_start" if from_edge == "start" else "rank_from_end"
        buckets = [-0.5, 2.5, 7.5, 17.5, 1e9]
        names = ["1-3 units from damaged edge", "4-8", "9-18", ">18"]
        sub["bucket"] = pd.cut(sub[col], buckets, labels=names)
        tab = sub.groupby("bucket", observed=True).agg(
            n=("final_both_err", "size"), hit100=("final_both_err", lambda x: (x <= 0.1).mean()),
            unsafe=("final_both_err", lambda x: (x >= 0.25).mean()),
            mae=("final_both_err", "mean")).reset_index()
        rows = [{"bucket": str(r.bucket), "n": int(r.n), "hit100": round(float(r.hit100), 4),
                 "unsafe_ge250": round(float(r.unsafe), 4), "mae_sec": round(float(r.mae), 4)}
                for r in tab.itertuples()]
        far = sub[sub[col] > 18]
        ref_far = base[base[col] > 18] if col in base else base
        entry: dict[str, Any] = {"available": True, "families": list(fams), "profile": rows,
                                 "far_from_edge": _rank_profile(far),
                                 "baseline_far_from_edge": _rank_profile(ref_far)}
        if len(far) > 200 and len(ref_far) > 200:
            entry["far_hit100_minus_baseline_pp"] = round(float(
                ((far["final_both_err"] <= 0.1).mean()
                 - (ref_far["final_both_err"] <= 0.1).mean()) * 100), 3)
            entry["far_unsafe_minus_baseline_pp"] = round(float(
                ((far["final_both_err"] >= 0.25).mean()
                 - (ref_far["final_both_err"] >= 0.25).mean()) * 100), 3)
        entry["label"] = label
        return entry

    out["tail_mutations_survivors"] = edge_profile(TAIL_FAMILIES, "start",
                                                   "text damaged at the tail: leading survivors")
    out["head_mutations_survivors"] = edge_profile(HEAD_FAMILIES, "end",
                                                   "text damaged at the head: trailing survivors")
    out["shift_mutations_profile"] = edge_profile(SHIFT_FAMILIES, "start",
                                                  "cursor-shifted text: whole-request profile")

    # paired comparison on the *same* canonical unit, baseline vs mutated request
    pairs = (base[["song", "canonical_unit_id", "final_both_err", "raw_both_err"]]
             .rename(columns={"final_both_err": "base_err", "raw_both_err": "base_raw_err"})
             .merge(d[~d["family"].astype(str).str.startswith("baseline")]
                    [["song", "canonical_unit_id", "family", "req_key", "final_both_err"]]
                    .rename(columns={"final_both_err": "mut_err"}),
                    on=["song", "canonical_unit_id"], how="inner"))
    if not pairs.empty:
        per_family = {}
        for fam, sub in pairs.groupby("family", observed=True):
            delta = sub["mut_err"] - sub["base_err"]
            rng2 = np.random.default_rng(SEED)
            draws = np.array([delta.to_numpy()[rng2.choice(len(delta), len(delta), True)].mean()
                              for _ in range(400)])
            per_family[str(fam)] = {
                "n_paired_units": int(len(sub)),
                "mean_err_delta_sec": round(float(delta.mean()), 4),
                "ci95_sec": [round(float(np.percentile(draws, 2.5)), 4),
                             round(float(np.percentile(draws, 97.5)), 4)],
                "hit100_delta_pp": round(float(((sub["mut_err"] <= 0.1).mean()
                                                - (sub["base_err"] <= 0.1).mean()) * 100), 3),
                "share_mut_worse": round(float((delta > 0.001).mean()), 4),
                "share_mut_better": round(float((delta < -0.001).mean()), 4)}
        out["paired_same_unit_baseline_vs_mutated"] = per_family
    out["realign_region_implication"] = {
        "question": "how large must a re-align region be when part of the text is wrong?",
        "answer_from_this_panel": "see far_from_edge vs baseline_far_from_edge: if survivors far "
                                  "from the damaged edge already match the baseline profile, a "
                                  "local region around the damaged span is sufficient",
    }
    return out


def _view_agreement(df: pd.DataFrame) -> dict[str, Any]:
    counts = df.groupby(["request_identity", "canonical_unit_id"], observed=True)["view_id"].nunique()
    if counts.max() < 2:
        return {"available": False, "reason": "one_view_per_request_unit",
                "note": "MULTIVIEW requests are separate evidence identities in this run"}
    pair = df.pivot_table(index=["request_identity", "canonical_unit_id"], columns="view_id",
                          values="final_start_sec", aggfunc="first").dropna()
    spread = (pair.max(axis=1) - pair.min(axis=1)).to_numpy(dtype=float)
    return {"available": True, "n_units_with_views": int(len(pair)),
            "views": [str(c) for c in pair.columns],
            "start_spread_median_sec": round(float(np.median(spread)), 4),
            "start_spread_p90_sec": round(float(np.percentile(spread, 90)), 4),
            "share_spread_gt_100ms": round(float((spread > 0.1).mean()), 4)}
