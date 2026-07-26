from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import (
    append_strict_core_commits,
    ass_time,
    build_serial_windows,
    future_character_range,
    parse_lyrics_text,
    split_core_commit_prefix,
    next_window_transcript_start,
)


def test_parse_lyrics_preserves_repeated_occurrences_and_phrase_spaces() -> None:
    document = parse_lyrics_text("甲乙 丙\n\n甲乙 丙\n")
    assert document.transcript == "甲乙丙甲乙丙"
    assert len(document.lines) == 2
    assert document.characters[1].display_suffix == " "
    assert document.characters[0].global_index != document.characters[3].global_index


def test_serial_windows_use_sixty_second_cores_with_context() -> None:
    windows = build_serial_windows(151.0, core_sec=60, left_context_sec=10, right_context_sec=10)
    assert windows == [
        {"window_index": 0, "core_start_sec": 0.0, "core_end_sec": 60.0, "input_start_sec": 0.0, "input_end_sec": 70.0},
        {"window_index": 1, "core_start_sec": 60.0, "core_end_sec": 120.0, "input_start_sec": 50.0, "input_end_sec": 130.0},
        {"window_index": 2, "core_start_sec": 120.0, "core_end_sec": 151.0, "input_start_sec": 110.0, "input_end_sec": 151.0},
    ]


def test_ass_time_is_centisecond_based() -> None:
    assert ass_time(61.234) == "0:01:01.23"


def test_future_range_starts_exactly_at_serial_cursor_without_backtracking() -> None:
    document = parse_lyrics_text("甲乙丙丁\n戊己庚辛\n壬癸子丑\n")
    start, end = future_character_range(
        document, cursor=5, target_character_count=2, line_padding=0
    )
    assert start == 5
    assert end == 8
    assert document.characters[start].text == "己"


def _row(index: int, character: str, start: float, end: float) -> dict[str, object]:
    return {
        "global_character_index": index,
        "line_index": 0,
        "index_in_line": index,
        "character": character,
        "display_suffix": "",
        "fixed_global_start_sec": start,
        "fixed_global_end_sec": end,
    }


def test_strict_core_owns_boundary_crossing_character_and_excludes_it_from_next_window() -> None:
    rows = [
        _row(0, "甲", 55.0, 58.0),
        _row(1, "乙", 58.0, 61.0),
        _row(2, "丙", 61.0, 63.0),
    ]
    context, committed, lookahead = split_core_commit_prefix(
        rows,
        expected_input_character_start=0,
        committed_character_start=0,
        core_start_sec=0.0,
        core_end_sec=60.0,
        final_core=False,
    )
    assert context == []
    assert [row["global_character_index"] for row in committed] == [0, 1]
    assert [row["global_character_index"] for row in lookahead] == [2]
    assert committed[-1]["fixed_global_end_sec"] == 61.0


def test_next_core_reinputs_left_overlap_lyrics_as_context_only() -> None:
    rows = [
        _row(1, "乙", 58.0, 61.0),
        _row(2, "丙", 61.0, 63.0),
        _row(3, "丁", 65.0, 67.0),
    ]
    context, committed, lookahead = split_core_commit_prefix(
        rows,
        expected_input_character_start=1,
        committed_character_start=2,
        core_start_sec=60.0,
        core_end_sec=120.0,
        final_core=False,
    )
    assert [row["global_character_index"] for row in context] == [1]
    assert [row["global_character_index"] for row in committed] == [2, 3]
    assert lookahead == []


def test_next_input_start_excludes_only_character_cut_by_acoustic_boundary() -> None:
    rows = [
        _row(10, "甲", 48.0, 50.4),
        _row(11, "乙", 50.4, 51.0),
        _row(12, "丙", 52.0, 53.0),
    ]
    start, cut = next_window_transcript_start(
        rows, input_boundary_sec=50.0, total_characters=20
    )
    assert start == 11
    assert cut is not None
    assert cut["global_character_index"] == 10

    silence_start, silence_cut = next_window_transcript_start(
        rows[1:], input_boundary_sec=50.0, total_characters=20
    )
    assert silence_start == 11
    assert silence_cut is None


def test_hard_core_append_does_not_allow_large_cumulative_repair() -> None:
    first = append_strict_core_commits(
        [],
        [_row(0, "甲", 58.0, 60.4)],
        window={"window_index": 0, "core_start_sec": 0.0, "core_end_sec": 60.0},
        duration_sec=130.0,
        seam_tolerance_sec=0.16,
    )
    assert first[0]["owner_window_index"] == 0
    assert first[0]["cross_window_repaired"] is False
    try:
        append_strict_core_commits(
            first,
            [_row(1, "乙", 59.0, 61.0)],
            window={"window_index": 1, "core_start_sec": 60.0, "core_end_sec": 120.0},
            duration_sec=130.0,
            seam_tolerance_sec=0.16,
        )
    except RuntimeError as exc:
        assert "seam tolerance" in str(exc)
    else:
        raise AssertionError("large cross-core conflict must hard fail")


