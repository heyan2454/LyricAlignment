"""Per-unit ground-truth evidence extraction for GTSinger evaluation runs.

Background
----------
``evaluation_v1`` GTSinger runs store, for every segment, a 3 x 2 x 2 alignment
matrix (models ``r0/r1/r2`` x audio input ``mix/vocal`` x planning mode
``full/windowed``) plus the word-level GTSinger ground truth (phoneme timings,
note pitches/durations, per-phoneme technique flags and song metadata).  The
published analyses only aggregate *one* config (``r*/vocal/windowed``) into
hit-rate tables, so nothing in the repository quantifies error structure against
the covariates that GTSinger actually provides, nor uses the recorded decoder
posteriors.

This module joins, for every (item, config, unit):

* the ground-truth unit (word text, interval, note/phoneme structure, technique
  flags, ``pace``/``range``/``emotion``/``singing_method``),
* every prediction stage (``raw`` / ``fixed`` / ``selected`` intervals),
* the recorded decoder confidence (top-1 probability, margin, entropy, candidate
  count) and repair flags,
* window-planning context (which window committed the unit, distance to the
  window core boundary, position inside the window),

into one compact JSON row per unit.  Rows are the analytical substrate; they are
small (a few bytes per field) and written gzip-compressed so that repeated
analyses cost seconds instead of re-parsing gigabytes of ``alignment.json``.

The extractor is deliberately strict: an item/config whose predicted unit count
does not match the filtered ground-truth count is *skipped with a recorded
reason* instead of being index-joined, so a mis-tokenized lyric can never
silently poison the metrics.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = "gtsinger_gt_unit_evidence_v1"

TECHNIQUE_FLAGS = ("mix", "falsetto", "breathy", "pharyngeal", "glissando", "vibrato")
MODELS = ("r0", "r1", "r2")
AUDIO_INPUTS = ("mix", "vocal")
MODES = ("full", "windowed")

MISSING = -1.0  # sentinel for absent numeric covariates (keeps rows fixed-shape)


def is_ap_marker(word: Any) -> bool:
    """Same ``<AP>`` aspiration filter used by ``evaluate_gtsinger_alignment.py``."""
    text = str(word or "").upper().replace("<AP/>", "<AP>")
    return text == "<AP>"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _round(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)


def clean_gt_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("gt-json must contain a JSON array")
    return [row for row in data if isinstance(row, dict) and not is_ap_marker(row.get("word"))]


def gt_unit_features(gt: dict[str, Any], index: int, count: int) -> dict[str, Any]:
    """Flatten one GTSinger word annotation into analysis-ready covariates."""
    start = _num(gt.get("start_time"))
    end = _num(gt.get("end_time"))
    dur = None if (start is None or end is None) else end - start

    notes = [n for n in gt.get("note", []) if isinstance(n, (int, float))]
    note_dur = [_num(x) for x in gt.get("note_dur", [])]
    note_dur = [x for x in note_dur if x is not None]
    ph = [str(x) for x in gt.get("ph", []) if str(x)]
    ph_dur: list[float] = []
    ph_start = [_num(x) for x in gt.get("ph_start", [])]
    ph_end = [_num(x) for x in gt.get("ph_end", [])]
    for a, b in zip(ph_start, ph_end):
        if a is not None and b is not None:
            ph_dur.append(b - a)

    flags: dict[str, int] = {}
    for key in TECHNIQUE_FLAGS:
        vals = [str(v) for v in gt.get(key, [])]
        flags[key] = 1 if any(v not in ("", "0", "None", "none") for v in vals) else 0

    tech_vals = [str(v) for v in gt.get("tech", []) if str(v) not in ("", "0", "None")]

    return {
        "unit_index": index,
        "unit_pos_frac": _round(index / max(count - 1, 1), 3),
        "text": str(gt.get("word", "")),
        "gt_start_sec": _round(start, 3),
        "gt_end_sec": _round(end, 3),
        "gt_dur_sec": _round(dur, 3),
        "gt_note_count": len(notes),
        "gt_pitch": _round(float(notes[0]), 1) if notes else MISSING,
        "gt_pitch_last": _round(float(notes[-1]), 1) if notes else MISSING,
        "gt_pitch_span": _round(float(max(notes) - min(notes)), 1) if notes else MISSING,
        "gt_note_dur_sec": _round(sum(note_dur) / len(note_dur), 4) if note_dur else MISSING,
        "gt_ph_count": len(ph),
        "gt_phonemes": "|".join(ph),
        "gt_ph_dur_max_sec": _round(max(ph_dur), 3) if ph_dur else MISSING,
        "gt_ph_dur_min_sec": _round(min(ph_dur), 3) if ph_dur else MISSING,
        "gt_is_melisma": 1 if len(notes) > 1 else 0,
        "gt_is_multi_phoneme": 1 if len(ph) > 1 else 0,
        "gt_tech": "|".join(sorted(set(tech_vals))),
        "singing_method": str(gt.get("singing_method", "")),
        "pace": str(gt.get("pace", "")),
        "range": str(gt.get("range", "")),
        "emotion": str(gt.get("emotion", "")),
        **{f"gt_flag_{k}": v for k, v in flags.items()},
    }


def window_context(trace: Any) -> list[dict[str, Any]]:
    """Per-unit window provenance from ``window_trace`` (empty list when absent).

    Uses ``committed_character_start/end`` when present and falls back to the
    candidate span.  For every unit index inside a window's committed range we
    record the window ordinal, the window core interval and the signed distance
    from the unit to the window core edges plus the ordinal position inside the
    window (first / last committed units are seam-adjacent).
    """
    spans: list[dict[str, Any]] = []
    if not isinstance(trace, list):
        return spans
    for w_idx, win in enumerate(trace):
        if not isinstance(win, dict):
            continue
        c_start = win.get("committed_character_start")
        c_end = win.get("committed_character_end")
        if c_start is None:
            c_start = win.get("candidate_character_start")
        if c_end is None:
            c_end = win.get("candidate_character_end")
        if c_start is None or c_end is None:
            continue
        spans.append(
            {
                "window_index": w_idx,
                "char_start": int(c_start),
                "char_end": int(c_end),
                "core_start_sec": _num(win.get("core_start_sec")),
                "core_end_sec": _num(win.get("core_end_sec")),
                "left_ctx_chars": int(win.get("left_context_character_count") or 0),
                "serial_policy": str(win.get("serial_policy", "")),
            }
        )
    return spans


def _window_for_unit(spans: list[dict[str, Any]], unit_index: int) -> dict[str, Any] | None:
    # Later windows overwrite earlier ones on overlap: committed ranges are
    # disjoint by construction, so this only matters for degenerate traces.
    match = None
    for span in spans:
        if span["char_start"] <= unit_index < span["char_end"]:
            match = span
    return match


def _interval_metrics(pred_start: float | None, pred_end: float | None,
                      gt_start: float | None, gt_end: float | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "start_err_signed_sec": None,
        "end_err_signed_sec": None,
        "start_abs_err_sec": None,
        "end_abs_err_sec": None,
        "both_abs_err_sec": None,
        "iou": None,
        "center_offset_sec": None,
        "dur_err_sec": None,
    }
    if None in (pred_start, pred_end, gt_start, gt_end):
        return out
    se = pred_start - gt_start
    ee = pred_end - gt_end
    out["start_err_signed_sec"] = _round(se, 3)
    out["end_err_signed_sec"] = _round(ee, 3)
    out["start_abs_err_sec"] = _round(abs(se), 3)
    out["end_abs_err_sec"] = _round(abs(ee), 3)
    out["both_abs_err_sec"] = _round(max(abs(se), abs(ee)), 3)
    out["dur_err_sec"] = _round((pred_end - pred_start) - (gt_end - gt_start), 3)
    inter = max(0.0, min(pred_end, gt_end) - max(pred_start, gt_start))
    union = max(pred_end, gt_end) - min(pred_start, gt_start)
    out["iou"] = _round(inter / union, 3) if union > 0 else None
    out["center_offset_sec"] = _round((pred_start + pred_end) / 2 - (gt_start + gt_end) / 2, 3)
    return out


@dataclass
class RunSpec:
    """One evaluation run root plus its pipeline label."""

    path: Path
    pipeline: str  # "official" | "raw"
    tag: str = ""

    @staticmethod
    def infer(path: Path) -> "RunSpec":
        name = path.name.lower()
        pipeline = "raw" if ("rawdec" in name or "_raw_" in name) else "official"
        tag = path.name
        return RunSpec(path=path, pipeline=pipeline, tag=tag)


@dataclass
class ExtractionStats:
    runs: int = 0
    items_seen: int = 0
    items_skipped: list[dict[str, Any]] = field(default_factory=list)
    configs_ok: int = 0
    configs_missing: int = 0
    configs_skipped: int = 0
    units: int = 0


def iter_item_dirs(run_root: Path) -> Iterator[tuple[Path, Path]]:
    """Yield ``(item_dir, gt_json)`` from a run's ``gt_map.jsonl``."""
    gt_map = run_root / "gt_map.jsonl"
    if not gt_map.exists():
        return
    for line in gt_map.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        gt_json = rec.get("gt_json")
        out_dir = rec.get("out_dir")
        if not gt_json or not out_dir:
            continue
        yield run_root / str(out_dir), Path(gt_json)


