"""Pure helpers for serial-window lyric alignment and KTV subtitle rendering.

The helpers intentionally do not load a model.  They keep lyric occurrence IDs,
window ownership and the final cross-window repair explicit so repeated lyrics
cannot be merged by text equality.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
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


def candidate_character_range(
    document: LyricDocument,
    *,
    duration_sec: float,
    input_start_sec: float,
    input_end_sec: float,
    cursor: int,
    line_padding: int = 2,
    character_backtrack: int = 24,
    minimum_forward_characters: int = 48,
) -> tuple[int, int]:
    """Choose one deterministic transcript slice for a serial window.

    The duration-proportional estimate is only a proposal.  The serial cursor
    prevents later windows from silently returning to an earlier repeated
    occurrence, while backtracking and whole-line padding permit recovery.
    """
    total = len(document.characters)
    if duration_sec <= 0 or not 0 <= input_start_sec <= input_end_sec:
        raise ValueError("invalid duration/window")
    cursor = min(max(cursor, 0), total)
    estimated_start = int(math.floor(total * input_start_sec / duration_sec))
    estimated_end = int(math.ceil(total * input_end_sec / duration_sec))
    start = min(estimated_start, max(0, cursor - character_backtrack))
    end = max(estimated_end, min(total, cursor + minimum_forward_characters))
    start = min(max(start, 0), total - 1)
    end = min(max(end, start + 1), total)

    start_line = max(0, _line_for_character(document, start) - line_padding)
    end_line = min(len(document.lines) - 1, _line_for_character(document, end - 1) + line_padding)
    return (
        document.lines[start_line].character_start,
        document.lines[end_line].character_end,
    )


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


def merge_window_candidates(
    candidates: Iterable[dict[str, Any]], *, duration_sec: float
) -> list[dict[str, Any]]:
    """Select one occurrence-aware prediction per global character index."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(int(candidate["global_character_index"]), []).append(dict(candidate))
    if not grouped:
        raise ValueError("no window candidates")

    selected: list[dict[str, Any]] = []
    for global_index in sorted(grouped):
        options = grouped[global_index]

        def rank(row: dict[str, Any]) -> tuple[float, float, float, float]:
            midpoint = (float(row["fixed_global_start_sec"]) + float(row["fixed_global_end_sec"])) / 2.0
            core_start = float(row["core_start_sec"])
            core_end = float(row["core_end_sec"])
            input_start = float(row["input_start_sec"])
            input_end = float(row["input_end_sec"])
            in_core = core_start <= midpoint < core_end or (
                abs(core_end - duration_sec) < 1e-9 and midpoint <= core_end
            )
            boundary_distance = min(midpoint - input_start, input_end - midpoint)
            core_distance = abs(midpoint - (core_start + core_end) / 2.0)
            margin = float(row.get("raw_boundary_margin_mean", 0.0))
            return (1.0 if in_core else 0.0, boundary_distance, margin, -core_distance)

        winner = max(options, key=rank)
        winner["candidate_count"] = len(options)
        winner["selected_start_sec"] = float(winner["fixed_global_start_sec"])
        winner["selected_end_sec"] = float(winner["fixed_global_end_sec"])
        selected.append(winner)
    return repair_monotonic_intervals(selected, duration_sec=duration_sec)


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100.0)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
