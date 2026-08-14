"""Real frozen population -> v2 request source adapter.

Pure helpers that enrich region rows produced by ``build_region_population``
(``src/lyricalign/unit_realign/region_sampling.py``) with the frozen baseline
context they need to become constructible v2 requests: per-window units,
audio path/sha256 and the 8-key execution identity_context consumed by
``build_request_identity`` (``src/lyricalign/unit_realign/request_families.py``).

No GT is read or produced here.  Missing input is never guessed: it is
recorded in the returned audit dicts and the region is simply left
not-ready/not-constructible.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

IDENTITY_KEYS = ("audio_sha256", "baseline_digest", "model_identity", "checkpoint_identity",
                 "decoder_identity", "mapping_schema", "code_identity", "text_adapter_identity")

AUDIT_SCHEMA = "unit_realign_source_adapter_audit_v1"

_TIMING_EPS = 1e-6

_SHA_CACHE: dict[Path, str | None] = {}


def _key(song_id: Any, window_index: Any) -> tuple[str, Any]:
    return (str(song_id), window_index)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a lines-of-JSON file (inventory helper, kept pure)."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def attach_real_units(
    region_rows: Sequence[Mapping[str, Any]],
    units_by_window: Mapping[tuple[str, Any], Sequence[Mapping[str, Any]]],
    *,
    shadow_by_window: Mapping[tuple[str, Any], Mapping[str, Mapping[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach per-window units to each region row using the detector alignment.

    ``units_by_window`` maps ``(song_id, window_index)`` to the BASELINE_UNITS
    rows of that window.  Every region receives a ``units`` field of
    ``{canonical_unit_id, start_sec, end_sec, text}`` sorted by canonical id.

    Timeline semantics (data-review P1-1 resolution): BASELINE_UNITS is the
    GT reference timeline in this corpus, while the detector alignment lives
    in ``detector_shadow.units``.  The request-local ``start_sec/end_sec`` and
    the fixed slots built from them must be the detector (baseline) alignment
    -- that is what the realign intervention moves.  When
    ``shadow_by_window`` is supplied, a unit's times are therefore taken from
    the shadow detector alignment; the GT reference times are preserved as
    ``reference_start_sec/reference_end_sec`` and a disagreement between the
    two is recorded as ``unit_time_mismatch`` in the audit.  Units without a
    shadow row fall back to BASELINE_UNITS times (recorded as
    ``missing_shadow_unit``).

    Returns ``(regions, audit)``.
    """
    out: list[dict[str, Any]] = []
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "n_regions": len(region_rows),
        "missing_units": [],
        "unit_time_mismatch": [],
        "missing_shadow_unit": [],
        "invalid_shadow_unit": [],
    }
    for region in region_rows:
        row = dict(region)
        key = _key(row.get("song_id"), row.get("window_index"))
        rows = units_by_window.get(key, ())
        by_id = {int(u["canonical_unit_id"]): u for u in rows}
        units = [{
            "canonical_unit_id": int(u["canonical_unit_id"]),
            "start_sec": float(u["start_sec"]),
            "end_sec": float(u["end_sec"]),
            "text": str(u["text"]),
            "reference_start_sec": float(u["start_sec"]),
            "reference_end_sec": float(u["end_sec"]),
        } for u in rows]
        units.sort(key=lambda u: u["canonical_unit_id"])
        row["units"] = units
        targets = [int(x) for x in row.get("target_unit_ids") or ()]
        missing = [cid for cid in targets if cid not in by_id]
        if missing:
            audit["missing_units"].append({
                "region_id": str(row.get("region_id") or ""),
                "song_id": str(row.get("song_id") or ""),
                "window_index": row.get("window_index"),
                "missing_target_unit_ids": missing,
            })
        if shadow_by_window is not None:
            shadow_units = (shadow_by_window.get(key, {}) or {}).get("units") or {}
            for unit in units:
                shadow = shadow_units.get(str(unit["canonical_unit_id"]))
                if not shadow:
                    audit["missing_shadow_unit"].append({
                        "region_id": str(row.get("region_id") or ""),
                        "song_id": str(row.get("song_id") or ""),
                        "window_index": row.get("window_index"),
                        "canonical_unit_id": unit["canonical_unit_id"],
                    })
                    continue
                s_start, s_end = shadow.get("start_sec"), shadow.get("end_sec")
                if not isinstance(s_start, (int, float)) or not isinstance(s_end, (int, float)):
                    audit["invalid_shadow_unit"].append({
                        "region_id": str(row.get("region_id") or ""),
                        "song_id": str(row.get("song_id") or ""),
                        "window_index": row.get("window_index"),
                        "canonical_unit_id": unit["canonical_unit_id"],
                        "shadow_start_sec": s_start, "shadow_end_sec": s_end,
                        "reason": "non_numeric",
                    })
                    continue
                if float(s_end) <= float(s_start):
                    audit["invalid_shadow_unit"].append({
                        "region_id": str(row.get("region_id") or ""),
                        "song_id": str(row.get("song_id") or ""),
                        "window_index": row.get("window_index"),
                        "canonical_unit_id": unit["canonical_unit_id"],
                        "shadow_start_sec": s_start, "shadow_end_sec": s_end,
                        "reason": "end_le_start",
                    })
                    continue
                if (abs(float(s_start) - unit["start_sec"]) > _TIMING_EPS
                        or abs(float(s_end) - unit["end_sec"]) > _TIMING_EPS):
                    audit["unit_time_mismatch"].append({
                        "region_id": str(row.get("region_id") or ""),
                        "song_id": str(row.get("song_id") or ""),
                        "window_index": row.get("window_index"),
                        "canonical_unit_id": unit["canonical_unit_id"],
                        "reference_start_sec": unit["start_sec"],
                        "reference_end_sec": unit["end_sec"],
                        "shadow_start_sec": s_start,
                        "shadow_end_sec": s_end,
                    })
                unit["start_sec"] = float(s_start)
                unit["end_sec"] = float(s_end)
                # Carry the detector unit's tri-state (ACCEPT/UNCERTAIN/REJECT) back
                # onto the region's unit so downstream partition/stratum logic
                # (split_variants.unsafe_groups, WP4) sees the detector's difficulty
                # classification.  Existing REGION_POOL products that lack state are
                # still handled by the split_variants fallback (WP4 P0 fix).
                shadow_state = str(shadow.get("state") or "").upper()
                if shadow_state in {"ACCEPT", "UNCERTAIN", "REJECT"}:
                    unit["state"] = shadow_state
        out.append(row)
    return out, audit


