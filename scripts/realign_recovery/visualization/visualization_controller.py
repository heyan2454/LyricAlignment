"""WP2 — shared visualization controller (07 plan §9).

Independent, rerender-safe controller that drives the *unit-realign* frozen
evidence through the existing renderer in the 03 V4 order:

    collection -> analysis_complete -> visualization (static pages) -> encode

It never runs a model forward and never touches GT/evaluator artifacts (GT
firewall).  All row data comes from ``track_view.rows_from_forward_evidence``
projecting frozen forward evidence, so the renderer only ever sees complete
``(start_sec, end_sec, global_character_index, display_text)`` rows.

Output layout follows 03 V7:

    <out>/scientific/
    <out>/collection/
    <out>/analysis_complete.json
    <out>/visuals/{group}/... png pages
    <out>/renders/{group}.mp4
    <out>/render_manifest.json
    <out>/scientific_hash_before.json / scientific_hash_after.json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lyricalign.demo import track_view as tv
from lyricalign.demo.timeline_video import OUTPUT_WIDTH, OUTPUT_HEIGHT, render_page_video
from lyricalign.demo.visual_diagnostics import render_timeline_page

FONT = "Noto Sans CJK SC"
VIDEO_WIDTH = OUTPUT_WIDTH  # 3840
VIDEO_HEIGHT = OUTPUT_HEIGHT  # 1080


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def hash_jsonl(path: Path) -> str:
    if not path.is_file():
        return "MISSING"
    return sha256_bytes(path.read_bytes())


def find_subdir(root: Path, *parts: str) -> Path:
    p = root
    for part in parts:
        p = p / part
    return p


# --------------------------------------------------------------------------- #
# Evidence loading (read-only frozen forward evidence)
# --------------------------------------------------------------------------- #

def load_plan(plan_path: Path | str) -> list[dict[str, Any]]:
    """Load TEST_DEMO_REALIGN_REQUEST_PLAN.jsonl into a list of request dicts."""
    rows: list[dict[str, Any]] = []
    for line in Path(plan_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def load_evidence_index(evidence_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Index forward evidence files by ``attempt.request.request_id``.

    Each evidence is a dict whose ``attempt.decoder_outputs`` holds the
    ``raw``/``official`` rows.  Only files whose attempt status is ``ok`` are
    indexed so a partial run never renders garbage.
    """
    evidence_dir = Path(evidence_dir)
    index: dict[str, dict[str, Any]] = {}
    if not evidence_dir.is_dir():
        return index
    for path in evidence_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        attempt = payload.get("attempt") or {}
        if attempt.get("status") != "ok":
            continue
        request = attempt.get("request") or {}
        request_id = request.get("request_id")
        if not request_id:
            continue
        index[str(request_id)] = payload
    return index


def rows_from_decoder(payload: Mapping[str, Any], decoder_kind: str = "official") -> list[dict[str, Any]]:
    """Pull visual rows straight from a stored decoder block into doc-global coords.

    The stored decoder rows carry a **window-local** ``global_character_index``
    (0..len(canonical_ids)-1); the document-global character index/canonical id
    is ``request.canonical_ids[local_idx]`` and the character text comes from
    ``request.text_units`` / ``canonical_to_local``.  We restore those document-global
    values *here* (rows_from_decoder), so every emitted row is already in global
    coordinates for ``track_view.rows_from_forward_evidence``'s pass-through path.

    ``start_sec/end_sec`` resolve from the stage-specific global fields, falling
    back to ``start_sec/end_sec``.
    """
    attempt = payload.get("attempt") or {}
    request = attempt.get("request") or {}
    decoder_outputs = attempt.get("decoder_outputs") or {}
    block = decoder_outputs.get(decoder_kind) or {}
    canonical_ids = [int(x) for x in request.get("canonical_ids") or ()]
    text_units = [str(x) for x in request.get("text_units") or ()]
    rows: list[dict[str, Any]] = []
    for row in block.get("rows") or []:
        start = row.get("official_fixed_global_start_sec") if decoder_kind == "official" else row.get("raw_global_start_sec")
        end = row.get("official_fixed_global_end_sec") if decoder_kind == "official" else row.get("raw_global_end_sec")
        start = start if start is not None else row.get("start_sec")
        end = end if end is not None else row.get("end_sec")
        if start is None or end is None:
            continue
        local_idx = row.get("global_character_index")
        if local_idx is None:
            local_idx = row.get("character_index")
        if local_idx is None:
            continue
        local_idx = int(local_idx)
        # Restore the document-global identity from the request.
        if 0 <= local_idx < len(canonical_ids):
            gci = canonical_ids[local_idx]
            text = text_units[local_idx] if local_idx < len(text_units) else ""
        else:
            # Degenerate request (no canonical_ids): keep the local index.
            gci = local_idx
            text = ""
        rows.append({
            "global_character_index": gci,
            "display_text": text,
            "start_sec": float(start),
            "end_sec": float(end),
        })
    rows.sort(key=lambda r: r["global_character_index"])
    return rows


