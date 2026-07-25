"""Pure helpers for serial-window lyric alignment and KTV subtitle rendering.

The helpers intentionally do not load a model. They keep lyric occurrence IDs,
window ownership, overlap-only transcript context, and strict seam checks
explicit so repeated lyrics cannot be merged by text equality.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class LyricCharacter:
    global_index: int
    line_index: int
    index_in_line: int
    text: str
    display_suffix: str = ""


@dataclass(frozen=True)
class LyricLine:
    line_index: int
    display_text: str
    character_start: int
    character_end: int


@dataclass(frozen=True)
class LyricDocument:
    lines: tuple[LyricLine, ...]
    characters: tuple[LyricCharacter, ...]

    @property
    def transcript(self) -> str:
        return "".join(item.text for item in self.characters)


def parse_lyrics_text(text: str) -> LyricDocument:
    """Parse non-empty text lines while excluding whitespace from model text.

    Whitespace following a character is kept as ``display_suffix`` so the KTV
    renderer can preserve intentional phrase spacing without sending spaces to
    the forced aligner.
    """
    lines: list[LyricLine] = []
    characters: list[LyricCharacter] = []
    for raw_line in text.splitlines():
        display = raw_line.strip()
        if not display:
            continue
        line_index = len(lines)
        start = len(characters)
        pending_spaces = ""
        index_in_line = 0
        for symbol in display:
            if symbol.isspace():
                pending_spaces += symbol
                continue
            if pending_spaces and characters and characters[-1].line_index == line_index:
                previous = characters[-1]
                characters[-1] = LyricCharacter(
                    global_index=previous.global_index,
                    line_index=previous.line_index,
                    index_in_line=previous.index_in_line,
                    text=previous.text,
                    display_suffix=previous.display_suffix + pending_spaces,
                )
            pending_spaces = ""
            characters.append(
                LyricCharacter(
                    global_index=len(characters),
                    line_index=line_index,
                    index_in_line=index_in_line,
                    text=symbol,
                )
            )
            index_in_line += 1
        if pending_spaces and characters and characters[-1].line_index == line_index:
            previous = characters[-1]
            characters[-1] = LyricCharacter(
                global_index=previous.global_index,
                line_index=previous.line_index,
                index_in_line=previous.index_in_line,
                text=previous.text,
                display_suffix=previous.display_suffix + pending_spaces,
            )
        end = len(characters)
        if end == start:
            continue
        lines.append(
            LyricLine(
                line_index=line_index,
                display_text=display,
                character_start=start,
                character_end=end,
            )
        )
    if not characters:
        raise ValueError("lyrics contain no non-whitespace characters")
    return LyricDocument(lines=tuple(lines), characters=tuple(characters))


def build_serial_windows(
    duration_sec: float,
    *,
    core_sec: float = 60.0,
    left_context_sec: float = 15.0,
    right_context_sec: float = 15.0,
) -> list[dict[str, float | int]]:
    if duration_sec <= 0:
        raise ValueError("duration_sec must be positive")
    if core_sec <= 0 or left_context_sec < 0 or right_context_sec < 0:
        raise ValueError("invalid window lengths")
    windows: list[dict[str, float | int]] = []
    core_start = 0.0
    index = 0
    while core_start < duration_sec - 1e-9:
        core_end = min(duration_sec, core_start + core_sec)
        windows.append(
            {
                "window_index": index,
                "core_start_sec": core_start,
                "core_end_sec": core_end,
                "input_start_sec": max(0.0, core_start - left_context_sec),
                "input_end_sec": min(duration_sec, core_end + right_context_sec),
            }
        )
        core_start += core_sec
        index += 1
    return windows


def _line_for_character(document: LyricDocument, character_index: int) -> int:
    index = min(max(character_index, 0), len(document.characters) - 1)
    return document.characters[index].line_index


def future_character_range(
    document: LyricDocument,
    *,
    cursor: int,
    target_character_count: int,
    line_padding: int = 1,
) -> tuple[int, int]:
    """Return a forward transcript slice beginning exactly at ``cursor``.

    ``cursor`` is the acoustic-input transcript start computed by the preceding
    window. It may precede the hard commit cursor because complete characters
    in the 10-second left overlap are intentionally re-input as context. The end
    is expanded to whole lyric lines so the aligner sees enough future text.
    """
    total = len(document.characters)
    if not 0 <= cursor <= total:
        raise ValueError(f"cursor out of range: {cursor}")
    if target_character_count <= 0 or line_padding < 0:
        raise ValueError("invalid future transcript range settings")
    if cursor == total:
        return total, total
    raw_end = min(total, cursor + target_character_count)
    end_line = min(
        len(document.lines) - 1,
        _line_for_character(document, max(cursor, raw_end - 1)) + line_padding,
    )
    return cursor, document.lines[end_line].character_end


def split_core_commit_prefix(
    rows: Iterable[dict[str, Any]],
    *,
    expected_input_character_start: int,
    committed_character_start: int,
    core_start_sec: float,
    core_end_sec: float,
    final_core: bool,
    start_tolerance_sec: float = 0.32,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split one window result into left context, hard commits and lookahead.

    A later window deliberately re-inputs the complete lyric characters that
    correspond to its left acoustic extension.  Those rows are context-only:
    every character with an index below ``committed_character_start`` has
    already been frozen by an earlier core and can never be committed again.

    Ownership of new characters is based on character *start* time.  A
    character whose start lies before ``core_end_sec`` belongs wholly to this
    core, even when its end crosses the boundary.
    """
    ordered = sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))
    for offset, row in enumerate(ordered):
        expected = expected_input_character_start + offset
        actual = int(row["global_character_index"])
        if actual != expected:
            raise RuntimeError(
                f"non-contiguous window transcript: expected character {expected}, got {actual}"
            )

    context = [
        row for row in ordered
        if int(row["global_character_index"]) < committed_character_start
    ]
    uncommitted = [
        row for row in ordered
        if int(row["global_character_index"]) >= committed_character_start
    ]
    if uncommitted and core_start_sec > 0:
        first_start = float(uncommitted[0]["fixed_global_start_sec"])
        if first_start < core_start_sec - start_tolerance_sec:
            raise RuntimeError(
                "first uncommitted character aligned before the trusted core: "
                f"start={first_start:.3f}s core_start={core_start_sec:.3f}s "
                f"tolerance={start_tolerance_sec:.3f}s"
            )

    if final_core:
        return context, uncommitted, []

    committed: list[dict[str, Any]] = []
    lookahead: list[dict[str, Any]] = []
    boundary_found = False
    for row in uncommitted:
        start = float(row["fixed_global_start_sec"])
        if not boundary_found and start < core_end_sec:
            committed.append(row)
        else:
            boundary_found = True
            lookahead.append(row)
    return context, committed, lookahead