def compute_audio_sha256(audio_path: str | Path) -> str | None:
    """Return ``sha256:<hex>`` of the audio file bytes; None when missing.

    Results are cached per resolved path so attaching context to large region
    pools (many windows over the same small audio set) does not re-read the
    same files hundreds of times.
    """
    path = Path(audio_path)
    resolved = path.resolve()
    cached = _SHA_CACHE.get(resolved)
    if cached is not None:
        return cached
    if not path.is_file():
        logger.warning("source adapter: audio file missing: %s", path)
        _SHA_CACHE[resolved] = None
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    value = "sha256:" + digest.hexdigest()
    _SHA_CACHE[resolved] = value
    return value


def attach_audio_and_identity(
    region_rows: Sequence[Mapping[str, Any]],
    window_index_rows: Sequence[Mapping[str, Any]],
    identity_context: Mapping[str, Any],
    *,
    audio_dir: str | Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Resolve audio_path/audio_sha256 and attach identity_context per region.

    ``window_index_rows`` are BASELINE_WINDOW_INDEX rows indexed by
    ``(song_id, window_index)``.  Relative ``audio_path`` values are resolved
    under ``audio_dir`` when provided; absolute paths are used as-is.  Each
    region gets ``audio_path`` and an ``identity_context`` whose
    ``audio_sha256`` is filled from the file (None when the file is missing).

    Returns ``(regions, audit)`` with ``missing_audio``/``missing_units``
    counts, per-region records, and ``n_ready`` regions (units present, every
    target resolvable, all 8 identity keys populated, audio_path set).
    """
    by_key: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    for wrow in window_index_rows:
        by_key.setdefault(_key(wrow.get("song_id"), wrow.get("window_index")), []).append(wrow)
    base_ctx = dict(identity_context or {})
    out: list[dict[str, Any]] = []
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "n_regions": len(region_rows),
        "missing_audio": 0,
        "missing_audio_records": [],
        "missing_units": 0,
        "missing_units_records": [],
        "n_ready": 0,
    }
    for region in region_rows:
        row = dict(region)
        key = _key(row.get("song_id"), row.get("window_index"))
        wrows = by_key.get(key, ())
        wrow = wrows[0] if wrows else None
        ctx = dict(base_ctx)
        audio_path: str | None = None
        if wrow is None:
            reason = "no_window_index_row"
        else:
            audio_path = str(wrow.get("audio_path") or "")
            if not audio_path:
                reason = "no_audio_path"
            else:
                resolved = Path(audio_path)
                if audio_dir is not None and not resolved.is_absolute():
                    resolved = Path(audio_dir) / resolved
                row["audio_path"] = str(resolved)
                sha = compute_audio_sha256(resolved)
                ctx["audio_sha256"] = sha
                if sha is None:
                    audit["missing_audio"] += 1
                    audit["missing_audio_records"].append({
                        "region_id": str(row.get("region_id") or ""),
                        "song_id": str(row.get("song_id") or ""),
                        "window_index": row.get("window_index"),
                        "audio_path": str(resolved),
                        "reason": "file_missing",
                    })
        if wrow is None or not audio_path:
            ctx["audio_sha256"] = None
            audit["missing_audio"] += 1
            audit["missing_audio_records"].append({
                "region_id": str(row.get("region_id") or ""),
                "song_id": str(row.get("song_id") or ""),
                "window_index": row.get("window_index"),
                "audio_path": audio_path,
                "reason": reason,
            })
        row["identity_context"] = ctx
        units = row.get("units") or ()
        known = {int(u["canonical_unit_id"]) for u in units}
        targets = [int(x) for x in row.get("target_unit_ids") or ()]
        missing_targets = [cid for cid in targets if cid not in known]
        if missing_targets:
            audit["missing_units"] += 1
            audit["missing_units_records"].append({
                "region_id": str(row.get("region_id") or ""),
                "song_id": str(row.get("song_id") or ""),
                "window_index": row.get("window_index"),
                "missing_target_unit_ids": missing_targets,
            })
        ready = (
            bool(units)
            and not missing_targets
            and bool(row.get("audio_path"))
            and all(ctx.get(k) for k in IDENTITY_KEYS)
        )
        if ready:
            audit["n_ready"] += 1
        out.append(row)
    return out, audit


def _baseline_digest(run_inventory_dir: str | Path) -> str:
    """Content-address the frozen baseline units of the inventory."""
    path = Path(run_inventory_dir) / "BASELINE_UNITS.jsonl"
    if not path.is_file():
        logger.warning("source adapter: BASELINE_UNITS.jsonl missing; baseline_digest over empty input")
        raw = b""
    else:
        raw = path.read_bytes()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def make_real_identity_context(
    run_inventory_dir: str | Path,
    *,
    code_identity: str | None = None,
    text_adapter_identity: str | None = None,
    decoder_identity: str | None = None,
    mapping_schema: str = "unit_realign_local_v2",
) -> dict[str, Any]:
    """Build a full 8-key identity_context from DETECTOR_BASELINE_IDENTITY.json.

    ``model_identity`` is ``"{model_id}:{model_revision}"`` and
    ``checkpoint_identity`` is ``"{checkpoint_id}:{checkpoint_path}"``.
    Defaults: ``code_identity="git:{repo_head}"``, ``decoder_identity="official"``,
    ``text_adapter_identity="pypinyin-zh"``.  ``baseline_digest`` content-addresses
    the inventory's BASELINE_UNITS.jsonl.  ``audio_sha256`` is None here and is
    filled per region by :func:`attach_audio_and_identity`.
    """
    inventory = Path(run_inventory_dir)
    identity_path = inventory / "DETECTOR_BASELINE_IDENTITY.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    model_identity = f"{identity['model_id']}:{identity['model_revision']}"
    checkpoint_identity = f"{identity['checkpoint_id']}:{identity['checkpoint_path']}"
    repo_head = identity.get("repo_head") or "unknown"
    return {
        "audio_sha256": None,
        "baseline_digest": _baseline_digest(inventory),
        "model_identity": model_identity,
        "checkpoint_identity": checkpoint_identity,
        "decoder_identity": decoder_identity or "official",
        "mapping_schema": mapping_schema,
        "code_identity": code_identity or f"git:{repo_head}",
        "text_adapter_identity": text_adapter_identity or "pypinyin-zh",
    }
