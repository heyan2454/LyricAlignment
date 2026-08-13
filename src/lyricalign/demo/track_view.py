"""TrackView — unified visualization projection for the 2026-08-14 session.

The existing renderer (``demo/visual_diagnostics.py``) consumes tracks as
``(label, rows[, windows])`` tuples where each ``row`` is a dict with
``start_sec/end_sec`` plus ``global_character_index``/``display_text``.  This
module adapts unit-realign v2 forward evidence (rows of
``{canonical_unit_id, start_sec, end_sec}``) into that contract by reverse
mapping canonical id -> global character index and injecting display text, so
visualisation never reads evaluator/GT artifacts (GT firewall preserved).

The structure mirrors the ``ComparisonTrack`` idea from 03 V5 without inventing
a class the renderer does not recognise: a ``TrackView`` is just a labelled
bundle of rows + window_trace + optional span annotations.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

TRACK_VIEW_SCHEMA = "track_view_v1"


def _canonical_index_and_text(
    request: Mapping[str, Any], canonical_unit_id: int,
) -> tuple[int, str]:
    """Map a canonical unit id back to a document-global char index + text.

    forward evidence stores only ``canonical_unit_id``; ``canonical_unit_id !=
    global_character_index``, so the v2 request's bijective ``canonical_to_local``
    map plus ``text_units``/``local_to_canonical`` are required.  When the request
    does not carry them the mapping degrades to the identity and empty text, which
    the renderer tolerates but which should never occur for a projective v2 request.
    """
    canon_to_local = request.get("canonical_to_local") or {}
    text_units = request.get("text_units") or []
    char_index_by_canon = {int(c): int(l) for c, l in canon_to_local.items()}
    gci = char_index_by_canon.get(int(canonical_unit_id))
    if gci is None:
        return int(canonical_unit_id), ""
    if 0 <= gci < len(text_units):
        return gci, str(text_units[gci])
    return gci, ""


def rows_from_forward_evidence(
    request: Mapping[str, Any], evidence: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project forward/decoder rows to visual rows.

    Two input forms are supported:
    - v2-forward-evidence form: each row is ``{canonical_unit_id, start_sec,
      end_sec}``; ``global_character_index``/``display_text`` are reverse-mapped
      via the request's ``canonical_to_local`` + ``text_units``.
    - decoder-row form: each row already carries ``global_character_index``
      and ``display_text`` (plus ``canonical_unit_id`` when available); these
      are used directly (no canonical reverse-map), so text/index are never
      lost when the source already has them.

    Every output row is safe for ``visual_diagnostics.canonical_visual_row`` /
    ``ordered_rows``: it carries a complete ``(start_sec, end_sec)`` pair plus
    ``global_character_index`` and ``display_text``.
    """
    out: list[dict[str, Any]] = []
    for row in evidence:
        cid = row.get("canonical_unit_id")
        gci = row.get("global_character_index")
        text = row.get("display_text")
        if cid is not None and gci is None and text is None:
            # v2-forward-evidence form: must reverse-map index + text.
            mapped_cid = int(cid)
            gci, text = _canonical_index_and_text(request, mapped_cid)
        else:
            # decoder-row form with index/text available (or degenerate).
            gci = int(gci) if gci is not None else (int(cid) if cid is not None else -1)
            text = str(text) if text is not None else ""
        out.append({
            "canonical_unit_id": int(cid) if cid is not None else gci,
            "global_character_index": gci,
            "display_text": text,
            "start_sec": float(row["start_sec"]),
            "end_sec": float(row["end_sec"]),
        })
    out.sort(key=lambda r: r["global_character_index"])
    return out


def build_track(
    label: str,
    rows: Sequence[Mapping[str, Any]],
    window_trace: Sequence[Mapping[str, Any]] | None = None,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a TrackView bundle for the renderer.

    ``render_timeline_page(tracks=[...])`` accepts ``(label, rows[, windows])``;
    we keep the same three-way meaning inside a dict for traceability and expose
    ``as_renderer_track()`` to emit the tuple form the renderer actually wants.
    """
    return {
        "schema": TRACK_VIEW_SCHEMA,
        "label": str(label),
        "rows": [dict(r) for r in rows],
        "window_trace": list(window_trace or []),
        "metadata": dict(metadata or {}),
    }


def as_renderer_track(track: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Emit the ``(label, rows[, windows])`` tuple the renderer consumes.

    A (possibly empty) window_trace keeps the 3-tuple form so the renderer draws
    that track's own window boundaries without ever swapping them between tracks.
    """
    return (
        str(track["label"]),
        [dict(r) for r in track.get("rows", [])],
        list(track.get("window_trace") or []),
    )


def track_rows_ready(track: Mapping[str, Any]) -> list[str]:
    """Validate every row for the renderer; return a list of problems (empty ok)."""
    problems: list[str] = []
    for i, row in enumerate(track.get("rows", [])):
        if row.get("start_sec") is None or row.get("end_sec") is None:
            problems.append(f"row[{i}] missing start_sec/end_sec")
        if row.get("global_character_index") is None:
            problems.append(f"row[{i}] missing global_character_index")
    return problems