def next_window_transcript_start(
    rows: Iterable[dict[str, Any]],
    *,
    input_boundary_sec: float,
    total_characters: int,
    epsilon_sec: float = 1e-9,
) -> tuple[int | None, dict[str, Any] | None]:
    """Find the first complete lyric character for the next input window.

    The boundary is the *next window's acoustic input start* (for example
    50 s for a 60 s core with 10 s left context), not the next core start.
    If one character straddles that cut, it is excluded and the next character
    becomes the transcript start.  If the cut lies in silence, the first
    character starting at or after the cut is used.

    ``None`` means that the supplied future transcript did not yet reach the
    boundary and the caller must expand the candidate text and rerun.
    """
    ordered = sorted((dict(row) for row in rows), key=lambda row: int(row["global_character_index"]))
    for row in ordered:
        index = int(row["global_character_index"])
        start = float(row["fixed_global_start_sec"])
        end = float(row["fixed_global_end_sec"])
        if start < input_boundary_sec - epsilon_sec and end > input_boundary_sec + epsilon_sec:
            return min(index + 1, total_characters), {
                "global_character_index": index,
                "character": row.get("character"),
                "start_sec": start,
                "end_sec": end,
                "crosses_input_start": True,
                "excluded_from_next_window_input": True,
            }
        if start >= input_boundary_sec - epsilon_sec:
            return index, None
    return None, None


def append_strict_core_commits(
    existing: list[dict[str, Any]],
    rows: Iterable[dict[str, Any]],
    *,
    window: dict[str, Any],
    duration_sec: float,
    seam_tolerance_sec: float = 0.16,
) -> list[dict[str, Any]]:
    """Append one core's immutable rows with only a tiny seam correction.

    Large cumulative monotonic repair is deliberately forbidden.  A conflict
    larger than ``seam_tolerance_sec`` is a boundary failure and must be
    diagnosed or locally re-run rather than flattened across later lyrics.
    """
    if seam_tolerance_sec < 0:
        raise ValueError("seam_tolerance_sec must be non-negative")
    result = [dict(row) for row in existing]
    previous_end = float(result[-1]["end_sec"]) if result else 0.0
    next_index = int(result[-1]["global_character_index"]) + 1 if result else 0
    for source in rows:
        row = dict(source)
        actual_index = int(row["global_character_index"])
        if actual_index != next_index:
            raise RuntimeError(
                f"hard-commit sequence gap: expected character {next_index}, got {actual_index}"
            )
        original_start = min(max(float(row["fixed_global_start_sec"]), 0.0), duration_sec)
        original_end = min(max(float(row["fixed_global_end_sec"]), original_start), duration_sec)
        overlap = max(0.0, previous_end - original_start)
        if overlap > seam_tolerance_sec + 1e-9:
            raise RuntimeError(
                "cross-core monotonic conflict exceeds seam tolerance: "
                f"character={actual_index} overlap={overlap:.3f}s "
                f"tolerance={seam_tolerance_sec:.3f}s"
            )
        start = max(original_start, previous_end)
        end = max(original_end, start)
        row.update(
            {
                "selected_start_sec": original_start,
                "selected_end_sec": original_end,
                "start_sec": start,
                "end_sec": end,
                "candidate_count": 1,
                "inference_source": "strict_serial_core",
                "owner_window_index": int(window["window_index"]),
                "owner_core_start_sec": float(window["core_start_sec"]),
                "owner_core_end_sec": float(window["core_end_sec"]),
                "ownership_rule": "character_start_in_core",
                "seam_repaired": overlap > 1e-9,
                "seam_repair_sec": overlap,
                "cross_window_repaired": False,
            }
        )
        result.append(row)
        previous_end = end
        next_index += 1
    return result

def repair_monotonic_intervals(
    rows: Iterable[dict[str, Any]], *, duration_sec: float
) -> list[dict[str, Any]]:
    """Apply a transparent cumulative monotonic repair after window merging."""
    repaired: list[dict[str, Any]] = []
    previous = 0.0
    for source in sorted(rows, key=lambda row: int(row["global_character_index"])):
        row = dict(source)
        original_start = float(row["selected_start_sec"])
        original_end = float(row["selected_end_sec"])
        start = min(max(original_start, previous, 0.0), duration_sec)
        end = min(max(original_end, start), duration_sec)
        row["start_sec"] = start
        row["end_sec"] = end
        row["cross_window_repaired"] = (
            abs(start - original_start) > 1e-9 or abs(end - original_end) > 1e-9
        )
        previous = end
        repaired.append(row)
    return repaired


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100.0)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