def test_windowed_alignment_is_strictly_serial_and_never_reinputs_boundary_character(monkeypatch) -> None:
    import importlib.util
    from types import SimpleNamespace

    script = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("strict_serial_demo_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    document = parse_lyrics_text("甲乙丙丁戊己\n")
    absolute = {
        0: (10.0, 20.0),
        1: (58.0, 61.0),  # crosses 60s and must stay with core 0
        2: (65.0, 70.0),
        3: (118.0, 121.0),  # crosses 120s and must stay with core 1
        4: (125.0, 128.0),
        5: (129.0, 130.0),
    }
    calls: list[tuple[int, int]] = []

    def fake_infer_slice(*, document, character_start, character_end, global_audio_offset_sec, **kwargs):
        calls.append((character_start, character_end))
        rows = []
        for item in document.characters[character_start:character_end]:
            start, end = absolute[item.global_index]
            rows.append(
                {
                    "global_character_index": item.global_index,
                    "line_index": item.line_index,
                    "index_in_line": item.index_in_line,
                    "character": item.text,
                    "display_suffix": item.display_suffix,
                    "fixed_local_start_sec": start - global_audio_offset_sec,
                    "fixed_local_end_sec": end - global_audio_offset_sec,
                    "fixed_global_start_sec": start,
                    "fixed_global_end_sec": end,
                    "raw_boundary_margin_mean": 1.0,
                }
            )
        return rows, {"character_count": len(rows)}

    class FakeAudio:
        def __init__(self, samples: int):
            self.samples = samples

        def __len__(self) -> int:
            return self.samples

        def __getitem__(self, item):
            if not isinstance(item, slice):
                raise TypeError(item)
            start = 0 if item.start is None else item.start
            stop = self.samples if item.stop is None else item.stop
            return FakeAudio(max(0, stop - start))

    monkeypatch.setattr(module, "infer_slice", fake_infer_slice)
    args = SimpleNamespace(
        core_sec=60.0,
        left_context_sec=10.0,
        right_context_sec=10.0,
        minimum_forward_characters=64,
        future_character_ratio=1.35,
        future_line_padding=1,
        max_candidate_expansions=4,
        boundary_start_tolerance_sec=0.32,
        seam_tolerance_sec=0.16,
    )
    rows, trace = module.windowed_alignment(
        object(), object(), FakeAudio(130 * 16000), document, args
    )

    assert [start for start, _ in calls] == [0, 1, 3]
    assert [row["owner_window_index"] for row in rows] == [0, 0, 1, 1, 2, 2]
    assert trace[0]["core_boundary_character"]["global_character_index"] == 1
    assert trace[0]["next_window_character_start"] == 1
    assert trace[0]["next_uncommitted_character_start"] == 2
    assert trace[1]["core_boundary_character"]["global_character_index"] == 3
    assert trace[1]["next_window_character_start"] == 3
    assert trace[1]["next_uncommitted_character_start"] == 4
    assert all(row["cross_window_repaired"] is False for row in rows)


def test_english_lyrics_use_word_units_and_preserve_visible_punctuation() -> None:
    document = parse_lyrics_text("Hello, world!\nDon't stop now.", language="English")
    assert document.language == "English"
    assert document.unit_mode == "space_word_or_cjk_character"
    assert [item.text for item in document.characters] == [
        "Hello", "world", "Don't", "stop", "now"
    ]
    assert [item.visible_text for item in document.characters] == [
        "Hello, ", "world!", "Don't ", "stop ", "now."
    ]
    assert document.transcript_for_slice(0, 2) == "Hello world"
    assert "".join(item.visible_text for item in document.characters[:2]) == "Hello, world!"


def test_chinese_english_mixed_lyrics_keep_cjk_characters_and_latin_words() -> None:
    document = parse_lyrics_text("今晚 sing with me!", language="Chinese")
    assert [item.text for item in document.characters] == ["今", "晚", "sing", "with", "me"]
    assert [item.unit_type for item in document.characters] == [
        "cjk_character", "cjk_character", "word", "word", "word"
    ]
    assert "".join(item.visible_text for item in document.characters) == "今晚 sing with me!"


def test_japanese_lyrics_use_nagisa_word_units_and_preserve_punctuation() -> None:
    # Production uses nagisa.tagging(text).words.  A deterministic stub keeps
    # this unit test independent of optional server-side Japanese dependencies.
    document = parse_lyrics_text(
        "今日は、晴れです。",
        language="Japanese",
        japanese_tokenizer=lambda _: ["今日", "は", "、", "晴れ", "です", "。"],
    )
    assert document.language == "Japanese"
    assert document.unit_mode == "japanese_word_nagisa"
    assert [item.text for item in document.characters] == ["今日", "は", "晴れ", "です"]
    assert [item.visible_text for item in document.characters] == ["今日", "は、", "晴れ", "です。"]
    assert document.transcript_for_slice(0, 4) == "今日 は 晴れ です"


def test_language_aliases_are_canonicalized() -> None:
    from lyricalign.demo.karaoke import normalize_alignment_language

    assert normalize_alignment_language("en") == "English"
    assert normalize_alignment_language("JA") == "Japanese"
    assert normalize_alignment_language("yue") == "Cantonese"
    assert normalize_alignment_language("中文") == "Chinese"