def extract_item(item_dir: Path, gt_json: Path, spec: RunSpec, stats: ExtractionStats) -> Iterable[dict[str, Any]]:
    stats.items_seen += 1
    try:
        gt_rows = clean_gt_rows(json.loads(gt_json.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        stats.items_skipped.append({"item": item_dir.name, "reason": f"gt_unreadable:{exc}"})
        return
    if not gt_rows:
        stats.items_skipped.append({"item": item_dir.name, "reason": "gt_empty_after_ap_filter"})
        return

    derived = item_dir.name
    parts = derived.split("__")
    # gtsinger_<singer>__<technique>__<song>__<group>__<segment>
    singer = parts[0] if parts else ""
    technique = parts[1] if len(parts) > 1 else ""
    song = parts[2] if len(parts) > 2 else ""
    group = parts[3] if len(parts) > 3 else ""
    segment = parts[4] if len(parts) > 4 else ""

    for model in MODELS:
        for audio in AUDIO_INPUTS:
            for mode in MODES:
                path = item_dir / "alignments" / model / audio / mode / "alignment.json"
                if not path.exists():
                    stats.configs_missing += 1
                    continue
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    stats.configs_skipped += 1
                    stats.items_skipped.append({"item": item_dir.name, "reason": f"{model}/{audio}/{mode}:{exc}"})
                    continue
                chars = doc.get("characters") or []
                if len(chars) != len(gt_rows):
                    stats.configs_skipped += 1
                    stats.items_skipped.append(
                        {
                            "item": item_dir.name,
                            "reason": f"count_mismatch:{model}/{audio}/{mode}:pred={len(chars)}:gt={len(gt_rows)}",
                        }
                    )
                    continue
                stats.configs_ok += 1

                summary = doc.get("summary") or {}
                spans = window_context(doc.get("window_trace")) if mode == "windowed" else []
                audio_dur = _num(summary.get("audio_duration_sec"))
                identity = doc.get("identity") or {}
                ckpt = identity.get("checkpoint") or {}
                audio_id = identity.get("audio") or {}
                win_id = identity.get("window") or {}
                dec_id = identity.get("decoder") or {}
                prov = {
                    "audio_name": identity.get("audio_name", ""),
                    "audio_path": str(audio_id.get("path", "")),
                    "audio_sha256": str(audio_id.get("sha256", "")),
                    "request_hash": str(identity.get("request_hash", "") or ""),
                    "decoder_id_kind": dec_id.get("kind", "") if isinstance(dec_id, dict) else "",
                    "window_core_sec": _num(win_id.get("core_sec")) if isinstance(win_id, dict) else None,
                    "window_left_ctx_sec": _num(win_id.get("left_context_sec")) if isinstance(win_id, dict) else None,
                    "window_policy": (win_id.get("policy") or "") if isinstance(win_id, dict) else "",
                    "checkpoint_path": str(ckpt.get("checkpoint_path", "") or ""),
                    "model_revision": str(identity.get("revision", "") or ""),
                }

                for i, (pred, gt) in enumerate(zip(chars, gt_rows)):
                    row: dict[str, Any] = {
                        "run": spec.tag,
                        "pipeline": spec.pipeline,
                        "item": derived,
                        "singer": singer,
                        "technique": technique,
                        "song": song,
                        "group": group,
                        "segment": segment,
                        "model": model,
                        "audio_input": audio,
                        "mode": mode,
                        "language": summary.get("language", ""),
                        "unit_mode": summary.get("alignment_unit_mode", ""),
                        "audio_dur_sec": _round(audio_dur, 3),
                        "item_unit_count": len(chars),
                        "checkpoint_kind": ckpt.get("checkpoint_kind", ""),
                        "decoder_kind": pred.get("decoder_kind", ""),
                        **prov,
                        "unit_type": pred.get("unit_type", ""),
                        "candidate_count": pred.get("candidate_count"),
                        "inference_source": pred.get("inference_source", ""),
                        "cross_window_repaired": 1 if pred.get("cross_window_repaired") else 0,
                        "raw_top1_start": _round(_num(pred.get("raw_start_top1_probability")), 5),
                        "raw_top1_end": _round(_num(pred.get("raw_end_top1_probability")), 5),
                        "raw_margin_start": _round(_num(pred.get("raw_start_margin")), 5),
                        "raw_margin_end": _round(_num(pred.get("raw_end_margin")), 5),
                        "raw_entropy_start": _round(_num(pred.get("raw_start_entropy")), 5),
                        "raw_entropy_end": _round(_num(pred.get("raw_end_entropy")), 5),
                        "raw_boundary_margin_mean": _round(_num(pred.get("raw_boundary_margin_mean")), 5),
                        "raw_top2cls_start": pred.get("raw_start_top2_class"),
                        "raw_top2cls_end": pred.get("raw_end_top2_class"),
                    }
                    row.update(gt_unit_features(gt, i, len(gt_rows)))

                    p_start = _num(pred.get("selected_start_sec"))
                    p_end = _num(pred.get("selected_end_sec"))
                    if p_start is None:
                        p_start = _num(pred.get("fixed_global_start_sec"))
                    if p_end is None:
                        p_end = _num(pred.get("fixed_global_end_sec"))
                    if p_start is None:
                        p_start = _num(pred.get("raw_global_start_sec"))
                    if p_end is None:
                        p_end = _num(pred.get("raw_global_end_sec"))
                    row["pred_start_sec"] = _round(p_start, 3)
                    row["pred_end_sec"] = _round(p_end, 3)
                    row["raw_start_sec"] = _round(_num(pred.get("raw_global_start_sec")), 3)
                    row["raw_end_sec"] = _round(_num(pred.get("raw_global_end_sec")), 3)
                    row["fixed_start_sec"] = _round(_num(pred.get("fixed_global_start_sec")), 3)
                    row["fixed_end_sec"] = _round(_num(pred.get("fixed_global_end_sec")), 3)
                    row["gpu_fixed_start_sec"] = _round(_num(pred.get("gpu_fixed_global_start_sec")), 3)
                    row["gpu_fixed_end_sec"] = _round(_num(pred.get("gpu_fixed_global_end_sec")), 3)
                    row.update(_interval_metrics(p_start, p_end, _num(gt.get("start_time")), _num(gt.get("end_time"))))
                    row["raw_iou"] = _interval_metrics(
                        _num(pred.get("raw_global_start_sec")), _num(pred.get("raw_global_end_sec")),
                        _num(gt.get("start_time")), _num(gt.get("end_time")))["iou"]

                    if spans:
                        win = _window_for_unit(spans, i)
                        if win is not None:
                            core_s, core_e = win["core_start_sec"], win["core_end_sec"]
                            g_start = _num(gt.get("start_time"))
                            g_end = _num(gt.get("end_time"))
                            row["window_index"] = win["window_index"]
                            row["window_char_start"] = win["char_start"]
                            row["window_char_end"] = win["char_end"]
                            row["window_left_ctx_chars"] = win["left_ctx_chars"]
                            if core_e is not None and g_start is not None:
                                row["dist_to_window_end_sec"] = _round(g_start - core_e, 3)
                            if core_s is not None and g_end is not None:
                                row["dist_to_window_start_sec"] = _round(g_start - core_s, 3)
                            row["units_from_window_end"] = win["char_end"] - 1 - i
                            row["units_from_window_start"] = i - win["char_start"]
                    yield row


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_runs(run_roots: Iterable[Path | str]) -> tuple[list[dict[str, Any]], ExtractionStats]:
    rows: list[dict[str, Any]] = []
    stats = ExtractionStats()
    for root in run_roots:
        path = Path(root)
        spec = RunSpec.infer(path)
        stats.runs += 1
        for item_dir, gt_json in iter_item_dirs(path):
            rows.extend(extract_item(item_dir, gt_json, spec, stats))
    return rows, stats


def write_rows(rows: list[dict[str, Any]], out_path: Path, compress: bool = True) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if (compress and out_path.suffix == ".gz") else open
    mode = "wt" if compress and out_path.suffix == ".gz" else "w"
    with opener(out_path, mode, encoding="utf-8") as fh:  # type: ignore[operator]
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_rows(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarise(rows: list[dict[str, Any]], stats: ExtractionStats, out_path: Path,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    by_run: dict[str, Any] = {}
    for row in rows:
        b = by_run.setdefault(row["run"], {"unit_rows": 0, "items": set(), "units": 0})
        b["unit_rows"] += 1
        b["items"].add(row["item"])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "evidence": str(out_path),
        "evidence_sha256": sha256_file(out_path) if out_path.exists() else None,
        "file_bytes": os.path.getsize(out_path) if out_path.exists() else None,
        "stats": {
            "runs": stats.runs,
            "items_seen": stats.items_seen,
            "configs_ok": stats.configs_ok,
            "configs_missing": stats.configs_missing,
            "configs_skipped": stats.configs_skipped,
            "unit_rows": len(rows),
            "items_skipped_count": len(stats.items_skipped),
        },
        "per_run": {
            run: {"unit_rows": b["unit_rows"], "distinct_items": len(b["items"])}
            for run, b in by_run.items()
        },
        "skipped": stats.items_skipped[:200],
    }
    if extra:
        summary.update(extra)
    return summary