def build_track_from_evidence(
    payloads: Sequence[Mapping[str, Any]],
    *,
    label: str,
    decoder_kind: str = "official",
    window_trace: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a TrackView bundle from one or more frozen evidence payloads.

    Rows from every payload are merged (same global timeline) then projected via
    ``track_view.rows_from_forward_evidence``.  ``window_trace`` is kept per
    track so the renderer never swaps window plans between tracks.
    """
    request: Mapping[str, Any] | None = None
    evidence_rows: list[dict[str, Any]] = []
    request_ids: list[str] = []
    for payload in payloads:
        attempt = payload.get("attempt") or {}
        request = attempt.get("request") or {}
        rid = request.get("request_id")
        if rid:
            request_ids.append(str(rid))
        evidence_rows.extend(rows_from_decoder(payload, decoder_kind=decoder_kind))
    request = request or {}
    projected = tv.rows_from_forward_evidence(request, evidence_rows)
    return tv.build_track(
        label, projected,
        window_trace=window_trace,
        metadata={
            "decoder_kind": decoder_kind,
            "n_payloads": len(payloads),
            "request_ids": request_ids,
            **(metadata or {}),
        },
    )


def evidence_payloads_for_family(
    evidence_index: Mapping[str, Mapping[str, Any]],
    request_ids: Iterable[str],
    *,
    family: str | None = None,
) -> list[Mapping[str, Any]]:
    """Return the evidence payloads whose proposal_method matches ``family``."""
    out: list[Mapping[str, Any]] = []
    for rid in request_ids:
        payload = evidence_index.get(str(rid))
        if payload is None:
            continue
        if family is not None:
            method = (payload.get("attempt") or {}).get("request") or {}
            method = method.get("mutation_parameters") or {}
            if method.get("proposal_method") != family:
                continue
        out.append(payload)
    return out


# --------------------------------------------------------------------------- #
# Window plan helpers
# --------------------------------------------------------------------------- #

def window_trace_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a window_trace entry from a v2 plan request's span info (if any)."""
    span = request.get("span") or {}
    trace: dict[str, Any] = {}
    if isinstance(span, dict):
        for key in (
            "core_start_sec", "core_end_sec", "input_start_sec", "input_end_sec",
            "audio_start_sec", "audio_end_sec", "start_sec", "end_sec",
            "text_start_index", "text_end_index",
        ):
            if span.get(key) is not None:
                trace[key] = span[key]
    if "audio_start_sec" in span and "audio_end_sec" in span:
        trace.setdefault("core_start_sec", span["audio_start_sec"])
        trace.setdefault("core_end_sec", span["audio_end_sec"])
    return trace


# --------------------------------------------------------------------------- #
# Scientific evaluation / collection stubs (no GT, read-only)
# --------------------------------------------------------------------------- #

def write_collection(out: Path, plan: list[Mapping[str, Any]], items: list[str]) -> dict[str, Any]:
    """Write a frozen-evidence collection (03 V7 ``collection/``).

    This is a content-addressed inventory of the request/evidence bindings the
    visualization will render.  It contains **no** GT rows and no model output
    beyond references to frozen evidence identities.
    """
    collection: dict[str, Any] = {
        "schema": "unit_realign_visualization_collection_v1",
        "result_status": "ok",
        "item_count": len(items),
        "request_count": len(plan),
        "items": items,
        "requests": [
            {
                "request_id": r.get("request_id"),
                "item": r.get("item"),
                "kind": r.get("kind"),
                "span": r.get("span"),
            }
            for r in plan
        ],
    }
    (out / "collection").mkdir(parents=True, exist_ok=True)
    (out / "collection" / "collection.json").write_text(
        json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return collection


def write_analysis_complete(out: Path, *, n_items: int, n_requests: int, resources: Mapping[str, Any]) -> dict[str, Any]:
    """Write ``analysis_complete.json`` (03 V7)."""
    payload = {
        "schema": "unit_realign_analysis_complete_v1",
        "result_status": "ok",
        "n_items": n_items,
        "n_requests": n_requests,
        "renderer": "demo/visual_diagnostics.render_timeline_page + demo/timeline_video.render_page_video",
        "resources": resources,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis_complete.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


_SCI_PATTERNS = ("scientific", "collection")


def snapshot_scientific_hashes(run_root: Path) -> dict[str, str]:
    """Snapshot sha256 of scientific/ JSON/JSONL artifacts under ``run_root``.

    Used by the rerender-only guard to assert frozen scientific hashes are
    unchanged before/after a visual re-render.
    """
    index: dict[str, str] = {}
    run_root = Path(run_root)
    if run_root.is_dir():
        for path in sorted(run_root.rglob("*.json*")):
            rel = str(path.relative_to(run_root))
            if any(part in _SCI_PATTERNS for part in path.parts) or rel.endswith("analysis_complete.json"):
                index[rel] = hash_jsonl(path)
    return index


def write_render_manifest(out: Path, *, visual_groups: list[dict[str, Any]], videos: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = {
        "schema": "unit_realign_render_manifest_v1",
        "result_status": "ok",
        "visual_groups": visual_groups,
        "videos": videos,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "render_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


# --------------------------------------------------------------------------- #
# Controller entrypoints
# --------------------------------------------------------------------------- #

def page_ranges_for(start: float, end: float, page_seconds: float) -> list[tuple[float, float]]:
    """Split [start, end] into fixed-width pages; last page uses real tail."""
    if end - start <= page_seconds:
        return [(start, end)]
    pages: list[tuple[float, float]] = []
    cursor = start
    while cursor < end:
        next_end = min(end, cursor + page_seconds)
        pages.append((cursor, next_end))
        cursor = next_end
    return pages


def full_timeline_pixel_width(duration: float) -> int:
    """Match the mature inline-realign viz: wide whole-song canvas so every
    unit's label gets room (160 px/sec, clamped to [12000, 64000]).
    See ``scripts/demo/analyze_inline_realign_visuals.full_timeline_pixel_width``."""
    return max(12000, min(64000, int(max(duration, 30.0) * 160.0)))


def render_static_group(
    out: Path,
    *,
    group: str,
    tracks: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    start: float,
    end: float,
    title: str,
    font: str = FONT,
    video_layout: bool = True,
    page_seconds: float = 30.0,
):
    """Render one static timeline PNG (+ split pages) for a track group.

    ``tracks`` are ``track_view`` bundles; ``windows`` is the **global** window
    list shared across tracks on the same axis.  Rows are projected to the
    renderer contract here so any missing-field error surfaces in the
    controller layer, not the renderer.
    """
    renderer_tracks = [tv.as_renderer_track(t) for t in tracks]
    for t, (label, rrows, _tw) in zip(tracks, renderer_tracks):
        problems = tv.track_rows_ready(t)
        if problems:
            raise RuntimeError(f"track {label!r} not renderer-ready: {problems}")
    group_dir = out / "visuals" / group
    group_dir.mkdir(parents=True, exist_ok=True)
    pages_meta: list[dict[str, Any]] = []
    for page_index, (p_start, p_end) in enumerate(page_ranges_for(start, end, page_seconds)):
        page_path = group_dir / f"page_{page_index:03d}_{p_start:07.2f}_{p_end:07.2f}.png"
        meta = render_timeline_page(
            output=page_path,
            tracks=renderer_tracks,
            windows=windows,
            start=p_start,
            end=p_end,
            title=title,
            font=font,
            video_layout=video_layout,
            pixel_width=VIDEO_WIDTH,
            pixel_height=VIDEO_HEIGHT,
        )
        pages_meta.append(meta)
    full_path = group_dir / "full_timeline.png"
    full_meta = render_timeline_page(
        output=full_path,
        tracks=renderer_tracks,
        windows=windows,
        start=start,
        end=end,
        title=title,
        font=font,
        video_layout=False,
        pixel_width=full_timeline_pixel_width(end - start),
    )
    return {
        "group": group,
        "title": title,
        "full_timeline": str(full_path),
        "pages": pages_meta,
        "start_sec": start,
        "end_sec": end,
    }


def build_karaoke_alignment(rows: Sequence[Mapping[str, Any]], duration_sec: float) -> dict[str, Any]:
    """Build a karaoke alignment dict consumable by ``build_bottom_ass``.

    ``rows`` are visual (track_view) rows carrying ``start_sec/end_sec`` and
    ``display_text``.  KTV needs ``characters`` grouped by ``line_index`` plus
    ``lines``.  We pack all characters into a single synthetic line so the karaoke
    band renders (two-row layout) without needing source line structure.
    """
    ordered = sorted(rows, key=lambda r: (float(r["start_sec"]), r.get("global_character_index") or 0))
    characters = [
        {
            "line_index": 0,
            "index_in_line": i,
            "start_sec": float(r["start_sec"]),
            "end_sec": float(r["end_sec"]),
            "display_text": str(r.get("display_text") or r.get("alignment_unit") or ""),
            "alignment_unit": str(r.get("display_text") or r.get("alignment_unit") or "·"),
            "character": str(r.get("display_text") or r.get("alignment_unit") or "·"),
        }
        for i, r in enumerate(ordered)
    ]
    return {
        "characters": characters,
        "lines": [{"line_index": 0}],
        "summary": {"audio_duration_sec": duration_sec},
    }


def render_video(
    out: Path,
    *,
    group: str,
    pages_meta: Sequence[Mapping[str, Any]],
    alignment: Mapping[str, Any],
    audio_track: Path,
    title: str,
    font: str = FONT,
    profile: str = "review",
    force: bool = False,
) -> dict[str, Any]:
    """Encode the static pages of a group into a review MP4 via render_page_video."""
    (out / "renders").mkdir(parents=True, exist_ok=True)
    output_path = out / "renders" / f"{group}.mp4"
    work_root = out / "renders" / f"{group}_work"
    # A nested group (e.g. "b4_vs_current/<item>") needs its sub-directory created
    # so multi-item batches never overwrite each other.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    if not pages_meta:
        raise ValueError(f"group {group!r} has no pages to encode")
    return render_page_video(
        pages=list(pages_meta),
        alignment=alignment,
        audio_track=audio_track,
        output_path=output_path,
        work_root=work_root,
        font=font,
        title=title,
        profile=profile,
        force=force,
        include_karaoke=True,
    )
