"""E1/E2 Oracle repairability: catastrophic region selection + no-GT oracle REQUESTS.

Oracle semantics (04 GT_ACCESS_CONTRACT §2, 10 C1):
- catastrophic regions are selected from real-GT confirmed unsafe units
  (LABELS ``label=="unsafe"`` and ``gt_unavailable==false``).
- The model only ever receives audio span + text units + non-GT config.
  GT timestamps never enter the request; real GT is used only by the offline
  evaluator (``evaluate_oracle_runs``).
- O0 exact / O1 +2s / O2 +5s / O3 +10s expand the *audio* span around the
  region; E2 additionally supports a single-axis text-span expansion
  (``text_extra_units``) and a small set of audio+text combinations.

This module is pure logic (no model import). It consumes explicit manifest
paths and writes research_v7-compatible REQUESTS lines, so the GPU forward is
driven by the existing ``scripts/research_v7/run_behavior_suite.py --real``.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from lyricalign.realign_recovery.gt_firewall import validate_no_gt_request
from lyricalign.realign_recovery.run_objects import atomic_write_text

ORACLE_MODES_SEC: dict[str, float] = {
    "O0": 0.0,
    "O1": 2.0,
    "O2": 5.0,
    "O3": 10.0,
}

ORACLE_WORKFLOW_MODE = "recovery_e1_oracle"
ORACLE_MUTATION = "oracle_repair"


@dataclass(frozen=True)
class OracleRegion:
    song_id: str
    region_id: str
    unit_ids: tuple[int, ...]
    texts: tuple[str, ...]
    audio_start_sec: float
    audio_end_sec: float
    duration_sec: float
    family: str | None
    split: str | None
    audit_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OracleRegion":
        return cls(
            song_id=d["song_id"],
            region_id=d["region_id"],
            unit_ids=tuple(int(u) for u in d["unit_ids"]),
            texts=tuple(d["texts"]),
            audio_start_sec=float(d["audio_start_sec"]),
            audio_end_sec=float(d["audio_end_sec"]),
            duration_sec=float(d["duration_sec"]),
            family=d.get("family"),
            split=d.get("split"),
            audit_reasons=tuple(d.get("audit_reasons", [])),
        )


def _load_labels(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_timeline(path: str | Path) -> dict[str, dict]:
    """timeline manifest -> {song_id: {'units': {cid: meta}, 'audio_path', 'duration_sec'}}."""
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            song = r["song_id"]
            out[song] = {
                "units": {
                    int(u["canonical_unit_id"]): {
                        "start_sec": float(u["start_sec"]),
                        "end_sec": float(u["end_sec"]),
                        "text": u.get("text"),
                    }
                    for u in r.get("canonical_units", [])
                },
                "audio_path": r.get("concat_audio_path"),
                "duration_sec": float(r.get("duration_sec", 0.0) or 0.0),
            }
    return out


def select_catastrophic_regions(
    labels_path: str | Path,
    timeline_manifest_path: str | Path,
    *,
    min_units_per_region: int = 1,
) -> list[OracleRegion]:
    """Select real-GT confirmed catastrophic regions (unsafe runs), one per unit run.

    A region is a maximal run of consecutive ``canonical_unit_id`` whose LABELS
    rows are ``label=="unsafe"`` and ``gt_unavailable==false``. Regions are
    ordered by (song_id, first unit id). Audio span comes from the (synthetic,
    non-GT) timeline manifest; it is used only to build the request window.
    """
    labels = _load_labels(labels_path)
    timeline = _load_timeline(timeline_manifest_path)

    unsafe_by_song: dict[str, list[int]] = {}
    audit_by_song: dict[str, list[str]] = {}
    split_by_song: dict[str, str] = {}
    family_by_song: dict[str, str] = {}
    for r in labels:
        if r.get("label") != "unsafe" or r.get("gt_unavailable") is True:
            continue
        song = r.get("song_id")
        if not song or song not in timeline:
            continue
        cid = int(r["canonical_unit_id"])
        unsafe_by_song.setdefault(song, []).append(cid)
        split_by_song.setdefault(song, r.get("split"))
        family_by_song.setdefault(song, r.get("family"))
        reason = ((r.get("audit") or {}).get("reason")) or "unsafe"
        audit_by_song.setdefault(song, []).append(reason)

    regions: list[OracleRegion] = []
    for song in sorted(unsafe_by_song):
        meta = timeline[song]
        units_meta = meta["units"]
        duration = meta["duration_sec"]
        ids = sorted(set(unsafe_by_song[song]))
        run: list[int] = []
        for cid in ids:
            if run and cid != run[-1] + 1:
                regions.extend(
                    _region_from_run(song, run, units_meta, duration,
                                     family_by_song.get(song),
                                     split_by_song.get(song))
                )
                run = []
            run.append(cid)
        if run:
            regions.extend(
                _region_from_run(song, run, units_meta, duration,
                                 family_by_song.get(song),
                                 split_by_song.get(song))
            )
    if min_units_per_region > 1:
        regions = [r for r in regions if len(r.unit_ids) >= min_units_per_region]
    return regions


def _region_from_run(song: str, run: list[int], units_meta: dict[int, dict],
                     duration: float, family: str | None,
                     split: str | None) -> list[OracleRegion]:
    texts: list[str] = []
    start = None
    end = None
    reasons: list[str] = []
    for cid in run:
        u = units_meta.get(cid)
        if u is None:
            continue
        texts.append(str(u.get("text") or ""))
        s = float(u["start_sec"])
        e = float(u["end_sec"])
        start = s if start is None else min(start, s)
        end = e if end is None else max(end, e)
        reasons.append(f"unit{cid}")
    if start is None or end is None or not texts:
        return []
    first = run[0]
    last = run[-1]
    region = OracleRegion(
        song_id=song,
        region_id=f"{song}:{first}-{last}",
        unit_ids=tuple(run),
        texts=tuple(texts),
        audio_start_sec=start,
        audio_end_sec=end,
        duration_sec=duration,
        family=family,
        split=split,
        audit_reasons=tuple(reasons),
    )
    return [region]


# manifest duration_sec 是 4 位小数，实际 wav 解码长度可有 ±几 sample 偏差；
# executor 只容忍 2 sample（约 0.000125s），故 clip 上限减 0.001s 安全余量，
# 避免 O1+ 扩展窗 clip 到 manifest 时长后在解码音频外被整体拒绝。
_CLIP_DURATION_MARGIN_SEC = 0.001


def _clip(start: float, end: float, duration: float) -> tuple[float, float]:
    cap = max(0.0, duration - _CLIP_DURATION_MARGIN_SEC)
    lo = max(0.0, min(start, cap))
    hi = max(lo, min(end, cap))
    return lo, hi


def build_oracle_requests(
    regions,
    timeline_manifest_path: str | Path,
    out_path: str | Path,
    *,
    modes: tuple[str, ...] | None = None,
    audio_extra_sec: float | None = None,
    text_extra_units: int = 0,
    model_id: str = "Qwen3-ForcedAligner-0.6B-hf",
    checkpoint_id: str = "r2-step-000750",
) -> tuple[list[dict], str]:
    """Build research_v7-compatible no-GT oracle REQUESTS lines.

    Each region x mode produces one line. ``audio_extra_sec`` overrides the
    mode-based expansion (E2 single-axis audio sweep); ``text_extra_units``
    adds that many neighbour units before/after the region (E2 text sweep).
    The returned JSONL carries only audio/text/config inputs; every line passes
    ``validate_no_gt_request``.
    """
    if modes is None:
        modes = tuple(ORACLE_MODES_SEC)
    timeline = _load_timeline(timeline_manifest_path)
    out_path = str(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    rows: list[dict] = []
    for region in _as_region_list(regions):
        meta = timeline.get(region.song_id)
        if meta is None or not meta.get("audio_path"):
            continue
        units_meta = meta["units"]
        audio = meta["audio_path"]
        duration = region.duration_sec or meta["duration_sec"]

        for mode in modes:
            extra = ORACLE_MODES_SEC.get(mode, 0.0) if audio_extra_sec is None else audio_extra_sec
            a0, a1 = _clip(region.audio_start_sec - extra,
                           region.audio_end_sec + extra, duration)
            unit_ids, texts = _expand_text(
                region, units_meta, extra_units=text_extra_units)
            text_content_hash = _sha256_text(json.dumps(
                list(texts), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            no_gt = {
                "model_id": model_id,
                "checkpoint_id": checkpoint_id,
                "audio_source": audio,
                "audio_start_sec": round(a0, 6),
                "audio_end_sec": round(a1, 6),
                "text_units": list(texts),
                "text_content_hash": text_content_hash,
                "workflow_mode": ORACLE_WORKFLOW_MODE,
                "mutation_type": ORACLE_MUTATION,
                "input_variant": f"oracle_{mode}",
                "text_extra_units": text_extra_units,
                "metadata": {
                    "song_id": region.song_id,
                    "region_id": region.region_id,
                    "mode": mode,
                    "target_unit_ids": list(region.unit_ids),
                    "family": region.family,
                    "split": region.split,
                    "audio_extra_sec": extra,
                },
            }
            found = validate_no_gt_request(no_gt)
            if found:
                raise ValueError(f"oracle request carries GT-bearing fields: {sorted(found)}")
            row = {
                "request_id": f"oracle-{region.region_id}-{mode}",
                "item_id": region.song_id,
                "parent_request_id": None,
                "audio_path": audio,
                "audio_source": "m4singer_segment_concat",
                "audio_start_sec": round(a0, 6),
                "audio_end_sec": round(a1, 6),
                "text_source": "labels",
                "text_start_index": 0,
                "text_end_index": len(texts),
                "text_units": list(texts),
                "timestamp_slot_indices": None,
                "workflow_mode": ORACLE_WORKFLOW_MODE,
                "mutation_type": ORACLE_MUTATION,
                "mutation_parameters": {"mode": mode, "audio_extra_sec": extra,
                                        "text_extra_units": text_extra_units,
                                        "region_id": region.region_id},
                "model_id": model_id,
                "checkpoint_id": checkpoint_id,
                "input_variant": f"oracle_{mode}",
                "evaluation_role": None,
                "language": "Chinese",
                "source_song_id": region.song_id,
                "source_window_start_sec": round(a0, 6),
                "source_window_end_sec": round(a1, 6),
                "schema_version": "research_v7_long_slot_v1",
                "provenance": {
                    "realign_recovery_stage": "E1_oracle",
                    "region_id": region.region_id,
                    "mode": mode,
                    "unit_ids": list(region.unit_ids),
                    "target_text": list(texts),
                },
            }
            rows.append(row)

    text = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + ("\n" if rows else "")
    atomic_write_text(out_path, text)
    return rows, out_path


def _as_region_list(regions) -> list[OracleRegion]:
    out: list[OracleRegion] = []
    for r in regions:
        if isinstance(r, OracleRegion):
            out.append(r)
        elif isinstance(r, dict):
            out.append(OracleRegion.from_dict(r))
        else:
            raise TypeError(f"unexpected region type {type(r).__name__}")
    return out


def _expand_text(region: OracleRegion, units_meta: dict[int, dict],
                 extra_units: int = 0) -> tuple[list[int], list[str]]:
    ids = list(region.unit_ids)
    texts = list(region.texts)
    if extra_units <= 0:
        return ids, texts
    lo = ids[0] - extra_units
    hi = ids[-1] + extra_units
    all_ids = sorted(u for u in units_meta if u is not None)
    expanded: list[int] = []
    for cid in all_ids:
        if lo <= cid <= hi:
            expanded.append(cid)
    if not expanded:
        return ids, texts
    return expanded, [str(units_meta[c]["text"] or "") for c in expanded]


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evaluate_oracle_runs(
    requests_path: str | Path,
    evidence_dir: str | Path,
    real_gt,
    timeline_manifest_path: str | Path,
    out_path: str | Path,
    *,
    thresholds_ms: tuple[float, ...] = (100, 200, 500),
    catastrophic_sec: tuple[float, ...] = (1, 2, 5, 10),
) -> dict:
    """Offline real-GT join: measure oracle repair on catastrophic regions.

    Reads raw rows from run_behavior_suite evidence, maps each request back to
    its region/mode, and compares raw alignment of the *target* units against
    the real-GT projection (the only place GT is read). Reports per-song and
    per-mode repair rate at the catastrophic thresholds (any raw abs error
    within ``catastrophic_sec`` counts as repaired), plus MAE.
    """
    requests_path = Path(requests_path)
    evidence_dir = Path(evidence_dir)

    requests: dict[str, dict] = {}
    for line in requests_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        requests[r["request_id"]] = r

    per_mode: dict[str, dict] = {}
    per_song: dict[str, dict] = {}
    per_region: dict[str, dict] = {}
    total_units = 0
    for ev_file in sorted(evidence_dir.glob("*.json")):
        payload = json.loads(ev_file.read_text(encoding="utf-8"))
        attempt = payload.get("attempt", {})
        req = attempt.get("request", {})
        rid = req.get("request_id")
        req_row = requests.get(rid)
        if req_row is None:
            continue
        provenance = req_row.get("provenance") or {}
        region_id = provenance.get("region_id")
        mode = provenance.get("mode") or req_row.get("input_variant", "oracle_?")
        song = req_row.get("source_song_id")
        target_ids = provenance.get("unit_ids") or []
        if not target_ids or region_id is None:
            continue
        gt_song = real_gt.get(song) or {}
        rows = ((attempt.get("decoder_outputs") or {}).get("raw") or {}).get("rows") or []
        mapped = _map_local_rows(rows, target_ids)
        n_units = 0
        n_repaired = {t: 0 for t in catastrophic_sec}
        abs_errors: list[float] = []
        for cid in target_ids:
            gt = gt_song.get(int(cid))
            if gt is None:
                continue
            out = mapped.get(int(cid))
            if out is None:
                continue
            n_units += 1
            err_s = max(abs(float(gt["start_sec"]) - float(out["start"])),
                        abs(float(gt["end_sec"]) - float(out["end"])))
            abs_errors.append(err_s)
            for t in catastrophic_sec:
                if err_s <= t:
                    n_repaired[t] += 1
        if n_units == 0:
            continue
        total_units += n_units
        mode_bucket = per_mode.setdefault(mode, {
            "n_units": 0, "n_repaired": {str(t): 0 for t in catastrophic_sec}})
        mode_bucket["n_units"] += n_units
        for t in catastrophic_sec:
            mode_bucket["n_repaired"][str(t)] += n_repaired[t]
        song_bucket = per_song.setdefault(song, {
            "n_units": 0, "mae": 0.0, "n_errors": 0.0,
            "n_repaired": {str(t): 0 for t in catastrophic_sec}})
        song_bucket["n_units"] += n_units
        song_bucket["mae"] += sum(abs_errors)
        song_bucket["n_errors"] += len(abs_errors)
        for t in catastrophic_sec:
            song_bucket["n_repaired"][str(t)] += n_repaired[t]
        per_region[region_id] = {
            "mode": mode, "n_units": n_units, "mae": sum(abs_errors) / len(abs_errors),
            "n_repaired": {str(t): n_repaired[t] for t in catastrophic_sec}}
    for bucket in per_song.values():
        if bucket["n_errors"]:
            bucket["mae"] = round(bucket["mae"] / bucket["n_errors"], 6)
        bucket.pop("n_errors", None)

    summary = {
        "schema_version": "realign_recovery_oracle_eval_v1",
        "total_units": total_units,
        "per_mode": per_mode,
        "per_song": per_song,
        "per_region": per_region,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return summary


def _map_local_rows(raw_rows: list[dict], target_ids) -> dict[int, dict]:
    """Map evidence raw rows back to canonical unit ids for an oracle request.

    For a region-local request the row ``global_character_index`` is a
    request-local index into ``text_units`` (text_start_index=0, no canonical
    mapping), so index ``i`` corresponds to ``target_ids[i]``. Times are
    already concat-global (executor shifts by audio_start_sec).
    """
    ids = [int(c) for c in target_ids]
    out: dict[int, dict] = {}
    for row in raw_rows:
        gci = row.get("global_character_index")
        if gci is None:
            continue
        idx = int(gci)
        if not (0 <= idx < len(ids)):
            continue
        out[ids[idx]] = {
            "start": float(row.get("raw_global_start_sec")
                           if row.get("raw_global_start_sec") is not None
                           else row.get("fixed_global_start_sec", 0.0)),
            "end": float(row.get("raw_global_end_sec")
                         if row.get("raw_global_end_sec") is not None
                         else row.get("fixed_global_end_sec", 0.0)),
        }
    return out
