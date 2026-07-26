"""Pure helpers for multilingual serial-window lyric alignment and rendering.

The helpers do not load a model.  Alignment units follow the official Qwen3
Forced Aligner processor policy: CJK characters and Latin words for
Chinese/Cantonese and space-delimited languages, and Nagisa word units for
Japanese.  Display punctuation and spacing are preserved separately from the
model-facing unit text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence
import unicodedata


SUPPORTED_DEMO_LANGUAGES = (
    "Chinese",
    "English",
    "Cantonese",
    "French",
    "German",
    "Italian",
    "Japanese",
    "Portuguese",
    "Russian",
    "Spanish",
)

_LANGUAGE_ALIASES = {
    "zh": "Chinese",
    "zho": "Chinese",
    "cmn": "Chinese",
    "mandarin": "Chinese",
    "chinese": "Chinese",
    "中文": "Chinese",
    "en": "English",
    "eng": "English",
    "english": "English",
    "英文": "English",
    "ja": "Japanese",
    "jpn": "Japanese",
    "japanese": "Japanese",
    "日文": "Japanese",
    "日语": "Japanese",
    "yue": "Cantonese",
    "cantonese": "Cantonese",
    "粤语": "Cantonese",
    "fr": "French",
    "french": "French",
    "de": "German",
    "german": "German",
    "it": "Italian",
    "italian": "Italian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "ru": "Russian",
    "russian": "Russian",
    "es": "Spanish",
    "spanish": "Spanish",
}


def normalize_alignment_language(language: str) -> str:
    """Return the canonical Forced Aligner language name.

    The command line accepts canonical names case-insensitively plus common ISO
    aliases.  Unsupported values fail before model loading so cache identities
    cannot silently mix languages.
    """
    value = str(language).strip()
    if not value:
        raise ValueError("language must be non-empty")
    for canonical in SUPPORTED_DEMO_LANGUAGES:
        if value.casefold() == canonical.casefold():
            return canonical
    canonical = _LANGUAGE_ALIASES.get(value.casefold())
    if canonical is None:
        raise ValueError(
            f"unsupported forced-aligner language {language!r}; supported: "
            + ", ".join(SUPPORTED_DEMO_LANGUAGES)
        )
    return canonical


def alignment_unit_mode(language: str) -> str:
    canonical = normalize_alignment_language(language)
    if canonical in {"Chinese", "Cantonese"}:
        return "cjk_character_or_latin_word"
    if canonical == "Japanese":
        return "japanese_word_nagisa"
    return "space_word_or_cjk_character"


def _is_kept_char(character: str) -> bool:
    if character == "'":
        return True
    category = unicodedata.category(character)
    return category.startswith("L") or category.startswith("N")


def _clean_token(token: str) -> str:
    return "".join(character for character in token if _is_kept_char(character))


def _is_cjk_char(character: str) -> bool:
    code = ord(character)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
    )


def _split_segment_with_chinese(segment: str) -> list[str]:
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            tokens.append("".join(buffer))
            buffer.clear()

    for character in segment:
        if _is_cjk_char(character):
            flush()
            tokens.append(character)
        else:
            buffer.append(character)
    flush()
    return tokens


def _tokenize_space_language(text: str) -> list[str]:
    tokens: list[str] = []
    for segment in text.split():
        cleaned = _clean_token(segment)
        if cleaned:
            tokens.extend(_split_segment_with_chinese(cleaned))
    return tokens


def _default_japanese_tokenizer(text: str) -> Sequence[str]:
    try:
        import nagisa
    except ImportError as exc:
        raise RuntimeError(
            "Japanese alignment requires the official Nagisa tokenizer. "
            "Install the Qwen3-ASR runtime dependencies or run: pip install nagisa"
        ) from exc
    return nagisa.tagging(text).words


def _tokenize_japanese(
    text: str,
    *,
    tokenizer: Callable[[str], Sequence[str]] | None = None,
) -> list[str]:
    raw_words = (tokenizer or _default_japanese_tokenizer)(text)
    return [cleaned for word in raw_words if (cleaned := _clean_token(str(word)))]


def _tokenize_line(
    text: str,
    *,
    language: str,
    japanese_tokenizer: Callable[[str], Sequence[str]] | None,
) -> list[str]:
    canonical = normalize_alignment_language(language)
    if canonical == "Japanese":
        return _tokenize_japanese(text, tokenizer=japanese_tokenizer)
    # This mirrors Qwen3ForceAlignProcessor.tokenize_space_lang.  Chinese and
    # Cantonese are therefore character-level for CJK while contiguous Latin
    # text remains one word, including mixed-language lyrics.
    return _tokenize_space_language(text)


def _visible_parts(display: str, tokens: Sequence[str]) -> list[tuple[str, str, str]]:
    """Map clean model tokens back to exact visible spans.

    Returns ``(prefix, visible_text, suffix)`` per token.  Punctuation and
    whitespace removed by the model processor are attached to neighboring
    units so joining the visible parts reconstructs the original line.
    """
    kept = [(index, character) for index, character in enumerate(display) if _is_kept_char(character)]
    expected = "".join(tokens)
    observed = "".join(character for _, character in kept)
    if expected != observed:
        raise ValueError(
            "alignment tokenizer cannot be mapped back to the source line: "
            f"tokens={tokens!r} cleaned_source={observed!r} source={display!r}"
        )
    spans: list[tuple[int, int]] = []
    cursor = 0
    for token in tokens:
        length = len(token)
        if length <= 0:
            raise ValueError("empty alignment unit")
        unit_positions = kept[cursor: cursor + length]
        if len(unit_positions) != length:
            raise ValueError(f"token exceeds source line: {token!r}")
        if "".join(character for _, character in unit_positions) != token:
            raise ValueError(f"token/source mismatch for {token!r} in {display!r}")
        spans.append((unit_positions[0][0], unit_positions[-1][0] + 1))
        cursor += length

    parts: list[tuple[str, str, str]] = []
    for index, (start, end) in enumerate(spans):
        prefix = display[:start] if index == 0 else ""
        next_start = spans[index + 1][0] if index + 1 < len(spans) else len(display)
        parts.append((prefix, display[start:end], display[end:next_start]))
    return parts


@dataclass(frozen=True)
class LyricCharacter:
    """One model-facing alignment unit.

    The historic class name is retained for compatibility.  ``text`` may be a
    CJK character or a multi-character word.  Rendering uses the separate
    display fields rather than assuming one Unicode character per timestamp.
    """

    global_index: int
    line_index: int
    index_in_line: int
    text: str
    display_suffix: str = ""
    display_prefix: str = ""
    display_text: str = ""
    unit_type: str = "character"

    @property
    def visible_text(self) -> str:
        return self.display_prefix + (self.display_text or self.text) + self.display_suffix


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
    language: str = "Chinese"
    unit_mode: str = "cjk_character_or_latin_word"

    @property
    def transcript(self) -> str:
        # Historical compact view used by existing diagnostics.  Model calls
        # should use ``transcript_for_slice`` so pre-tokenized units remain
        # stable across English/Japanese window boundaries.
        return "".join(item.text for item in self.characters)

    def transcript_for_slice(self, start: int, end: int) -> str:
        selected = self.characters[start:end]
        # Explicit spaces make each pre-tokenized unit stable when the official
        # processor tokenizes a window slice again.  The processor removes the
        # separators; this also prevents Japanese words from merging when a
        # slice starts or ends mid-line.
        return " ".join(item.text for item in selected)

    def display_transcript_for_slice(self, start: int, end: int) -> str:
        """Reconstruct visible source text for a unit slice.

        This is a processor-compatibility fallback.  Line changes are separated
        explicitly so the last word of one line cannot merge with the first word
        of the next line.
        """
        selected = self.characters[start:end]
        parts: list[str] = []
        previous_line: int | None = None
        for item in selected:
            if previous_line is not None and item.line_index != previous_line:
                parts.append("\n")
            parts.append(item.visible_text)
            previous_line = item.line_index
        return "".join(parts)


def parse_lyrics_text(
    text: str,
    *,
    language: str = "Chinese",
    japanese_tokenizer: Callable[[str], Sequence[str]] | None = None,
) -> LyricDocument:
    """Parse lyrics into language-aware Forced Aligner units.

    - Chinese/Cantonese: CJK character units; contiguous Latin text is one word.
    - English and other space languages: word units, while embedded CJK remains
      character-level as in the official processor.
    - Japanese: Nagisa word units.  Punctuation is display-only.
    """
    canonical = normalize_alignment_language(language)
    mode = alignment_unit_mode(canonical)
    lines: list[LyricLine] = []
    characters: list[LyricCharacter] = []
    for raw_line in text.splitlines():
        display = raw_line.strip()
        if not display:
            continue
        tokens = _tokenize_line(
            display,
            language=canonical,
            japanese_tokenizer=japanese_tokenizer,
        )
        if not tokens:
            continue
        visible_parts = _visible_parts(display, tokens)
        line_index = len(lines)
        start = len(characters)
        for index_in_line, (token, visible) in enumerate(zip(tokens, visible_parts, strict=True)):
            prefix, visible_text, suffix = visible
            if len(token) == 1 and _is_cjk_char(token):
                unit_type = "cjk_character"
            elif canonical == "Japanese":
                unit_type = "japanese_word"
            else:
                unit_type = "word"
            characters.append(
                LyricCharacter(
                    global_index=len(characters),
                    line_index=line_index,
                    index_in_line=index_in_line,
                    text=token,
                    display_prefix=prefix,
                    display_text=visible_text,
                    display_suffix=suffix,
                    unit_type=unit_type,
                )
            )
        end = len(characters)
        lines.append(
            LyricLine(
                line_index=line_index,
                display_text=display,
                character_start=start,
                character_end=end,
            )
        )
    if not characters:
        raise ValueError("lyrics contain no alignable letters or numbers")
    return LyricDocument(
        lines=tuple(lines),
        characters=tuple(characters),
        language=canonical,
        unit_mode=mode,
    )


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
